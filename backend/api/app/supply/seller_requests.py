from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.core.action_context import ActionContext, ActionContextError, resolve_action_context
from app.integrations.iiko.document_routing import outgoing_invoice_flows_for_department
from app.models.employee import EmployeeRole
from app.models.supply import (
    Department, DepartmentBusinessType, SupplyRequest, SupplyRequestCycle,
    SupplyRequestDirection, SupplyRequestLine, SupplyUnit,
)
from app.models.user import User
from app.supply.parser import supported_unit_labels
from app.schemas.seller_supply import (
    SellerDepartmentRead, SellerRequestConfirm, SellerRequestRead,
    SellerRequestSave, SellerWindowRead,
)
from app.schemas.supply import SupplyRequestCreate
from app.supply.service import (
    SupplyRequestVersionConflictError, create_supply_request,
    get_supply_request, submit_supply_request,
)


class SellerWindowUnavailable(ValueError):
    pass


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _departments(db: Session, tenant_id: str) -> list[Department]:
    return [item for item in db.scalars(select(Department).where(
        Department.tenant_id == tenant_id,
        Department.is_active.is_(True),
        Department.business_type == DepartmentBusinessType.RETAIL_POINT,
    ).order_by(Department.display_order, Department.code)).all()
        if outgoing_invoice_flows_for_department(item.code)]


def _cycle(db: Session, tenant_id: str, now: datetime) -> SupplyRequestCycle | None:
    cycles = db.scalars(select(SupplyRequestCycle).join(SupplyRequestDirection).where(
        SupplyRequestCycle.tenant_id == tenant_id,
        SupplyRequestCycle.status == 'OPEN',
        SupplyRequestDirection.tenant_id == tenant_id,
        SupplyRequestDirection.is_active.is_(True),
    )).all()
    open_cycles = [item for item in cycles if _aware(item.opens_at) <= now <= _aware(item.hard_closes_at or item.closes_at)]
    if len(open_cycles) > 1:
        raise SellerWindowUnavailable('Открыто несколько окон заявок. Обратитесь к снабжению')
    return open_cycles[0] if open_cycles else None


def _seller_context(db: Session, user: User, department_id: UUID | None, allowed: list[Department], *, write: bool) -> tuple[ActionContext, Department | None]:
    base = resolve_action_context(
        db, user, required_roles=frozenset({EmployeeRole.SELLER}),
        role_precedence=(EmployeeRole.SELLER,), write=False,
    )
    allowed_by_id = {item.id: item for item in allowed}
    if base.shift_id is None:
        if write:
            raise ActionContextError('IIKO_SHIFT_REQUIRED', 'Для заявки требуется открытая смена iiko')
        return base, None
    if base.actual_department_id is not None:
        if department_id is not None and department_id != base.actual_department_id:
            raise ActionContextError('DEPARTMENT_FORBIDDEN', 'Точка определяется активной сменой')
        department = allowed_by_id.get(base.actual_department_id)
        if department is None:
            raise ActionContextError('SELLER_SHIFT_DEPARTMENT_INVALID', 'Точка смены недоступна для перемещения')
        if write:
            context = resolve_action_context(
                db, user, required_roles=frozenset({EmployeeRole.SELLER}),
                role_precedence=(EmployeeRole.SELLER,), write=True,
                requested_department_id=department.id,
            )
            return context, department
        return base, department
    if department_id is None:
        if write:
            raise ActionContextError('DEPARTMENT_REQUIRED', 'Выберите торговую точку')
        return base, None
    department = allowed_by_id.get(department_id)
    if department is None:
        raise ActionContextError('DEPARTMENT_FORBIDDEN', 'Торговая точка недоступна')
    context = replace(base, actual_department_id=department.id,
                      actual_department_name_snapshot=department.name)
    if write:
        db.info['action_context'] = context
        db.info['action_user'] = user
    return context, department


def _existing(db: Session, tenant_id: str, cycle: SupplyRequestCycle, department: Department, *, lock: bool = False) -> SupplyRequest | None:
    statement = select(SupplyRequest).where(
        SupplyRequest.tenant_id == tenant_id,
        SupplyRequest.cycle_id == cycle.id,
        SupplyRequest.direction_id == cycle.direction_id,
        SupplyRequest.department_id == department.id,
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _request_read(item: SupplyRequest) -> SellerRequestRead:
    return SellerRequestRead(id=item.id, status=item.status, version=item.version, raw_input=item.raw_input)


def current_window(db: Session, user: User, department_id: UUID | None = None, *, now: datetime | None = None) -> SellerWindowRead:
    now = now or datetime.now(timezone.utc)
    allowed = _departments(db, user.tenant_id)
    context, department = _seller_context(db, user, department_id, allowed, write=False)
    cycle = _cycle(db, user.tenant_id, now)
    if cycle is None:
        return SellerWindowRead(is_open=False, can_write=False, reason='Приём заявок сейчас закрыт')
    existing = _existing(db, user.tenant_id, cycle, department) if department else None
    catalog_codes = set(db.scalars(select(SupplyUnit.code).where(
        SupplyUnit.tenant_id == user.tenant_id, SupplyUnit.is_active.is_(True),
    )).all())
    return SellerWindowRead(
        is_open=True, can_write=context.shift_id is not None and department is not None,
        closes_at=cycle.hard_closes_at or cycle.closes_at,
        need_date=cycle.cycle_date + timedelta(days=1),
        cycle_id=cycle.id,
        department=SellerDepartmentRead(id=department.id, name=department.name) if department else None,
        allowed_departments=[SellerDepartmentRead(id=item.id, name=item.name) for item in allowed] if context.shift_id and base_is_unresolved(context) else [],
        supported_units=supported_unit_labels(catalog_codes),
        request=_request_read(existing) if existing and existing.created_by_user_id == user.id else None,
        reason='Для заявки требуется открытая смена iiko' if context.shift_id is None else None,
    )


def base_is_unresolved(context: ActionContext) -> bool:
    return context.shift_id is not None and context.actual_department_id is None


def _write_window(db: Session, user: User, department_id: UUID | None) -> tuple[SupplyRequestCycle, ActionContext, Department]:
    now = datetime.now(timezone.utc)
    cycle = _cycle(db, user.tenant_id, now)
    if cycle is None:
        raise SellerWindowUnavailable('Приём заявок сейчас закрыт')
    cycle = db.scalar(select(SupplyRequestCycle).where(SupplyRequestCycle.id == cycle.id).with_for_update().execution_options(populate_existing=True))
    if cycle is None or cycle.status != 'OPEN' or not (_aware(cycle.opens_at) <= now <= _aware(cycle.hard_closes_at or cycle.closes_at)):
        raise SellerWindowUnavailable('Приём заявок сейчас закрыт')
    context, department = _seller_context(db, user, department_id, _departments(db, user.tenant_id), write=True)
    if department is None:
        raise SellerWindowUnavailable('Торговая точка не определена')
    return cycle, context, department


def save_request(db: Session, user: User, payload: SellerRequestSave) -> SellerRequestRead:
    cycle, context, department = _write_window(db, user, payload.department_id)
    item = _existing(db, user.tenant_id, cycle, department, lock=True)
    if item is None:
        if payload.expected_version is not None:
            raise SellerWindowUnavailable('Заявка изменилась. Обновите страницу')
        created = create_supply_request(
            db, SupplyRequestCreate(
                department_id=department.id, direction_id=cycle.direction_id,
                cycle_id=cycle.id, need_date=cycle.cycle_date + timedelta(days=1),
                raw_input=payload.raw_input,
                lines=[{'raw_text': line} for line in payload.raw_input.splitlines()],
            ), created_by_user_id=user.id, audit_context=context, actor_user=user,
        )
        return _request_read(created)
    if item.created_by_user_id != user.id or item.status not in {'DRAFT', 'SUBMITTED'}:
        raise SellerWindowUnavailable('Эту заявку нельзя изменить')
    if payload.expected_version != item.version:
        raise SupplyRequestVersionConflictError(item.version, payload.expected_version)
    before = {'raw_input': item.raw_input, 'status': item.status, 'version': item.version}
    item.lines.clear()
    db.flush()
    item.lines = [SupplyRequestLine(tenant_id=user.tenant_id, position=index, raw_text=line)
                  for index, line in enumerate(payload.raw_input.splitlines(), start=1)]
    item.raw_input = payload.raw_input
    item.status = 'DRAFT'
    item.submitted_at = None
    item.version += 1
    record_audit_event(
        db, tenant_id=user.tenant_id, event_type='SUPPLY_REQUEST_SELLER_EDITED',
        entity_type='SupplyRequest', entity_id=item.id, operation='UPDATE',
        context=context, actor_user=user, before=before,
        after={'raw_input': item.raw_input, 'status': item.status, 'version': item.version},
    )
    db.commit()
    return _request_read(get_supply_request(db, item.id, tenant_id=user.tenant_id))


def confirm_request(db: Session, user: User, payload: SellerRequestConfirm) -> SellerRequestRead:
    cycle, context, department = _write_window(db, user, payload.department_id)
    item = _existing(db, user.tenant_id, cycle, department, lock=True)
    if item is None or item.created_by_user_id != user.id:
        raise SellerWindowUnavailable('Заявка не найдена')
    if payload.expected_version != item.version:
        raise SupplyRequestVersionConflictError(item.version, payload.expected_version)
    if item.status == 'SUBMITTED':
        return _request_read(item)
    if item.status != 'DRAFT':
        raise SellerWindowUnavailable('Эту заявку нельзя подтвердить')
    return _request_read(submit_supply_request(
        db, item.id, expected_version=item.version, audit_context=context, actor_user=user,
    ))
