from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.automation import AutomationSchedule


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
