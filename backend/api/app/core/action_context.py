from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.models.employee import (
    Employee,
    EmployeeDepartmentAssignment,
    EmployeeIikoShift,
    EmployeeIikoShiftStatus,
    EmployeeRole,
    EmployeeRoleAssignment,
    EmployeeStatus,
    ShiftDepartmentConfirmation,
)
from app.models.supply import Department, DepartmentBusinessType
from app.models.user import User, UserAccountType


class ActionContextError(PermissionError):
    def __init__(self, code: str, message: str, *, context: dict | None = None):
        self.code = code
        self.message = message
        self.context = context or {}
        super().__init__(message)


@dataclass(frozen=True)
class ActionContext:
    user_id: int
    employee_id: UUID
    roles: frozenset[EmployeeRole]
    authorized_as: EmployeeRole | None
    employee_name_snapshot: str
    primary_department_id: UUID | None
    primary_department_name_snapshot: str | None
    actual_department_id: UUID | None
    actual_department_name_snapshot: str | None
    shift_id: UUID | None
    shift_opened_at: datetime | None
    substitution_confirmed: bool
    determined_at: datetime


def _active_period(at: datetime, model):
    return (
        model.valid_from <= at,
        or_(model.valid_to.is_(None), model.valid_to > at),
    )


def _linked_employee(db: Session, user: User) -> Employee:
    employee = db.scalar(select(Employee).where(
        Employee.tenant_id == user.tenant_id,
        Employee.linked_user_id == user.id,
    ))
    if employee is None:
        raise ActionContextError(
            "EMPLOYEE_NOT_LINKED",
            "Учётная запись не связана с сотрудником",
        )
    if employee.status != EmployeeStatus.ACTIVE:
        raise ActionContextError(
            "EMPLOYEE_DISMISSED",
            "Действия уволенного сотрудника запрещены",
        )
    return employee


def resolve_action_context(
    db: Session,
    user: User,
    *,
    required_roles: frozenset[EmployeeRole] = frozenset(),
    role_precedence: tuple[EmployeeRole, ...] = (),
    write: bool,
    requested_department_id: UUID | None = None,
    allow_unconfirmed_substitution: bool = False,
    at: datetime | None = None,
) -> ActionContext:
    determined_at = at or datetime.now(timezone.utc)
    if not user.is_active:
        raise ActionContextError("USER_INACTIVE", "Учётная запись заблокирована")
    if user.account_type != UserAccountType.HUMAN:
        raise ActionContextError(
            "EMPLOYEE_NOT_LINKED",
            "Действие требует личной учётной записи сотрудника",
        )
    employee = _linked_employee(db, user)

    roles = frozenset(db.scalars(select(EmployeeRoleAssignment.role).where(
        EmployeeRoleAssignment.tenant_id == user.tenant_id,
        EmployeeRoleAssignment.employee_id == employee.id,
        *_active_period(determined_at, EmployeeRoleAssignment),
    )).all())
    allowed_roles = roles & required_roles
    if required_roles and not allowed_roles:
        raise ActionContextError(
            "ROLE_REQUIRED",
            "Для действия не назначена требуемая роль",
            context={"required_roles": sorted(role.value for role in required_roles)},
        )
    authorized_as = None
    if required_roles:
        if role_precedence:
            authorized_as = next(
                (role for role in role_precedence if role in allowed_roles), None
            )
            if authorized_as is None:
                raise ActionContextError(
                    "ROLE_REQUIRED",
                    "Для действия не назначена требуемая роль",
                    context={"required_roles": [role.value for role in role_precedence]},
                )
        elif len(allowed_roles) == 1:
            authorized_as = next(iter(allowed_roles))
        else:
            raise ActionContextError(
                "AUTHORIZATION_ROLE_AMBIGUOUS",
                "Для действия не определена авторизующая роль",
            )

    assignments = list(db.scalars(select(EmployeeDepartmentAssignment).where(
        EmployeeDepartmentAssignment.tenant_id == user.tenant_id,
        EmployeeDepartmentAssignment.employee_id == employee.id,
        *_active_period(determined_at, EmployeeDepartmentAssignment),
    )).all())
    primary = next((item for item in assignments if item.is_primary), None)
    primary_department_id = primary.department_id if primary else None

    if authorized_as == EmployeeRole.SELLER:
        primary_department = db.get(Department, primary_department_id) if primary_department_id else None
        if (len(assignments) != 1 or primary_department is None
                or not primary_department.is_active
                or primary_department.business_type != DepartmentBusinessType.RETAIL_POINT):
            raise ActionContextError("SELLER_DEPARTMENT_INVALID", "Рабочая точка продавца не определена")
    if authorized_as == EmployeeRole.DRIVER:
        primary_department = db.get(Department, primary_department_id) if primary_department_id else None
        if (len(assignments) != 1 or primary_department is None
                or not primary_department.is_active
                or primary_department.business_type != DepartmentBusinessType.AUTO):
            raise ActionContextError("DRIVER_DEPARTMENT_INVALID", "Подразделение водителя не определено")
    if authorized_as in {EmployeeRole.HEAD_OF_PRODUCTION, EmployeeRole.CHEF_CONFECTIONER}:
        production_ids = {item.department_id for item in assignments if (
            (department := db.get(Department, item.department_id)) is not None
            and department.tenant_id == user.tenant_id and department.is_active
            and department.business_type == DepartmentBusinessType.PRODUCTION
        )}
        if not production_ids or (requested_department_id is not None
                                  and requested_department_id not in production_ids):
            raise ActionContextError("PRODUCTION_DEPARTMENT_INVALID", "Производственное подразделение не назначено")
        if primary_department_id not in production_ids and requested_department_id is None:
            raise ActionContextError("PRODUCTION_DEPARTMENT_INVALID", "Производственное подразделение не назначено")

    shift = db.scalar(select(EmployeeIikoShift).where(
        EmployeeIikoShift.tenant_id == user.tenant_id,
        EmployeeIikoShift.employee_id == employee.id,
        EmployeeIikoShift.status == EmployeeIikoShiftStatus.OPEN,
    ).order_by(EmployeeIikoShift.opened_at.desc()))
    seller_shift_required = write and authorized_as == EmployeeRole.SELLER

    if seller_shift_required and shift is None:
        raise ActionContextError(
            "IIKO_SHIFT_REQUIRED",
            "Для записи откройте личную смену iiko",
        )
    if seller_shift_required and shift is not None and shift.department_id is None:
        raise ActionContextError(
            "IIKO_SHIFT_DEPARTMENT_UNRESOLVED",
            "Подразделение активной смены iiko не сопоставлено с EOS",
        )
    if seller_shift_required and shift is not None:
        shift_department = db.get(Department, shift.department_id)
        if (shift_department is None or shift_department.tenant_id != user.tenant_id
                or not shift_department.is_active
                or shift_department.business_type != DepartmentBusinessType.RETAIL_POINT):
            raise ActionContextError(
                "SELLER_SHIFT_DEPARTMENT_INVALID", "Смена открыта вне торговой точки",
            )

    actual_department_id = (
        shift.department_id
        if authorized_as == EmployeeRole.SELLER and shift is not None
        else primary_department_id
    )
    if requested_department_id is not None:
        if seller_shift_required:
            department_allowed = requested_department_id == actual_department_id
        else:
            department_allowed = requested_department_id in {
                assignment.department_id for assignment in assignments
            }
        if not department_allowed:
            raise ActionContextError(
                "DEPARTMENT_FORBIDDEN",
                "Нельзя выполнить действие от имени выбранного подразделения",
                context={
                    "actual_department_id": (
                        str(actual_department_id) if actual_department_id else None
                    )
                },
            )
        if not seller_shift_required:
            actual_department_id = requested_department_id

    substitution = bool(
        seller_shift_required
        and shift is not None
        and primary_department_id is not None
        and shift.department_id != primary_department_id
    )
    confirmation = None
    if substitution:
        confirmation = db.scalar(select(ShiftDepartmentConfirmation).where(
            ShiftDepartmentConfirmation.tenant_id == user.tenant_id,
            ShiftDepartmentConfirmation.employee_id == employee.id,
            ShiftDepartmentConfirmation.shift_id == shift.id,
        ))
        if confirmation is None and not allow_unconfirmed_substitution:
            primary_department = db.get(Department, primary_department_id)
            actual_department = db.get(Department, shift.department_id)
            raise ActionContextError(
                "SHIFT_SUBSTITUTION_CONFIRMATION_REQUIRED",
                "Подтвердите работу от имени фактического подразделения",
                context={
                    "shift_id": str(shift.id),
                    "primary_department_id": str(primary_department_id),
                    "primary_department_name": primary_department.name if primary_department else None,
                    "actual_department_id": str(shift.department_id),
                    "actual_department_name": actual_department.name if actual_department else None,
                },
            )

    primary_department = (
        db.get(Department, primary_department_id) if primary_department_id else None
    )
    actual_department = (
        db.get(Department, actual_department_id) if actual_department_id else None
    )
    return ActionContext(
        user_id=user.id,
        employee_id=employee.id,
        roles=roles,
        authorized_as=authorized_as,
        employee_name_snapshot=employee.full_name,
        primary_department_id=primary_department_id,
        primary_department_name_snapshot=(primary_department.name if primary_department else None),
        actual_department_id=actual_department_id,
        actual_department_name_snapshot=(actual_department.name if actual_department else None),
        shift_id=shift.id if shift else None,
        shift_opened_at=shift.opened_at if shift else None,
        substitution_confirmed=confirmation is not None,
        determined_at=determined_at,
    )


def confirm_shift_substitution(
    db: Session,
    user: User,
    *,
    shift_id: UUID,
    at: datetime | None = None,
) -> ActionContext:
    context = resolve_action_context(
        db,
        user,
        required_roles=frozenset({EmployeeRole.SELLER}),
        role_precedence=(EmployeeRole.SELLER,),
        write=True,
        allow_unconfirmed_substitution=True,
        at=at,
    )
    if context.shift_id != shift_id:
        raise ActionContextError(
            "IIKO_SHIFT_REQUIRED",
            "Активная смена изменилась. Обновите данные и повторите действие",
        )
    if context.primary_department_id == context.actual_department_id:
        return context
    confirmation = ShiftDepartmentConfirmation(
        tenant_id=user.tenant_id,
        employee_id=context.employee_id,
        shift_id=shift_id,
        primary_department_id=context.primary_department_id,
        actual_department_id=context.actual_department_id,
        confirmed_at=context.determined_at,
        actor_user_id=user.id,
    )
    db.add(confirmation)
    try:
        db.flush()
        record_audit_event(
            db,
            tenant_id=user.tenant_id,
            event_type="SHIFT_SUBSTITUTION_CONFIRMED",
            entity_type="ShiftDepartmentConfirmation",
            entity_id=confirmation.id,
            operation="CONFIRM_SUBSTITUTION",
            context=context,
            actor_user=user,
            before={},
            after={
                "primary_department_id": context.primary_department_id,
                "actual_department_id": context.actual_department_id,
                "shift_id": shift_id,
            },
        )
        db.commit()
    except IntegrityError:
        db.rollback()
    return resolve_action_context(
        db,
        user,
        required_roles=frozenset({EmployeeRole.SELLER}),
        role_precedence=(EmployeeRole.SELLER,),
        write=True,
        at=context.determined_at,
    )
