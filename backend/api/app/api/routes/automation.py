from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.automation.schedules import (
    InvalidScheduleScopeError,
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from app.automation.executions import (
    DEFAULT_EXECUTION_LIMIT,
    get_execution,
    get_latest_schedule_execution,
    list_executions,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.automation import (
    AutomationExecution,
    AutomationSchedule,
    ExecutionStatus,
)
from app.models.user import User
from app.schemas.automation import (
    AutomationCallbackResult,
    AutomationCallbackStatus,
    AutomationExecutionRead,
    AutomationScheduleCreate,
    AutomationScheduleRead,
    AutomationScheduleUpdate,
)


router = APIRouter(prefix="/automation", tags=["automation"])
callback_bearer = HTTPBearer(auto_error=False)

TERMINAL_STATUSES = {
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMED_OUT,
    ExecutionStatus.CANCELLED,
}


def schedule_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Automation schedule not found",
    )


@router.get("/schedules", response_model=list[AutomationScheduleRead])
def read_schedules(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> list[AutomationSchedule]:
    return list_schedules(db)


@router.post(
    "/schedules",
    response_model=AutomationScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_automation_schedule(
    payload: AutomationScheduleCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> AutomationSchedule:
    return create_schedule(
        db,
        payload,
        created_by_user_id=current_admin.id,
    )


@router.get(
    "/schedules/{schedule_id}",
    response_model=AutomationScheduleRead,
)
def read_automation_schedule(
    schedule_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> AutomationSchedule:
    schedule = get_schedule(db, schedule_id)

    if schedule is None:
        raise schedule_not_found()

    return schedule


@router.patch(
    "/schedules/{schedule_id}",
    response_model=AutomationScheduleRead,
)
def update_automation_schedule(
    schedule_id: int,
    payload: AutomationScheduleUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> AutomationSchedule:
    schedule = get_schedule(db, schedule_id)

    if schedule is None:
        raise schedule_not_found()

    try:
        return update_schedule(db, schedule, payload)
    except InvalidScheduleScopeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_automation_schedule(
    schedule_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> None:
    schedule = get_schedule(db, schedule_id)

    if schedule is None:
        raise schedule_not_found()

    delete_schedule(db, schedule)


def execution_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Automation execution not found",
    )


@router.get("/executions", response_model=list[AutomationExecutionRead])
def read_executions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    schedule_id: int | None = None,
    execution_status: Annotated[
        AutomationCallbackStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_EXECUTION_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AutomationExecution]:
    return list_executions(
        db,
        schedule_id=schedule_id,
        status=execution_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/executions/{execution_id}",
    response_model=AutomationExecutionRead,
)
def read_execution(
    execution_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> AutomationExecution:
    execution = get_execution(db, execution_id)
    if execution is None:
        raise execution_not_found()
    return execution


@router.get(
    "/schedules/{schedule_id}/executions/latest",
    response_model=AutomationExecutionRead | None,
)
def read_latest_schedule_execution(
    schedule_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> AutomationExecution | None:
    if get_schedule(db, schedule_id) is None:
        raise schedule_not_found()
    return get_latest_schedule_execution(db, schedule_id)


@router.get(
    "/schedules/{schedule_id}/executions",
    response_model=list[AutomationExecutionRead],
)
def read_schedule_executions(
    schedule_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_EXECUTION_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AutomationExecution]:
    if get_schedule(db, schedule_id) is None:
        raise schedule_not_found()
    return list_executions(
        db,
        schedule_id=schedule_id,
        limit=limit,
        offset=offset,
    )


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
