from collections.abc import Callable
from datetime import datetime, timedelta, timezone

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
from app.employees.iiko import sync_shifts
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.models.automation import (
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
)


class LocalAutomationActionExecutor:
    SALES_REPORTS = "sales.finalize_reports"
    SALES_SYNC = "sales.sync_iiko"
    PRODUCT_RECIPES = "products.sync_iiko_recipes"
    PRODUCT_PRICES = "products.sync_iiko_prices"
    IIKO_SHIFT_SYNC = "employee.sync_iiko_shifts"

    def __init__(
        self,
        session_factory: Callable[[], Session],
    ) -> None:
        self._session_factory = session_factory

    @staticmethod
    def supports(automation_type: str) -> bool:
        return (
            automation_type in SUPPLY_ACTION_HANDLERS
            or automation_type in (LocalAutomationActionExecutor.IIKO_SHIFT_SYNC, LocalAutomationActionExecutor.SALES_SYNC, LocalAutomationActionExecutor.SALES_REPORTS, LocalAutomationActionExecutor.PRODUCT_PRICES, LocalAutomationActionExecutor.PRODUCT_RECIPES)
        )

    def execute(
        self,
        claim: ClaimedOutboxEvent,
        *,
        executed_at: datetime,
    ):
        if executed_at.tzinfo is None or executed_at.utcoffset() is None:
            raise ValueError("executed_at must include a timezone")
        executed_at = executed_at.astimezone(timezone.utc)
        if claim.automation_type in (self.SALES_SYNC, self.PRODUCT_PRICES, self.PRODUCT_RECIPES):
            return self._execute_sales_sync(claim, executed_at=executed_at)
        if claim.automation_type == self.IIKO_SHIFT_SYNC:
            return self._execute_iiko_shift_sync(claim, executed_at=executed_at)
        handler = SUPPLY_ACTION_HANDLERS.get(claim.automation_type)
        if claim.automation_type == self.SALES_REPORTS:
            from app.sales.reports import finalize_reports
            handler = finalize_reports
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
                if execution.status in (ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED,
                                         ExecutionStatus.TIMED_OUT, ExecutionStatus.CANCELLED):
                    raise OutboxClaimLostError("Local execution already terminal")
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

    async def _execute_sales_sync(self, claim, *, executed_at):
        from app.sales.sync import sync_sales
        from app.schemas.automation import SalesSyncPayload

        snapshot = None
        if claim.automation_type == self.PRODUCT_RECIPES:
            from app.product_knowledge.recipes import RecipeRefreshPayload, collect_recipes
            payload = RecipeRefreshPayload.model_validate(claim.payload)
            snapshot = await collect_recipes(self._session_factory, tenant_id=claim.tenant_id,
                                             payload=payload, now=executed_at)
            result = {}
        elif claim.automation_type == self.PRODUCT_PRICES:
            from app.product_knowledge.price_refresh import PriceRefreshPayload, collect_prices
            payload = PriceRefreshPayload.model_validate(claim.payload)
            snapshot = await collect_prices(self._session_factory, tenant_id=claim.tenant_id,
                                            payload=payload, now=executed_at)
            result = dict(products=len(snapshot.products), contexts=len(snapshot.contexts))
        else:
            payload = SalesSyncPayload.model_validate(claim.payload)
            result = await sync_sales(self._session_factory, tenant_id=claim.tenant_id,
                                      source_id=payload.source_id, now=executed_at)
        with self._session_factory() as session:
            with session.begin():
                event = session.scalar(select(OutboxEvent).where(
                    OutboxEvent.id == claim.id,
                    OutboxEvent.status == OutboxStatus.PROCESSING,
                    OutboxEvent.locked_by == claim.lock_token,
                ).with_for_update())
                if event is None:
                    raise OutboxClaimLostError("Sales sync claim no longer owned")
                execution = event.execution
                if execution.status in (ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED,
                                         ExecutionStatus.TIMED_OUT, ExecutionStatus.CANCELLED):
                    raise OutboxClaimLostError("Sales sync execution already terminal")
                if claim.automation_type == self.PRODUCT_RECIPES:
                    from app.product_knowledge.recipes import publish_recipes
                    result = publish_recipes(session, claim.tenant_id, snapshot, execution_id=claim.execution_id)
                elif snapshot is not None:
                    from app.product_knowledge.price_refresh import source_price_preview, publish_source_prices
                    report = source_price_preview(session, claim.tenant_id, snapshot)
                    row = publish_source_prices(session, claim.tenant_id, snapshot,
                        expected_hash=report['plan_hash'], execution_id=claim.execution_id)
                    result['snapshot_id'] = str(row.id)
                event.status, event.published_at = OutboxStatus.PUBLISHED, executed_at
                event.next_attempt_at = event.locked_at = event.locked_by = event.last_error = None
                execution.provider, execution.status = "enterpriseos", ExecutionStatus.SUCCEEDED
                execution.result = result
                execution.started_at = execution.started_at or executed_at
                execution.finished_at = executed_at
                execution.error_code = execution.error_message = execution.next_retry_at = None
                execution.attempt_count = event.attempt_count
                session.flush()
        return result

    async def _execute_iiko_shift_sync(
        self,
        claim: ClaimedOutboxEvent,
        *,
        executed_at: datetime,
    ) -> dict[str, object]:
        lookback_days = claim.payload.get("lookback_days", 7)
        if isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or not 1 <= lookback_days <= 93:
            raise ValueError("lookback_days must be an integer between 1 and 93")
        date_to = executed_at.date()
        date_from = date_to - timedelta(days=lookback_days)
        async with IikoServerClient(get_iiko_settings()) as provider:
            external_shifts = await provider.get_personal_shifts(
                date_from=date_from,
                date_to=date_to,
            )

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
                        f"Outbox event {claim.event_id} is no longer owned by this worker claim"
                    )
                result = sync_shifts(
                    session,
                    external_shifts,
                    tenant_id=claim.tenant_id,
                    seen_at=executed_at,
                    commit=False,
                )
                payload = {
                    "received": result.received,
                    "matched": result.matched,
                    "created": result.created,
                    "updated": result.updated,
                    "unchanged": result.unchanged,
                    "unresolved_department": result.unresolved_department,
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                }
                execution = event.execution
                if execution.started_at is None:
                    execution.started_at = executed_at
                event.status = OutboxStatus.PUBLISHED
                event.published_at = executed_at
                event.next_attempt_at = None
                event.locked_at = None
                event.locked_by = None
                event.last_error = None
                execution.provider = "enterpriseos"
                execution.status = ExecutionStatus.SUCCEEDED
                execution.result = payload
                execution.error_code = None
                execution.error_message = None
                execution.next_retry_at = None
                execution.attempt_count = event.attempt_count
                execution.finished_at = executed_at
                session.flush()
        return payload
