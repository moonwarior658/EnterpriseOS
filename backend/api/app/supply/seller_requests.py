from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.core.action_context import ActionContext, ActionContextError, resolve_action_context
from app.core.authorization import (
    Capability, GRANTS, supply_request_authorize,
)
from app.models.employee import EmployeeRole, EmployeeIikoShift
from app.models.supply import (
    Department, SupplyRequest, SupplyRequestCycle,
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


def _departments(db: Session, user: User) -> list[Department]:
    departments = db.scalars(select(Department).where(
        Department.tenant_id == user.tenant_id,
        Department.is_active.is_(True),
    ).order_by(Department.display_order, Department.code)).all()
    allowed = []
    for department in departments:
        try:
            supply_request_authorize(db, user, Capability.SUPPLY_REQUEST_CREATE,
                                     department_id=department.id, write=False)
        except ActionContextError:
            continue
        allowed.append(department)
    return allowed


def _seller_only(context: ActionContext) -> bool:
    return EmployeeRole.SELLER in context.roles and not any(
        role in context.roles for role, _ in GRANTS[Capability.SUPPLY_REQUEST_CREATE]
        if role != EmployeeRole.SELLER
    )


def _own_window_request(db: Session, user: User, cycle: SupplyRequestCycle) -> SupplyRequest | None:
    base = resolve_action_context(db, user, write=False)
    if not _seller_only(base):
        return None
    requests = db.scalars(select(SupplyRequest).where(
        SupplyRequest.tenant_id == user.tenant_id,
        SupplyRequest.cycle_id == cycle.id,
        SupplyRequest.created_by_user_id == user.id,
    )).all()
    if len(requests) > 1:
        raise SellerWindowUnavailable('В текущем окне найдено несколько ваших заявок. Обратитесь к снабжению')
    return requests[0] if requests else None


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
    base = resolve_action_context(db, user, write=False)
    if not any(role in base.roles for role, _ in GRANTS[Capability.SUPPLY_REQUEST_CREATE]):
        raise ActionContextError('PERMISSION_DENIED', 'Недостаточно прав для создания заявки')
    allowed_by_id = {item.id: item for item in allowed}
    if department_id is None and _seller_only(base):
        shift = db.get(EmployeeIikoShift, base.shift_id) if base.shift_id else None
        department_id = shift.department_id if shift and shift.department_id in allowed_by_id else None
    department = allowed_by_id.get(department_id)
    if department_id is not None and department is None:
        raise ActionContextError('DEPARTMENT_FORBIDDEN', 'Подразделение недоступно для заявки')
    if department is None:
        if write:
            raise ActionContextError('DEPARTMENT_REQUIRED', 'Выберите подразделение')
        return base, None
    context = supply_request_authorize(db, user, Capability.SUPPLY_REQUEST_CREATE,
                                       department_id=department.id, write=write)
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
    base = resolve_action_context(db, user, write=False)
    allowed = _departments(db, user)
    cycle = _cycle(db, user.tenant_id, now)
    if cycle is None:
        return SellerWindowRead(is_open=False, can_write=False, reason='Приём заявок сейчас закрыт')
    if not allowed:
        return SellerWindowRead(is_open=True, can_write=False,
                                closes_at=cycle.hard_closes_at or cycle.closes_at,
                                reason='Нет доступных подразделений для создания заявки')
    own = _own_window_request(db, user, cycle)
    if own is not None:
        department_id = own.department_id
    context, department = _seller_context(db, user, department_id, allowed, write=False)
    existing = _existing(db, user.tenant_id, cycle, department) if department else None
    can_write = department is not None and (existing is None or (
        existing.created_by_user_id == user.id and existing.status in {'DRAFT', 'SUBMITTED'}
    ))
    if can_write and existing is not None and existing.status == 'SUBMITTED':
        try:
            supply_request_authorize(db, user, Capability.SUPPLY_REQUEST_EDIT,
                                     request=existing, write=False)
        except ActionContextError:
            can_write = False
    reason = None
    if department is None:
        reason = 'Выберите торговую точку' if _seller_only(base) else 'Выберите подразделение'
    elif not can_write:
        reason = 'Для выбранного подразделения уже есть заявка, которую нельзя изменить в этой форме'
    catalog_codes = set(db.scalars(select(SupplyUnit.code).where(
        SupplyUnit.tenant_id == user.tenant_id, SupplyUnit.is_active.is_(True),
    )).all())
    return SellerWindowRead(
        is_open=True, can_write=can_write,
        allowed_actions=['CREATE'] if own is None or own.status in {'DRAFT', 'SUBMITTED'} else [],
        department_label='Точка' if _seller_only(base) else 'Подразделение',
        closes_at=cycle.hard_closes_at or cycle.closes_at,
        need_date=cycle.cycle_date + timedelta(days=1), cycle_id=cycle.id,
        department=SellerDepartmentRead(id=department.id, name=department.name) if department else None,
        allowed_departments=[SellerDepartmentRead(id=item.id, name=item.name) for item in allowed],
        supported_units=supported_unit_labels(catalog_codes),
        request=_request_read(existing) if existing and existing.created_by_user_id == user.id else None,
        reason=reason,
    )


def _write_window(db: Session, user: User, department_id: UUID | None) -> tuple[SupplyRequestCycle, ActionContext, Department]:
    now = datetime.now(timezone.utc)
    cycle = _cycle(db, user.tenant_id, now)
    if cycle is None:
        raise SellerWindowUnavailable('Приём заявок сейчас закрыт')
    cycle = db.scalar(select(SupplyRequestCycle).where(SupplyRequestCycle.id == cycle.id).with_for_update().execution_options(populate_existing=True))
    if cycle is None or cycle.status != 'OPEN' or not (_aware(cycle.opens_at) <= now <= _aware(cycle.hard_closes_at or cycle.closes_at)):
        raise SellerWindowUnavailable('Приём заявок сейчас закрыт')
    own = _own_window_request(db, user, cycle)
    if own is not None:
        if department_id is not None and department_id != own.department_id:
            raise SellerWindowUnavailable('В текущем окне уже есть ваша заявка. Откройте её для изменения')
        department_id = own.department_id
    context, department = _seller_context(db, user, department_id, _departments(db, user), write=True)
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
    if item.status == 'SUBMITTED':
        context = supply_request_authorize(db, user, Capability.SUPPLY_REQUEST_EDIT,
                                           request=item, write=True)
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
