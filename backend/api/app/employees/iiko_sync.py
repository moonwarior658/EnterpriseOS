"""Centralized iiko personal-shift cache refresh for the EOS worker."""
import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.employees.iiko import sync_shifts
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.models.employee import IikoEmployeeLink


logger = logging.getLogger("eos.automation.iiko_shifts")


async def sync_iiko_shifts_once() -> None:
    with SessionLocal() as db:
        tenants = list(db.scalars(select(IikoEmployeeLink.tenant_id).where(
            IikoEmployeeLink.valid_to.is_(None),
        ).distinct()).all())
    if not tenants:
        return
    today = date.today()
    async with IikoServerClient(get_iiko_settings()) as provider:
        shifts = await provider.get_personal_shifts(
            date_from=today - timedelta(days=1), date_to=today,
        )
    for tenant_id in tenants:
        with SessionLocal() as db:
            result = sync_shifts(db, shifts, tenant_id=tenant_id)
            logger.info(
                "iiko shift sync tenant=%s received=%s matched=%s created=%s updated=%s unchanged=%s unresolved_department=%s",
                tenant_id, result.received, result.matched, result.created,
                result.updated, result.unchanged, result.unresolved_department,
            )


async def run_iiko_shift_sync_loop(stop_event: asyncio.Event, interval_seconds: float) -> None:
    logger.info("iiko shift sync starting interval_seconds=%s", interval_seconds)
    while not stop_event.is_set():
        try:
            await sync_iiko_shifts_once()
        except Exception:
            logger.exception("iiko shift sync pass failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
    logger.info("iiko shift sync stopped")
