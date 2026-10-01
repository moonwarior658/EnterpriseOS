from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.audit.service import record_audit_event
from app.core.action_context import ActionContextError
from app.core.authorization import Capability, authorize, linked_employee
from app.core.action_context import resolve_action_context
from app.models.employee import EmployeeRole
from app.core.security import generate_password, hash_password
from app.db.session import get_db
from app.models.employee import Employee, EmployeeStatus
from app.models.user import User, UserAccountType
from app.schemas.user import UserCreate, UserCreated, UserRead, UserUpdate


router = APIRouter(prefix="/users", tags=["users"])


def permission(db: Session, actor: User, capability: Capability, target: User | None = None):
    employee = linked_employee(db, target) if target else None
    try:
        return authorize(db, actor, capability, target=employee, write=capability != Capability.USER_READ)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail={"code": error.code, "message": error.message}) from error


def visible_user(context, user: User) -> bool:
    return user.account_type == UserAccountType.HUMAN or context.authorized_as.value == "ADMIN"


@router.get("", response_model=list[UserRead])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_user)],
) -> list[User]:
    try:
        base = resolve_action_context(db, current_admin, write=False)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail={"code": error.code, "message": error.message}) from error
    if not base.roles & {EmployeeRole.ADMIN, EmployeeRole.DIRECTOR,
                         EmployeeRole.DEPUTY_DIRECTOR, EmployeeRole.NETWORK_MANAGER}:
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра учётных записей")
    result = []
    for user in db.scalars(select(User).where(
        User.tenant_id == current_admin.tenant_id,
    ).order_by(User.id)).all():
        if user.account_type == UserAccountType.SERVICE and EmployeeRole.ADMIN not in base.roles:
            continue
        try:
            permission(db, current_admin, Capability.USER_READ, user)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            continue
        result.append(user)
    return result


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_user)],
) -> User:
    user = db.scalar(select(User).where(
        User.id == user_id,
        User.tenant_id == current_admin.tenant_id,
    ))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    context = permission(db, current_admin, Capability.USER_READ, user)
    if not visible_user(context, user):
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post(
    "",
    response_model=UserCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_user)],
) -> UserCreated:
    employee = None
    if payload.employee_id is not None:
        employee = db.scalar(select(Employee).where(
            Employee.id == payload.employee_id, Employee.tenant_id == current_admin.tenant_id,
        ).with_for_update())
        if employee is None:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        if employee.linked_user_id is not None:
            raise HTTPException(status_code=409, detail="Сотрудник уже связан с учётной записью")
    try:
        context = authorize(db, current_admin, Capability.USER_CREATE,
                            target=employee, write=True)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail={"code": error.code, "message": error.message}) from error
    if context.authorized_as.value != "ADMIN" and (
        payload.account_type != UserAccountType.HUMAN or employee is None
        or payload.is_admin or payload.can_view_requests
    ):
        raise HTTPException(status_code=403, detail="Недостаточно прав для создания учётной записи")
    existing_user = db.scalar(
        select(User).where(User.username == payload.username)
    )

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Login already exists",
        )

    temporary_password = (
        generate_password()
        if payload.account_type == UserAccountType.HUMAN
        else None
    )
    password = temporary_password or payload.password
    if password is None:  # Protected by UserCreate validation.
        raise HTTPException(status_code=422, detail="Password is required")

    user = User(
        username=payload.username,
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
        hashed_password=hash_password(password),
        is_active=True,
        is_admin=payload.is_admin,
        can_view_requests=payload.can_view_requests,
        account_type=payload.account_type,
        tenant_id=current_admin.tenant_id,
    )

    db.add(user)

    try:
        db.flush()
        if employee is not None:
            employee.linked_user_id = user.id
        record_audit_event(
            db, tenant_id=current_admin.tenant_id, event_type="USER_CREATED",
            entity_type="User", entity_id=user.id, operation="CREATE",
            context=context, actor_user=current_admin, before={},
            after={"account_type": user.account_type.value,
                   "employee_id": str(employee.id) if employee else None},
        )
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Login already exists",
        ) from error

    return UserCreated(
        **UserRead.model_validate(user).model_dump(),
        temporary_password=temporary_password,
    )


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_user)],
) -> User:
    user = db.scalar(select(User).where(
        User.id == user_id,
        User.tenant_id == current_admin.tenant_id,
    ))

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    updates = payload.model_dump(exclude_unset=True)
    reason = updates.pop("reason", None)
    if not updates:
        raise HTTPException(status_code=422, detail="Укажите изменение учётной записи")
    if "is_active" in updates and updates["is_active"] != user.is_active and not reason:
        raise HTTPException(status_code=422, detail="Укажите причину блокировки или активации")
    capability = Capability.USER_BLOCK if set(updates) <= {"is_active"} else Capability.TECHNICAL_ADMIN
    context = permission(db, current_admin, capability, user)
    if user.account_type == UserAccountType.SERVICE and context.authorized_as.value != "ADMIN":
        raise HTTPException(status_code=403, detail="Сервисные учётные записи доступны только администратору")

    if user.id == current_admin.id:
        if updates.get("is_active") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot block your own account",
            )

        if updates.get("is_admin") is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot remove your own administrator role",
            )

    new_username = updates.get("username")

    if new_username is not None:
        existing_user = db.scalar(
            select(User).where(
                User.username == new_username,
                User.id != user.id,
            )
        )

        if existing_user is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Login already exists",
            )

    password = updates.pop("password", None)

    if password is not None:
        user.hashed_password = hash_password(password)

    if updates.get("is_active") is True:
        dismissed_employee = db.scalar(
            select(Employee.id).where(
                Employee.tenant_id == current_admin.tenant_id,
                Employee.linked_user_id == user.id,
                Employee.status == EmployeeStatus.DISMISSED,
            )
        )
        if dismissed_employee is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dismissed employee account cannot be activated",
            )

    if "is_active" in updates:
        user.blocked_by_employee_dismissal = False

    before = {field: getattr(user, field) for field in updates if field != "password"}
    for field, value in updates.items():
        setattr(user, field, value)

    record_audit_event(
        db, tenant_id=current_admin.tenant_id, event_type="USER_UPDATED",
        entity_type="User", entity_id=user.id, operation="UPDATE",
        context=context, actor_user=current_admin, before=before,
        after={field: getattr(user, field) for field in before}, reason=reason,
    )

    try:
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Login already exists",
        ) from error

    return user
