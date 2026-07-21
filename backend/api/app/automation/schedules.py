from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.automation import AutomationSchedule
from app.schemas.automation import AutomationScheduleCreate


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
