import unittest
from unittest.mock import patch

from sqlalchemy.dialects import postgresql

from app.automation.schedules import get_schedule, list_schedules
from app.models.automation import AutomationSchedule


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
    ) -> None:
        self.scalar_result = FakeScalarResult(schedules or [])
        self.schedule = schedule
        self.statement = None
        self.get_model = None
        self.get_identity = None
        self.commit_count = 0
        self.rollback_count = 0

    def scalars(self, statement) -> FakeScalarResult:
        self.statement = statement
        return self.scalar_result

    def get(self, model, identity):
        self.get_model = model
        self.get_identity = identity
        return self.schedule

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
