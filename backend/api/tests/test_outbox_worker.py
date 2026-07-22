import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.dialects import postgresql

from app.automation.outbox import (
    ClaimedOutboxEvent,
    DeliveryStatus,
    OutboxWorker,
    SqlAlchemyOutboxStore,
)
from app.automation.providers.base import (
    AutomationProvider,
    CommandAcceptance,
)
from app.automation.providers.errors import ProviderUnavailableError
from app.models.automation import (
    AutomationExecution,
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
)
from app.schemas.automation import AutomationCommand


NOW = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)
EVENT_ID = UUID("ba051a22-2818-47de-b3c2-80a1ec0f4a9b")
EXECUTION_ID = UUID("41644d7a-8875-4f35-a493-371b330fb154")
CALLBACK_URL = "https://api.example.test/automation/callback"


def make_claim() -> ClaimedOutboxEvent:
    return ClaimedOutboxEvent(
        id=1,
        event_id=EVENT_ID,
        execution_id=EXECUTION_ID,
        contract_version="1.0",
        automation_type="daily_sales_report",
        tenant_id="tenant-42",
        requested_at=NOW - timedelta(minutes=1),
        payload={"location_ids": [10, 20]},
        attempt_count=1,
        max_attempts=3,
        lock_token="not-claimed",
    )


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._claim = make_claim()
        self.status = "pending"
        self.owner: str | None = None
        self.acceptance: CommandAcceptance | None = None
        self.last_error: str | None = None
        self.next_attempt_at: datetime | None = None

    def claim_next(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
    ) -> ClaimedOutboxEvent | None:
        if self.status != "pending":
            return None

        self.status = "processing"
        self.owner = worker_id
        self._claim = replace(self._claim, lock_token=worker_id)
        return self._claim

    def mark_published(
        self,
        claim: ClaimedOutboxEvent,
        *,
        acceptance: CommandAcceptance,
        published_at: datetime,
    ) -> None:
        self._assert_owner(claim)
        self.status = "published"
        self.owner = None
        self.acceptance = acceptance

    def mark_failed(
        self,
        claim: ClaimedOutboxEvent,
        *,
        error_code: str,
        error_message: str,
        failed_at: datetime,
        next_attempt_at: datetime | None,
    ) -> None:
        self._assert_owner(claim)
        self.status = "pending" if next_attempt_at else "failed"
        self.owner = None
        self.last_error = f"{error_code}: {error_message}"
        self.next_attempt_at = next_attempt_at

    def _assert_owner(self, claim: ClaimedOutboxEvent) -> None:
        if self.status != "processing" or self.owner != claim.lock_token:
            raise AssertionError("Worker does not own the event")


class RecordingProvider(AutomationProvider):
    def __init__(self) -> None:
        self.commands: list[AutomationCommand] = []

    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        self.commands.append(command)
        return CommandAcceptance(
            provider="recording",
            accepted=True,
            status_code=202,
        )

    async def check_availability(self) -> bool:
        return True


class FailingProvider(AutomationProvider):
    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        raise ProviderUnavailableError("provider is offline")

    async def check_availability(self) -> bool:
        return False


class RecordingFailingProvider(RecordingProvider):
    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        self.commands.append(command)
        raise ProviderUnavailableError("provider is offline")


class DeduplicatingProvider(RecordingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.processed_keys: set[UUID] = set()
        self.side_effect_count = 0

    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        self.commands.append(command)
        if command.idempotency_key not in self.processed_keys:
            self.processed_keys.add(command.idempotency_key)
            self.side_effect_count += 1
        return CommandAcceptance(
            provider="deduplicating",
            accepted=True,
            status_code=202,
        )


class BlockingProvider(RecordingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        self.entered.set()
        await self.release.wait()
        return await super().send_command(command)


class LeakyProvider(AutomationProvider):
    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        raise RuntimeError(
            "Bearer secret-token payload={'private': 'value'}"
        )

    async def check_availability(self) -> bool:
        return False


class FakeScalarResult:
    def __init__(self, value: OutboxEvent | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> OutboxEvent | None:
        return self._value


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session

    def __enter__(self) -> "FakeTransaction":
        self._session.transaction_open = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        self._session.transaction_open = False


class FakeSession:
    def __init__(self, results: list[OutboxEvent | None]) -> None:
        self._results = results
        self.transaction_open = False
        self.flush_count = 0

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        pass

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    def execute(self, statement: object) -> FakeScalarResult:
        return FakeScalarResult(self._results.pop(0))

    def flush(self) -> None:
        self.flush_count += 1


class SequencedSessionFactory:
    def __init__(self, sessions: list[FakeSession]) -> None:
        self._sessions = sessions

    def __call__(self) -> FakeSession:
        return self._sessions.pop(0)


class TransactionCheckingProvider(RecordingProvider):
    def __init__(self, claim_session: FakeSession) -> None:
        super().__init__()
        self._claim_session = claim_session

    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        if self._claim_session.transaction_open:
            raise AssertionError(
                "Database transaction is open during provider call"
            )
        return await super().send_command(command)


def make_database_event(
    *,
    status: OutboxStatus = OutboxStatus.PENDING,
    attempt_count: int = 0,
    max_attempts: int = 3,
    locked_at: datetime | None = None,
    locked_by: str | None = None,
) -> OutboxEvent:
    execution = AutomationExecution(
        id=1,
        execution_id=EXECUTION_ID,
        contract_version="1.0",
        automation_type="daily_sales_report",
        tenant_id="tenant-42",
        scope_type="company",
        scope_id=None,
        recipients=[],
        status=ExecutionStatus.PENDING,
        requested_at=NOW - timedelta(minutes=1),
        payload={"location_ids": [10, 20]},
        attempt_count=0,
        max_attempts=3,
    )
    event = OutboxEvent(
        id=1,
        event_id=EVENT_ID,
        execution_id=EXECUTION_ID,
        event_type="automation.command.requested",
        contract_version="1.0",
        payload={"location_ids": [10, 20]},
        status=status,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        available_at=NOW - timedelta(minutes=10),
        locked_at=locked_at,
        locked_by=locked_by,
    )
    event.execution = execution
    return event


class OutboxWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_delivery_marks_event_published(self) -> None:
        store = InMemoryOutboxStore()
        provider = RecordingProvider()
        worker = OutboxWorker(
            store=store,
            provider=provider,
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )

        result = await worker.process_one()

        self.assertEqual(result.status, DeliveryStatus.PUBLISHED)
        self.assertEqual(result.event_id, EVENT_ID)
        self.assertEqual(store.status, "published")
        self.assertEqual(store.acceptance.provider, "recording")
        self.assertEqual(len(provider.commands), 1)
        self.assertEqual(provider.commands[0].execution_id, EXECUTION_ID)
        self.assertEqual(
            provider.commands[0].payload,
            {"location_ids": [10, 20]},
        )

        second_result = await worker.process_one()

        self.assertEqual(second_result.status, DeliveryStatus.NO_EVENT)
        self.assertEqual(len(provider.commands), 1)

    async def test_provider_error_is_saved_and_retry_is_scheduled(
        self,
    ) -> None:
        store = InMemoryOutboxStore()
        worker = OutboxWorker(
            store=store,
            provider=FailingProvider(),
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            retry_base_delay=timedelta(seconds=20),
            clock=lambda: NOW,
        )

        result = await worker.process_one()

        self.assertEqual(
            result.status,
            DeliveryStatus.RETRY_SCHEDULED,
        )
        self.assertEqual(store.status, "pending")
        self.assertIn(
            "Automation provider is unavailable",
            store.last_error,
        )
        self.assertEqual(
            store.next_attempt_at,
            NOW + timedelta(seconds=20),
        )
        self.assertEqual(result.next_attempt_at, store.next_attempt_at)

    async def test_retry_reuses_the_same_idempotency_key(self) -> None:
        store = InMemoryOutboxStore()
        provider = RecordingFailingProvider()
        worker = OutboxWorker(
            store=store,
            provider=provider,
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )

        first_result = await worker.process_one()
        second_result = await worker.process_one()

        self.assertEqual(
            first_result.status,
            DeliveryStatus.RETRY_SCHEDULED,
        )
        self.assertEqual(
            second_result.status,
            DeliveryStatus.RETRY_SCHEDULED,
        )
        self.assertEqual(len(provider.commands), 2)
        self.assertEqual(
            provider.commands[0].idempotency_key,
            provider.commands[1].idempotency_key,
        )
        self.assertEqual(
            provider.commands[0].idempotency_key,
            EXECUTION_ID,
        )

    async def test_replayed_event_is_deduplicated_by_execution_key(
        self,
    ) -> None:
        store = InMemoryOutboxStore()
        provider = DeduplicatingProvider()
        worker = OutboxWorker(
            store=store,
            provider=provider,
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )

        first_result = await worker.process_one()
        store.status = "pending"
        replay_result = await worker.process_one()

        self.assertEqual(first_result.status, DeliveryStatus.PUBLISHED)
        self.assertEqual(replay_result.status, DeliveryStatus.PUBLISHED)
        self.assertEqual(len(provider.commands), 2)
        self.assertEqual(
            provider.commands[0].idempotency_key,
            provider.commands[1].idempotency_key,
        )
        self.assertEqual(provider.side_effect_count, 1)

    async def test_provider_error_after_final_attempt_is_terminal(
        self,
    ) -> None:
        store = InMemoryOutboxStore()
        store._claim = replace(
            store._claim,
            attempt_count=3,
            max_attempts=3,
        )
        worker = OutboxWorker(
            store=store,
            provider=FailingProvider(),
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )

        result = await worker.process_one()

        self.assertEqual(result.status, DeliveryStatus.FAILED)
        self.assertEqual(store.status, "failed")
        self.assertIsNone(store.next_attempt_at)
        self.assertIn(
            "Automation provider is unavailable",
            store.last_error,
        )

    async def test_unexpected_error_does_not_persist_sensitive_details(
        self,
    ) -> None:
        store = InMemoryOutboxStore()
        worker = OutboxWorker(
            store=store,
            provider=LeakyProvider(),
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )

        result = await worker.process_one()

        self.assertEqual(
            result.error,
            "RuntimeError while delivering automation command",
        )
        self.assertNotIn("secret-token", store.last_error)
        self.assertNotIn("private", store.last_error)

    async def test_processing_event_cannot_be_claimed_by_second_worker(
        self,
    ) -> None:
        store = InMemoryOutboxStore()
        provider = BlockingProvider()
        first_worker = OutboxWorker(
            store=store,
            provider=provider,
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )
        second_worker = OutboxWorker(
            store=store,
            provider=RecordingProvider(),
            worker_id="worker-2",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )

        first_delivery = asyncio.create_task(first_worker.process_one())
        await provider.entered.wait()

        second_result = await second_worker.process_one()

        self.assertEqual(second_result.status, DeliveryStatus.NO_EVENT)
        self.assertEqual(store.owner, "worker-1")

        provider.release.set()
        first_result = await first_delivery

        self.assertEqual(first_result.status, DeliveryStatus.PUBLISHED)
        self.assertEqual(store.status, "published")

    def test_postgresql_claim_uses_skip_locked(self) -> None:
        compiled = str(
            SqlAlchemyOutboxStore.claim_statement(NOW).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )

        self.assertIn("FOR UPDATE SKIP LOCKED", compiled)
        self.assertIn("outbox_events.status = 'pending'", compiled)
        self.assertIn(
            "outbox_events.attempt_count < outbox_events.max_attempts",
            compiled,
        )
        self.assertIn("outbox_events.status = 'processing'", compiled)
        self.assertIn("outbox_events.locked_at <=", compiled)
        self.assertNotIn("outbox_events.status = 'published'", compiled)

    def test_claim_reclaims_expired_processing_event(self) -> None:
        event = make_database_event(
            status=OutboxStatus.PROCESSING,
            attempt_count=1,
            locked_at=NOW - timedelta(minutes=10),
            locked_by="dead-worker",
        )
        session = FakeSession([event])
        store = SqlAlchemyOutboxStore(
            SequencedSessionFactory([session]),
            processing_timeout=timedelta(minutes=5),
        )

        claim = store.claim_next(
            worker_id="worker-2",
            claimed_at=NOW,
        )

        self.assertIsNotNone(claim)
        self.assertEqual(claim.attempt_count, 2)
        self.assertEqual(event.status, OutboxStatus.PROCESSING)
        self.assertTrue(event.locked_by.startswith("worker-2:"))
        self.assertEqual(event.locked_by, claim.lock_token)
        self.assertNotEqual(event.locked_by, "dead-worker")
        self.assertEqual(event.last_error, "Previous outbox worker claim expired")
        self.assertFalse(session.transaction_open)

    def test_expired_final_attempt_is_marked_failed(self) -> None:
        event = make_database_event(
            status=OutboxStatus.PROCESSING,
            attempt_count=3,
            max_attempts=3,
            locked_at=NOW - timedelta(minutes=10),
            locked_by="dead-worker",
        )
        session = FakeSession([event, None])
        store = SqlAlchemyOutboxStore(
            SequencedSessionFactory([session]),
            processing_timeout=timedelta(minutes=5),
        )

        claim = store.claim_next(
            worker_id="worker-2",
            claimed_at=NOW,
        )

        self.assertIsNone(claim)
        self.assertEqual(event.status, OutboxStatus.FAILED)
        self.assertIsNone(event.locked_by)
        self.assertEqual(
            event.execution.error_code,
            "OutboxClaimExpired",
        )
        self.assertEqual(session.flush_count, 1)

    async def test_provider_call_runs_after_claim_transaction_closes(
        self,
    ) -> None:
        event = make_database_event()
        claim_session = FakeSession([event])
        publish_session = FakeSession([event])
        store = SqlAlchemyOutboxStore(
            SequencedSessionFactory(
                [claim_session, publish_session]
            )
        )
        worker = OutboxWorker(
            store=store,
            provider=TransactionCheckingProvider(claim_session),
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: NOW,
        )

        result = await worker.process_one()

        self.assertEqual(result.status, DeliveryStatus.PUBLISHED)
        self.assertFalse(claim_session.transaction_open)
        self.assertFalse(publish_session.transaction_open)
        self.assertEqual(event.status, OutboxStatus.PUBLISHED)

    async def test_naive_clock_is_rejected(self) -> None:
        worker = OutboxWorker(
            store=InMemoryOutboxStore(),
            provider=RecordingProvider(),
            worker_id="worker-1",
            callback_url=CALLBACK_URL,
            clock=lambda: datetime(2026, 7, 20, 8, 0),
        )

        with self.assertRaisesRegex(
            ValueError,
            "clock result must include a timezone",
        ):
            await worker.process_one()


if __name__ == "__main__":
    unittest.main()
