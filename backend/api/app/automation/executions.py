from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.automation import AutomationExecution, ExecutionStatus


DEFAULT_EXECUTION_LIMIT = 50
MAX_EXECUTION_LIMIT = 100


def validate_page(limit: int, offset: int) -> None:
    if not 1 <= limit <= MAX_EXECUTION_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_EXECUTION_LIMIT}"
        )
    if offset < 0:
        raise ValueError("offset must not be negative")


def list_executions(
    session: Session,
    *,
    schedule_id: int | None = None,
    status: ExecutionStatus | str | None = None,
    limit: int = DEFAULT_EXECUTION_LIMIT,
    offset: int = 0,
) -> list[AutomationExecution]:
    validate_page(limit, offset)
    statement = select(AutomationExecution)

    if schedule_id is not None:
        statement = statement.where(
            AutomationExecution.schedule_id == schedule_id
        )
    if status is not None:
        status_value = getattr(status, "value", status)
        statement = statement.where(
            AutomationExecution.status == status_value
        )

    statement = (
        statement.order_by(
            AutomationExecution.requested_at.desc(),
            AutomationExecution.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return session.scalars(statement).all()


def get_execution(
    session: Session,
    execution_id: UUID,
) -> AutomationExecution | None:
    return session.scalar(
        select(AutomationExecution).where(
            AutomationExecution.execution_id == execution_id
        )
    )


def get_latest_schedule_execution(
    session: Session,
    schedule_id: int,
) -> AutomationExecution | None:
    return session.scalar(
        select(AutomationExecution)
        .where(AutomationExecution.schedule_id == schedule_id)
        .order_by(
            AutomationExecution.requested_at.desc(),
            AutomationExecution.id.desc(),
        )
        .limit(1)
    )
