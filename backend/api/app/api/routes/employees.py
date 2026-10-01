from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_admin as get_current_legacy_admin,
    get_current_user,
)
from app.api.routes.action_context import action_context_http_error
from app.core.action_context import ActionContextError, resolve_action_context
from app.core.authorization import Capability, GRANTS, Scope, authorize, scoped_department_ids
from app.db.session import get_db
from app.employees import service
from app.employees import iiko as iiko_employee_service
from app.api.routes.iiko import get_iiko_provider, integration_error
from app.integrations.iiko.exceptions import IikoError
from app.integrations.iiko.provider import IikoProvider
from app.models.employee import (
    Employee, EmployeeDepartmentAssignment, EmployeeRole, EmployeeRoleAssignment,
    EmployeeStatus,
)
from app.models.user import User
from app.models.supply import Department
from app.schemas.supply import DepartmentRead
from app.supply.service import list_departments
from app.schemas.employee import (
    AssignmentEnd, DepartmentAssignmentRead, EmployeeBootstrapCreate,
    EmployeeBootstrapStatus, EmployeeCreate,
    EmployeeDepartmentAssignmentCreate, EmployeeDismiss, EmployeeReactivate,
    EmployeeRead, EmployeeBasicRead, EmployeeRoleAssignmentCreate, EmployeeUpdate,
    EmployeeUserLink, EmployeeUserUnlink, RoleAssignmentRead,
    EmployeeIikoShiftRead, EmployeeIikoSyncRead, IikoEmployeeCandidateRead,
    IikoEmployeeLinkCorrect, IikoEmployeeLinkCreate, IikoEmployeeLinkRead,
)
from app.schemas.user import GeneratedCredentials, PasswordReset


router = APIRouter(prefix="/employees", tags=["employees"])


def get_current_admin(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_legacy_admin)],
) -> User:
    try:
        resolve_action_context(
            db, user, required_roles=frozenset({EmployeeRole.ADMIN}),
            role_precedence=(EmployeeRole.ADMIN,), write=False,
        )
    except ActionContextError as error:
        raise action_context_http_error(error) from error
    return user


def get_current_employee_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


def employee_read(db: Session, employee: Employee) -> EmployeeRead:
    result = EmployeeRead.model_validate(employee)
    result.linked_user_id = service.linked_user_id(db, employee.id, employee.tenant_id)
    return result


def employee_basic_read(employee: Employee, at: datetime) -> EmployeeBasicRead:
    def active(item) -> bool:
        start = item.valid_from.replace(tzinfo=item.valid_from.tzinfo or timezone.utc)
        end = item.valid_to.replace(tzinfo=item.valid_to.tzinfo or timezone.utc) if item.valid_to else None
        return start <= at and (end is None or end > at)

    return EmployeeBasicRead(
        id=employee.id, full_name=employee.full_name, birth_date=employee.birth_date,
        photo_url=employee.photo_url, phone=employee.phone,
        roles=sorted({item.role for item in employee.role_assignments if active(item)}, key=lambda role: role.value),
        department_ids=sorted({item.department_id for item in employee.department_assignments if active(item)}, key=str),
    )


def authorized_employee_read(db: Session, user: User, employee: Employee) -> EmployeeRead | EmployeeBasicRead:
    try:
        context = authorize(db, user, Capability.EMPLOYEE_READ, target=employee)
    except ActionContextError as error:
        raise action_context_http_error(error) from error
    if context.authorized_as in {EmployeeRole.HEAD_OF_PRODUCTION, EmployeeRole.SUPPLY_MANAGER}:
        return employee_basic_read(employee, context.determined_at)
    return employee_read(db, employee)


@router.get("/bootstrap", response_model=EmployeeBootstrapStatus)
def get_bootstrap_status(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> EmployeeBootstrapStatus:
    return service.first_admin_bootstrap_status(db, current_user)


@router.post("/bootstrap", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def bootstrap_first_admin(
    payload: EmployeeBootstrapCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> EmployeeRead:
    return employee_read(db, service.bootstrap_first_admin(db, payload, current_user))


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> EmployeeRead:
    return employee_read(db, service.create_employee(db, payload, current_admin))


@router.get("/departments", response_model=list[DepartmentRead])
def list_employee_departments(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_employee_user)],
) -> list[Department]:
    departments = list_departments(db, tenant_id=current_user.tenant_id)
    if service.first_admin_bootstrap_status(db, current_user).available:
        return departments
    try:
        context = resolve_action_context(db, current_user, write=False)
    except ActionContextError as error:
        raise action_context_http_error(error) from error
    if context.roles & {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR}:
        return departments
    if EmployeeRole.NETWORK_MANAGER in context.roles:
        allowed_ids = scoped_department_ids(db, current_user, Scope.ECLAIR_POINTS, context)
        return [department for department in departments if department.id in allowed_ids]
    if EmployeeRole.HEAD_OF_PRODUCTION in context.roles:
        allowed_ids = scoped_department_ids(db, current_user, Scope.PRODUCTION, context)
        return [department for department in departments if department.id in allowed_ids]
    visible_ids = set()
    for employee in db.scalars(service._employee_query(current_user.tenant_id)).all():
        try:
            profile = authorized_employee_read(db, current_user, employee)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            continue
        if isinstance(profile, EmployeeBasicRead):
            visible_ids.update(profile.department_ids)
        else:
            visible_ids.update(item.department_id for item in profile.department_assignments)
    return [department for department in departments if department.id in visible_ids]


@router.get("", response_model=list[EmployeeRead | EmployeeBasicRead])
def list_employees(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_employee_user)],
    employee_status: Annotated[EmployeeStatus | None, Query(alias="status")] = None,
) -> list[EmployeeRead | EmployeeBasicRead]:
    try:
        context = resolve_action_context(db, current_admin, write=False)
    except ActionContextError as error:
        raise action_context_http_error(error) from error
    if not any(role in context.roles for role, _ in GRANTS[Capability.EMPLOYEE_READ]):
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра сотрудников")
    query = service._employee_query(current_admin.tenant_id).order_by(Employee.full_name, Employee.id)
    if employee_status is not None:
        query = query.where(Employee.status == employee_status)
    result: list[EmployeeRead | EmployeeBasicRead] = []
    for item in db.scalars(query).all():
        try:
            result.append(authorized_employee_read(db, current_admin, item))
        except HTTPException as error:
            if error.status_code != 403:
                raise
    return result


@router.get("/{employee_id}", response_model=EmployeeRead | EmployeeBasicRead)
def get_employee(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> EmployeeRead | EmployeeBasicRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id)
    return authorized_employee_read(db, current_admin, employee)


@router.post("/{employee_id}/password-reset", response_model=GeneratedCredentials)
def reset_employee_password(
    employee_id: UUID,
    payload: PasswordReset,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> GeneratedCredentials:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    user, temporary_password = service.reset_linked_user_password(
        db, employee, payload.reason, current_admin,
    )
    return GeneratedCredentials(
        username=user.username,
        temporary_password=temporary_password,
    )


@router.patch("/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: UUID, payload: EmployeeUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.update_employee(db, employee, payload, current_admin))


@router.post("/{employee_id}/roles", response_model=RoleAssignmentRead, status_code=201)
def assign_role(
    employee_id: UUID, payload: EmployeeRoleAssignmentCreate,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return service.assign_role(db, employee, payload, current_admin)


@router.post("/{employee_id}/roles/{assignment_id}/end", response_model=RoleAssignmentRead)
def end_role_assignment(
    employee_id: UUID, assignment_id: UUID, payload: AssignmentEnd,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
):
    service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    assignment = db.scalar(select(EmployeeRoleAssignment).where(
        EmployeeRoleAssignment.id == assignment_id,
        EmployeeRoleAssignment.employee_id == employee_id,
        EmployeeRoleAssignment.tenant_id == current_admin.tenant_id,
    ).with_for_update())
    return service.end_assignment(db, assignment, payload, current_admin)


@router.post("/{employee_id}/departments", response_model=DepartmentAssignmentRead, status_code=201)
def assign_department(
    employee_id: UUID, payload: EmployeeDepartmentAssignmentCreate,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return service.assign_department(db, employee, payload, current_admin)


@router.post("/{employee_id}/departments/{assignment_id}/end", response_model=DepartmentAssignmentRead)
def end_department_assignment(
    employee_id: UUID, assignment_id: UUID, payload: AssignmentEnd,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
):
    service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    assignment = db.scalar(select(EmployeeDepartmentAssignment).where(
        EmployeeDepartmentAssignment.id == assignment_id,
        EmployeeDepartmentAssignment.employee_id == employee_id,
        EmployeeDepartmentAssignment.tenant_id == current_admin.tenant_id,
    ).with_for_update())
    return service.end_assignment(db, assignment, payload, current_admin)


@router.post("/{employee_id}/dismiss", response_model=EmployeeRead)
def dismiss_employee(
    employee_id: UUID, payload: EmployeeDismiss,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.dismiss_employee(db, employee, payload, current_admin))


@router.post("/{employee_id}/reactivate", response_model=EmployeeRead)
def reactivate_employee(
    employee_id: UUID, payload: EmployeeReactivate,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.reactivate_employee(db, employee, payload, current_admin))


@router.post("/{employee_id}/user", response_model=EmployeeRead)
def link_user(
    employee_id: UUID, payload: EmployeeUserLink,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.link_user(db, employee, payload.user_id, payload.reason, current_admin))


@router.post("/{employee_id}/user/unlink", response_model=EmployeeRead)
def unlink_user(
    employee_id: UUID, payload: EmployeeUserUnlink,
    db: Annotated[Session, Depends(get_db)], current_admin: Annotated[User, Depends(get_current_employee_user)],
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    return employee_read(db, service.unlink_user(db, employee, payload.reason, current_admin))


@router.get("/{employee_id}/iiko/candidates", response_model=list[IikoEmployeeCandidateRead])
async def find_iiko_candidates(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> list[IikoEmployeeCandidateRead]:
    employee = service.get_employee(db, employee_id, current_admin.tenant_id)
    try:
        return await iiko_employee_service.find_candidates(
            provider, full_name=employee.full_name, birth_date=employee.birth_date,
        )
    except IikoError as error:
        raise integration_error(error) from error


@router.get("/{employee_id}/iiko/link", response_model=IikoEmployeeLinkRead | None)
def get_iiko_link(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id)
    return iiko_employee_service.current_link(db, employee)


@router.get("/{employee_id}/iiko/link/history", response_model=list[IikoEmployeeLinkRead])
def get_iiko_link_history(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id)
    return iiko_employee_service.link_history(db, employee)


@router.post("/{employee_id}/iiko/link", response_model=IikoEmployeeLinkRead, status_code=201)
async def create_iiko_link(
    employee_id: UUID,
    payload: IikoEmployeeLinkCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    try:
        return await iiko_employee_service.create_link(
            db, employee, iiko_user_id=payload.iiko_user_id,
            reason=payload.reason, actor=current_admin, provider=provider,
        )
    except IikoError as error:
        raise integration_error(error) from error


@router.post("/{employee_id}/iiko/link/correct", response_model=IikoEmployeeLinkRead)
async def correct_iiko_link(
    employee_id: UUID,
    payload: IikoEmployeeLinkCorrect,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id, lock=True)
    try:
        return await iiko_employee_service.correct_link(
            db, employee, iiko_user_id=payload.iiko_user_id,
            reason=payload.reason, actor=current_admin, provider=provider,
        )
    except IikoError as error:
        raise integration_error(error) from error


@router.get("/{employee_id}/iiko/shifts", response_model=list[EmployeeIikoShiftRead])
def get_iiko_shifts(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id)
    return iiko_employee_service.list_shifts(db, employee, limit=limit)


@router.get("/{employee_id}/iiko/shifts/active", response_model=EmployeeIikoShiftRead | None)
def get_active_iiko_shift(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id)
    return iiko_employee_service.active_shift(db, employee)


@router.post("/{employee_id}/iiko/shifts/refresh", response_model=EmployeeIikoSyncRead)
async def refresh_iiko_shifts(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
):
    employee = service.get_employee(db, employee_id, current_admin.tenant_id)
    link = iiko_employee_service.current_link(db, employee)
    if link is None:
        raise HTTPException(status_code=409, detail="Employee has no active iiko link")
    until = date_to or date.today()
    since = date_from or (until - timedelta(days=7))
    if since > until or (until - since).days > 93:
        raise HTTPException(status_code=422, detail="Invalid shift sync period")
    try:
        shifts = await provider.get_personal_shifts(date_from=since, date_to=until)
    except IikoError as error:
        raise integration_error(error) from error
    scoped = [item for item in shifts if item.employee_external_id == link.iiko_user_id]
    return EmployeeIikoSyncRead.model_validate(
        iiko_employee_service.sync_shifts(
            db, scoped, tenant_id=current_admin.tenant_id,
        ),
        from_attributes=True,
    )
