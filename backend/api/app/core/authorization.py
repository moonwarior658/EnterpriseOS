"""Capabilities and scopes for Employee and User administration."""

from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.action_context import ActionContext, ActionContextError, resolve_action_context
from app.models.employee import Employee, EmployeeRole, EmployeeRoleAssignment, EmployeeDepartmentAssignment
from app.models.supply import Department
from app.models.user import User


class Capability(StrEnum):
    EMPLOYEE_READ = "EMPLOYEE_READ"
    EMPLOYEE_WRITE = "EMPLOYEE_WRITE"
    EMPLOYEE_LIFECYCLE = "EMPLOYEE_LIFECYCLE"
    USER_READ = "USER_READ"
    USER_CREATE = "USER_CREATE"
    USER_BLOCK = "USER_BLOCK"
    USER_RESET_PASSWORD = "USER_RESET_PASSWORD"
    ROLE_ASSIGN = "ROLE_ASSIGN"
    DEPARTMENT_ASSIGN = "DEPARTMENT_ASSIGN"
    AUDIT_READ = "AUDIT_READ"
    TECHNICAL_ADMIN = "TECHNICAL_ADMIN"


class Scope(StrEnum):
    ALL_COMPANY = "ALL_COMPANY"
    ECLAIR_POINTS = "ECLAIR_POINTS"
    PRODUCTION = "PRODUCTION"
    PRIMARY_DEPARTMENT = "PRIMARY_DEPARTMENT"
    ACTUAL_SHIFT_DEPARTMENT = "ACTUAL_SHIFT_DEPARTMENT"
    ASSIGNED_OBJECTS = "ASSIGNED_OBJECTS"
    DRIVER_HANDYMAN = "DRIVER_HANDYMAN"


# Tuple order is the permission-specific authorized_as precedence.
GRANTS: dict[Capability, tuple[tuple[EmployeeRole, Scope], ...]] = {
    Capability.EMPLOYEE_READ: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION),
        (EmployeeRole.SUPPLY_MANAGER, Scope.DRIVER_HANDYMAN),
    ),
    Capability.EMPLOYEE_WRITE: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
    ),
    Capability.EMPLOYEE_LIFECYCLE: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
    ),
    Capability.USER_READ: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
    ),
    Capability.USER_CREATE: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
    ),
    Capability.USER_BLOCK: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
    ),
    Capability.USER_RESET_PASSWORD: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
    ),
    Capability.ROLE_ASSIGN: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
    ),
    Capability.DEPARTMENT_ASSIGN: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
    ),
    Capability.AUDIT_READ: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY),),
    Capability.TECHNICAL_ADMIN: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY),),
}

ROLE_ASSIGNABLE = {
    EmployeeRole.ADMIN: frozenset(EmployeeRole),
    EmployeeRole.DEPUTY_DIRECTOR: frozenset({
        EmployeeRole.NETWORK_MANAGER, EmployeeRole.HEAD_OF_PRODUCTION,
        EmployeeRole.SUPPLY_MANAGER, EmployeeRole.ACCOUNTANT,
        EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HANDYMAN,
        EmployeeRole.DRIVER, EmployeeRole.SELLER,
        EmployeeRole.CONFECTIONER, EmployeeRole.BAKER,
    }),
    EmployeeRole.NETWORK_MANAGER: frozenset({
        EmployeeRole.SELLER, EmployeeRole.DRIVER, EmployeeRole.HANDYMAN,
    }),
}

# Populate only from an owner-approved Department.code inventory. Empty is fail closed.
ECLAIR_POINT_DEPARTMENT_CODES: frozenset[str] = frozenset()
PRODUCTION_DEPARTMENT_CODES: frozenset[str] = frozenset()


def has_request_view_access(user: User) -> bool:
    return user.is_admin or user.can_view_requests


def _active_departments(db: Session, tenant_id: str, employee_id, at):
    return set(db.scalars(select(EmployeeDepartmentAssignment.department_id).where(
        EmployeeDepartmentAssignment.tenant_id == tenant_id,
        EmployeeDepartmentAssignment.employee_id == employee_id,
        EmployeeDepartmentAssignment.valid_from <= at,
        (EmployeeDepartmentAssignment.valid_to.is_(None)
         | (EmployeeDepartmentAssignment.valid_to > at)),
    )).all())


def scoped_department_ids(db: Session, user: User, scope: Scope, actor: ActionContext) -> set:
    codes = (ECLAIR_POINT_DEPARTMENT_CODES if scope == Scope.ECLAIR_POINTS
             else PRODUCTION_DEPARTMENT_CODES if scope == Scope.PRODUCTION else frozenset())
    if not codes:
        return set()
    assigned = _active_departments(db, user.tenant_id, actor.employee_id, actor.determined_at)
    return set(db.scalars(select(Department.id).where(
        Department.tenant_id == user.tenant_id,
        Department.id.in_(assigned), Department.code.in_(codes), Department.is_active.is_(True),
    )).all())


def _in_scope(
    db: Session, user: User, actor: ActionContext, scope: Scope,
    target: Employee | None, department_id=None,
) -> bool:
    if scope == Scope.ALL_COMPANY:
        return True
    if scope in {Scope.ECLAIR_POINTS, Scope.PRODUCTION}:
        allowed = scoped_department_ids(db, user, scope, actor)
        if not allowed:
            return False
        if target is not None and not (_active_departments(
            db, user.tenant_id, target.id, actor.determined_at,
        ) & allowed):
            return False
        return department_id in allowed if department_id is not None else target is not None
    if target is None:
        return False
    if scope == Scope.DRIVER_HANDYMAN:
        return db.scalar(select(EmployeeRoleAssignment.id).where(
            EmployeeRoleAssignment.tenant_id == target.tenant_id,
            EmployeeRoleAssignment.employee_id == target.id,
            EmployeeRoleAssignment.role.in_((EmployeeRole.DRIVER, EmployeeRole.HANDYMAN)),
            EmployeeRoleAssignment.valid_from <= actor.determined_at,
            (EmployeeRoleAssignment.valid_to.is_(None)
             | (EmployeeRoleAssignment.valid_to > actor.determined_at)),
        )) is not None
    return False


def authorize(
    db: Session, user: User, capability: Capability, *,
    target: Employee | None = None, write: bool = False,
    assigned_role: EmployeeRole | None = None,
    department_id=None,
) -> ActionContext:
    base = resolve_action_context(db, user, write=False)
    for role, scope in GRANTS[capability]:
        if role not in base.roles or not _in_scope(db, user, base, scope, target, department_id):
            continue
        if assigned_role is not None and assigned_role not in ROLE_ASSIGNABLE.get(role, frozenset()):
            continue
        return resolve_action_context(
            db, user, required_roles=frozenset({role}),
            role_precedence=(role,), write=write,
        )
    raise ActionContextError("PERMISSION_DENIED", "Недостаточно прав для действия")


def linked_employee(db: Session, user: User) -> Employee | None:
    return db.scalar(select(Employee).where(
        Employee.tenant_id == user.tenant_id, Employee.linked_user_id == user.id,
    ))
