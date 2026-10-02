from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_admin as get_current_legacy_admin,
    get_current_user,
)
from app.api.routes.action_context import action_context_http_error
from app.core.action_context import ActionContextError, resolve_action_context
from app.core.authorization import Capability, GRANTS, Scope, authorize, scoped_department_ids
from app.core.config import settings
from app.audit.service import record_audit_event
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
from app.models.supply import Department, DepartmentBusinessType
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


def employee_read(db: Session, employee: Employee, actor: User | None = None) -> EmployeeRead:
    result = EmployeeRead.model_validate(employee)
    result.linked_user_id = service.linked_user_id(db, employee.id, employee.tenant_id)
    if actor is not None:
        if result.linked_user_id is None:
            try:
                authorize(db, actor, Capability.USER_CREATE, target=employee, write=False)
                result.allowed_actions.append("create_human_user")
            except ActionContextError:
                pass
        else:
            try:
                authorize(db, actor, Capability.USER_RESET_PASSWORD, target=employee, write=False)
                result.allowed_actions.append("manage_user_access")
            except ActionContextError:
                pass
    return result


def employee_basic_read(employee: Employee, at: datetime) -> EmployeeBasicRead:
    def active(item) -> bool:
        start = item.valid_from.replace(tzinfo=item.valid_from.tzinfo or timezone.utc)
        end = item.valid_to.replace(tzinfo=item.valid_to.tzinfo or timezone.utc) if item.valid_to else None
        return start <= at and (end is None or end > at)

    return EmployeeBasicRead(
        id=employee.id, full_name=employee.full_name,
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
    return employee_read(db, employee, user)


def _employee_photo_context(db: Session, user: User, employee: Employee):
    if employee.linked_user_id == user.id:
        return resolve_action_context(db, user, write=True)
    try:
        return authorize(db, user, Capability.EMPLOYEE_WRITE, target=employee, write=True)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


def _avatar_path(employee: Employee) -> Path:
    return Path(settings.employee_avatar_upload_dir) / str(employee.id) / "avatar.webp"


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
        return [department for department in departments if department.id in allowed_ids
                or (department.is_active and department.business_type == DepartmentBusinessType.AUTO)]
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


@router.get("/{employee_id}/avatar")
def get_employee_avatar(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_employee_user)],
):
    employee = service.get_employee(db, employee_id, current_user.tenant_id)
    if employee.linked_user_id != current_user.id:
        authorized_employee_read(db, current_user, employee)
    path = _avatar_path(employee)
    if employee.photo_url != "employee-avatar" or not path.is_file():
        raise HTTPException(status_code=404, detail="Фотография не найдена")
    return FileResponse(path, media_type="image/webp", filename="avatar.webp")


@router.post("/{employee_id}/avatar", response_model=EmployeeRead)
async def upload_employee_avatar(
    employee_id: UUID,
    photo: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_employee_user)],
    reason: Annotated[str | None, Form(max_length=1000)] = None,
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_user.tenant_id, lock=True)
    context = _employee_photo_context(db, current_user, employee)
    if photo.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        await photo.close()
        raise HTTPException(status_code=422, detail="Допустимы фотографии JPEG, PNG или WebP")
    content = await photo.read(10 * 1024 * 1024 + 1)
    await photo.close()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Размер фотографии должен быть не более 10 МБ")
    try:
        image = Image.open(BytesIO(content))
        image = ImageOps.exif_transpose(image)
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise HTTPException(status_code=422, detail="Файл не является корректной фотографией") from error
    path = _avatar_path(employee)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    image.save(temporary, format="WEBP", quality=86, method=6)
    previous = path.read_bytes() if path.is_file() else None
    temporary.replace(path)
    before = {"photo_url": employee.photo_url}
    employee.photo_url = "employee-avatar"
    record_audit_event(
        db, tenant_id=current_user.tenant_id, event_type="EMPLOYEE_AVATAR_UPDATED",
        entity_type="Employee", entity_id=employee.id, operation="UPDATE_AVATAR",
        context=context, actor_user=current_user, before=before,
        after={"photo_url": employee.photo_url},
        reason=(reason.strip() or None) if reason else None,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)
        raise
    db.refresh(employee)
    return employee_read(db, employee)


@router.delete("/{employee_id}/avatar", response_model=EmployeeRead)
def delete_employee_avatar(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_employee_user)],
    reason: Annotated[str | None, Query(max_length=1000)] = None,
) -> EmployeeRead:
    employee = service.get_employee(db, employee_id, current_user.tenant_id, lock=True)
    context = _employee_photo_context(db, current_user, employee)
    before = {"photo_url": employee.photo_url}
    employee.photo_url = None
    record_audit_event(
        db, tenant_id=current_user.tenant_id, event_type="EMPLOYEE_AVATAR_REMOVED",
        entity_type="Employee", entity_id=employee.id, operation="REMOVE_AVATAR",
        context=context, actor_user=current_user, before=before,
        after={"photo_url": None},
        reason=(reason.strip() or None) if reason else None,
    )
    db.commit()
    _avatar_path(employee).unlink(missing_ok=True)
    return employee_read(db, employee)


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
    current_user: Annotated[User, Depends(get_current_employee_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    employee = service.get_employee(db, employee_id, current_user.tenant_id)
    authorized_employee_read(db, current_user, employee)
    return iiko_employee_service.list_shifts(db, employee, limit=limit)


@router.get("/{employee_id}/iiko/shifts/active", response_model=EmployeeIikoShiftRead | None)
def get_active_iiko_shift(
    employee_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_employee_user)],
):
    employee = service.get_employee(db, employee_id, current_user.tenant_id)
    authorized_employee_read(db, current_user, employee)
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
    since = date_from or (until - timedelta(days=1))
    if since > until or (until - since).days > 93:
        raise HTTPException(status_code=422, detail="Invalid shift sync period")
    try:
        shifts = await provider.get_personal_shifts(date_from=since, date_to=until)
    except IikoError as error:
        raise integration_error(error) from error
    return EmployeeIikoSyncRead.model_validate(
        iiko_employee_service.sync_shifts(
            db, shifts, tenant_id=current_admin.tenant_id,
        ),
        from_attributes=True,
    )
