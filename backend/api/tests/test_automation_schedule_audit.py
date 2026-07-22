import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.dependencies import get_current_admin
from app.automation.audit import (
    list_schedule_audit_events,
    schedule_audit_changes,
    schedule_audit_snapshot,
)
from app.automation.schedules import create_schedule, update_schedule
from app.db.session import get_db
from app.main import app
from app.models.automation import (
    AutomationScheduleAuditEvent,
    ScheduleAuditEventType,
)
from app.models.user import User
from app.schemas.automation import (
    AutomationScheduleCreate,
    AutomationScheduleUpdate,
)
from tests.test_automation_schedules_api import make_schedule
from tests.test_automation_schedules_service import (
    FakeSession,
    make_update_schedule,
)


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


def create_payload() -> AutomationScheduleCreate:
    return AutomationScheduleCreate(
        name="Daily report",
        automation_type="daily_report",
        scope_type="company",
        scope_id=None,
        schedule_config={"type": "daily", "time": "08:30"},
        payload={"secret": "must-not-be-audited"},
        recipients=[{"email": "private@example.test"}],
        timezone="UTC",
        is_enabled=False,
    )


class AssignedIdSession(FakeSession):
    def flush(self) -> None:
        super().flush()
        if self.added and getattr(self.added[0], "id", None) is None:
            self.added[0].id = 42


class FailAuditFlushSession(AssignedIdSession):
    def flush(self) -> None:
        if self.flush_count == 1:
            self.operations.append("flush")
            self.flush_count += 1
            raise RuntimeError("audit insert failed")
        super().flush()


class AuditWriteTests(unittest.TestCase):
    def test_create_adds_safe_event_with_actor(self) -> None:
        session = AssignedIdSession()
        create_schedule(session, create_payload(), created_by_user_id=7)

        event = session.added[1]
        self.assertIsInstance(event, AutomationScheduleAuditEvent)
        self.assertEqual(event.event_type, ScheduleAuditEventType.CREATED)
        self.assertEqual(event.actor_user_id, 7)
        self.assertEqual(event.schedule_id, 42)
        serialized = str(event.metadata_)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("private@example.test", serialized)

    def test_update_contains_only_real_safe_changes(self) -> None:
        session = FakeSession()
        schedule = make_update_schedule()
        original_payload = schedule.payload
        update_schedule(
            session,
            schedule,
            AutomationScheduleUpdate(
                name="Changed",
                payload={"raw": "hidden"},
                recipients=[{"email": "hidden@example.test"}],
            ),
            actor_user_id=9,
        )

        event = session.added[0]
        self.assertEqual(event.event_type, ScheduleAuditEventType.UPDATED)
        self.assertEqual(event.actor_user_id, 9)
        self.assertEqual(set(event.metadata_["changes"]), {"name"})
        self.assertIsNot(schedule.payload, original_payload)
        self.assertNotIn("hidden", str(event.metadata_))

    def test_enable_and_disable_use_specific_events(self) -> None:
        schedule = make_update_schedule()
        enable_session = FakeSession()
        update_schedule(
            enable_session,
            schedule,
            AutomationScheduleUpdate(is_enabled=True),
            actor_user_id=7,
        )
        self.assertEqual(
            enable_session.added[0].event_type,
            ScheduleAuditEventType.ENABLED,
        )

        disable_session = FakeSession()
        update_schedule(
            disable_session,
            schedule,
            AutomationScheduleUpdate(is_enabled=False),
            actor_user_id=7,
        )
        self.assertEqual(
            disable_session.added[0].event_type,
            ScheduleAuditEventType.DISABLED,
        )

    def test_audit_failure_rolls_back_main_create(self) -> None:
        session = FailAuditFlushSession()
        with self.assertRaisesRegex(RuntimeError, "audit insert failed"):
            create_schedule(session, create_payload(), created_by_user_id=7)

        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 1)

    def test_audit_failure_rolls_back_main_update(self) -> None:
        session = FailAuditFlushSession()
        with self.assertRaisesRegex(RuntimeError, "audit insert failed"):
            update_schedule(
                session,
                make_update_schedule(),
                AutomationScheduleUpdate(name="Changed"),
                actor_user_id=7,
            )

        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 1)

    def test_diff_helper_ignores_payload_and_recipients(self) -> None:
        schedule = make_update_schedule()
        before = schedule_audit_snapshot(schedule)
        schedule.payload = {"jwt": "secret"}
        schedule.recipients = [{"email": "private@example.test"}]
        after = schedule_audit_snapshot(schedule)
        self.assertEqual(schedule_audit_changes(before, after), {})


class QuerySession:
    def __init__(self) -> None:
        self.statement = None

    class Result:
        def all(self):
            return []

    def execute(self, statement):
        self.statement = statement
        return self.Result()


class AuditReadTests(unittest.TestCase):
    def test_query_is_newest_first_and_paginated(self) -> None:
        session = QuerySession()
        list_schedule_audit_events(session, 42, limit=10, offset=20)
        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("occurred_at DESC", compiled)
        self.assertIn("automation_schedule_audit_events.id DESC", compiled)
        self.assertIn("LIMIT 10 OFFSET 20", compiled)


class AuditApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.session = object()
        self.admin = User(
            id=7,
            username="admin",
            display_name="Administrator",
            hashed_password="unused",
            is_active=True,
            is_admin=True,
        )
        app.dependency_overrides[get_db] = lambda: self.session
        app.dependency_overrides[get_current_admin] = lambda: self.admin
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None

    def test_unknown_schedule_returns_404(self) -> None:
        with patch(
            "app.api.routes.automation.get_schedule", return_value=None
        ):
            response = self.client.get("/automation/schedules/404/audit")
        self.assertEqual(response.status_code, 404)

    def test_safe_response_and_pagination(self) -> None:
        event = AutomationScheduleAuditEvent(
            id=5,
            event_type=ScheduleAuditEventType.UPDATED,
            actor_user_id=7,
            schedule_id=42,
            occurred_at=NOW,
            metadata_={
                "changes": {"name": {"old": "A", "new": "B"}},
                "payload": {"password": "secret"},
            },
        )
        with (
            patch(
                "app.api.routes.automation.get_schedule",
                return_value=make_schedule(),
            ),
            patch(
                "app.api.routes.automation.list_schedule_audit_events",
                return_value=[(event, "Administrator")],
            ) as listing,
            patch(
                "app.api.routes.automation.count_schedule_audit_events",
                return_value=21,
            ),
        ):
            response = self.client.get(
                "/automation/schedules/42/audit?limit=10&offset=10"
            )

        self.assertEqual(response.status_code, 200)
        listing.assert_called_once_with(
            self.session, 42, limit=10, offset=10
        )
        body = response.json()
        self.assertEqual(body["total"], 21)
        self.assertEqual(body["items"][0]["actor_user_id"], 7)
        serialized = response.text.lower()
        for forbidden in (
            "payload",
            "recipients",
            "execution_id",
            "webhook",
            "callback",
            "password",
        ):
            self.assertNotIn(forbidden, serialized)


if __name__ == "__main__":
    unittest.main()
