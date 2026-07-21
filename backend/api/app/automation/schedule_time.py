from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import TypeAdapter, ValidationError

from app.schemas.automation import (
    DailyScheduleConfig,
    IntervalScheduleConfig,
    ScheduleConfig,
    WeeklyScheduleConfig,
)


UTC = timezone.utc
SCHEDULE_CONFIG_ADAPTER = TypeAdapter(ScheduleConfig)


class InvalidScheduleConfigError(ValueError):
    pass


class InvalidScheduleTimezoneError(ValueError):
    pass


def require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")

    return value


def parse_schedule_config(
    schedule_config: ScheduleConfig | dict[str, object],
) -> DailyScheduleConfig | WeeklyScheduleConfig | IntervalScheduleConfig:
    try:
        return SCHEDULE_CONFIG_ADAPTER.validate_python(schedule_config)
    except ValidationError as error:
        raise InvalidScheduleConfigError(
            "Invalid schedule configuration"
        ) from error


def parse_local_time(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)


def valid_utc_instants(
    local_value: datetime,
    schedule_timezone: ZoneInfo,
) -> list[datetime]:
    instants: set[datetime] = set()

    for fold in (0, 1):
        candidate = local_value.replace(
            tzinfo=schedule_timezone,
            fold=fold,
        )
        candidate_utc = candidate.astimezone(UTC)
        round_trip = candidate_utc.astimezone(schedule_timezone)

        if round_trip.replace(tzinfo=None) == local_value:
            instants.add(candidate_utc)

    return sorted(instants)


def resolve_local_time(
    local_date: date,
    scheduled_time: time,
    schedule_timezone: ZoneInfo,
) -> list[datetime]:
    local_value = datetime.combine(local_date, scheduled_time)

    # A wall time in a DST gap does not map to a real instant. Move it to
    # the first existing local minute after the gap, with a one-day bound.
    for _ in range(24 * 60 + 1):
        instants = valid_utc_instants(local_value, schedule_timezone)
        if instants:
            return instants
        local_value += timedelta(minutes=1)

    raise InvalidScheduleTimezoneError(
        "Could not resolve local schedule time"
    )


def calculate_daily_next_run(
    config: DailyScheduleConfig,
    schedule_timezone: ZoneInfo,
    now_utc: datetime,
) -> datetime:
    local_date = now_utc.astimezone(schedule_timezone).date()
    scheduled_time = parse_local_time(config.time)

    for day_offset in (0, 1):
        candidates = resolve_local_time(
            local_date + timedelta(days=day_offset),
            scheduled_time,
            schedule_timezone,
        )
        future_candidates = [value for value in candidates if value > now_utc]
        if future_candidates:
            return future_candidates[0]

    raise InvalidScheduleConfigError("Could not calculate daily schedule")


def calculate_weekly_next_run(
    config: WeeklyScheduleConfig,
    schedule_timezone: ZoneInfo,
    now_utc: datetime,
) -> datetime:
    local_date = now_utc.astimezone(schedule_timezone).date()
    scheduled_time = parse_local_time(config.time)

    for day_offset in range(8):
        candidate_date = local_date + timedelta(days=day_offset)
        if candidate_date.weekday() not in config.weekdays:
            continue

        candidates = resolve_local_time(
            candidate_date,
            scheduled_time,
            schedule_timezone,
        )
        future_candidates = [value for value in candidates if value > now_utc]
        if future_candidates:
            return future_candidates[0]

    raise InvalidScheduleConfigError("Could not calculate weekly schedule")


def calculate_interval_next_run(
    config: IntervalScheduleConfig,
    now_utc: datetime,
    previous_run_at: datetime | None,
) -> datetime:
    interval = timedelta(minutes=config.minutes)

    if previous_run_at is None:
        return now_utc + interval

    previous_utc = require_aware(
        previous_run_at,
        "previous_run_at",
    ).astimezone(UTC)
    candidate = previous_utc + interval

    if candidate <= now_utc:
        elapsed = now_utc - previous_utc
        intervals_to_skip = elapsed // interval + 1
        candidate = previous_utc + intervals_to_skip * interval

    return candidate


def calculate_next_run_at(
    schedule_config: ScheduleConfig | dict[str, object],
    timezone_name: str,
    *,
    now: datetime | None = None,
    previous_run_at: datetime | None = None,
) -> datetime:
    config = parse_schedule_config(schedule_config)

    try:
        schedule_timezone = ZoneInfo(timezone_name)
    except (TypeError, ZoneInfoNotFoundError) as error:
        raise InvalidScheduleTimezoneError(
            f"Unknown schedule timezone: {timezone_name}"
        ) from error

    if now is None:
        now_utc = datetime.now(UTC)
    else:
        now_utc = require_aware(now, "now").astimezone(UTC)

    if isinstance(config, DailyScheduleConfig):
        return calculate_daily_next_run(
            config,
            schedule_timezone,
            now_utc,
        )

    if isinstance(config, WeeklyScheduleConfig):
        return calculate_weekly_next_run(
            config,
            schedule_timezone,
            now_utc,
        )

    return calculate_interval_next_run(
        config,
        now_utc,
        previous_run_at,
    )
