from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.audit.service import record_audit_event
from app.core.action_context import ActionContext, resolve_action_context
from app.models.employee import (
    Employee, EmployeeDepartmentAssignment, EmployeeLifecycleEvent,
    EmployeeLifecycleEventType, EmployeeRole, EmployeeRoleAssignment, EmployeeStatus,
)
from app.models.supply import Department
from app.models.user import User, UserAccountType
from app.schemas.employee import (
    AssignmentEnd, EmployeeCreate, EmployeeDepartmentAssignmentCreate,
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


def _admin_context(db: Session, actor: User) -> ActionContext:
    return resolve_action_context(
        db,
        actor,
        required_roles=frozenset({EmployeeRole.ADMIN}),
        role_precedence=(EmployeeRole.ADMIN,),
        write=True,
    )


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


def create_employee(db: Session, payload: EmployeeCreate, actor: User) -> Employee:
    context = _admin_context(db, actor)
    employee = Employee(
        tenant_id=actor.tenant_id, full_name=payload.full_name, birth_date=payload.birth_date,
        photo_url=payload.photo_url, phone=payload.phone,
        residence_address=payload.residence_address,
    )
    db.add(employee)
    db.flush()
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
    context = _admin_context(db, actor)
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
    context = _admin_context(db, actor)
    _require_active(employee)
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
    context = _admin_context(db, actor)
    _require_active(employee)
    department = db.scalar(select(Department.id).where(
        Department.id == payload.department_id, Department.tenant_id == actor.tenant_id,
    ))
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
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
    context = _admin_context(db, actor)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
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
    context = _admin_context(db, actor)
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
    context = _admin_context(db, actor)
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
    context = _admin_context(db, actor)
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
    context = _admin_context(db, actor)
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


def _commit_integrity(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise _conflict(detail) from error
