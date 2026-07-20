from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.automation import (
    AutomationExecution,
    ExecutionStatus,
)


EXECUTION_TIMEOUT_CODE = "AutomationExecutionTimeout"
EXECUTION_TIMEOUT_MESSAGE = (
    "Automation execution did not return a callback before timeout"
)


def aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")

    return value.astimezone(timezone.utc)


def timeout_statement(
    now: datetime,
    *,
    timeout: timedelta,
    limit: int = 100,
) -> Select[tuple[AutomationExecution]]:
    now = aware_utc(now, field_name="now")

    if timeout <= timedelta(0):
        raise ValueError("timeout must be positive")

    if limit < 1:
        raise ValueError("limit must be at least 1")

    stale_before = now - timeout

    return (
        select(AutomationExecution)
        .where(
            AutomationExecution.status == ExecutionStatus.RUNNING,
            AutomationExecution.updated_at <= stale_before,
        )
        .order_by(
            AutomationExecution.updated_at,
            AutomationExecution.id,
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def expire_stale_executions(
    session_factory: Callable[[], Session],
    *,
    now: datetime,
    timeout: timedelta,
    limit: int = 100,
) -> list[UUID]:
    now = aware_utc(now, field_name="now")
    statement = timeout_statement(
        now,
        timeout=timeout,
        limit=limit,
    )

    with session_factory() as session:
        with session.begin():
            executions = session.scalars(statement).all()

            for execution in executions:
                execution.status = ExecutionStatus.TIMED_OUT
                execution.finished_at = now
                execution.result = None
                execution.error_code = EXECUTION_TIMEOUT_CODE
                execution.error_message = EXECUTION_TIMEOUT_MESSAGE
                execution.next_retry_at = None

            execution_ids = [
                execution.execution_id for execution in executions
            ]

    return execution_ids
