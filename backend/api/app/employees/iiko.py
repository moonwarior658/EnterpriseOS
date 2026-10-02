from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.core.action_context import resolve_action_context
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import IikoEmployeeDto, IikoPersonalShiftDto
from app.models.employee import (
    Employee, EmployeeIikoShift, EmployeeIikoShiftStatus, EmployeeRole,
    IikoDepartmentMapping, IikoEmployeeLink,
)
from app.models.audit import AuditEvent
from app.models.supply import Department
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
    birth_date: date | None = None,
) -> list[IikoEmployeeCandidateRead]:
    needle = _normalized_name(full_name)
    needle_parts = set(needle.split())
    results: list[IikoEmployeeCandidateRead] = []
    for employee in await provider.get_employees():
        if employee.is_deleted or not employee.is_employee:
            continue
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
            birth_date=employee.birth_date,
            is_deleted=employee.is_deleted,
        ))
    return sorted(results, key=lambda item: (
        item.birth_date != birth_date if birth_date is not None else False,
        item.display_name.casefold(), item.iiko_user_id,
    ))


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
    employee = matches[0]
    if employee.is_deleted or not employee.is_employee:
        raise HTTPException(status_code=409, detail="iiko identity is not an active employee")
    return employee


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
    context = resolve_action_context(
        db, actor, required_roles=frozenset({EmployeeRole.ADMIN}),
        role_precedence=(EmployeeRole.ADMIN,), write=True,
    )
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
        iiko_birth_date=authoritative.birth_date,
        valid_from=now or datetime.now(UTC),
        reason=reason,
        created_by_user_id=actor.id,
    )
    db.add(link)
    try:
        db.flush()
        record_audit_event(
            db, tenant_id=actor.tenant_id, event_type="IIKO_EMPLOYEE_LINK_CREATED",
            entity_type="Employee", entity_id=employee.id, operation="LINK_IIKO_EMPLOYEE",
            context=context, actor_user=actor, before={},
            after={
                "iiko_user_id": link.iiko_user_id,
                "iiko_display_name": link.iiko_display_name,
            },
            reason=reason,
        )
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
    context = resolve_action_context(
        db, actor, required_roles=frozenset({EmployeeRole.ADMIN}),
        role_precedence=(EmployeeRole.ADMIN,), write=True,
    )
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
        iiko_birth_date=authoritative.birth_date,
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
    corrected_event_id = db.scalar(select(AuditEvent.id).where(
        AuditEvent.tenant_id == actor.tenant_id,
        AuditEvent.entity_type == "Employee",
        AuditEvent.entity_id == str(employee.id),
        AuditEvent.event_type.in_({
            "IIKO_EMPLOYEE_LINK_CREATED", "IIKO_EMPLOYEE_LINK_CORRECTED",
        }),
    ).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()))
    try:
        db.flush()
        record_audit_event(
            db, tenant_id=actor.tenant_id, event_type="IIKO_EMPLOYEE_LINK_CORRECTED",
            entity_type="Employee", entity_id=employee.id, operation="CORRECT_IIKO_EMPLOYEE_LINK",
            context=context, actor_user=actor,
            before={"iiko_user_id": old.iiko_user_id, "iiko_display_name": old.iiko_display_name},
            after={
                "iiko_user_id": replacement.iiko_user_id,
                "iiko_display_name": replacement.iiko_display_name,
                "reattributed_shift_count": len(shifts),
            },
            reason=reason,
            correction_of_event_id=corrected_event_id,
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict("Employee or iiko identity is already linked") from error
    db.refresh(replacement)
    return replacement


def _reconciliation_key(shift: IikoPersonalShiftDto) -> str:
    raw = (
        f"IIKO_PERSONAL|{shift.employee_external_id}|"
        f"{_utc(shift.opened_at).isoformat()}"
    )
    return "personal-shift:sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _department_id(
    db: Session,
    *,
    tenant_id: str,
    external_id: str | None,
) -> UUID | None:
    if not external_id:
        return None
    try:
        iiko_department_id = UUID(external_id)
    except ValueError:
        return None
    return db.scalar(select(IikoDepartmentMapping.eos_department_id).where(
        IikoDepartmentMapping.tenant_id == tenant_id,
        IikoDepartmentMapping.iiko_department_id == iiko_department_id,
    ))


def list_department_mappings(
    db: Session,
    *,
    tenant_id: str,
) -> list[tuple[IikoDepartmentMapping, str]]:
    return list(db.execute(
        select(IikoDepartmentMapping, Department.name)
        .join(
            Department,
            (Department.tenant_id == IikoDepartmentMapping.tenant_id)
            & (Department.id == IikoDepartmentMapping.eos_department_id),
        )
        .where(IikoDepartmentMapping.tenant_id == tenant_id)
        .order_by(IikoDepartmentMapping.source_name, IikoDepartmentMapping.iiko_department_id)
    ).all())


def set_department_mapping(
    db: Session,
    *,
    tenant_id: str,
    iiko_department_id: UUID,
    eos_department_id: UUID,
    source_name: str | None,
    reason: str,
    actor: User,
) -> IikoDepartmentMapping:
    context = resolve_action_context(
        db, actor, required_roles=frozenset({EmployeeRole.ADMIN}),
        role_precedence=(EmployeeRole.ADMIN,), write=True,
    )
    department = db.scalar(select(Department).where(
        Department.tenant_id == tenant_id,
        Department.id == eos_department_id,
    ))
    if department is None:
        raise HTTPException(status_code=404, detail="EOS department not found")
    mapping = db.scalar(select(IikoDepartmentMapping).where(
        IikoDepartmentMapping.tenant_id == tenant_id,
        IikoDepartmentMapping.iiko_department_id == iiko_department_id,
    ).with_for_update())
    before: dict[str, str | None] = {}
    event_type = "IIKO_DEPARTMENT_MAPPING_CONFIRMED"
    if mapping is None:
        mapping = IikoDepartmentMapping(
            tenant_id=tenant_id,
            iiko_department_id=iiko_department_id,
            eos_department_id=eos_department_id,
            source_name=source_name,
            reason=reason.strip(),
            decided_by_user_id=actor.id,
        )
        db.add(mapping)
    else:
        before = {
            "iiko_department_id": str(mapping.iiko_department_id),
            "eos_department_id": str(mapping.eos_department_id),
            "source_name": mapping.source_name,
        }
        mapping.eos_department_id = eos_department_id
        mapping.source_name = source_name
        mapping.reason = reason.strip()
        mapping.decided_by_user_id = actor.id
        event_type = "IIKO_DEPARTMENT_MAPPING_REPLACED"
    try:
        db.flush()
        record_audit_event(
            db, tenant_id=tenant_id, event_type=event_type,
            entity_type="IikoDepartmentMapping", entity_id=mapping.id,
            operation="MAP_IIKO_DEPARTMENT", context=context, actor_user=actor,
            before=before,
            after={
                "iiko_department_id": str(mapping.iiko_department_id),
                "eos_department_id": str(mapping.eos_department_id),
                "source_name": mapping.source_name,
            },
            reason=reason,
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict("Conflicting iiko department mapping") from error
    db.refresh(mapping)
    return mapping


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
        key = _reconciliation_key(external)
        stored = db.scalar(select(EmployeeIikoShift).where(
            EmployeeIikoShift.tenant_id == tenant_id,
            EmployeeIikoShift.reconciliation_key == key,
        ).with_for_update())
        if stored is None:
            stored = db.scalar(select(EmployeeIikoShift).where(
                EmployeeIikoShift.tenant_id == tenant_id,
                EmployeeIikoShift.iiko_user_id == external.employee_external_id,
                EmployeeIikoShift.opened_at == opened_at,
                EmployeeIikoShift.source == "IIKO",
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
                reconciliation_key=key,
                first_seen_at=observed_at,
                last_seen_at=observed_at,
            ))
            created += 1
            continue
        changed = any((
            stored.employee_id != link.employee_id,
            stored.iiko_user_id != external.employee_external_id,
            stored.external_shift_id != external.external_id,
            stored.reconciliation_key != key,
            stored.iiko_department_id != external.department_external_id,
            stored.department_id != department_id,
            _utc(stored.opened_at) != opened_at,
            (_utc(stored.closed_at) if stored.closed_at else None) != closed_at,
            stored.duration_minutes != duration,
            stored.status != shift_status,
        ))
        stored.employee_id = link.employee_id
        stored.iiko_user_id = external.employee_external_id
        stored.external_shift_id = external.external_id
        stored.iiko_department_id = external.department_external_id
        stored.department_id = department_id
        stored.opened_at = opened_at
        stored.closed_at = closed_at
        stored.duration_minutes = duration
        stored.status = shift_status
        stored.reconciliation_key = key
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


def shift_page(db: Session, employee: Employee, *, date_from: date | None,
               date_to: date | None, offset: int, limit: int) -> dict:
    query = select(EmployeeIikoShift).where(
        EmployeeIikoShift.tenant_id == employee.tenant_id,
        EmployeeIikoShift.employee_id == employee.id,
    )
    if date_from is not None:
        query = query.where(EmployeeIikoShift.opened_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to is not None:
        query = query.where(EmployeeIikoShift.opened_at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = list(db.scalars(query.order_by(EmployeeIikoShift.opened_at.desc(),
        EmployeeIikoShift.id.desc()).offset(offset).limit(limit)).all())
    return {"items": items, "total": total, "offset": offset, "limit": limit}


def active_shift(db: Session, employee: Employee) -> EmployeeIikoShift | None:
    return db.scalar(select(EmployeeIikoShift).where(
        EmployeeIikoShift.tenant_id == employee.tenant_id,
        EmployeeIikoShift.employee_id == employee.id,
        EmployeeIikoShift.status == EmployeeIikoShiftStatus.OPEN,
    ).order_by(EmployeeIikoShift.opened_at.desc()))
