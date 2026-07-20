from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.automation import AutomationExecution, ExecutionStatus
from app.schemas.automation import AutomationCallbackResult


router = APIRouter(prefix="/automation", tags=["automation"])
callback_bearer = HTTPBearer(auto_error=False)

TERMINAL_STATUSES = {
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.CANCELLED,
}


def require_callback_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(callback_bearer),
    ],
) -> None:
    configured_token = settings.automation_callback_token
    provided_token = credentials.credentials if credentials else ""
    expected_token = (
        configured_token.get_secret_value()
        if configured_token is not None
        else ""
    )

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not expected_token
        or not compare_digest(
            provided_token.encode(),
            expected_token.encode(),
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def callback_matches_execution(
    execution: AutomationExecution,
    callback: AutomationCallbackResult,
) -> bool:
    return (
        execution.status == ExecutionStatus(callback.status.value)
        and execution.started_at == callback.started_at
        and execution.finished_at == callback.finished_at
        and execution.result == callback.result
        and execution.error_code == callback.error_code
        and execution.error_message == callback.error_message
    )


@router.post("/callback")
def receive_automation_callback(
    callback: AutomationCallbackResult,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[None, Depends(require_callback_token)],
) -> dict[str, str]:
    execution = db.scalar(
        select(AutomationExecution)
        .where(
            AutomationExecution.execution_id == callback.execution_id
        )
        .with_for_update()
    )

    if execution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation execution not found",
        )

    if callback_matches_execution(execution, callback):
        return {"status": "accepted"}

    if execution.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Automation execution is already finalized",
        )

    execution.status = ExecutionStatus(callback.status.value)
    execution.started_at = callback.started_at
    execution.finished_at = callback.finished_at
    execution.result = callback.result
    execution.error_code = callback.error_code
    execution.error_message = callback.error_message
    db.commit()

    return {"status": "accepted"}
