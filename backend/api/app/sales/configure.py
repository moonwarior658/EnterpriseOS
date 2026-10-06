"""Explicit admin setup after migration. Never infer mappings or iiko timezone.

python -m app.sales.configure --actor-user-id ID --timezone ZONE --history-from YYYY-MM-DD
"""
import argparse
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.automation.schedule_time import calculate_next_run_at
from app.automation.audit import add_schedule_audit_event, schedule_audit_snapshot
from app.core.authorization import resolve_action_context
from app.integrations.iiko.config import get_iiko_settings
from app.models.automation import AutomationSchedule, AutomationScope, ScheduleAuditEventType
from app.models.employee import EmployeeRole
from app.models.sales import SalesSyncState
from app.sales.sync import ACTION, source_identity


def configure_source(db, *, actor, source_timezone: str, history_from: date) -> SalesSyncState:
    resolve_action_context(db, actor, required_roles=frozenset({EmployeeRole.ADMIN}),
                           role_precedence=(EmployeeRole.ADMIN,), write=True)
    ZoneInfo(source_timezone)
    now = datetime.now(timezone.utc)
    if history_from > now.astimezone(ZoneInfo(source_timezone)).date():
        raise ValueError("SALES_HISTORY_INVALID")
    settings = get_iiko_settings()
    settings.validate_enabled()
    source_id = source_identity(settings)
    state = db.get(SalesSyncState, (actor.tenant_id, source_id))
    if state is not None:
        if state.source_timezone != source_timezone or state.history_from != history_from:
            raise ValueError("SALES_SOURCE_ALREADY_CONFIGURED")
        configure_reports(db, actor=actor, source_timezone=source_timezone)
        return state
    state = SalesSyncState(tenant_id=actor.tenant_id, source_id=source_id,
                          source_timezone=source_timezone, history_from=history_from,
                          backfill_next=history_from)
    db.add(state)
    schedule = AutomationSchedule(
        name="Обновление данных продаж", automation_type=ACTION, contract_version="1.0",
        tenant_id=actor.tenant_id, scope_type=AutomationScope.COMPANY,
        schedule_config={"type": "interval", "minutes": 15},
        payload={"source_id": source_id}, recipients=[], timezone=source_timezone,
        is_enabled=True, next_run_at=now, created_by_user_id=actor.id,
    )
    db.add(schedule)
    db.flush()
    add_schedule_audit_event(db, event_type=ScheduleAuditEventType.CREATED,
                            actor_user_id=actor.id, schedule_id=schedule.id,
                            metadata={"fields": schedule_audit_snapshot(schedule)})
    db.flush()
    configure_reports(db, actor=actor, source_timezone=source_timezone)
    return state


def configure_reports(db, *, actor, source_timezone):
    from app.sales.reports import ACTION as reports_action
    if db.scalar(select(AutomationSchedule.id).where(AutomationSchedule.tenant_id == actor.tenant_id, AutomationSchedule.automation_type == reports_action)) is not None:
        return
    config = {"type": "daily", "time": "08:00"}
    schedule = AutomationSchedule(name="Отчёты продаж", automation_type=reports_action, contract_version="1.0", tenant_id=actor.tenant_id, scope_type=AutomationScope.COMPANY, schedule_config=config, payload={}, recipients=[], timezone=source_timezone, is_enabled=True, next_run_at=calculate_next_run_at(config, source_timezone), created_by_user_id=actor.id)
    db.add(schedule); db.flush()
    add_schedule_audit_event(db, event_type=ScheduleAuditEventType.CREATED, actor_user_id=actor.id, schedule_id=schedule.id, metadata={"fields": schedule_audit_snapshot(schedule)})


def main():
    from app.db.session import SessionLocal
    from app.models.user import User
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-user-id", type=int, required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--history-from", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        actor = db.get(User, args.actor_user_id)
        if actor is None:
            raise ValueError("SALES_ADMIN_NOT_FOUND")
        configure_source(db, actor=actor, source_timezone=args.timezone, history_from=args.history_from)
    print("Sales source configured; existing scheduler will sync every 15 minutes.")


if __name__ == "__main__":
    main()
