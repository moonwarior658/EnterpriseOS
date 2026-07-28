from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.automation.schedule_time import parse_local_time, resolve_local_time
from app.models.supply import (
    SupplyRequestCycle,
    SupplyRequestDirection,
)
from app.schemas.automation import (
    SUPPLY_CLOSE_EXPIRED_REQUEST_CYCLES,
    SUPPLY_ENSURE_REQUEST_CYCLE,
    SupplyCloseExpiredRequestCyclesPayload,
    SupplyEnsureRequestCyclePayload,
)
from app.supply.service import _advance_debts_for_closed_cycle


class SupplyAutomationActionError(ValueError):
    pass


class SupplyDirectionNotFoundError(SupplyAutomationActionError):
    pass


class SupplyDirectionInactiveError(SupplyAutomationActionError):
    pass


class SupplyTimezoneInvalidError(SupplyAutomationActionError):
    pass


class SupplyCyclePeriodInvalidError(SupplyAutomationActionError):
    pass


class SupplyActionPayloadInvalidError(SupplyAutomationActionError):
    pass


@dataclass(frozen=True, slots=True)
class SupplyAutomationContext:
    execution_id: UUID
    tenant_id: str
    requested_at: datetime
    executed_at: datetime


SupplyActionHandler = Callable[
    [Session, SupplyAutomationContext, dict[str, Any]],
    dict[str, Any],
]


def _raise_payload_validation(error: ValidationError) -> None:
    locations = {
        str(part)
        for item in error.errors()
        for part in item.get("loc", ())
    }
    if "timezone" in locations:
        raise SupplyTimezoneInvalidError from error
    if locations & {
        "opens_time",
        "closes_time",
        "hard_closes_time",
        "cycle_date_offset_days",
    } or any(
        "later than" in str(item.get("msg", ""))
        for item in error.errors()
    ):
        raise SupplyCyclePeriodInvalidError from error
    raise SupplyActionPayloadInvalidError from error


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(timezone.utc)


def _zoneinfo(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (TypeError, ZoneInfoNotFoundError) as error:
        raise SupplyTimezoneInvalidError from error


def require_active_supply_direction(
    session: Session,
    *,
    tenant_id: str,
    direction_code: str,
) -> SupplyRequestDirection:
    direction = session.scalar(
        select(SupplyRequestDirection).where(
            SupplyRequestDirection.tenant_id == tenant_id,
            SupplyRequestDirection.code == direction_code,
        )
    )
    if direction is None:
        raise SupplyDirectionNotFoundError
    if not direction.is_active:
        raise SupplyDirectionInactiveError
    return direction


def _cycle_instant(
    cycle_date: date,
    local_time: str,
    cycle_timezone: ZoneInfo,
) -> datetime:
    candidates = resolve_local_time(
        cycle_date,
        parse_local_time(local_time),
        cycle_timezone,
    )
    if not candidates:
        raise SupplyCyclePeriodInvalidError
    return candidates[0]


def _cycle_result(
    *,
    outcome: str,
    cycle: SupplyRequestCycle,
    direction_code: str,
) -> dict[str, Any]:
    return {
        "outcome": outcome,
        "cycle_id": str(cycle.id),
        "direction_code": direction_code,
        "cycle_date": cycle.cycle_date.isoformat(),
        "opens_at": cycle.opens_at.isoformat(),
        "closes_at": cycle.closes_at.isoformat(),
        "hard_closes_at": (
            cycle.hard_closes_at.isoformat()
            if cycle.hard_closes_at is not None
            else None
        ),
    }


def _find_cycle(
    session: Session,
    *,
    tenant_id: str,
    direction_id: UUID,
    cycle_date: date,
) -> SupplyRequestCycle | None:
    return session.scalar(
        select(SupplyRequestCycle).where(
            SupplyRequestCycle.tenant_id == tenant_id,
            SupplyRequestCycle.direction_id == direction_id,
            SupplyRequestCycle.cycle_date == cycle_date,
        )
    )


def ensure_request_cycle(
    session: Session,
    context: SupplyAutomationContext,
    raw_payload: dict[str, Any],
    *,
    before_insert: Callable[[], None] | None = None,
) -> dict[str, Any]:
    try:
        payload = SupplyEnsureRequestCyclePayload.model_validate(raw_payload)
    except ValidationError as error:
        _raise_payload_validation(error)

    cycle_timezone = _zoneinfo(payload.timezone)
    requested_at = _aware_utc(
        context.requested_at,
        field_name="requested_at",
    )
    cycle_date = (
        requested_at.astimezone(cycle_timezone).date()
        + timedelta(days=payload.cycle_date_offset_days)
    )
    opens_at = _cycle_instant(
        cycle_date,
        payload.opens_time,
        cycle_timezone,
    )
    closes_at = _cycle_instant(
        cycle_date,
        payload.closes_time,
        cycle_timezone,
    )
    hard_close_date = cycle_date + timedelta(
        days=1 if payload.hard_close_next_day else 0
    )
    hard_closes_at = _cycle_instant(
        hard_close_date,
        payload.hard_closes_time,
        cycle_timezone,
    )
    if closes_at <= opens_at or hard_closes_at <= closes_at:
        raise SupplyCyclePeriodInvalidError

    direction = require_active_supply_direction(
        session,
        tenant_id=context.tenant_id,
        direction_code=payload.direction_code,
    )
    existing = _find_cycle(
        session,
        tenant_id=context.tenant_id,
        direction_id=direction.id,
        cycle_date=cycle_date,
    )
    if existing is not None:
        return _cycle_result(
            outcome="already_exists",
            cycle=existing,
            direction_code=direction.code,
        )

    if before_insert is not None:
        before_insert()

    cycle = SupplyRequestCycle(
        tenant_id=context.tenant_id,
        direction_id=direction.id,
        cycle_date=cycle_date,
        opens_at=opens_at,
        closes_at=closes_at,
        hard_closes_at=hard_closes_at,
        status=payload.initial_status,
    )
    try:
        with session.begin_nested():
            session.add(cycle)
            session.flush()
    except IntegrityError:
        existing = _find_cycle(
            session,
            tenant_id=context.tenant_id,
            direction_id=direction.id,
            cycle_date=cycle_date,
        )
        if existing is None:
            raise
        return _cycle_result(
            outcome="already_exists",
            cycle=existing,
            direction_code=direction.code,
        )

    return _cycle_result(
        outcome="created",
        cycle=cycle,
        direction_code=direction.code,
    )


def close_expired_request_cycles(
    session: Session,
    context: SupplyAutomationContext,
    raw_payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        payload = SupplyCloseExpiredRequestCyclesPayload.model_validate(
            raw_payload
        )
    except ValidationError as error:
        _raise_payload_validation(error)

    cycle_timezone = _zoneinfo(payload.timezone)
    executed_at = _aware_utc(
        context.executed_at,
        field_name="executed_at",
    )
    cycles = list(
        session.scalars(
            select(SupplyRequestCycle)
            .where(
                SupplyRequestCycle.tenant_id == context.tenant_id,
                SupplyRequestCycle.status.in_(("SCHEDULED", "OPEN")),
                func.coalesce(
                    SupplyRequestCycle.hard_closes_at,
                    SupplyRequestCycle.closes_at,
                )
                <= executed_at,
            )
            .order_by(
                SupplyRequestCycle.cycle_date.asc(),
                SupplyRequestCycle.id.asc(),
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    closed_ids: list[str] = []
    for cycle in cycles:
        cycle.status = "CLOSED"
        _advance_debts_for_closed_cycle(session, cycle)
        closed_ids.append(str(cycle.id))

    session.flush()
    return {
        "closed_count": len(closed_ids),
        "closed_cycle_ids": closed_ids,
        "executed_at": executed_at.astimezone(cycle_timezone).isoformat(),
    }


SUPPLY_ACTION_HANDLERS: dict[str, SupplyActionHandler] = {
    SUPPLY_ENSURE_REQUEST_CYCLE: ensure_request_cycle,
    SUPPLY_CLOSE_EXPIRED_REQUEST_CYCLES: close_expired_request_cycles,
}
