from copy import deepcopy
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.automation import (
    AutomationScheduleAuditEvent,
    ScheduleAuditEventType,
)
from app.models.user import User


SAFE_SCHEDULE_AUDIT_FIELDS = (
    "name",
    "automation_type",
    "scope_type",
    "scope_id",
    "schedule_config",
    "timezone",
    "is_enabled",
)
DEFAULT_AUDIT_LIMIT = 20


def safe_audit_value(value: Any) -> Any:
    enum_value = getattr(value, "value", value)
    if hasattr(enum_value, "model_dump"):
        return enum_value.model_dump(mode="json")
    return deepcopy(enum_value)


def schedule_audit_snapshot(schedule: object) -> dict[str, Any]:
    return {
        field: safe_audit_value(getattr(schedule, field))
        for field in SAFE_SCHEDULE_AUDIT_FIELDS
    }


def schedule_audit_changes(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        field: {"old": before[field], "new": after[field]}
        for field in SAFE_SCHEDULE_AUDIT_FIELDS
        if before[field] != after[field]
    }


def add_schedule_audit_event(
    session: Session,
    *,
    event_type: ScheduleAuditEventType,
    actor_user_id: int,
    schedule_id: int,
    metadata: dict[str, Any] | None = None,
) -> AutomationScheduleAuditEvent:
    event = AutomationScheduleAuditEvent(
        event_type=event_type,
        actor_user_id=actor_user_id,
        schedule_id=schedule_id,
        metadata_=safe_schedule_audit_metadata(event_type, metadata or {}),
    )
    session.add(event)
    return event


def safe_schedule_audit_metadata(
    event_type: ScheduleAuditEventType,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if event_type == ScheduleAuditEventType.CREATED:
        fields = metadata.get("fields")
        if not isinstance(fields, dict):
            return {}
        return {
            "fields": {
                field: deepcopy(fields[field])
                for field in SAFE_SCHEDULE_AUDIT_FIELDS
                if field in fields
            }
        }

    if event_type in {
        ScheduleAuditEventType.UPDATED,
        ScheduleAuditEventType.ENABLED,
        ScheduleAuditEventType.DISABLED,
    }:
        changes = metadata.get("changes")
        if not isinstance(changes, dict):
            return {}
        allowed_fields = (
            ("is_enabled",)
            if event_type
            in {
                ScheduleAuditEventType.ENABLED,
                ScheduleAuditEventType.DISABLED,
            }
            else SAFE_SCHEDULE_AUDIT_FIELDS
        )
        return {
            "changes": {
                field: deepcopy(changes[field])
                for field in allowed_fields
                if field in changes
            }
        }

    return {}


def list_schedule_audit_events(
    session: Session,
    schedule_id: int,
    *,
    limit: int = DEFAULT_AUDIT_LIMIT,
    offset: int = 0,
) -> list[tuple[AutomationScheduleAuditEvent, str | None]]:
    statement = (
        select(AutomationScheduleAuditEvent, User.display_name)
        .join(User, User.id == AutomationScheduleAuditEvent.actor_user_id)
        .where(AutomationScheduleAuditEvent.schedule_id == schedule_id)
        .order_by(
            AutomationScheduleAuditEvent.occurred_at.desc(),
            AutomationScheduleAuditEvent.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(session.execute(statement).all())


def count_schedule_audit_events(
    session: Session,
    schedule_id: int,
) -> int:
    statement = select(func.count(AutomationScheduleAuditEvent.id)).where(
        AutomationScheduleAuditEvent.schedule_id == schedule_id
    )
    return session.scalar(statement) or 0
