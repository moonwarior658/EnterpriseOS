import inspect
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy.dialects import postgresql

from app.automation.schedules import (
    create_schedule,
    get_schedule,
    list_schedules,
)
from app.core.config import Settings, settings
from app.models.automation import AutomationSchedule
from app.schemas.automation import AutomationScheduleCreate


def make_schedule(schedule_id: int) -> AutomationSchedule:
    return AutomationSchedule(
        id=schedule_id,
        name=f"Schedule {schedule_id}",
        automation_type="test_notification",
        tenant_id="enterpriseos",
        scope_type="company",
        scope_id=None,
        schedule_config={},
        payload={},
        recipients=[],
        timezone="UTC",
        is_enabled=False,
        created_by_user_id=1,
    )


def make_create_payload() -> AutomationScheduleCreate:
    return AutomationScheduleCreate(
        name="  Daily report  ",
        automation_type="  daily_report  ",
        scope_type="department",
        scope_id="  department-1  ",
        schedule_config={"frequency": "daily"},
        payload={"report": "sales"},
        recipients=[{"user_id": 7}],
        timezone="Asia/Yekaterinburg",
        is_enabled=True,
    )


class FakeScalarResult:
    def __init__(self, schedules: list[AutomationSchedule]) -> None:
        self.schedules = schedules
        self.all_count = 0

    def all(self) -> list[AutomationSchedule]:
        self.all_count += 1
        return self.schedules


class FakeSession:
    def __init__(
        self,
        *,
        schedules: list[AutomationSchedule] | None = None,
        schedule: AutomationSchedule | None = None,
        fail_on: str | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.scalar_result = FakeScalarResult(schedules or [])
        self.schedule = schedule
        self.fail_on = fail_on
        self.failure = failure or RuntimeError(f"{fail_on} failed")
        self.statement = None
        self.get_model = None
        self.get_identity = None
        self.added: list[AutomationSchedule] = []
        self.refreshed: list[AutomationSchedule] = []
        self.operations: list[str] = []
        self.add_count = 0
        self.flush_count = 0
        self.commit_count = 0
        self.refresh_count = 0
        self.rollback_count = 0

    def scalars(self, statement) -> FakeScalarResult:
        self.statement = statement
        return self.scalar_result

    def get(self, model, identity):
        self.get_model = model
        self.get_identity = identity
        return self.schedule

    def add(self, schedule: AutomationSchedule) -> None:
        self.operations.append("add")
        self.add_count += 1

        if self.fail_on == "add":
            raise self.failure

        self.added.append(schedule)

    def flush(self) -> None:
        self.operations.append("flush")
        self.flush_count += 1

        if self.fail_on == "flush":
            raise self.failure

    def commit(self) -> None:
        self.operations.append("commit")
        self.commit_count += 1

        if self.fail_on == "commit":
            raise self.failure

    def refresh(self, schedule: AutomationSchedule) -> None:
        self.operations.append("refresh")
        self.refresh_count += 1

        if self.fail_on == "refresh":
            raise self.failure

        self.refreshed.append(schedule)

    def rollback(self) -> None:
        self.operations.append("rollback")
        self.rollback_count += 1


class ListSchedulesTests(unittest.TestCase):
    def test_returns_empty_list(self) -> None:
        session = FakeSession()

        schedules = list_schedules(session)

        self.assertEqual(schedules, [])

    def test_returns_multiple_schedules(self) -> None:
        expected = [make_schedule(1), make_schedule(2)]
        session = FakeSession(schedules=expected)

        schedules = list_schedules(session)

        self.assertEqual(schedules, expected)

    def test_uses_stable_id_ascending_order(self) -> None:
        session = FakeSession()

        list_schedules(session)

        compiled = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn(
            "ORDER BY automation_schedules.id ASC",
            compiled,
        )

    def test_returns_scalars_all_result(self) -> None:
        expected = [make_schedule(1)]
        session = FakeSession(schedules=expected)

        schedules = list_schedules(session)

        self.assertIs(schedules, session.scalar_result.schedules)
        self.assertEqual(session.scalar_result.all_count, 1)

    def test_does_not_commit(self) -> None:
        session = FakeSession()

        list_schedules(session)

        self.assertEqual(session.commit_count, 0)

    def test_does_not_rollback(self) -> None:
        session = FakeSession()

        list_schedules(session)

        self.assertEqual(session.rollback_count, 0)


class GetScheduleTests(unittest.TestCase):
    def test_returns_found_schedule(self) -> None:
        expected = make_schedule(42)
        session = FakeSession(schedule=expected)

        schedule = get_schedule(session, 42)

        self.assertIs(schedule, expected)

    def test_returns_none_for_missing_schedule(self) -> None:
        session = FakeSession(schedule=None)

        schedule = get_schedule(session, 42)

        self.assertIsNone(schedule)

    def test_looks_up_passed_primary_key(self) -> None:
        session = FakeSession()

        get_schedule(session, 73)

        self.assertIs(session.get_model, AutomationSchedule)
        self.assertEqual(session.get_identity, 73)

    def test_does_not_commit(self) -> None:
        session = FakeSession()

        get_schedule(session, 42)

        self.assertEqual(session.commit_count, 0)

    def test_does_not_rollback(self) -> None:
        session = FakeSession()

        get_schedule(session, 42)

        self.assertEqual(session.rollback_count, 0)


class CreateScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_tenant_id = settings.default_tenant_id
        settings.default_tenant_id = "server-tenant"

    def tearDown(self) -> None:
        settings.default_tenant_id = self.previous_tenant_id

    def test_creates_automation_schedule(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertIsInstance(schedule, AutomationSchedule)

    def test_copies_all_client_fields(self) -> None:
        session = FakeSession()
        payload = make_create_payload()

        schedule = create_schedule(
            session,
            payload,
            created_by_user_id=7,
        )

        self.assertEqual(schedule.name, payload.name)
        self.assertEqual(schedule.automation_type, payload.automation_type)
        self.assertEqual(schedule.scope_type, payload.scope_type)
        self.assertEqual(schedule.scope_id, payload.scope_id)
        self.assertIs(schedule.schedule_config, payload.schedule_config)
        self.assertIs(schedule.payload, payload.payload)
        self.assertIs(schedule.recipients, payload.recipients)
        self.assertEqual(schedule.timezone, payload.timezone)
        self.assertEqual(schedule.is_enabled, payload.is_enabled)

    def test_uses_tenant_id_from_settings(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertEqual(schedule.tenant_id, "server-tenant")

    def test_uses_created_by_user_id_argument(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=91,
        )

        self.assertEqual(schedule.created_by_user_id, 91)

    def test_leaves_contract_version_to_model_default(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertNotIn("contract_version", schedule.__dict__)

    def test_does_not_set_next_run_at(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertNotIn("next_run_at", schedule.__dict__)

    def test_adds_created_schedule_once(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertEqual(session.add_count, 1)
        self.assertEqual(session.added, [schedule])

    def test_calls_add_flush_refresh_commit_in_order(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertEqual(
            session.operations,
            ["add", "flush", "refresh", "commit"],
        )
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(session.refresh_count, 1)
        self.assertEqual(session.refreshed, [schedule])

    def test_flushes_once(self) -> None:
        session = FakeSession()

        create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertEqual(session.flush_count, 1)

    def test_success_does_not_rollback(self) -> None:
        session = FakeSession()

        create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertEqual(session.rollback_count, 0)

    def test_returns_same_object_added_to_session(self) -> None:
        session = FakeSession()

        schedule = create_schedule(
            session,
            make_create_payload(),
            created_by_user_id=7,
        )

        self.assertIs(schedule, session.added[0])

    def test_add_error_rolls_back_and_is_reraised(self) -> None:
        error = RuntimeError("add failed")
        session = FakeSession(fail_on="add", failure=error)

        with self.assertRaises(RuntimeError) as raised:
            create_schedule(
                session,
                make_create_payload(),
                created_by_user_id=7,
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(session.rollback_count, 1)
        self.assertEqual(session.flush_count, 0)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.refresh_count, 0)

    def test_flush_error_rolls_back_before_refresh_or_commit(self) -> None:
        error = RuntimeError("flush failed")
        session = FakeSession(fail_on="flush", failure=error)

        with self.assertRaises(RuntimeError) as raised:
            create_schedule(
                session,
                make_create_payload(),
                created_by_user_id=7,
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.refresh_count, 0)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 1)

    def test_commit_error_rolls_back_and_is_not_retried(self) -> None:
        error = RuntimeError("commit failed")
        session = FakeSession(fail_on="commit", failure=error)

        with self.assertRaises(RuntimeError) as raised:
            create_schedule(
                session,
                make_create_payload(),
                created_by_user_id=7,
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(session.refresh_count, 1)
        self.assertEqual(session.rollback_count, 1)

    def test_refresh_error_rolls_back_and_is_reraised(self) -> None:
        error = RuntimeError("refresh failed")
        session = FakeSession(fail_on="refresh", failure=error)

        with self.assertRaises(RuntimeError) as raised:
            create_schedule(
                session,
                make_create_payload(),
                created_by_user_id=7,
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.refresh_count, 1)
        self.assertEqual(session.rollback_count, 1)

    def test_does_not_accept_tenant_id_argument(self) -> None:
        parameters = inspect.signature(create_schedule).parameters

        self.assertNotIn("tenant_id", parameters)


class SettingsTests(unittest.TestCase):
    def test_default_tenant_id_is_available_without_environment_value(
        self,
    ) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configured = Settings(
                postgres_db="test",
                postgres_user="test",
                postgres_password="test",
                jwt_secret_key="test-jwt-secret",
            )

        self.assertEqual(configured.default_tenant_id, "eclair")


class ScheduleServiceIsolationTests(unittest.TestCase):
    def test_read_functions_do_not_call_automation_execution_components(
        self,
    ) -> None:
        session = FakeSession()

        with (
            patch(
                "app.automation.dispatch.create_automation_execution"
            ) as dispatch,
            patch(
                "app.automation.providers.base."
                "AutomationProvider.send_command"
            ) as provider,
            patch(
                "app.automation.outbox.OutboxWorker.process_one"
            ) as outbox,
        ):
            list_schedules(session)
            get_schedule(session, 42)

        dispatch.assert_not_called()
        provider.assert_not_called()
        outbox.assert_not_called()

    def test_create_error_does_not_call_execution_components(self) -> None:
        session = FakeSession(fail_on="commit")

        with (
            patch(
                "app.automation.dispatch.create_automation_execution"
            ) as dispatch,
            patch(
                "app.automation.providers.base."
                "AutomationProvider.send_command"
            ) as provider,
            patch(
                "app.automation.outbox.OutboxWorker.process_one"
            ) as outbox,
            self.assertRaises(RuntimeError),
        ):
            create_schedule(
                session,
                make_create_payload(),
                created_by_user_id=7,
            )

        dispatch.assert_not_called()
        provider.assert_not_called()
        outbox.assert_not_called()


if __name__ == "__main__":
    unittest.main()
