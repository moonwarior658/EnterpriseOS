"""Local action invoked exclusively through existing scheduler/outbox delivery."""
from datetime import datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy import select
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.models.sales import SalesSyncState
from app.sales.service import SalesContractError, daily_query, ingest_day, retail_mappings

ACTION = "sales.sync_iiko"


def source_identity(settings) -> str:
    # Namespace by configured endpoint, without including credentials.
    return sha256(str(settings.base_url).rstrip('/').encode()).hexdigest()


async def sync_sales(session_factory, *, tenant_id: str, source_id: str, now: datetime) -> dict:
    settings = get_iiko_settings()
    with session_factory() as db:
        state = db.get(SalesSyncState, (tenant_id, source_id))
        if state is None:
            raise SalesContractError("SALES_SOURCE_NOT_CONFIGURED")
    try:
        if source_id != source_identity(settings):
            raise SalesContractError("SALES_SOURCE_INSTANCE_MISMATCH")
        settings.validate_enabled()
        with session_factory() as db:
            state = db.get(SalesSyncState, (tenant_id, source_id))
            points = list(retail_mappings(db, tenant_id))
            if not points:
                raise SalesContractError("SALES_NO_CONFIRMED_POINTS")
            today = now.astimezone(ZoneInfo(state.source_timezone)).date()
            if state.history_from > today:
                raise SalesContractError("SALES_HISTORY_INVALID")
            cursor = max(state.history_from, min(state.backfill_next, today))
            # Freshness + bounded daily history scan. Cycles through stored history
            # forever, catching late changes and newly approved point mappings.
            days = {today - timedelta(days=i) for i in range(7) if today - timedelta(days=i) >= state.history_from}
            for _ in range(7):
                days.add(cursor)
                cursor = cursor + timedelta(days=1) if cursor < today else state.history_from
        received = 0
        with session_factory() as db:
            with db.begin():
                state = db.scalar(select(SalesSyncState).where(
                    SalesSyncState.tenant_id == tenant_id,
                    SalesSyncState.source_id == source_id,
                ).with_for_update(skip_locked=True))
                if state is None:
                    return {"skipped": True, "reason": "SALES_SYNC_ALREADY_RUNNING"}
                state.last_attempt_at = now
                async with IikoServerClient(settings) as client:
                    for day in sorted(days):
                        rows = await client.get_sales_olap(daily_query(day, points))
                        received += ingest_day(db, rows, state=state, day=day,
                                               department_ids=points, seen_at=now)
                state.last_success_at, state.error_code, state.backfill_next = now, None, cursor
        return {"days": len(days), "received": received}
    except Exception as error:
        code = str(error) if isinstance(error, SalesContractError) else "SALES_SYNC_FAILED"
        with session_factory() as db:
            with db.begin():
                state = db.get(SalesSyncState, (tenant_id, source_id))
                state.last_attempt_at = now
                state.error_code = code
        raise SalesContractError(code) from None
