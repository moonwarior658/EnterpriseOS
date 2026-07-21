import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.dependencies import get_current_admin
from app.automation.outbox import (
    ClaimedOutboxEvent,
    DeliveryStatus,
    OutboxWorker,
)
from app.automation.providers.base import (
    AutomationProvider,
    CommandAcceptance,
)
from app.automation.scheduler import run_scheduler_once
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.automation import ExecutionStatus, OutboxStatus
from app.models.user import User
from app.schemas.automation import AutomationCommand
from tests.test_automation_scheduler import NOW, Store, make_schedule


class FlowProvider(AutomationProvider):
    def __init__(self) -> None:
        self.commands: list[AutomationCommand] = []

    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        self.commands.append(command)
        return CommandAcceptance(
            provider="flow-provider",
            accepted=True,
            status_code=202,
        )

    async def check_availability(self) -> bool:
        return True


class FlowOutboxStore:
    def __init__(self, event, execution) -> None:
        self.event = event
        self.execution = execution
        self.claimed = False

    def claim_next(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
    ) -> ClaimedOutboxEvent | None:
        if self.claimed:
            return None
        self.claimed = True
        self.event.status = OutboxStatus.PROCESSING
        self.event.attempt_count = 1
        return ClaimedOutboxEvent(
            id=self.event.id,
            event_id=self.event.event_id,
            execution_id=self.execution.execution_id,
            contract_version=self.execution.contract_version,
            automation_type=self.execution.automation_type,
            tenant_id=self.execution.tenant_id,
            requested_at=self.execution.requested_at,
            payload=dict(self.event.payload),
            attempt_count=1,
            max_attempts=10,
            lock_token=f"{worker_id}:claim",
        )

    def mark_published(
        self,
        claim: ClaimedOutboxEvent,
        *,
        acceptance: CommandAcceptance,
        published_at: datetime,
    ) -> None:
        self.event.status = OutboxStatus.PUBLISHED
        self.event.published_at = published_at
        self.execution.provider = acceptance.provider
        self.execution.status = ExecutionStatus.RUNNING

    def mark_failed(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("Flow provider must not fail")


class CallbackSession:
    def __init__(self, execution) -> None:
        self.execution = execution
        self.commit_count = 0

    def scalar(self, statement: object):
        return self.execution

    def commit(self) -> None:
        self.commit_count += 1


def make_admin() -> User:
    return User(
        id=7,
        username="admin",
        display_name="Administrator",
        hashed_password="unused",
        is_active=True,
        is_admin=True,
        created_at=NOW,
    )


class AutomationSchedulerFlowTests(unittest.TestCase):
    def test_schedule_to_callback_and_history(self) -> None:
        schedule = make_schedule(
            42,
            schedule_config={"type": "interval", "minutes": 30},
            next_run_at=NOW - timedelta(hours=2),
        )
        scheduler_store = Store([schedule])

        first = run_scheduler_once(scheduler_store, now=NOW)
        second = run_scheduler_once(scheduler_store, now=NOW)

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        self.assertEqual(len(scheduler_store.executions), 1)
        self.assertEqual(len(scheduler_store.events), 1)
        self.assertGreater(schedule.next_run_at, NOW)

        execution = scheduler_store.executions[0]
        event = scheduler_store.events[0]
        execution.id = 100
        execution.attempt_count = 0
        execution.max_attempts = 3
        execution.created_at = NOW
        execution.updated_at = NOW
        event.id = 200
        event.event_id = event.event_id or uuid4()
        event.attempt_count = 0
        event.max_attempts = 10
        provider = FlowProvider()
        worker = OutboxWorker(
            store=FlowOutboxStore(event, execution),
            provider=provider,
            worker_id="flow-worker",
            callback_url="http://testserver/automation/callback",
            clock=lambda: NOW + timedelta(seconds=1),
        )

        delivery = asyncio.run(worker.process_one())

        self.assertEqual(delivery.status, DeliveryStatus.PUBLISHED)
        self.assertEqual(len(provider.commands), 1)
        self.assertEqual(provider.commands[0].payload, schedule.payload)
        self.assertEqual(execution.status, ExecutionStatus.RUNNING)

        callback_session = CallbackSession(execution)
        previous_token = settings.automation_callback_token
        settings.automation_callback_token = SecretStr("flow-token")
        app.dependency_overrides[get_db] = lambda: callback_session
        client = TestClient(app)

        try:
            callback = client.post(
                "/automation/callback",
                headers={"Authorization": "Bearer flow-token"},
                json={
                    "contract_version": "1.0",
                    "execution_id": str(execution.execution_id),
                    "status": "succeeded",
                    "started_at": (NOW + timedelta(seconds=1)).isoformat(),
                    "finished_at": (NOW + timedelta(minutes=1)).isoformat(),
                    "result": {"document_id": 123},
                    "error_code": None,
                    "error_message": None,
                },
            )
            self.assertEqual(callback.status_code, 200)
            self.assertEqual(execution.status, ExecutionStatus.SUCCEEDED)

            app.dependency_overrides[get_current_admin] = make_admin
            with (
                patch(
                    "app.api.routes.automation.get_execution",
                    return_value=execution,
                ),
                patch(
                    "app.api.routes.automation.get_schedule",
                    return_value=schedule,
                ),
                patch(
                    "app.api.routes.automation.get_latest_schedule_execution",
                    return_value=execution,
                ),
            ):
                history = client.get(
                    f"/automation/executions/{execution.execution_id}"
                )
                latest = client.get(
                    "/automation/schedules/42/executions/latest"
                )

            self.assertEqual(history.status_code, 200)
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(
                history.json()["execution_id"],
                str(execution.execution_id),
            )
            self.assertEqual(
                latest.json()["scope_id"],
                "department-7",
            )
        finally:
            settings.automation_callback_token = previous_token
            app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
