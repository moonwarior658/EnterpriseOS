"""Local action through existing scheduler/outbox; no DB connection during iiko I/O."""
import calendar
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update, or_
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.models.sales import SalesSyncState, SalesDaySync
from app.sales.service import SalesContractError, daily_query, ingest_day, retail_mappings

ACTION = "sales.sync_iiko"
BACKFILL_DAYS_PER_RUN = 31
LEASE_DURATION = timedelta(minutes=5)


def source_identity(settings) -> str:
    return sha256(str(settings.base_url).rstrip('/').encode()).hexdigest()


def required_history_start(today):
    # Six months of selectable dates, plus an equally long comparison period.
    year, month = divmod(today.year * 12 + today.month - 7, 12)
    earliest = today.replace(year=year, month=month + 1,
        day=min(today.day, calendar.monthrange(year, month + 1)[1]))
    return earliest - timedelta(days=(today - earliest).days + 1)


def sync_days(db, state, today):
    floor = required_history_start(today)
    # Preserve all older stored facts; query checkpoints only in the UI/comparison window.
    loaded = set(db.scalars(select(SalesDaySync.business_date).where(
        SalesDaySync.tenant_id == state.tenant_id, SalesDaySync.source_id == state.source_id,
        SalesDaySync.business_date.between(floor, today))))
    recent = [today - timedelta(days=i) for i in range(7)]
    missing = [today - timedelta(days=i) for i in range((today - floor).days + 1)
               if today - timedelta(days=i) not in loaded and today - timedelta(days=i) not in recent]
    cursor = max(state.history_from, min(state.backfill_next, today))
    corrections = []
    for _ in range(7):
        corrections.append(cursor)
        cursor = cursor + timedelta(days=1) if cursor < today else state.history_from
    # Recent sales first, then newest missing history, then bounded historical corrections.
    return list(dict.fromkeys(recent + missing[:BACKFILL_DAYS_PER_RUN] + corrections)), cursor


def wall_now():
    return datetime.now(timezone.utc)


def lease_guard(db, tenant_id, source_id, token):
    return db.scalar(select(SalesSyncState).where(
        SalesSyncState.tenant_id == tenant_id, SalesSyncState.source_id == source_id,
        SalesSyncState.lease_token == token, SalesSyncState.lease_until > wall_now(),
    ).with_for_update())


async def sync_sales(session_factory, *, tenant_id: str, source_id: str, now: datetime) -> dict:
    settings = get_iiko_settings()
    token = uuid4()
    with session_factory() as db:
        state = db.get(SalesSyncState, (tenant_id, source_id))
        if state is None:
            raise SalesContractError("SALES_SOURCE_NOT_CONFIGURED")
    try:
        if source_id != source_identity(settings):
            raise SalesContractError("SALES_SOURCE_INSTANCE_MISMATCH")
        settings.validate_enabled()
        with session_factory.begin() as db:
            clock = wall_now()
            state = db.scalar(update(SalesSyncState).where(
                SalesSyncState.tenant_id == tenant_id, SalesSyncState.source_id == source_id,
                or_(SalesSyncState.lease_until.is_(None), SalesSyncState.lease_until <= clock),
            ).values(lease_token=token, lease_until=clock + LEASE_DURATION,
                     last_attempt_at=now).returning(SalesSyncState))
            if state is None:
                return {"skipped": True, "reason": "SALES_SYNC_ALREADY_RUNNING"}
            points = list(retail_mappings(db, tenant_id))
            if not points:
                raise SalesContractError("SALES_NO_CONFIRMED_POINTS")
            today = now.astimezone(ZoneInfo(state.source_timezone)).date()
            if state.history_from > today:
                raise SalesContractError("SALES_HISTORY_INVALID")
            state.history_from = min(state.history_from, required_history_start(today))
            days, next_cursor = sync_days(db, state, today)
        received = 0
        async with IikoServerClient(settings) as client:
            for day in days:
                with session_factory.begin() as db:
                    state = lease_guard(db, tenant_id, source_id, token)
                    if state is None:
                        raise SalesContractError("SALES_SYNC_LEASE_LOST")
                    state.lease_until = wall_now() + LEASE_DURATION
                # No Session or checked-out connection is held across this await.
                rows = await client.get_sales_olap(daily_query(day, points))
                with session_factory.begin() as db:
                    state = lease_guard(db, tenant_id, source_id, token)
                    if state is None:
                        raise SalesContractError("SALES_SYNC_LEASE_LOST")
                    # Each authoritative daily snapshot and checkpoint commit atomically.
                    received += ingest_day(db, rows, state=state, day=day,
                                           department_ids=points, seen_at=now)
        with session_factory.begin() as db:
            state = lease_guard(db, tenant_id, source_id, token)
            if state is None:
                raise SalesContractError("SALES_SYNC_LEASE_LOST")
            state.last_success_at, state.error_code, state.backfill_next = now, None, next_cursor
            state.lease_token, state.lease_until = None, None
        return {"days": len(days), "received": received}
    except Exception as error:
        code = str(error) if isinstance(error, SalesContractError) else "SALES_SYNC_FAILED"
        with session_factory.begin() as db:
            # An expired worker can never overwrite the new owner's state or release its lease.
            state = db.scalar(select(SalesSyncState).where(
                SalesSyncState.tenant_id == tenant_id, SalesSyncState.source_id == source_id,
                or_(SalesSyncState.lease_token == token, SalesSyncState.lease_token.is_(None)),
            ).with_for_update())
            if state is not None:
                state.last_attempt_at, state.error_code = now, code
                state.lease_token, state.lease_until = None, None
        raise SalesContractError(code) from None
