from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.authorization import Capability, authorize, supply_visible_departments
from app.core.action_context import ActionContextError
from app.db.session import get_db
from app.models.user import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise credentials_error

    user = db.get(User, user_id)

    if user is None or not user.is_active:
        raise credentials_error

    return user


def get_current_admin(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    try:
        context = authorize(db, current_user, Capability.TECHNICAL_ADMIN)
    except ActionContextError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required",
        ) from error

    if isinstance(db, Session):
        db.info["action_context"] = context
        db.info["action_user"] = current_user
    return current_user


def _supply_permission(db: Session, user: User, capability: Capability, *, write: bool = False) -> User:
    try:
        context = authorize(db, user, capability, write=write)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail=error.message) from error
    if write:
        db.info["action_context"] = context
        db.info["action_user"] = user
    return user


def get_supply_reader(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return _supply_permission(db, current_user, Capability.SUPPLY_DOWNSTREAM_READ)


def get_supply_request_viewer(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    try:
        departments = supply_visible_departments(db, current_user)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail=error.message) from error
    if departments == set():
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра заявок")
    return current_user


def get_supply_operator(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return _supply_permission(db, current_user, Capability.SUPPLY_OPERATE, write=True)


def get_supplier_editor(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return _supply_permission(db, current_user, Capability.SUPPLIER_EDIT, write=True)


def get_payment_writer(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return _supply_permission(db, current_user, Capability.PAYMENT_WRITE, write=True)


def get_supply_technical_admin(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return _supply_permission(db, current_user, Capability.TECHNICAL_ADMIN, write=True)
