import inspect
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy.dialects import postgresql

from app.automation.schedules import (
    InvalidScheduleScopeError,
    create_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from app.core.config import Settings, settings
from app.models.automation import AutomationSchedule
from app.schemas.automation import (
    AutomationScheduleCreate,
    AutomationScheduleUpdate,
)


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


def make_update_schedule(
    *,
    scope_type: str = "department",
    scope_id: str | None = "department-1",
) -> AutomationSchedule:
    schedule = make_schedule(42)
    schedule.name = "Original name"
    schedule.automation_type = "original_automation"
    schedule.scope_type = scope_type
    schedule.scope_id = scope_id
    schedule.schedule_config = {"frequency": "weekly"}
    schedule.payload = {"report": "original"}
    schedule.recipients = [{"user_id": 1}]
    schedule.timezone = "UTC"
    schedule.is_enabled = False
    schedule.contract_version = "1.0"
    schedule.tenant_id = "enterpriseos"
    schedule.next_run_at = datetime(
        2026,
        7,
        22,
        5,
        0,
        tzinfo=timezone.utc,
    )
    schedule.created_by_user_id = 1
    schedule.created_at = datetime(
        2026,
        7,
        21,
        10,
        0,
        tzinfo=timezone.utc,
    )
    schedule.updated_at = datetime(
        2026,
        7,
        21,
        11,
        0,
        tzinfo=timezone.utc,
    )
    return schedule


def schedule_client_state(schedule: AutomationSchedule) -> dict[str, object]:
    return {
        "name": schedule.name,
        "automation_type": schedule.automation_type,
        "scope_type": schedule.scope_type,
        "scope_id": schedule.scope_id,
        "schedule_config": schedule.schedule_config,
        "payload": schedule.payload,
        "recipients": schedule.recipients,
        "timezone": schedule.timezone,
        "is_enabled": schedule.is_enabled,
    }


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


class UpdateScheduleTests(unittest.TestCase):
    def test_updates_name_only(self) -> None:
        session = FakeSession()
        schedule = make_update_schedule()

        updated = update_schedule(
            session,
            schedule,
            AutomationScheduleUpdate(name="  Updated name  "),
        )

        self.assertEqual(updated.name, "Updated name")
        self.assertEqual(updated.automation_type, "original_automation")

    def test_updates_automation_type_only(self) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(
                automation_type="updated_automation"
            ),
        )

        self.assertEqual(schedule.automation_type, "updated_automation")
        self.assertEqual(schedule.name, "Original name")

    def test_updates_schedule_config(self) -> None:
        schedule = make_update_schedule()
        value = {"frequency": "daily"}

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(schedule_config=value),
        )

        self.assertEqual(schedule.schedule_config, value)

    def test_updates_payload(self) -> None:
        schedule = make_update_schedule()
        value = {"report": "updated"}

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(payload=value),
        )

        self.assertEqual(schedule.payload, value)

    def test_updates_recipients(self) -> None:
        schedule = make_update_schedule()
        value = [{"user_id": 7}]

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(recipients=value),
        )

        self.assertEqual(schedule.recipients, value)

    def test_updates_timezone(self) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(timezone="Asia/Yekaterinburg"),
        )

        self.assertEqual(schedule.timezone, "Asia/Yekaterinburg")

    def test_updates_is_enabled(self) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(is_enabled=True),
        )

        self.assertTrue(schedule.is_enabled)

    def test_updates_multiple_fields(self) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(
                name="Updated name",
                automation_type="updated_automation",
                timezone="Asia/Yekaterinburg",
                is_enabled=True,
            ),
        )

        self.assertEqual(schedule.name, "Updated name")
        self.assertEqual(schedule.automation_type, "updated_automation")
        self.assertEqual(schedule.timezone, "Asia/Yekaterinburg")
        self.assertTrue(schedule.is_enabled)

    def test_unset_fields_are_preserved(self) -> None:
        schedule = make_update_schedule()
        original_state = schedule_client_state(schedule)

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(name="Updated name"),
        )

        updated_state = schedule_client_state(schedule)
        updated_state["name"] = original_state["name"]
        self.assertEqual(updated_state, original_state)

    def test_empty_patch_returns_same_object_without_database_calls(
        self,
    ) -> None:
        session = FakeSession()
        schedule = make_update_schedule()
        original_state = schedule_client_state(schedule)

        updated = update_schedule(
            session,
            schedule,
            AutomationScheduleUpdate(),
        )

        self.assertIs(updated, schedule)
        self.assertEqual(schedule_client_state(schedule), original_state)
        self.assertEqual(session.operations, [])
        self.assertEqual(session.flush_count, 0)
        self.assertEqual(session.refresh_count, 0)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 0)

    def test_returns_same_orm_object(self) -> None:
        schedule = make_update_schedule()

        updated = update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(name="Updated name"),
        )

        self.assertIs(updated, schedule)

    def test_preserves_server_owned_fields(self) -> None:
        schedule = make_update_schedule()
        server_fields = {
            "id": schedule.id,
            "contract_version": schedule.contract_version,
            "tenant_id": schedule.tenant_id,
            "next_run_at": schedule.next_run_at,
            "created_by_user_id": schedule.created_by_user_id,
            "created_at": schedule.created_at,
            "updated_at": schedule.updated_at,
        }

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(name="Updated name"),
        )

        for field, value in server_fields.items():
            with self.subTest(field=field):
                self.assertEqual(getattr(schedule, field), value)

    def test_preserves_contract_version_and_next_run_at(self) -> None:
        schedule = make_update_schedule()
        next_run_at = schedule.next_run_at

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(name="Updated name"),
        )

        self.assertEqual(schedule.contract_version, "1.0")
        self.assertIs(schedule.next_run_at, next_run_at)

    def test_changes_company_to_department_with_scope_id(self) -> None:
        schedule = make_update_schedule(
            scope_type="company",
            scope_id=None,
        )

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(
                scope_type="department",
                scope_id="department-2",
            ),
        )

        self.assertEqual(schedule.scope_type, "department")
        self.assertEqual(schedule.scope_id, "department-2")

    def test_changes_department_to_company_with_explicit_null(self) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(
                scope_type="company",
                scope_id=None,
            ),
        )

        self.assertEqual(schedule.scope_type, "company")
        self.assertIsNone(schedule.scope_id)

    def test_changes_department_to_location_using_existing_scope_id(
        self,
    ) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(scope_type="location"),
        )

        self.assertEqual(schedule.scope_type, "location")
        self.assertEqual(schedule.scope_id, "department-1")

    def test_updates_scope_id_using_existing_department_type(self) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(scope_id="department-2"),
        )

        self.assertEqual(schedule.scope_type, "department")
        self.assertEqual(schedule.scope_id, "department-2")

    def test_updates_scope_type_using_existing_scope_id(self) -> None:
        schedule = make_update_schedule()

        update_schedule(
            FakeSession(),
            schedule,
            AutomationScheduleUpdate(scope_type="user"),
        )

        self.assertEqual(schedule.scope_type, "user")
        self.assertEqual(schedule.scope_id, "department-1")

    def test_rejects_company_with_non_null_scope_id(self) -> None:
        schedule = make_update_schedule()

        with self.assertRaisesRegex(
            InvalidScheduleScopeError,
            "Invalid schedule scope: company requires scope_id to be null",
        ):
            update_schedule(
                FakeSession(),
                schedule,
                AutomationScheduleUpdate(scope_type="company"),
            )

    def test_rejects_department_with_null_scope_id(self) -> None:
        schedule = make_update_schedule(
            scope_type="company",
            scope_id=None,
        )

        with self.assertRaisesRegex(
            InvalidScheduleScopeError,
            "department requires a non-empty scope_id",
        ):
            update_schedule(
                FakeSession(),
                schedule,
                AutomationScheduleUpdate(scope_type="department"),
            )

    def test_rejects_location_with_empty_existing_scope_id(self) -> None:
        schedule = make_update_schedule(scope_id="")

        with self.assertRaises(InvalidScheduleScopeError):
            update_schedule(
                FakeSession(),
                schedule,
                AutomationScheduleUpdate(scope_type="location"),
            )

    def test_rejects_user_with_empty_existing_scope_id(self) -> None:
        schedule = make_update_schedule(scope_id="   ")

        with self.assertRaises(InvalidScheduleScopeError):
            update_schedule(
                FakeSession(),
                schedule,
                AutomationScheduleUpdate(scope_type="user"),
            )

    def test_invalid_scope_does_not_mutate_or_touch_database(self) -> None:
        session = FakeSession()
        schedule = make_update_schedule()
        original_state = schedule_client_state(schedule)

        with self.assertRaises(InvalidScheduleScopeError):
            update_schedule(
                session,
                schedule,
                AutomationScheduleUpdate(scope_type="company"),
            )

        self.assertEqual(schedule_client_state(schedule), original_state)
        self.assertEqual(session.operations, [])
        self.assertEqual(session.flush_count, 0)
        self.assertEqual(session.refresh_count, 0)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 0)

    def test_calls_flush_refresh_commit_in_order_without_add(self) -> None:
        session = FakeSession()
        schedule = make_update_schedule()

        update_schedule(
            session,
            schedule,
            AutomationScheduleUpdate(name="Updated name"),
        )

        self.assertEqual(session.operations, ["flush", "refresh", "commit"])
        self.assertEqual(session.add_count, 0)

    def test_flush_error_rolls_back_and_is_reraised(self) -> None:
        error = RuntimeError("flush failed")
        session = FakeSession(fail_on="flush", failure=error)

        with self.assertRaises(RuntimeError) as raised:
            update_schedule(
                session,
                make_update_schedule(),
                AutomationScheduleUpdate(name="Updated name"),
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.refresh_count, 0)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 1)

    def test_refresh_error_rolls_back_without_commit(self) -> None:
        error = RuntimeError("refresh failed")
        session = FakeSession(fail_on="refresh", failure=error)

        with self.assertRaises(RuntimeError) as raised:
            update_schedule(
                session,
                make_update_schedule(),
                AutomationScheduleUpdate(name="Updated name"),
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.refresh_count, 1)
        self.assertEqual(session.commit_count, 0)
        self.assertEqual(session.rollback_count, 1)

    def test_commit_error_rolls_back_without_retry(self) -> None:
        error = RuntimeError("commit failed")
        session = FakeSession(fail_on="commit", failure=error)

        with self.assertRaises(RuntimeError) as raised:
            update_schedule(
                session,
                make_update_schedule(),
                AutomationScheduleUpdate(name="Updated name"),
            )

        self.assertIs(raised.exception, error)
        self.assertEqual(session.flush_count, 1)
        self.assertEqual(session.refresh_count, 1)
        self.assertEqual(session.commit_count, 1)
        self.assertEqual(session.rollback_count, 1)


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

    def test_update_does_not_call_execution_components(self) -> None:
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
            update_schedule(
                FakeSession(),
                make_update_schedule(),
                AutomationScheduleUpdate(name="Updated name"),
            )

        dispatch.assert_not_called()
        provider.assert_not_called()
        outbox.assert_not_called()


if __name__ == "__main__":
    unittest.main()
