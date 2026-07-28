from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automation.outbox import (
    ClaimedOutboxEvent,
    OutboxClaimLostError,
)
from app.automation.supply_actions import (
    SUPPLY_ACTION_HANDLERS,
    SupplyAutomationContext,
)
from app.models.automation import (
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
)


class LocalAutomationActionExecutor:
    def __init__(
        self,
        session_factory: Callable[[], Session],
    ) -> None:
        self._session_factory = session_factory

    @staticmethod
    def supports(automation_type: str) -> bool:
        return automation_type in SUPPLY_ACTION_HANDLERS

    def execute(
        self,
        claim: ClaimedOutboxEvent,
        *,
        executed_at: datetime,
    ) -> dict[str, object]:
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise ValueError("executed_at must include a timezone")
        executed_at = executed_at.astimezone(timezone.utc)
        handler = SUPPLY_ACTION_HANDLERS.get(claim.automation_type)
        if handler is None:
            raise ValueError("Unsupported local automation action")

        with self._session_factory() as session:
            with session.begin():
                event = session.scalar(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.id == claim.id,
                        OutboxEvent.status == OutboxStatus.PROCESSING,
                        OutboxEvent.locked_by == claim.lock_token,
                    )
                    .with_for_update()
                )
                if event is None:
                    raise OutboxClaimLostError(
                        f"Outbox event {claim.event_id} is no longer owned "
                        "by this worker claim"
                    )

                execution = event.execution
                if execution.started_at is None:
                    execution.started_at = executed_at

                result = handler(
                    session,
                    SupplyAutomationContext(
                        execution_id=claim.execution_id,
                        tenant_id=claim.tenant_id,
                        requested_at=claim.requested_at,
                        executed_at=executed_at,
                    ),
                    claim.payload,
                )

                event.status = OutboxStatus.PUBLISHED
                event.published_at = executed_at
                event.next_attempt_at = None
                event.locked_at = None
                event.locked_by = None
                event.last_error = None

                execution.provider = "enterpriseos"
                execution.status = ExecutionStatus.SUCCEEDED
                execution.result = result
                execution.error_code = None
                execution.error_message = None
                execution.next_retry_at = None
                execution.attempt_count = event.attempt_count
                execution.finished_at = executed_at
                session.flush()

        return result
