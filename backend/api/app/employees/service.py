from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.audit.service import record_audit_event
from app.core.action_context import ActionContext, ActionContextError, resolve_action_context
from app.core.authorization import Capability, authorize
from app.core.security import generate_password, hash_password
from app.models.employee import (
    Employee, EmployeeDepartmentAssignment, EmployeeLifecycleEvent,
    EmployeeLifecycleEventType, EmployeeRole, EmployeeRoleAssignment, EmployeeStatus,
)
from app.models.supply import Department, DepartmentBusinessType
from app.models.user import User, UserAccountType
from app.schemas.employee import (
    AssignmentEnd, EmployeeBootstrapCreate, EmployeeBootstrapStatus, EmployeeCreate,
    EmployeeDepartmentAssignmentCreate,
    EmployeeDismiss, EmployeeReactivate, EmployeeRoleAssignmentCreate,
    EmployeeUpdate,
)


EMPLOYEE_LOAD = (
    selectinload(Employee.role_assignments),
    selectinload(Employee.department_assignments),
    selectinload(Employee.lifecycle_events),
)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _require_active(employee: Employee) -> None:
    if employee.status != EmployeeStatus.ACTIVE:
        raise _conflict("Assignments cannot be changed for a dismissed employee")


def _admin_context(
    db: Session, actor: User, capability: Capability = Capability.EMPLOYEE_WRITE,
    employee: Employee | None = None, assigned_role: EmployeeRole | None = None,
    department_id: UUID | None = None,
) -> ActionContext:
    try:
        return authorize(db, actor, capability, target=employee, write=True,
                         assigned_role=assigned_role, department_id=department_id)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail={"code": error.code, "message": error.message}) from error


def _employee_query(tenant_id: str):
    return (
        select(Employee)
        .where(Employee.tenant_id == tenant_id)
        .options(*EMPLOYEE_LOAD)
        .execution_options(populate_existing=True)
    )


def get_employee(db: Session, employee_id: UUID, tenant_id: str, *, lock: bool = False) -> Employee:
    query = _employee_query(tenant_id).where(Employee.id == employee_id)
    if lock:
        query = query.with_for_update()
    employee = db.scalar(query)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


def linked_user_id(db: Session, employee_id: UUID, tenant_id: str) -> int | None:
    return db.scalar(select(Employee.linked_user_id).where(
        Employee.id == employee_id, Employee.tenant_id == tenant_id,
    ))


def _has_admin_assignment(db: Session, tenant_id: str) -> bool:
    return db.scalar(select(EmployeeRoleAssignment.id).where(
        EmployeeRoleAssignment.tenant_id == tenant_id,
        EmployeeRoleAssignment.role == EmployeeRole.ADMIN,
    ).limit(1)) is not None


def first_admin_bootstrap_status(db: Session, actor: User) -> EmployeeBootstrapStatus:
    unavailable_reason = None
    if actor.account_type != UserAccountType.HUMAN:
        unavailable_reason = "SERVICE_ACCOUNT_FORBIDDEN"
    elif not actor.is_admin:
        unavailable_reason = "LEGACY_ADMIN_REQUIRED"
    elif db.scalar(select(Employee.id).where(
        Employee.tenant_id == actor.tenant_id,
        Employee.linked_user_id == actor.id,
    ).limit(1)) is not None:
        unavailable_reason = "CURRENT_USER_ALREADY_LINKED"
    elif _has_admin_assignment(db, actor.tenant_id):
        unavailable_reason = "ADMIN_EMPLOYEE_ALREADY_EXISTS"
    return EmployeeBootstrapStatus(
        available=unavailable_reason is None,
        username=actor.username,
        unavailable_reason=unavailable_reason,
    )


def bootstrap_first_admin(
    db: Session, payload: EmployeeBootstrapCreate, actor: User,
) -> Employee:
    # Every bootstrap attempt for a tenant locks the same stable row set. This
    # prevents two legacy admins from both observing an empty ADMIN assignment set.
    tenant_users = db.scalars(select(User).where(
        User.tenant_id == actor.tenant_id,
    ).order_by(User.id).with_for_update()).all()
    actor = next((item for item in tenant_users if item.id == actor.id), actor)

    if actor.account_type != UserAccountType.HUMAN:
        raise HTTPException(
            status_code=403,
            detail="Сервисная учётная запись не может создать первого администратора",
        )
    if not actor.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Bootstrap доступен только legacy-администратору",
        )
    if db.scalar(select(Employee.id).where(
        Employee.tenant_id == actor.tenant_id,
        Employee.linked_user_id == actor.id,
    ).limit(1)) is not None:
        raise _conflict("Текущая учётная запись уже связана с сотрудником")
    if _has_admin_assignment(db, actor.tenant_id):
        raise _conflict(
            "Роль ADMIN уже назначалась сотруднику; bootstrap навсегда недоступен"
        )

    department = db.scalar(select(Department).where(
        Department.id == payload.department_id,
        Department.tenant_id == actor.tenant_id,
        Department.is_active.is_(True),
    ).with_for_update())
    if department is None:
        raise HTTPException(status_code=404, detail="Активное подразделение не найдено")

    now = datetime.now(UTC)
    employee = Employee(
        tenant_id=actor.tenant_id,
        linked_user_id=actor.id,
        full_name=payload.full_name,
        birth_date=payload.birth_date,
        photo_url=payload.photo_url,
        phone=payload.phone,
        residence_address=payload.residence_address,
    )
    db.add(employee)
    db.flush()
    db.add_all([
        EmployeeLifecycleEvent(
            tenant_id=actor.tenant_id,
            employee_id=employee.id,
            event_type=EmployeeLifecycleEventType.CREATED,
            effective_date=now.date(),
            reason=payload.reason,
            actor_user_id=actor.id,
        ),
        EmployeeLifecycleEvent(
            tenant_id=actor.tenant_id,
            employee_id=employee.id,
            event_type=EmployeeLifecycleEventType.USER_LINKED,
            effective_date=now.date(),
            reason=payload.reason,
            actor_user_id=actor.id,
        ),
        EmployeeRoleAssignment(
            tenant_id=actor.tenant_id,
            employee_id=employee.id,
            role=EmployeeRole.ADMIN,
            valid_from=now,
            reason=payload.reason,
            assigned_by_user_id=actor.id,
        ),
        EmployeeDepartmentAssignment(
            tenant_id=actor.tenant_id,
            employee_id=employee.id,
            department_id=department.id,
            is_primary=True,
            valid_from=now,
            reason=payload.reason,
            assigned_by_user_id=actor.id,
        ),
    ])
    try:
        db.flush()
        context = resolve_action_context(
            db,
            actor,
            required_roles=frozenset({EmployeeRole.ADMIN}),
            role_precedence=(EmployeeRole.ADMIN,),
            write=True,
            at=now,
        )
        audit_events = (
            ("FIRST_ADMIN_BOOTSTRAPPED", "BOOTSTRAP", {}, {
                "linked_user_id": actor.id,
                "role": EmployeeRole.ADMIN.value,
                "primary_department_id": department.id,
            }),
            ("EMPLOYEE_CREATED", "CREATE", {}, {
                "full_name": employee.full_name,
                "status": employee.status.value,
            }),
            ("EMPLOYEE_USER_LINKED", "LINK_USER", {"linked_user_id": None}, {
                "linked_user_id": actor.id,
            }),
            ("EMPLOYEE_ROLE_ASSIGNED", "ASSIGN_ROLE", {}, {
                "role": EmployeeRole.ADMIN.value,
                "valid_from": now,
            }),
            ("EMPLOYEE_DEPARTMENT_ASSIGNED", "ASSIGN_DEPARTMENT", {}, {
                "department_id": department.id,
                "is_primary": True,
                "valid_from": now,
            }),
        )
        for event_type, operation, before, after in audit_events:
            record_audit_event(
                db,
                tenant_id=actor.tenant_id,
                event_type=event_type,
                entity_type="Employee",
                entity_id=employee.id,
                operation=operation,
                context=context,
                actor_user=actor,
                before=before,
                after=after,
                reason=payload.reason,
            )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict("Bootstrap конфликтует с существующими данными сотрудника") from error
    return get_employee(db, employee.id, actor.tenant_id)


def create_employee(db: Session, payload: EmployeeCreate, actor: User) -> Employee:
    context = _admin_context(db, actor, department_id=payload.department_id)
    if context.authorized_as == EmployeeRole.NETWORK_MANAGER:
        department = db.get(Department, payload.department_id) if payload.department_id else None
        if department is None or department.business_type not in {
            DepartmentBusinessType.RETAIL_POINT, DepartmentBusinessType.AUTO,
        }:
            raise HTTPException(status_code=422, detail="Выберите торговую точку или Авто")
    employee = Employee(
        tenant_id=actor.tenant_id, full_name=payload.full_name, birth_date=payload.birth_date,
        photo_url=payload.photo_url, phone=payload.phone,
        residence_address=payload.residence_address,
    )
    db.add(employee)
    db.flush()
    if context.authorized_as == EmployeeRole.NETWORK_MANAGER:
        if payload.department_id is None:
            raise HTTPException(status_code=422, detail="Выберите рабочую точку сотрудника")
        db.add(EmployeeDepartmentAssignment(
            tenant_id=actor.tenant_id, employee_id=employee.id,
            department_id=payload.department_id, is_primary=True,
            valid_from=datetime.now(UTC), reason=payload.reason,
            assigned_by_user_id=actor.id,
        ))
        record_audit_event(
            db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_DEPARTMENT_ASSIGNED",
            entity_type="Employee", entity_id=employee.id, operation="ASSIGN_DEPARTMENT",
            context=context, actor_user=actor, before={},
            after={"department_id": payload.department_id, "is_primary": True},
            reason=payload.reason,
        )
    db.add(EmployeeLifecycleEvent(
        tenant_id=actor.tenant_id, employee_id=employee.id,
        event_type=EmployeeLifecycleEventType.CREATED, effective_date=date.today(),
        reason=payload.reason, actor_user_id=actor.id,
    ))
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_CREATED",
        entity_type="Employee", entity_id=employee.id, operation="CREATE",
        context=context, actor_user=actor, before={},
        after={"full_name": employee.full_name, "status": employee.status.value},
        reason=payload.reason,
    )
    db.commit()
    return get_employee(db, employee.id, actor.tenant_id)


def update_employee(db: Session, employee: Employee, payload: EmployeeUpdate, actor: User) -> Employee:
    context = _admin_context(db, actor, employee=employee)
    updates = payload.model_dump(exclude_unset=True, exclude={"reason"})
    before = {"changed_fields": sorted(updates)}
    after = {"changed_fields": sorted(updates)}
    if "full_name" in updates:
        before["full_name"] = employee.full_name
        after["full_name"] = updates["full_name"]
    for field, value in updates.items():
        setattr(employee, field, value)
    db.add(EmployeeLifecycleEvent(
        tenant_id=actor.tenant_id, employee_id=employee.id,
        event_type=EmployeeLifecycleEventType.UPDATED, effective_date=date.today(),
        reason=payload.reason, actor_user_id=actor.id,
    ))
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_UPDATED",
        entity_type="Employee", entity_id=employee.id, operation="UPDATE",
        context=context, actor_user=actor, before=before, after=after,
        reason=payload.reason,
    )
    db.commit()
    return get_employee(db, employee.id, employee.tenant_id)


def assign_role(db: Session, employee: Employee, payload: EmployeeRoleAssignmentCreate, actor: User):
    context = _admin_context(db, actor, Capability.ROLE_ASSIGN, employee, payload.role)
    _require_active(employee)
    if payload.role in {EmployeeRole.SELLER, EmployeeRole.DRIVER}:
        departments = list(db.execute(select(Department, EmployeeDepartmentAssignment.is_primary).join(
            EmployeeDepartmentAssignment,
            EmployeeDepartmentAssignment.department_id == Department.id,
        ).where(
            EmployeeDepartmentAssignment.tenant_id == actor.tenant_id,
            EmployeeDepartmentAssignment.employee_id == employee.id,
            EmployeeDepartmentAssignment.valid_from <= payload.valid_from,
            (EmployeeDepartmentAssignment.valid_to.is_(None)
             | (EmployeeDepartmentAssignment.valid_to > payload.valid_from)),
        )).all())
        expected = (DepartmentBusinessType.RETAIL_POINT if payload.role == EmployeeRole.SELLER
                    else DepartmentBusinessType.AUTO)
        if (len(departments) != 1 or not departments[0].is_primary
                or departments[0].Department.business_type != expected
                or not departments[0].Department.is_active):
            raise _conflict("Для роли требуется одно основное подразделение допустимой категории")
    existing = db.scalar(select(EmployeeRoleAssignment.id).where(
        EmployeeRoleAssignment.tenant_id == actor.tenant_id,
        EmployeeRoleAssignment.employee_id == employee.id,
        EmployeeRoleAssignment.role == payload.role,
        (
            EmployeeRoleAssignment.valid_to.is_(None)
            | (EmployeeRoleAssignment.valid_to > payload.valid_from)
        ),
    ))
    if existing is not None:
        raise _conflict("Role assignment overlaps an existing assignment")
    assignment = EmployeeRoleAssignment(
        tenant_id=actor.tenant_id, employee_id=employee.id, role=payload.role,
        valid_from=payload.valid_from, reason=payload.reason, assigned_by_user_id=actor.id,
    )
    db.add(assignment)
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_ROLE_ASSIGNED",
        entity_type="Employee", entity_id=employee.id, operation="ASSIGN_ROLE",
        context=context, actor_user=actor, before={},
        after={"role": payload.role.value, "valid_from": payload.valid_from},
        reason=payload.reason,
    )
    _commit_integrity(db, "Active role assignment conflicts with an existing assignment")
    db.refresh(assignment)
    return assignment


def assign_department(db: Session, employee: Employee, payload: EmployeeDepartmentAssignmentCreate, actor: User):
    context = _admin_context(db, actor, Capability.DEPARTMENT_ASSIGN, employee,
                             department_id=payload.department_id)
    _require_active(employee)
    department = db.scalar(select(Department).where(
        Department.id == payload.department_id, Department.tenant_id == actor.tenant_id,
    ))
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    if not department.is_active:
        raise _conflict("Подразделение неактивно")
    roles = set(db.scalars(select(EmployeeRoleAssignment.role).where(
        EmployeeRoleAssignment.tenant_id == actor.tenant_id,
        EmployeeRoleAssignment.employee_id == employee.id,
        EmployeeRoleAssignment.valid_from <= payload.valid_from,
        (EmployeeRoleAssignment.valid_to.is_(None)
         | (EmployeeRoleAssignment.valid_to > payload.valid_from)),
    )).all())
    required = ({EmployeeRole.SELLER: DepartmentBusinessType.RETAIL_POINT,
                 EmployeeRole.DRIVER: DepartmentBusinessType.AUTO})
    for role, category in required.items():
        if role in roles:
            if department.business_type != category or not payload.is_primary:
                raise _conflict("Роль допускает только одно основное подразделение своей категории")
            others = db.scalar(select(EmployeeDepartmentAssignment.id).where(
                EmployeeDepartmentAssignment.tenant_id == actor.tenant_id,
                EmployeeDepartmentAssignment.employee_id == employee.id,
                (EmployeeDepartmentAssignment.valid_to.is_(None)
                 | (EmployeeDepartmentAssignment.valid_to > payload.valid_from)),
            ))
            if others is not None:
                raise _conflict("Сначала завершите прежнее назначение подразделения")
    if context.authorized_as == EmployeeRole.NETWORK_MANAGER:
        if department.business_type not in {DepartmentBusinessType.RETAIL_POINT,
                                            DepartmentBusinessType.AUTO}:
            raise _conflict("Недопустимая категория подразделения")
        if department.business_type == DepartmentBusinessType.AUTO and EmployeeRole.DRIVER not in roles:
            raise _conflict("Авто можно назначить только водителю")
    if payload.is_primary:
        primary = db.scalar(select(EmployeeDepartmentAssignment.id).where(
            EmployeeDepartmentAssignment.tenant_id == actor.tenant_id,
            EmployeeDepartmentAssignment.employee_id == employee.id,
            EmployeeDepartmentAssignment.is_primary.is_(True),
            (
                EmployeeDepartmentAssignment.valid_to.is_(None)
                | (EmployeeDepartmentAssignment.valid_to > payload.valid_from)
            ),
        ))
        if primary is not None:
            raise _conflict("Employee already has an active primary department")
    duplicate = db.scalar(select(EmployeeDepartmentAssignment.id).where(
        EmployeeDepartmentAssignment.tenant_id == actor.tenant_id,
        EmployeeDepartmentAssignment.employee_id == employee.id,
        EmployeeDepartmentAssignment.department_id == payload.department_id,
        (
            EmployeeDepartmentAssignment.valid_to.is_(None)
            | (EmployeeDepartmentAssignment.valid_to > payload.valid_from)
        ),
    ))
    if duplicate is not None:
        raise _conflict("Employee already has an active assignment for this department")
    assignment = EmployeeDepartmentAssignment(
        tenant_id=actor.tenant_id, employee_id=employee.id,
        department_id=payload.department_id, is_primary=payload.is_primary,
        valid_from=payload.valid_from, reason=payload.reason, assigned_by_user_id=actor.id,
    )
    db.add(assignment)
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_DEPARTMENT_ASSIGNED",
        entity_type="Employee", entity_id=employee.id, operation="ASSIGN_DEPARTMENT",
        context=context, actor_user=actor, before={},
        after={
            "department_id": payload.department_id,
            "is_primary": payload.is_primary,
            "valid_from": payload.valid_from,
        },
        reason=payload.reason,
    )
    _commit_integrity(db, "Active department assignment conflicts with an existing assignment")
    db.refresh(assignment)
    return assignment


def end_assignment(db: Session, assignment, payload: AssignmentEnd, actor: User):
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    employee = get_employee(db, assignment.employee_id, actor.tenant_id)
    context = _admin_context(
        db, actor,
        Capability.ROLE_ASSIGN if isinstance(assignment, EmployeeRoleAssignment) else Capability.DEPARTMENT_ASSIGN,
        employee,
        assignment.role if isinstance(assignment, EmployeeRoleAssignment) else None,
        assignment.department_id if isinstance(assignment, EmployeeDepartmentAssignment) else None,
    )
    if assignment.valid_to is not None:
        raise _conflict("Assignment is already ended")
    if _utc(payload.valid_to) <= _utc(assignment.valid_from):
        raise HTTPException(status_code=422, detail="valid_to must be later than valid_from")
    assignment.valid_to = payload.valid_to
    assignment.ended_reason = payload.reason
    assignment.ended_by_user_id = actor.id
    is_role = isinstance(assignment, EmployeeRoleAssignment)
    record_audit_event(
        db,
        tenant_id=actor.tenant_id,
        event_type=("EMPLOYEE_ROLE_ENDED" if is_role else "EMPLOYEE_DEPARTMENT_ENDED"),
        entity_type="Employee",
        entity_id=assignment.employee_id,
        operation=("END_ROLE" if is_role else "END_DEPARTMENT"),
        context=context,
        actor_user=actor,
        before={"valid_to": None},
        after={
            "valid_to": payload.valid_to,
            **({"role": assignment.role.value} if is_role else {
                "department_id": assignment.department_id,
                "is_primary": assignment.is_primary,
            }),
        },
        reason=payload.reason,
    )
    db.commit()
    db.refresh(assignment)
    return assignment


def dismiss_employee(db: Session, employee: Employee, payload: EmployeeDismiss, actor: User) -> Employee:
    context = _admin_context(db, actor, Capability.EMPLOYEE_LIFECYCLE, employee)
    if employee.status == EmployeeStatus.DISMISSED:
        raise _conflict("Employee is already dismissed")
    now = datetime.now(UTC)
    employee.status = EmployeeStatus.DISMISSED
    employee.dismissal_date = payload.dismissal_date
    employee.dismissal_reason = payload.reason
    for assignment in (*employee.role_assignments, *employee.department_assignments):
        if assignment.valid_to is None:
            assignment.valid_to = max(now, _utc(assignment.valid_from))
            if assignment.valid_to == _utc(assignment.valid_from):
                assignment.valid_to = _utc(assignment.valid_from) + timedelta(microseconds=1)
            assignment.ended_reason = payload.reason
            assignment.ended_by_user_id = actor.id
    user = db.get(User, employee.linked_user_id) if employee.linked_user_id is not None else None
    if user is not None and user.is_active:
        user.is_active = False
        user.blocked_by_employee_dismissal = True
    db.add(EmployeeLifecycleEvent(
        tenant_id=actor.tenant_id, employee_id=employee.id,
        event_type=EmployeeLifecycleEventType.DISMISSED,
        effective_date=payload.dismissal_date, reason=payload.reason, actor_user_id=actor.id,
    ))
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_DISMISSED",
        entity_type="Employee", entity_id=employee.id, operation="DISMISS",
        context=context, actor_user=actor,
        before={"status": EmployeeStatus.ACTIVE.value},
        after={"status": EmployeeStatus.DISMISSED.value, "dismissal_date": payload.dismissal_date},
        reason=payload.reason,
    )
    db.commit()
    return get_employee(db, employee.id, actor.tenant_id)


def reactivate_employee(db: Session, employee: Employee, payload: EmployeeReactivate, actor: User) -> Employee:
    context = _admin_context(db, actor, Capability.EMPLOYEE_LIFECYCLE, employee)
    if employee.status == EmployeeStatus.ACTIVE:
        raise _conflict("Employee is already active")
    employee.status = EmployeeStatus.ACTIVE
    employee.dismissal_date = None
    employee.dismissal_reason = None
    user = db.get(User, employee.linked_user_id) if employee.linked_user_id is not None else None
    if (
        user is not None
        and user.account_type == UserAccountType.HUMAN
        and user.blocked_by_employee_dismissal
    ):
        user.is_active = True
        user.blocked_by_employee_dismissal = False
    db.add(EmployeeLifecycleEvent(
        tenant_id=actor.tenant_id, employee_id=employee.id,
        event_type=EmployeeLifecycleEventType.REACTIVATED,
        effective_date=payload.effective_date, reason=payload.reason, actor_user_id=actor.id,
    ))
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_REACTIVATED",
        entity_type="Employee", entity_id=employee.id, operation="REACTIVATE",
        context=context, actor_user=actor,
        before={"status": EmployeeStatus.DISMISSED.value},
        after={"status": EmployeeStatus.ACTIVE.value, "effective_date": payload.effective_date},
        reason=payload.reason,
    )
    db.commit()
    return get_employee(db, employee.id, actor.tenant_id)


def link_user(db: Session, employee: Employee, user_id: int, reason: str, actor: User) -> Employee:
    context = _admin_context(db, actor, Capability.USER_CREATE, employee)
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == actor.tenant_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.account_type != UserAccountType.HUMAN:
        raise HTTPException(status_code=422, detail="Service account cannot be linked to an employee")
    if employee.linked_user_id == user.id:
        return employee
    existing = db.scalar(select(Employee.id).where(
        Employee.tenant_id == actor.tenant_id,
        Employee.linked_user_id == user.id,
        Employee.id != employee.id,
    ))
    if existing is not None:
        raise _conflict("User is already linked to another employee")
    if employee.linked_user_id is not None:
        raise _conflict("Employee is already linked to another user")
    employee.linked_user_id = user.id
    if employee.status == EmployeeStatus.DISMISSED and user.is_active:
        user.is_active = False
        user.blocked_by_employee_dismissal = True
    db.add(EmployeeLifecycleEvent(
        tenant_id=actor.tenant_id, employee_id=employee.id,
        event_type=EmployeeLifecycleEventType.USER_LINKED, effective_date=date.today(),
        reason=reason, actor_user_id=actor.id,
    ))
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_USER_LINKED",
        entity_type="Employee", entity_id=employee.id, operation="LINK_USER",
        context=context, actor_user=actor, before={"linked_user_id": None},
        after={"linked_user_id": user.id}, reason=reason,
    )
    _commit_integrity(db, "User or employee is already linked")
    return get_employee(db, employee.id, actor.tenant_id)


def unlink_user(db: Session, employee: Employee, reason: str, actor: User) -> Employee:
    context = _admin_context(db, actor, Capability.USER_CREATE, employee)
    if employee.linked_user_id is None:
        raise _conflict("Employee has no linked user")
    user = db.scalar(select(User).where(
        User.id == employee.linked_user_id, User.tenant_id == actor.tenant_id,
    ).with_for_update())
    if user is None:
        raise _conflict("Linked user is unavailable")
    previous_user_id = employee.linked_user_id
    employee.linked_user_id = None
    if user.blocked_by_employee_dismissal:
        user.is_active = True
        user.blocked_by_employee_dismissal = False
    db.add(EmployeeLifecycleEvent(
        tenant_id=actor.tenant_id, employee_id=employee.id,
        event_type=EmployeeLifecycleEventType.USER_UNLINKED, effective_date=date.today(),
        reason=reason, actor_user_id=actor.id,
    ))
    record_audit_event(
        db, tenant_id=actor.tenant_id, event_type="EMPLOYEE_USER_UNLINKED",
        entity_type="Employee", entity_id=employee.id, operation="UNLINK_USER",
        context=context, actor_user=actor, before={"linked_user_id": previous_user_id},
        after={"linked_user_id": None}, reason=reason,
    )
    db.commit()
    return get_employee(db, employee.id, actor.tenant_id)


def reset_linked_user_password(
    db: Session, employee: Employee, reason: str | None, actor: User,
) -> tuple[User, str]:
    context = _admin_context(db, actor, Capability.USER_RESET_PASSWORD, employee)
    if employee.linked_user_id is None:
        raise _conflict("Employee has no linked user")
    user = db.scalar(select(User).where(
        User.id == employee.linked_user_id,
        User.tenant_id == actor.tenant_id,
    ).with_for_update())
    if user is None:
        raise _conflict("Linked user is unavailable")
    if user.account_type != UserAccountType.HUMAN:
        raise HTTPException(
            status_code=422,
            detail="Service account password cannot be reset through Employee",
        )

    temporary_password = generate_password()
    user.hashed_password = hash_password(temporary_password)
    record_audit_event(
        db,
        tenant_id=actor.tenant_id,
        event_type="USER_PASSWORD_RESET",
        entity_type="User",
        entity_id=user.id,
        operation="RESET_PASSWORD",
        context=context,
        actor_user=actor,
        before={},
        after={},
        reason=reason,
    )
    db.commit()
    return user, temporary_password


def _commit_integrity(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict(detail) from error
