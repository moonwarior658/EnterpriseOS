from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import IikoEmployeeDto, IikoPersonalShiftDto
from app.models.employee import (
    Employee, EmployeeIikoShift, EmployeeIikoShiftStatus, IikoEmployeeLink,
)
from app.models.iiko import (
    IikoMappingStatus, IikoWarehouseDestinationType, IikoWarehouseMapping,
)
from app.models.user import User
from app.schemas.employee import IikoEmployeeCandidateRead


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _normalized_name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


async def find_candidates(
    provider: IikoProvider,
    *,
    full_name: str,
) -> list[IikoEmployeeCandidateRead]:
    needle = _normalized_name(full_name)
    needle_parts = set(needle.split())
    results: list[IikoEmployeeCandidateRead] = []
    for employee in await provider.get_employees():
        candidate_name = _normalized_name(employee.name)
        candidate_parts = set(candidate_name.split())
        if not needle_parts or not (
            candidate_name == needle
            or needle_parts.issubset(candidate_parts)
            or candidate_parts.issubset(needle_parts)
        ):
            continue
        results.append(IikoEmployeeCandidateRead(
            iiko_user_id=employee.external_id,
            display_name=employee.name,
            code=employee.code,
            birth_date=None,
            is_deleted=employee.is_deleted,
        ))
    return sorted(results, key=lambda item: (item.is_deleted, item.display_name.casefold(), item.iiko_user_id))


async def _authoritative_iiko_employee(
    provider: IikoProvider,
    iiko_user_id: str,
) -> IikoEmployeeDto:
    matches = [
        item for item in await provider.get_employees()
        if item.external_id == iiko_user_id
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="iiko employee not found")
    if len(matches) > 1:
        raise HTTPException(status_code=502, detail="IIKO_EMPLOYEE_ID_AMBIGUOUS")
    return matches[0]


def current_link(db: Session, employee: Employee, *, lock: bool = False) -> IikoEmployeeLink | None:
    query = select(IikoEmployeeLink).where(
        IikoEmployeeLink.tenant_id == employee.tenant_id,
        IikoEmployeeLink.employee_id == employee.id,
        IikoEmployeeLink.valid_to.is_(None),
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def link_history(db: Session, employee: Employee) -> list[IikoEmployeeLink]:
    return list(db.scalars(select(IikoEmployeeLink).where(
        IikoEmployeeLink.tenant_id == employee.tenant_id,
        IikoEmployeeLink.employee_id == employee.id,
    ).order_by(IikoEmployeeLink.valid_from.desc(), IikoEmployeeLink.created_at.desc())).all())


def _ensure_iiko_identity_available(
    db: Session,
    *,
    tenant_id: str,
    employee_id: UUID,
    iiko_user_id: str,
) -> None:
    occupied = db.execute(
        select(IikoEmployeeLink, Employee.full_name)
        .join(Employee, Employee.id == IikoEmployeeLink.employee_id)
        .where(
            IikoEmployeeLink.tenant_id == tenant_id,
            IikoEmployeeLink.iiko_user_id == iiko_user_id,
            IikoEmployeeLink.valid_to.is_(None),
            IikoEmployeeLink.employee_id != employee_id,
        )
        .with_for_update()
    ).first()
    if occupied is not None:
        link, full_name = occupied
        raise _conflict(
            f"iiko employee is already linked to {full_name} ({link.employee_id})"
        )


async def create_link(
    db: Session,
    employee: Employee,
    *,
    iiko_user_id: str,
    reason: str,
    actor: User,
    provider: IikoProvider,
    now: datetime | None = None,
) -> IikoEmployeeLink:
    if current_link(db, employee, lock=True) is not None:
        raise _conflict("Employee already has an active iiko link")
    authoritative = await _authoritative_iiko_employee(provider, iiko_user_id)
    _ensure_iiko_identity_available(
        db, tenant_id=employee.tenant_id, employee_id=employee.id,
        iiko_user_id=iiko_user_id,
    )
    link = IikoEmployeeLink(
        tenant_id=employee.tenant_id,
        employee_id=employee.id,
        iiko_user_id=authoritative.external_id,
        iiko_display_name=authoritative.name,
        iiko_birth_date=None,
        valid_from=now or datetime.now(UTC),
        reason=reason,
        created_by_user_id=actor.id,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict("Employee or iiko identity is already linked") from error
    db.refresh(link)
    return link


async def correct_link(
    db: Session,
    employee: Employee,
    *,
    iiko_user_id: str,
    reason: str,
    actor: User,
    provider: IikoProvider,
    now: datetime | None = None,
) -> IikoEmployeeLink:
    old = current_link(db, employee, lock=True)
    if old is None:
        raise _conflict("Employee has no active iiko link")
    if old.iiko_user_id == iiko_user_id:
        raise _conflict("New iiko identity must differ from the current link")
    authoritative = await _authoritative_iiko_employee(provider, iiko_user_id)
    _ensure_iiko_identity_available(
        db, tenant_id=employee.tenant_id, employee_id=employee.id,
        iiko_user_id=iiko_user_id,
    )
    corrected_at = _utc(now or datetime.now(UTC))
    if corrected_at <= _utc(old.valid_from):
        raise HTTPException(status_code=422, detail="Correction time must follow link start")
    old.valid_to = corrected_at
    old.ended_reason = reason
    old.ended_by_user_id = actor.id
    replacement = IikoEmployeeLink(
        tenant_id=employee.tenant_id,
        employee_id=employee.id,
        iiko_user_id=authoritative.external_id,
        iiko_display_name=authoritative.name,
        iiko_birth_date=None,
        valid_from=corrected_at,
        reason=reason,
        created_by_user_id=actor.id,
    )
    db.add(replacement)
    shifts = list(db.scalars(select(EmployeeIikoShift).where(
        EmployeeIikoShift.tenant_id == employee.tenant_id,
        EmployeeIikoShift.employee_id == employee.id,
        EmployeeIikoShift.iiko_user_id == old.iiko_user_id,
        EmployeeIikoShift.opened_at >= old.valid_from,
        EmployeeIikoShift.opened_at < corrected_at,
    ).with_for_update()).all())
    for shift in shifts:
        shift.iiko_user_id = authoritative.external_id
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict("Employee or iiko identity is already linked") from error
    db.refresh(replacement)
    return replacement


def _idempotency_key(shift: IikoPersonalShiftDto) -> str:
    if shift.external_id:
        return f"attendance:{shift.external_id}"
    raw = f"{shift.employee_external_id}|{_utc(shift.opened_at).isoformat()}"
    return "attendance:sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _department_id(
    db: Session,
    *,
    tenant_id: str,
    external_id: str | None,
) -> UUID | None:
    if not external_id:
        return None
    try:
        warehouse_id = UUID(external_id)
    except ValueError:
        return None
    return db.scalar(select(IikoWarehouseMapping.eos_department_id).where(
        IikoWarehouseMapping.tenant_id == tenant_id,
        IikoWarehouseMapping.iiko_warehouse_id == warehouse_id,
        IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
        IikoWarehouseMapping.destination_type == IikoWarehouseDestinationType.DESTINATION,
        IikoWarehouseMapping.is_deleted.is_(False),
        IikoWarehouseMapping.eos_department_id.is_not(None),
    ))


def _link_for_shift(
    db: Session,
    *,
    tenant_id: str,
    iiko_user_id: str,
    opened_at: datetime,
) -> IikoEmployeeLink | None:
    active = db.scalar(select(IikoEmployeeLink).where(
        IikoEmployeeLink.tenant_id == tenant_id,
        IikoEmployeeLink.iiko_user_id == iiko_user_id,
        IikoEmployeeLink.valid_to.is_(None),
    ))
    if active is not None:
        return active
    return db.scalar(select(IikoEmployeeLink).where(
        IikoEmployeeLink.tenant_id == tenant_id,
        IikoEmployeeLink.iiko_user_id == iiko_user_id,
        IikoEmployeeLink.valid_from <= opened_at,
        or_(IikoEmployeeLink.valid_to.is_(None), IikoEmployeeLink.valid_to > opened_at),
    ).order_by(IikoEmployeeLink.valid_from.desc()))


@dataclass(frozen=True, slots=True)
class ShiftSyncResult:
    received: int
    matched: int
    created: int
    updated: int
    unchanged: int
    unresolved_department: int


def sync_shifts(
    db: Session,
    shifts: list[IikoPersonalShiftDto],
    *,
    tenant_id: str,
    seen_at: datetime | None = None,
    commit: bool = True,
) -> ShiftSyncResult:
    observed_at = _utc(seen_at or datetime.now(UTC))
    matched = created = updated = unchanged = unresolved = 0
    for external in shifts:
        opened_at = _utc(external.opened_at)
        link = _link_for_shift(
            db, tenant_id=tenant_id, iiko_user_id=external.employee_external_id,
            opened_at=opened_at,
        )
        if link is None:
            continue
        matched += 1
        department_id = _department_id(
            db, tenant_id=tenant_id, external_id=external.department_external_id,
        )
        if external.department_external_id and department_id is None:
            unresolved += 1
        closed_at = _utc(external.closed_at) if external.closed_at else None
        if closed_at is not None and closed_at < opened_at:
            raise HTTPException(status_code=502, detail="IIKO_SHIFT_PERIOD_INVALID")
        duration = (
            int((closed_at - opened_at).total_seconds() // 60)
            if closed_at is not None else None
        )
        shift_status = (
            EmployeeIikoShiftStatus.CLOSED if closed_at is not None
            else EmployeeIikoShiftStatus.OPEN
        )
        key = _idempotency_key(external)
        stored = db.scalar(select(EmployeeIikoShift).where(
            EmployeeIikoShift.tenant_id == tenant_id,
            EmployeeIikoShift.raw_external_idempotency_key == key,
        ).with_for_update())
        if stored is None:
            db.add(EmployeeIikoShift(
                tenant_id=tenant_id,
                employee_id=link.employee_id,
                iiko_user_id=external.employee_external_id,
                external_shift_id=external.external_id,
                iiko_department_id=external.department_external_id,
                department_id=department_id,
                opened_at=opened_at,
                closed_at=closed_at,
                duration_minutes=duration,
                status=shift_status,
                raw_external_idempotency_key=key,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            ))
            created += 1
            continue
        changed = any((
            stored.employee_id != link.employee_id,
            stored.iiko_user_id != external.employee_external_id,
            stored.iiko_department_id != external.department_external_id,
            stored.department_id != department_id,
            _utc(stored.opened_at) != opened_at,
            (_utc(stored.closed_at) if stored.closed_at else None) != closed_at,
            stored.duration_minutes != duration,
            stored.status != shift_status,
        ))
        stored.employee_id = link.employee_id
        stored.iiko_user_id = external.employee_external_id
        stored.iiko_department_id = external.department_external_id
        stored.department_id = department_id
        stored.opened_at = opened_at
        stored.closed_at = closed_at
        stored.duration_minutes = duration
        stored.status = shift_status
        stored.last_seen_at = observed_at
        if changed:
            updated += 1
        else:
            unchanged += 1
    try:
        if commit:
            db.commit()
        else:
            db.flush()
    except IntegrityError as error:
        db.rollback()
        raise _conflict("Conflicting active iiko shifts received") from error
    return ShiftSyncResult(
        received=len(shifts), matched=matched, created=created, updated=updated,
        unchanged=unchanged, unresolved_department=unresolved,
    )


def list_shifts(db: Session, employee: Employee, *, limit: int = 50) -> list[EmployeeIikoShift]:
    return list(db.scalars(select(EmployeeIikoShift).where(
        EmployeeIikoShift.tenant_id == employee.tenant_id,
        EmployeeIikoShift.employee_id == employee.id,
    ).order_by(EmployeeIikoShift.opened_at.desc()).limit(limit)).all())


def active_shift(db: Session, employee: Employee) -> EmployeeIikoShift | None:
    return db.scalar(select(EmployeeIikoShift).where(
        EmployeeIikoShift.tenant_id == employee.tenant_id,
        EmployeeIikoShift.employee_id == employee.id,
        EmployeeIikoShift.status == EmployeeIikoShiftStatus.OPEN,
    ).order_by(EmployeeIikoShift.opened_at.desc()))
