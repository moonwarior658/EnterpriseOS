import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy.dialects import postgresql

from app.automation.scheduler import (
    SchedulerRunResult,
    claim_due_schedule,
    due_schedule_statement,
    process_due_schedule,
    run_scheduler_once,
)
from app.models.automation import (
    AutomationExecution,
    AutomationSchedule,
    OutboxEvent,
)


NOW = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)


def make_schedule(
    schedule_id: int,
    *,
    schedule_config: dict[str, object] | None = None,
    next_run_at: datetime | None = None,
    is_enabled: bool = True,
) -> AutomationSchedule:
    return AutomationSchedule(
        id=schedule_id,
        name=f"Schedule {schedule_id}",
        automation_type="daily_report",
        contract_version="1.0",
        tenant_id="eclair",
        scope_type="department",
        scope_id="department-7",
        schedule_config=schedule_config
        or {"type": "daily", "time": "09:00"},
        payload={"report": "sales"},
        recipients=[{"user_id": 7}],
        timezone="UTC",
        is_enabled=is_enabled,
        next_run_at=(
            next_run_at
            if next_run_at is not None
            else NOW - timedelta(minutes=1)
        ),
        created_by_user_id=1,
    )


class ScalarResult:
    def __init__(self, value: AutomationSchedule | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> AutomationSchedule | None:
        return self.value


class NestedTransaction:
    def __enter__(self) -> "NestedTransaction":
        return self

    def __exit__(self, *args: object) -> None:
        return None

class Store:
    def __init__(
        self,
        schedules: list[AutomationSchedule],
        *,
        fail_ids: set[int] | None = None,
    ) -> None:
        self.schedules = schedules
        self.fail_ids = fail_ids or set()
        self.executions: list[AutomationExecution] = []
        self.events: list[OutboxEvent] = []
        self.locked_ids: set[int] = set()
        self.commits = 0
        self.rollbacks = 0

    def __call__(self) -> "FakeSession":
        return FakeSession(self)


class Transaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session
        self.original_next_runs: dict[int, datetime | None] = {}

    def __enter__(self) -> "Transaction":
        self.session.transaction_open = True
        self.original_next_runs = {
            schedule.id: schedule.next_run_at
            for schedule in self.session.store.schedules
        }
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        self.session.transaction_open = False
        if self.session.claimed_id is not None:
            self.session.store.locked_ids.discard(self.session.claimed_id)

        if exc_type is None:
            self.session.store.executions.extend(
                item
                for item in self.session.staged
                if isinstance(item, AutomationExecution)
            )
            self.session.store.events.extend(
                item
                for item in self.session.staged
                if isinstance(item, OutboxEvent)
            )
            self.session.store.commits += 1
        else:
            for schedule in self.session.store.schedules:
                schedule.next_run_at = self.original_next_runs[schedule.id]
            self.session.store.rollbacks += 1

        self.session.staged.clear()


class FakeSession:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.transaction_open = False
        self.claimed_id: int | None = None
        self.staged: list[object] = []
        self.original_next_runs = {
            schedule.id: schedule.next_run_at
            for schedule in store.schedules
        }

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def close(self) -> None:
        return None

    def begin(self) -> Transaction:
        return Transaction(self)

    def begin_nested(self) -> NestedTransaction:
        return NestedTransaction()

    def in_transaction(self) -> bool:
        return self.transaction_open

    def execute(self, statement: object) -> ScalarResult:
        self.transaction_open = True
        params = statement.compile().params
        excluded_ids: set[int] = set()
        for value in params.values():
            if isinstance(value, (list, tuple)):
                excluded_ids.update(value)

        candidates = sorted(
            (
                schedule
                for schedule in self.store.schedules
                if schedule.is_enabled
                and schedule.next_run_at is not None
                and schedule.next_run_at <= NOW
                and schedule.id not in excluded_ids
                and schedule.id not in self.store.locked_ids
            ),
            key=lambda schedule: (schedule.next_run_at, schedule.id),
        )
        schedule = candidates[0] if candidates else None
        if schedule is not None:
            self.claimed_id = schedule.id
            self.store.locked_ids.add(schedule.id)
        return ScalarResult(schedule)

    def add_all(self, instances: list[object]) -> None:
        self.staged.extend(instances)

    def flush(self) -> None:
        if self.claimed_id in self.store.fail_ids:
            raise RuntimeError("database write failed")

    def commit(self) -> None:
        self.store.executions.extend(
            item
            for item in self.staged
            if isinstance(item, AutomationExecution)
        )
        self.store.events.extend(
            item
            for item in self.staged
            if isinstance(item, OutboxEvent)
        )
        self.store.commits += 1
        self._finish()

    def rollback(self) -> None:
        for schedule in self.store.schedules:
            schedule.next_run_at = self.original_next_runs[schedule.id]
        self.store.rollbacks += 1
        self._finish()

    def _finish(self) -> None:
        if self.claimed_id is not None:
            self.store.locked_ids.discard(self.claimed_id)
        self.staged.clear()
        self.transaction_open = False


class DueScheduleQueryTests(unittest.TestCase):
    def test_query_filters_orders_limits_and_uses_skip_locked(self) -> None:
        compiled = str(
            due_schedule_statement(NOW).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("is_enabled IS true", compiled)
        self.assertIn("next_run_at IS NOT NULL", compiled)
        self.assertIn("next_run_at <=", compiled)
        self.assertIn("ORDER BY automation_schedules.next_run_at ASC", compiled)
        self.assertIn("automation_schedules.id ASC", compiled)
        self.assertIn("LIMIT 1", compiled)
        self.assertIn("FOR UPDATE SKIP LOCKED", compiled)

    def test_rejects_naive_now(self) -> None:
        with self.assertRaisesRegex(ValueError, "now must include a timezone"):
            due_schedule_statement(datetime(2026, 7, 21, 8, 0))

    def test_two_claims_cannot_hold_same_schedule(self) -> None:
        store = Store([make_schedule(1)])
        first = store()
        second = store()

        with first.begin():
            first_claim = claim_due_schedule(first, now=NOW)
            with second.begin():
                second_claim = claim_due_schedule(second, now=NOW)

        self.assertIsNotNone(first_claim)
        self.assertIsNone(second_claim)


class SchedulerRunTests(unittest.TestCase):
    def test_empty_due_set(self) -> None:
        result = run_scheduler_once(Store([]), now=NOW)

        self.assertEqual(result, SchedulerRunResult())

    def test_disabled_none_and_future_schedules_are_ignored(self) -> None:
        disabled = make_schedule(1, is_enabled=False)
        no_next = make_schedule(2)
        no_next.next_run_at = None
        future = make_schedule(3, next_run_at=NOW + timedelta(hours=1))

        result = run_scheduler_once(
            Store([disabled, no_next, future]),
            now=NOW,
        )

        self.assertEqual(result.created, 0)

    def test_daily_weekly_and_interval_create_execution_and_outbox(self) -> None:
        configs = (
            {"type": "daily", "time": "09:00"},
            {"type": "weekly", "weekdays": [1], "time": "09:00"},
            {"type": "interval", "minutes": 30},
        )

        for index, config in enumerate(configs, start=1):
            with self.subTest(config=config):
                store = Store([make_schedule(index, schedule_config=config)])
                result = run_scheduler_once(store, now=NOW)

                self.assertEqual(result.created, 1)
                self.assertEqual(len(store.executions), 1)
                self.assertEqual(len(store.events), 1)
                self.assertGreater(store.schedules[0].next_run_at, NOW)
                self.assertEqual(store.commits, 1)

    def test_execution_contains_immutable_schedule_snapshot(self) -> None:
        schedule = make_schedule(1)
        store = Store([schedule])

        run_scheduler_once(store, now=NOW)
        execution = store.executions[0]
        schedule.scope_type = "company"
        schedule.scope_id = None
        schedule.recipients.append({"user_id": 99})

        self.assertEqual(execution.scope_type, "department")
        self.assertEqual(execution.scope_id, "department-7")
        self.assertEqual(execution.recipients, [{"user_id": 7}])

    def test_missed_intervals_create_one_execution_and_skip_backlog(self) -> None:
        for age in (timedelta(minutes=31), timedelta(days=365)):
            with self.subTest(age=age):
                schedule = make_schedule(
                    1,
                    schedule_config={"type": "interval", "minutes": 30},
                    next_run_at=NOW - age,
                )
                store = Store([schedule])

                first = run_scheduler_once(store, now=NOW)
                second = run_scheduler_once(store, now=NOW)

                self.assertEqual(first.created, 1)
                self.assertEqual(second.created, 0)
                self.assertEqual(len(store.executions), 1)
                self.assertGreater(schedule.next_run_at, NOW)

    def test_batch_size_limits_processing_in_stable_order(self) -> None:
        schedules = [make_schedule(3), make_schedule(1), make_schedule(2)]
        store = Store(schedules)

        result = run_scheduler_once(store, now=NOW, batch_size=2)

        self.assertEqual(result.created, 2)
        self.assertEqual(
            [execution.schedule_id for execution in store.executions],
            [1, 2],
        )

    def test_failure_rolls_back_and_does_not_block_next_schedule(self) -> None:
        failed_schedule = make_schedule(1)
        original_next_run = failed_schedule.next_run_at
        store = Store([failed_schedule, make_schedule(2)], fail_ids={1})

        result = run_scheduler_once(store, now=NOW, batch_size=2)

        self.assertEqual(result.claimed, 2)
        self.assertEqual(result.created, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(store.rollbacks, 1)
        self.assertEqual(failed_schedule.next_run_at, original_next_run)
        self.assertEqual([item.schedule_id for item in store.executions], [2])

    def test_invalid_batch_size_and_naive_now_are_rejected(self) -> None:
        for batch_size in (0, 101):
            with self.subTest(batch_size=batch_size):
                with self.assertRaises(ValueError):
                    run_scheduler_once(Store([]), now=NOW, batch_size=batch_size)

        with self.assertRaisesRegex(ValueError, "now must include a timezone"):
            run_scheduler_once(
                Store([]),
                now=datetime(2026, 7, 21, 8, 0),
            )

    def test_scheduler_never_calls_provider_callback_or_outbox_worker(self) -> None:
        with (
            patch("app.automation.providers.base.AutomationProvider.send_command")
            as provider,
            patch("app.automation.outbox.OutboxWorker.process_one") as outbox,
        ):
            result = run_scheduler_once(Store([make_schedule(1)]), now=NOW)

        self.assertEqual(result.created, 1)
        provider.assert_not_called()
        outbox.assert_not_called()


if __name__ == "__main__":
    unittest.main()
