from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.automation import (
    AutomationExecution,
    AutomationSchedule,
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
)


AUTOMATION_COMMAND_EVENT_TYPE = "automation.command.requested"


class AutomationScheduleNotFoundError(LookupError):
    pass


class DisabledAutomationScheduleError(ValueError):
    pass


def create_automation_execution(
    session: Session,
    *,
    automation_type: str,
    tenant_id: str,
    scope_type: str,
    scope_id: str | None,
    recipients: list[dict[str, Any]],
    payload: dict[str, Any],
    contract_version: str = "1.0",
    schedule_id: int | None = None,
    requested_at: datetime | None = None,
) -> AutomationExecution:
    execution_id = uuid4()
    command_payload = dict(payload)
    execution = AutomationExecution(
        execution_id=execution_id,
        schedule_id=schedule_id,
        contract_version=contract_version,
        automation_type=automation_type,
        tenant_id=tenant_id,
        scope_type=scope_type,
        scope_id=scope_id,
        recipients=deepcopy(recipients),
        status=ExecutionStatus.PENDING,
        requested_at=requested_at or datetime.now(timezone.utc),
        payload=command_payload,
    )
    outbox_event = OutboxEvent(
        event_id=uuid4(),
        execution_id=execution_id,
        event_type=AUTOMATION_COMMAND_EVENT_TYPE,
        contract_version=contract_version,
        payload=dict(command_payload),
        status=OutboxStatus.PENDING,
        execution=execution,
    )

    transaction = (
        session.begin_nested()
        if session.in_transaction()
        else session.begin()
    )

    with transaction:
        session.add_all([execution, outbox_event])
        session.flush()

    return execution


def dispatch_schedule_now(
    session: Session,
    schedule_id: int,
) -> AutomationExecution:
    try:
        if not session.in_transaction():
            session.begin()

        schedule = session.get(AutomationSchedule, schedule_id)

        if schedule is None:
            raise AutomationScheduleNotFoundError

        if not schedule.is_enabled:
            raise DisabledAutomationScheduleError

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
        )
        session.refresh(execution)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return execution
