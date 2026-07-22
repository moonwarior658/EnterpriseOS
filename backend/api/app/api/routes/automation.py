from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.automation.audit import (
    DEFAULT_AUDIT_LIMIT,
    count_schedule_audit_events,
    list_schedule_audit_events,
    safe_schedule_audit_metadata,
)
from app.automation.dispatch import (
    AutomationScheduleNotFoundError,
    DisabledAutomationScheduleError,
    dispatch_schedule_now,
)
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
    NO_EXECUTION_STATE,
    classify_execution_status,
    count_executions,
    execution_duration_seconds,
    get_execution,
    get_latest_schedule_execution,
    get_latest_schedule_executions,
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
    AutomationExecutionHistoryItem,
    AutomationExecutionHistoryPage,
    AutomationLatestExecutionItem,
    AutomationScheduleCreate,
    AutomationScheduleAuditItem,
    AutomationScheduleAuditPage,
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


@router.get(
    "/schedules/executions/latest",
    response_model=list[AutomationLatestExecutionItem],
)
def read_latest_schedule_executions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    schedule_ids: Annotated[
        list[int] | None,
        Query(alias="schedule_id"),
    ] = None,
) -> list[AutomationLatestExecutionItem]:
    return [
        public_latest_execution_item(schedule_id, execution)
        for schedule_id, execution in get_latest_schedule_executions(
            db,
            schedule_ids,
        )
    ]


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
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> AutomationSchedule:
    schedule = get_schedule(db, schedule_id)

    if schedule is None:
        raise schedule_not_found()

    try:
        return update_schedule(
            db,
            schedule,
            payload,
            actor_user_id=current_admin.id,
        )
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


@router.post(
    "/schedules/{schedule_id}/run",
    response_model=AutomationExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
def run_automation_schedule(
    schedule_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> AutomationExecution:
    try:
        return dispatch_schedule_now(
            db,
            schedule_id,
            actor_user_id=current_admin.id,
        )
    except AutomationScheduleNotFoundError as error:
        raise schedule_not_found() from error
    except DisabledAutomationScheduleError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disabled automation schedule cannot be started",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start automation schedule",
        ) from error


@router.get(
    "/schedules/{schedule_id}/audit",
    response_model=AutomationScheduleAuditPage,
)
def read_schedule_audit(
    schedule_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_AUDIT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AutomationScheduleAuditPage:
    if get_schedule(db, schedule_id) is None:
        raise schedule_not_found()

    rows = list_schedule_audit_events(
        db,
        schedule_id,
        limit=limit,
        offset=offset,
    )
    return AutomationScheduleAuditPage(
        items=[
            AutomationScheduleAuditItem(
                id=event.id,
                event_type=event.event_type.value,
                actor_user_id=event.actor_user_id,
                actor_display_name=display_name,
                occurred_at=event.occurred_at,
                metadata=safe_schedule_audit_metadata(
                    event.event_type,
                    event.metadata_,
                ),
            )
            for event, display_name in rows
        ],
        total=count_schedule_audit_events(db, schedule_id),
        limit=limit,
        offset=offset,
    )


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
    response_model=AutomationExecutionHistoryPage,
)
def read_schedule_executions(
    schedule_id: int,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = DEFAULT_EXECUTION_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AutomationExecutionHistoryPage:
    if get_schedule(db, schedule_id) is None:
        raise schedule_not_found()

    executions = list_executions(
        db,
        schedule_id=schedule_id,
        limit=limit,
        offset=offset,
    )
    return AutomationExecutionHistoryPage(
        items=[public_history_item(item) for item in executions],
        total=count_executions(db, schedule_id=schedule_id),
        limit=limit,
        offset=offset,
    )


def public_history_item(
    execution: AutomationExecution,
) -> AutomationExecutionHistoryItem:
    public_state = classify_execution_status(execution.status)

    return AutomationExecutionHistoryItem(
        status=AutomationCallbackStatus(execution.status.value),
        requested_at=execution.requested_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        duration_seconds=execution_duration_seconds(execution),
        user_status=public_state.user_status,
        user_message=public_state.user_message,
        error_category=public_state.error_category,
        error_code=public_state.error_code,
        error_message=(
            public_state.user_message
            if public_state.error_code is not None
            else None
        ),
    )


def public_latest_execution_item(
    schedule_id: int,
    execution: AutomationExecution | None,
) -> AutomationLatestExecutionItem:
    public_state = (
        classify_execution_status(execution.status)
        if execution is not None
        else NO_EXECUTION_STATE
    )
    return AutomationLatestExecutionItem(
        schedule_id=schedule_id,
        status=(
            AutomationCallbackStatus(execution.status.value)
            if execution is not None
            else None
        ),
        requested_at=execution.requested_at if execution else None,
        started_at=execution.started_at if execution else None,
        finished_at=execution.finished_at if execution else None,
        duration_seconds=(
            execution_duration_seconds(execution) if execution else None
        ),
        user_status=public_state.user_status,
        user_message=public_state.user_message,
        error_category=public_state.error_category,
        error_code=public_state.error_code,
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
