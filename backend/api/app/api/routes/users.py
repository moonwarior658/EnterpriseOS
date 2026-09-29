from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.security import generate_password, hash_password
from app.db.session import get_db
from app.models.employee import Employee, EmployeeStatus
from app.models.user import User, UserAccountType
from app.schemas.user import UserCreate, UserCreated, UserRead, UserUpdate


router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserRead])
def list_users(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .where(User.tenant_id == current_admin.tenant_id)
            .order_by(User.id)
        ).all()
    )


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
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
    return user


@router.post(
    "",
    response_model=UserCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> UserCreated:
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
    current_admin: Annotated[User, Depends(get_current_admin)],
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

    for field, value in updates.items():
        setattr(user, field, value)

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
