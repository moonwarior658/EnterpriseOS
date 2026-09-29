from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.action_context import (
    ActionContext,
    ActionContextError,
    confirm_shift_substitution,
    resolve_action_context,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.action_context import ActionContextRead, ShiftSubstitutionConfirm


router = APIRouter(prefix="/auth/action-context", tags=["auth"])


def action_context_http_error(error: ActionContextError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": error.code, "message": error.message, **error.context},
    )


def action_context_read(context: ActionContext) -> ActionContextRead:
    return ActionContextRead(
        user_id=context.user_id,
        employee_id=context.employee_id,
        roles=sorted(context.roles, key=lambda role: role.value),
        authorized_as=context.authorized_as,
        primary_department_id=context.primary_department_id,
        actual_department_id=context.actual_department_id,
        shift_id=context.shift_id,
        shift_opened_at=context.shift_opened_at,
        substitution_confirmed=context.substitution_confirmed,
        determined_at=context.determined_at,
    )


@router.get("", response_model=ActionContextRead)
def read_action_context(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ActionContextRead:
    try:
        return action_context_read(resolve_action_context(db, user, write=False))
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.post("/shift-substitution-confirmation", response_model=ActionContextRead)
def confirm_substitution(
    payload: ShiftSubstitutionConfirm,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ActionContextRead:
    try:
        return action_context_read(confirm_shift_substitution(
            db, user, shift_id=payload.shift_id
        ))
    except ActionContextError as error:
        raise action_context_http_error(error) from error
