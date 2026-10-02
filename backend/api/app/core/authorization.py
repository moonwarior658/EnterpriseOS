"""Capabilities and scopes for Employee and User administration."""

from enum import StrEnum
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.action_context import ActionContext, ActionContextError, resolve_action_context
from app.models.employee import Employee, EmployeeRole, EmployeeRoleAssignment, EmployeeDepartmentAssignment
from app.models.supply import Department, DepartmentBusinessType, SupplyRequest
from app.models.user import User
from app.models.work_request import WorkRequest


class Capability(StrEnum):
    SUPPLY_REQUEST_READ = "SUPPLY_REQUEST_READ"
    SUPPLY_REQUEST_CREATE = "SUPPLY_REQUEST_CREATE"
    SUPPLY_REQUEST_EDIT = "SUPPLY_REQUEST_EDIT"
    SUPPLY_REQUEST_CANCEL = "SUPPLY_REQUEST_CANCEL"
    SUPPLY_DOWNSTREAM_READ = "SUPPLY_DOWNSTREAM_READ"
    SUPPLY_OPERATE = "SUPPLY_OPERATE"
    SUPPLIER_EDIT = "SUPPLIER_EDIT"
    PAYMENT_WRITE = "PAYMENT_WRITE"
    REPAIR_READ = "REPAIR_READ"
    REPAIR_CREATE = "REPAIR_CREATE"
    REPAIR_TAKE = "REPAIR_TAKE"
    REPAIR_OPERATE = "REPAIR_OPERATE"
    REPAIR_REOPEN = "REPAIR_REOPEN"
    CONTRACTOR_MANAGE = "CONTRACTOR_MANAGE"
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
    Capability.SUPPLY_REQUEST_READ: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY),
        (EmployeeRole.ACCOUNTANT, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION),
        (EmployeeRole.CHEF_CONFECTIONER, Scope.PRODUCTION),
        (EmployeeRole.SELLER, Scope.PRIMARY_DEPARTMENT),
    ),
    Capability.SUPPLY_REQUEST_CREATE: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION),
        (EmployeeRole.CHEF_CONFECTIONER, Scope.PRODUCTION),
        (EmployeeRole.SELLER, Scope.ACTUAL_SHIFT_DEPARTMENT),
    ),
    Capability.SUPPLY_REQUEST_EDIT: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION),
        (EmployeeRole.CHEF_CONFECTIONER, Scope.PRODUCTION),
        (EmployeeRole.SELLER, Scope.ACTUAL_SHIFT_DEPARTMENT),
    ),
    Capability.SUPPLY_REQUEST_CANCEL: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION),
        (EmployeeRole.CHEF_CONFECTIONER, Scope.PRODUCTION),
    ),
    Capability.SUPPLY_DOWNSTREAM_READ: (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY), (EmployeeRole.ACCOUNTANT, Scope.ALL_COMPANY),
    ),
    Capability.SUPPLY_OPERATE: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY)),
    Capability.SUPPLIER_EDIT: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY), (EmployeeRole.ACCOUNTANT, Scope.ALL_COMPANY)),
    Capability.PAYMENT_WRITE: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY), (EmployeeRole.ACCOUNTANT, Scope.ALL_COMPANY)),
    Capability.REPAIR_READ: tuple((role, scope) for role, scope in (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY), (EmployeeRole.ACCOUNTANT, Scope.ALL_COMPANY),
        (EmployeeRole.HANDYMAN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION), (EmployeeRole.CHEF_CONFECTIONER, Scope.PRODUCTION),
        (EmployeeRole.SELLER, Scope.PRIMARY_DEPARTMENT), (EmployeeRole.DRIVER, Scope.ASSIGNED_OBJECTS),
        (EmployeeRole.CONFECTIONER, Scope.ASSIGNED_OBJECTS), (EmployeeRole.BAKER, Scope.ASSIGNED_OBJECTS),
    )),
    Capability.REPAIR_CREATE: tuple((role, scope) for role, scope in (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.DEPUTY_DIRECTOR, Scope.ALL_COMPANY),
        (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION), (EmployeeRole.CHEF_CONFECTIONER, Scope.PRODUCTION),
        (EmployeeRole.SELLER, Scope.ACTUAL_SHIFT_DEPARTMENT), (EmployeeRole.DRIVER, Scope.PRIMARY_DEPARTMENT),
        (EmployeeRole.CONFECTIONER, Scope.PRODUCTION), (EmployeeRole.BAKER, Scope.PRODUCTION),
        (EmployeeRole.HANDYMAN, Scope.ALL_COMPANY),
    )),
    Capability.REPAIR_TAKE: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.HANDYMAN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY)),
    Capability.REPAIR_OPERATE: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.HANDYMAN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY)),
    Capability.REPAIR_REOPEN: tuple((role, scope) for role, scope in (
        (EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.NETWORK_MANAGER, Scope.ECLAIR_POINTS),
        (EmployeeRole.HEAD_OF_PRODUCTION, Scope.PRODUCTION), (EmployeeRole.CHEF_CONFECTIONER, Scope.PRODUCTION),
        (EmployeeRole.SELLER, Scope.PRIMARY_DEPARTMENT), (EmployeeRole.DEPUTY_DIRECTOR, Scope.ASSIGNED_OBJECTS),
        (EmployeeRole.DRIVER, Scope.ASSIGNED_OBJECTS), (EmployeeRole.CONFECTIONER, Scope.ASSIGNED_OBJECTS),
        (EmployeeRole.BAKER, Scope.ASSIGNED_OBJECTS),
    )),
    Capability.CONTRACTOR_MANAGE: ((EmployeeRole.ADMIN, Scope.ALL_COMPANY), (EmployeeRole.SUPPLY_MANAGER, Scope.ALL_COMPANY)),
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

def _active_departments(db: Session, tenant_id: str, employee_id, at):
    return set(db.scalars(select(EmployeeDepartmentAssignment.department_id).where(
        EmployeeDepartmentAssignment.tenant_id == tenant_id,
        EmployeeDepartmentAssignment.employee_id == employee_id,
        EmployeeDepartmentAssignment.valid_from <= at,
        (EmployeeDepartmentAssignment.valid_to.is_(None)
         | (EmployeeDepartmentAssignment.valid_to > at)),
    )).all())


def scoped_department_ids(db: Session, user: User, scope: Scope, actor: ActionContext) -> set:
    category = (DepartmentBusinessType.RETAIL_POINT if scope == Scope.ECLAIR_POINTS
                else DepartmentBusinessType.PRODUCTION if scope == Scope.PRODUCTION else None)
    if category is None:
        return set()
    query = select(Department.id).where(
        Department.tenant_id == user.tenant_id,
        Department.business_type == category, Department.is_active.is_(True),
    )
    if scope == Scope.PRODUCTION:
        query = query.where(Department.id.in_(_active_departments(
            db, user.tenant_id, actor.employee_id, actor.determined_at,
        )))
    return set(db.scalars(query).all())


def _in_scope(
    db: Session, user: User, actor: ActionContext, scope: Scope,
    target: Employee | None, department_id=None, assigned_role: EmployeeRole | None = None,
) -> bool:
    if scope == Scope.ALL_COMPANY:
        return True
    if scope in {Scope.ECLAIR_POINTS, Scope.PRODUCTION}:
        allowed = scoped_department_ids(db, user, scope, actor)
        if scope == Scope.ECLAIR_POINTS and target is not None:
            staff_roles = set(db.scalars(select(EmployeeRoleAssignment.role).where(
                EmployeeRoleAssignment.tenant_id == user.tenant_id,
                EmployeeRoleAssignment.employee_id == target.id,
                EmployeeRoleAssignment.role.in_((EmployeeRole.DRIVER, EmployeeRole.HANDYMAN)),
                EmployeeRoleAssignment.valid_from <= actor.determined_at,
                (EmployeeRoleAssignment.valid_to.is_(None)
                 | (EmployeeRoleAssignment.valid_to > actor.determined_at)),
            )).all())
            assigned = _active_departments(db, user.tenant_id, target.id, actor.determined_at)
            auto_assigned = db.scalar(select(Department.id).where(
                Department.tenant_id == user.tenant_id,
                Department.id.in_(assigned), Department.is_active.is_(True),
                Department.business_type == DepartmentBusinessType.AUTO,
            )) is not None
            staff_role = EmployeeRole.HANDYMAN in staff_roles or (
                EmployeeRole.DRIVER in staff_roles and auto_assigned
            )
            if staff_role and department_id is None:
                return True
            if assigned_role in {EmployeeRole.DRIVER, EmployeeRole.HANDYMAN} and department_id is None:
                if auto_assigned:
                    return True
        if department_id is not None:
            if department_id in allowed:
                return target is None or bool(_active_departments(
                    db, user.tenant_id, target.id, actor.determined_at,
                ) & allowed)
            if scope == Scope.ECLAIR_POINTS:
                department = db.get(Department, department_id)
                return bool(department and department.tenant_id == user.tenant_id
                            and department.is_active
                            and department.business_type == DepartmentBusinessType.AUTO
                            and (target is None or staff_role))
            return False
        return bool(target is not None and _active_departments(
            db, user.tenant_id, target.id, actor.determined_at,
        ) & allowed)
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
        if role not in base.roles or not _in_scope(db, user, base, scope, target, department_id, assigned_role):
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


def supply_request_authorize(
    db: Session, user: User, capability: Capability, *,
    request: SupplyRequest | None = None, department_id=None, write: bool = False,
) -> ActionContext:
    """Resolve one role for a SupplyRequest action; never trust a legacy admin flag."""
    base = resolve_action_context(db, user, write=False)
    target = request.department_id if request is not None else department_id
    for role, scope in GRANTS[capability]:
        if role not in base.roles:
            continue
        if scope == Scope.ALL_COMPANY:
            allowed = True
        elif scope in {Scope.ECLAIR_POINTS, Scope.PRODUCTION}:
            allowed = target in scoped_department_ids(db, user, scope, base)
        elif role == EmployeeRole.SELLER:
            context = resolve_action_context(
                db, user, required_roles=frozenset({role}), role_precedence=(role,), write=write,
            )
            expected = context.actual_department_id if write or context.shift_id else context.primary_department_id
            department = db.get(Department, expected) if expected else None
            allowed = (target == expected and department is not None
                       and department.tenant_id == user.tenant_id
                       and department.is_active
                       and department.business_type == DepartmentBusinessType.RETAIL_POINT)
        else:
            allowed = False
        if request is not None and role == EmployeeRole.SELLER and write:
            cycle = request.cycle
            now = datetime.now(timezone.utc)
            if cycle is None:
                allowed = False
            else:
                opens_at = cycle.opens_at.replace(tzinfo=cycle.opens_at.tzinfo or timezone.utc)
                closes = cycle.hard_closes_at or cycle.closes_at
                closes_at = closes.replace(tzinfo=closes.tzinfo or timezone.utc)
                allowed = allowed and cycle.status == "OPEN" and opens_at <= now <= closes_at
        if request is not None and capability == Capability.SUPPLY_REQUEST_EDIT:
            if role == EmployeeRole.SELLER:
                allowed = allowed and request.created_by_user_id == user.id
        if not allowed:
            continue
        context = resolve_action_context(
            db, user, required_roles=frozenset({role}), role_precedence=(role,),
            write=write,
        )
        if write:
            db.info["action_context"] = context
            db.info["action_user"] = user
        return context
    raise ActionContextError("PERMISSION_DENIED", "Недостаточно прав для действия")


def supply_visible_departments(db: Session, user: User) -> set | None:
    """None means global read; an empty set means no SupplyRequest access."""
    base = resolve_action_context(db, user, write=False)
    visible: set = set()
    for role, scope in GRANTS[Capability.SUPPLY_REQUEST_READ]:
        if role not in base.roles:
            continue
        if scope == Scope.ALL_COMPANY:
            return None
        if scope in {Scope.ECLAIR_POINTS, Scope.PRODUCTION}:
            visible |= scoped_department_ids(db, user, scope, base)
        elif role == EmployeeRole.SELLER:
            seller = resolve_action_context(
                db, user, required_roles=frozenset({role}), role_precedence=(role,), write=False,
            )
            department_id = seller.actual_department_id if seller.shift_id else seller.primary_department_id
            department = db.get(Department, department_id) if department_id else None
            if (department is not None and department.tenant_id == user.tenant_id
                    and department.is_active
                    and department.business_type == DepartmentBusinessType.RETAIL_POINT):
                visible.add(department_id)
    return visible - {None}


def repair_authorize(
    db: Session, user: User, capability: Capability, *,
    repair: WorkRequest | None = None, department_id=None, write: bool = False,
    only_roles: frozenset[EmployeeRole] | None = None,
) -> ActionContext:
    """Return the single role authorizing this repair action and its context."""
    base = resolve_action_context(db, user, write=False)
    own = repair is not None and repair.creator_employee_id == base.employee_id
    target_department = repair.department_id if repair is not None else department_id
    for role, scope in GRANTS[capability]:
        if role not in base.roles or (only_roles is not None and role not in only_roles):
            continue
        if scope == Scope.ALL_COMPANY:
            allowed = True
        elif scope == Scope.ASSIGNED_OBJECTS:
            allowed = own
        elif scope == Scope.ECLAIR_POINTS:
            allowed = target_department in scoped_department_ids(db, user, scope, base)
        elif scope == Scope.PRODUCTION:
            allowed = target_department in scoped_department_ids(db, user, scope, base)
        elif scope in {Scope.PRIMARY_DEPARTMENT, Scope.ACTUAL_SHIFT_DEPARTMENT}:
            if role == EmployeeRole.SELLER:
                seller = resolve_action_context(
                    db, user, required_roles=frozenset({role}),
                    role_precedence=(role,), write=write,
                )
                shift_department = db.get(Department, seller.actual_department_id) if seller.shift_id else None
                expected = (seller.actual_department_id if shift_department is not None
                            and shift_department.tenant_id == user.tenant_id
                            and shift_department.business_type == DepartmentBusinessType.RETAIL_POINT
                            else seller.primary_department_id)
                allowed = target_department == expected
            else:
                allowed = target_department == base.primary_department_id
        else:
            allowed = False
        if role == EmployeeRole.DRIVER and capability == Capability.REPAIR_CREATE:
            department = db.get(Department, target_department) if target_department else None
            allowed = bool(allowed and department and department.business_type == DepartmentBusinessType.AUTO)
        if capability in {Capability.REPAIR_TAKE, Capability.REPAIR_OPERATE} and repair is not None:
            allowed = allowed and (role == EmployeeRole.ADMIN or role.value == repair.responsible_role)
        if not allowed:
            continue
        return resolve_action_context(
            db, user, required_roles=frozenset({role}),
            role_precedence=(role,), write=write,
        )
    raise ActionContextError("PERMISSION_DENIED", "Недостаточно прав для действия")
