import logging
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.automation.dispatch import create_automation_execution
from app.automation.schedule_time import calculate_next_run_at
from app.models.automation import AutomationExecution, AutomationSchedule


logger = logging.getLogger("eos.automation.scheduler")
DEFAULT_SCHEDULER_BATCH_SIZE = 100
MAX_SCHEDULER_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class SchedulerRunResult:
    scanned: int = 0
    claimed: int = 0
    created: int = 0
    failed: int = 0
    skipped: int = 0


def aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")

    return value.astimezone(timezone.utc)


def due_schedule_statement(
    now: datetime,
    *,
    excluded_ids: Collection[int] = (),
) -> Select[tuple[AutomationSchedule]]:
    now = aware_utc(now, field_name="now")
    statement = (
        select(AutomationSchedule)
        .where(
            AutomationSchedule.is_enabled.is_(True),
            AutomationSchedule.next_run_at.is_not(None),
            AutomationSchedule.next_run_at <= now,
        )
        .order_by(
            AutomationSchedule.next_run_at.asc(),
            AutomationSchedule.id.asc(),
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )

    if excluded_ids:
        statement = statement.where(
            AutomationSchedule.id.not_in(tuple(excluded_ids))
        )

    return statement


def claim_due_schedule(
    session: Session,
    *,
    now: datetime,
    excluded_ids: Collection[int] = (),
) -> AutomationSchedule | None:
    return session.execute(
        due_schedule_statement(now, excluded_ids=excluded_ids)
    ).scalar_one_or_none()


def process_due_schedule(
    session: Session,
    schedule: AutomationSchedule,
    *,
    now: datetime,
) -> AutomationExecution | None:
    now = aware_utc(now, field_name="now")
    scheduled_for = schedule.next_run_at

    if (
        not schedule.is_enabled
        or scheduled_for is None
        or aware_utc(scheduled_for, field_name="next_run_at") > now
    ):
        return None

    schedule_type = schedule.schedule_config.get("type")
    previous_run_at = scheduled_for if schedule_type == "interval" else None
    next_run_at = calculate_next_run_at(
        schedule.schedule_config,
        schedule.timezone,
        now=now,
        previous_run_at=previous_run_at,
    )
    scope_type = getattr(schedule.scope_type, "value", schedule.scope_type)
    execution = create_automation_execution(
        session,
        automation_type=schedule.automation_type,
        tenant_id=schedule.tenant_id,
        scope_type=scope_type,
        scope_id=schedule.scope_id,
        recipients=schedule.recipients,
        payload=schedule.payload,
        contract_version=schedule.contract_version,
        schedule_id=schedule.id,
        requested_at=now,
    )
    schedule.next_run_at = next_run_at
    return execution


def run_scheduler_once(
    session_factory: Callable[[], Session],
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_SCHEDULER_BATCH_SIZE,
) -> SchedulerRunResult:
    if not 1 <= batch_size <= MAX_SCHEDULER_BATCH_SIZE:
        raise ValueError(
            f"batch_size must be between 1 and {MAX_SCHEDULER_BATCH_SIZE}"
        )

    scheduler_now = aware_utc(
        now or datetime.now(timezone.utc),
        field_name="now",
    )
    excluded_ids: set[int] = set()
    scanned = claimed = created = failed = skipped = 0

    for _ in range(batch_size):
        schedule_id: int | None = None
        execution_id: str | None = None
        session = session_factory()

        try:
            schedule = claim_due_schedule(
                session,
                now=scheduler_now,
                excluded_ids=excluded_ids,
            )
            if schedule is None:
                session.rollback()
                break

            schedule_id = schedule.id
            scanned += 1
            claimed += 1
            execution = process_due_schedule(
                session,
                schedule,
                now=scheduler_now,
            )
            if execution is None:
                excluded_ids.add(schedule.id)
                skipped += 1
                session.rollback()
            else:
                execution_id = str(execution.execution_id)
                session.flush()
                session.commit()
                created += 1
        except Exception as error:
            session.rollback()
            failed += 1
            if schedule_id is not None:
                excluded_ids.add(schedule_id)
            logger.error(
                "Schedule processing failed schedule_id=%s "
                "execution_id=%s error_type=%s error=%s",
                schedule_id,
                execution_id,
                type(error).__name__,
                "schedule transaction failed",
            )
        finally:
            session.close()

    return SchedulerRunResult(
        scanned=scanned,
        claimed=claimed,
        created=created,
        failed=failed,
        skipped=skipped,
    )
