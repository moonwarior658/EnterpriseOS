from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.audit.service import record_audit_event
from app.core.action_context import ActionContextError, resolve_action_context
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.user import OwnPasswordChange, UserRead
from app.models.user import UserAccountType
from app.models.employee import EmployeeRole


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> Token:
    user = db.scalar(
        select(User).where(User.username == form_data.username)
    )

    if user is None:
        verify_password(form_data.password, DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active or not verify_password(
        form_data.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Token(
        access_token=create_access_token(user.id),
        token_type="bearer",
    )


@router.get("/me", response_model=UserRead)
def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    return current_user


@router.post("/change-password", status_code=204)
def change_own_password(
    payload: OwnPasswordChange,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    user = db.get(User, current_user.id)
    if user is None or not user.is_active or user.account_type != UserAccountType.HUMAN:
        raise HTTPException(status_code=403, detail="Личная смена пароля доступна только сотруднику")
    if not verify_password(payload.current_password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Текущий пароль указан неверно")
    try:
        context = resolve_action_context(
            db, user, required_roles=frozenset(EmployeeRole),
            role_precedence=tuple(EmployeeRole), write=False,
        )
    except ActionContextError as error:
        if error.code != "EMPLOYEE_NOT_LINKED":
            raise HTTPException(status_code=403, detail=error.message) from error
        context = None
    user.hashed_password = hash_password(payload.new_password)
    record_audit_event(
        db, tenant_id=user.tenant_id, event_type="USER_PASSWORD_CHANGED",
        entity_type="User", entity_id=user.id, operation="CHANGE_PASSWORD",
        context=context, actor_user=user, before={}, after={},
    )
    db.commit()
