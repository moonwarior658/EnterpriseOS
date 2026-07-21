from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.automation import AutomationSchedule
from app.schemas.automation import (
    AutomationScheduleCreate,
    AutomationScheduleUpdate,
)


SCHEDULE_MUTABLE_FIELDS = (
    "name",
    "automation_type",
    "scope_type",
    "scope_id",
    "schedule_config",
    "payload",
    "recipients",
    "timezone",
    "is_enabled",
)


class InvalidScheduleScopeError(ValueError):
    pass


def validate_schedule_scope(
    scope_type: object,
    scope_id: str | None,
) -> None:
    scope_type_value = getattr(scope_type, "value", scope_type)

    if scope_type_value == "company":
        if scope_id is not None:
            raise InvalidScheduleScopeError(
                "Invalid schedule scope: company requires scope_id to be null"
            )
        return

    if scope_type_value not in {"department", "location", "user"}:
        raise InvalidScheduleScopeError(
            f"Invalid schedule scope type: {scope_type_value}"
        )

    if scope_id is None or not scope_id.strip():
        raise InvalidScheduleScopeError(
            "Invalid schedule scope: "
            f"{scope_type_value} requires a non-empty scope_id"
        )


def list_schedules(session: Session) -> list[AutomationSchedule]:
    statement = select(AutomationSchedule).order_by(
        AutomationSchedule.id.asc()
    )
    return session.scalars(statement).all()


def get_schedule(
    session: Session,
    schedule_id: int,
) -> AutomationSchedule | None:
    return session.get(AutomationSchedule, schedule_id)


def create_schedule(
    session: Session,
    payload: AutomationScheduleCreate,
    *,
    created_by_user_id: int,
) -> AutomationSchedule:
    try:
        schedule = AutomationSchedule(
            name=payload.name,
            automation_type=payload.automation_type,
            tenant_id=settings.default_tenant_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            schedule_config=payload.schedule_config,
            payload=payload.payload,
            recipients=payload.recipients,
            timezone=payload.timezone,
            is_enabled=payload.is_enabled,
            created_by_user_id=created_by_user_id,
        )
        session.add(schedule)
        session.flush()
        session.refresh(schedule)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return schedule


def update_schedule(
    session: Session,
    schedule: AutomationSchedule,
    payload: AutomationScheduleUpdate,
) -> AutomationSchedule:
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        return schedule

    final_scope_type = updates.get("scope_type", schedule.scope_type)
    final_scope_id = (
        updates["scope_id"]
        if "scope_id" in updates
        else schedule.scope_id
    )
    validate_schedule_scope(final_scope_type, final_scope_id)

    try:
        for field in SCHEDULE_MUTABLE_FIELDS:
            if field in updates:
                setattr(schedule, field, updates[field])

        session.flush()
        session.refresh(schedule)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return schedule


def delete_schedule(
    session: Session,
    schedule: AutomationSchedule,
) -> None:
    try:
        session.delete(schedule)
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
