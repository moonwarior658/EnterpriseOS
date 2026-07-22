from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.automation import (
    AutomationExecution,
    AutomationSchedule,
    ExecutionStatus,
)


DEFAULT_EXECUTION_LIMIT = 50
MAX_EXECUTION_LIMIT = 100


@dataclass(frozen=True)
class PublicExecutionState:
    user_status: str
    user_message: str
    error_category: str | None = None
    error_code: str | None = None


PUBLIC_EXECUTION_STATES = {
    ExecutionStatus.PENDING: PublicExecutionState(
        user_status="Ожидает запуска",
        user_message="Запуск ожидает обработки",
    ),
    ExecutionStatus.DISPATCHING: PublicExecutionState(
        user_status="Запускается",
        user_message="Регламент запускается",
    ),
    ExecutionStatus.RUNNING: PublicExecutionState(
        user_status="Выполняется",
        user_message="Регламент выполняется",
    ),
    ExecutionStatus.RETRYING: PublicExecutionState(
        user_status="Ожидает повторного запуска",
        user_message="Система повторит запуск автоматически",
    ),
    ExecutionStatus.SUCCEEDED: PublicExecutionState(
        user_status="Выполнено",
        user_message="Регламент выполнен",
    ),
    ExecutionStatus.FAILED: PublicExecutionState(
        user_status="Ошибка выполнения",
        user_message="Не удалось выполнить регламент",
        error_category="execution_failed",
        error_code="AUTOMATION_FAILED",
    ),
    ExecutionStatus.TIMED_OUT: PublicExecutionState(
        user_status="Превышено время ожидания",
        user_message="Регламент не завершился за отведённое время",
        error_category="timeout",
        error_code="AUTOMATION_TIMED_OUT",
    ),
    ExecutionStatus.CANCELLED: PublicExecutionState(
        user_status="Отменено",
        user_message="Запуск регламента отменён",
        error_category="cancelled",
        error_code="AUTOMATION_CANCELLED",
    ),
}

NO_EXECUTION_STATE = PublicExecutionState(
    user_status="Нет запусков",
    user_message="Регламент ещё не запускался",
)


def classify_execution_status(
    status: ExecutionStatus | str,
) -> PublicExecutionState:
    return PUBLIC_EXECUTION_STATES[ExecutionStatus(status)]


def execution_duration_seconds(
    execution: AutomationExecution,
) -> float | None:
    if execution.started_at is None or execution.finished_at is None:
        return None

    return max(
        0.0,
        (execution.finished_at - execution.started_at).total_seconds(),
    )


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


def count_executions(
    session: Session,
    *,
    schedule_id: int,
) -> int:
    statement = select(func.count(AutomationExecution.id)).where(
        AutomationExecution.schedule_id == schedule_id
    )
    return session.scalar(statement) or 0


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


def get_latest_schedule_executions(
    session: Session,
    schedule_ids: list[int] | None = None,
) -> list[tuple[int, AutomationExecution | None]]:
    normalized_schedule_ids = (
        sorted(set(schedule_ids)) if schedule_ids is not None else None
    )
    if normalized_schedule_ids == []:
        return []

    ranked_statement = (
        select(
            AutomationExecution.id.label("execution_row_id"),
            AutomationExecution.schedule_id.label("schedule_id"),
            func.row_number()
            .over(
                partition_by=AutomationExecution.schedule_id,
                order_by=(
                    AutomationExecution.requested_at.desc(),
                    AutomationExecution.id.desc(),
                ),
            )
            .label("execution_rank"),
        )
        .where(AutomationExecution.schedule_id.is_not(None))
    )
    if normalized_schedule_ids is not None:
        ranked_statement = ranked_statement.where(
            AutomationExecution.schedule_id.in_(normalized_schedule_ids)
        )
    ranked_executions = ranked_statement.subquery()
    statement = (
        select(AutomationSchedule.id, AutomationExecution)
        .outerjoin(
            ranked_executions,
            and_(
                ranked_executions.c.schedule_id == AutomationSchedule.id,
                ranked_executions.c.execution_rank == 1,
            ),
        )
        .outerjoin(
            AutomationExecution,
            AutomationExecution.id
            == ranked_executions.c.execution_row_id,
        )
        .order_by(AutomationSchedule.id.asc())
    )

    if normalized_schedule_ids is not None:
        statement = statement.where(
            AutomationSchedule.id.in_(normalized_schedule_ids)
        )

    return [
        (schedule_id, execution)
        for schedule_id, execution in session.execute(statement).all()
    ]
