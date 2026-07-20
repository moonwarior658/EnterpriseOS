from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.automation.providers.base import (
    AutomationProvider,
    CommandAcceptance,
)
from app.automation.providers.errors import (
    AutomationProviderError,
    ProviderAuthenticationError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.models.automation import (
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
)
from app.schemas.automation import AutomationCommand


class OutboxClaimLostError(RuntimeError):
    """The event is no longer owned by the worker finalizing it."""


EXPIRED_CLAIM_ERROR = "Previous outbox worker claim expired"


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")

    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ClaimedOutboxEvent:
    id: int
    event_id: UUID
    execution_id: UUID
    contract_version: str
    automation_type: str
    tenant_id: str
    requested_at: datetime
    payload: dict[str, object]
    attempt_count: int
    max_attempts: int
    lock_token: str


class DeliveryStatus(StrEnum):
    NO_EVENT = "no_event"
    PUBLISHED = "published"
    RETRY_SCHEDULED = "retry_scheduled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    status: DeliveryStatus
    event_id: UUID | None = None
    error: str | None = None
    next_attempt_at: datetime | None = None


class OutboxStore(Protocol):
    def claim_next(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
    ) -> ClaimedOutboxEvent | None:
        """Atomically claim one currently deliverable event."""

    def mark_published(
        self,
        claim: ClaimedOutboxEvent,
        *,
        acceptance: CommandAcceptance,
        published_at: datetime,
    ) -> None:
        """Persist successful transport-level delivery."""

    def mark_failed(
        self,
        claim: ClaimedOutboxEvent,
        *,
        error_code: str,
        error_message: str,
        failed_at: datetime,
        next_attempt_at: datetime | None,
    ) -> None:
        """Persist an error and either requeue or terminally fail the event."""


class SqlAlchemyOutboxStore:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        processing_timeout: timedelta = timedelta(minutes=5),
    ) -> None:
        if processing_timeout <= timedelta(0):
            raise ValueError("processing_timeout must be positive")

        self._session_factory = session_factory
        self._processing_timeout = processing_timeout

    @staticmethod
    def claim_statement(
        claimed_at: datetime,
        *,
        processing_timeout: timedelta = timedelta(minutes=5),
    ) -> Select[tuple[OutboxEvent]]:
        if processing_timeout <= timedelta(0):
            raise ValueError("processing_timeout must be positive")

        claimed_at = _aware_utc(
            claimed_at,
            field_name="claimed_at",
        )
        stale_before = claimed_at - processing_timeout

        return (
            select(OutboxEvent)
            .where(
                or_(
                    and_(
                        OutboxEvent.status == OutboxStatus.PENDING,
                        OutboxEvent.available_at <= claimed_at,
                        OutboxEvent.attempt_count
                        < OutboxEvent.max_attempts,
                    ),
                    and_(
                        OutboxEvent.status == OutboxStatus.PROCESSING,
                        or_(
                            OutboxEvent.locked_at.is_(None),
                            OutboxEvent.locked_at <= stale_before,
                        ),
                    ),
                )
            )
            .order_by(OutboxEvent.available_at, OutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

    def claim_next(
        self,
        *,
        worker_id: str,
        claimed_at: datetime,
    ) -> ClaimedOutboxEvent | None:
        claimed_at = _aware_utc(
            claimed_at,
            field_name="claimed_at",
        )
        normalized_worker_id = worker_id.strip()
        if not normalized_worker_id:
            raise ValueError("worker_id must not be empty")
        if len(normalized_worker_id) > 95:
            raise ValueError("worker_id must not exceed 95 characters")

        lock_token = f"{normalized_worker_id}:{uuid4().hex}"

        with self._session_factory() as session:
            with session.begin():
                while True:
                    event = session.execute(
                        self.claim_statement(
                            claimed_at,
                            processing_timeout=self._processing_timeout,
                        )
                    ).scalar_one_or_none()

                    if event is None:
                        return None

                    execution = event.execution

                    if (
                        event.status == OutboxStatus.PROCESSING
                        and event.attempt_count >= event.max_attempts
                    ):
                        event.status = OutboxStatus.FAILED
                        event.next_attempt_at = None
                        event.locked_at = None
                        event.locked_by = None
                        event.last_error = EXPIRED_CLAIM_ERROR
                        execution.status = ExecutionStatus.FAILED
                        execution.error_code = "OutboxClaimExpired"
                        execution.error_message = EXPIRED_CLAIM_ERROR
                        execution.next_retry_at = None
                        session.flush()
                        continue

                    if event.status == OutboxStatus.PROCESSING:
                        event.last_error = EXPIRED_CLAIM_ERROR

                    event.status = OutboxStatus.PROCESSING
                    event.attempt_count += 1
                    event.locked_at = claimed_at
                    event.locked_by = lock_token

                    execution.status = ExecutionStatus.DISPATCHING
                    execution.error_code = None
                    execution.error_message = None
                    execution.next_retry_at = None

                    claim = ClaimedOutboxEvent(
                        id=event.id,
                        event_id=event.event_id,
                        execution_id=event.execution_id,
                        contract_version=event.contract_version,
                        automation_type=execution.automation_type,
                        tenant_id=execution.tenant_id,
                        requested_at=execution.requested_at,
                        payload=dict(event.payload),
                        attempt_count=event.attempt_count,
                        max_attempts=event.max_attempts,
                        lock_token=lock_token,
                    )
                    break

            return claim

    def mark_published(
        self,
        claim: ClaimedOutboxEvent,
        *,
        acceptance: CommandAcceptance,
        published_at: datetime,
    ) -> None:
        published_at = _aware_utc(
            published_at,
            field_name="published_at",
        )

        with self._session_factory() as session:
            with session.begin():
                event = self._get_owned_event(session, claim)
                event.status = OutboxStatus.PUBLISHED
                event.published_at = published_at
                event.next_attempt_at = None
                event.locked_at = None
                event.locked_by = None
                event.last_error = None

                execution = event.execution
                execution.provider = acceptance.provider
                execution.status = ExecutionStatus.RUNNING
                execution.error_code = None
                execution.error_message = None
                execution.next_retry_at = None

    def mark_failed(
        self,
        claim: ClaimedOutboxEvent,
        *,
        error_code: str,
        error_message: str,
        failed_at: datetime,
        next_attempt_at: datetime | None,
    ) -> None:
        failed_at = _aware_utc(
            failed_at,
            field_name="failed_at",
        )
        if next_attempt_at is not None:
            next_attempt_at = _aware_utc(
                next_attempt_at,
                field_name="next_attempt_at",
            )

        with self._session_factory() as session:
            with session.begin():
                event = self._get_owned_event(session, claim)
                retry_scheduled = next_attempt_at is not None

                event.status = (
                    OutboxStatus.PENDING
                    if retry_scheduled
                    else OutboxStatus.FAILED
                )
                event.available_at = next_attempt_at or failed_at
                event.next_attempt_at = next_attempt_at
                event.locked_at = None
                event.locked_by = None
                event.last_error = error_message

                execution = event.execution
                execution.status = (
                    ExecutionStatus.RETRYING
                    if retry_scheduled
                    else ExecutionStatus.FAILED
                )
                execution.error_code = error_code
                execution.error_message = error_message
                execution.next_retry_at = next_attempt_at

    @staticmethod
    def _get_owned_event(
        session: Session,
        claim: ClaimedOutboxEvent,
    ) -> OutboxEvent:
        event = session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.id == claim.id,
                OutboxEvent.status == OutboxStatus.PROCESSING,
                OutboxEvent.locked_by == claim.lock_token,
            )
            .with_for_update()
        ).scalar_one_or_none()

        if event is None:
            raise OutboxClaimLostError(
                f"Outbox event {claim.event_id} is no longer owned "
                "by this worker claim"
            )

        return event


class OutboxWorker:
    def __init__(
        self,
        *,
        store: OutboxStore,
        provider: AutomationProvider,
        worker_id: str,
        callback_url: str,
        retry_base_delay: timedelta = timedelta(seconds=30),
        retry_max_delay: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if len(worker_id.strip()) > 95:
            raise ValueError("worker_id must not exceed 95 characters")
        if retry_base_delay <= timedelta(0):
            raise ValueError("retry_base_delay must be positive")
        if retry_max_delay < retry_base_delay:
            raise ValueError(
                "retry_max_delay must not be shorter than retry_base_delay"
            )

        self._store = store
        self._provider = provider
        self._worker_id = worker_id
        self._callback_url = callback_url
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def process_one(self) -> DeliveryResult:
        claim = self._store.claim_next(
            worker_id=self._worker_id,
            claimed_at=self._now(),
        )

        if claim is None:
            return DeliveryResult(status=DeliveryStatus.NO_EVENT)

        try:
            command = AutomationCommand(
                contract_version=claim.contract_version,
                execution_id=claim.execution_id,
                automation_type=claim.automation_type,
                tenant_id=claim.tenant_id,
                requested_at=claim.requested_at,
                payload=claim.payload,
                callback_url=self._callback_url,
            )
            acceptance = await self._provider.send_command(command)

            if not acceptance.accepted:
                raise RuntimeError(
                    "Automation provider did not accept the command"
                )
        except Exception as error:
            failed_at = self._now()
            error_message = self._safe_error_message(error)
            next_attempt_at = self._next_attempt_at(claim, failed_at)
            self._store.mark_failed(
                claim,
                error_code=type(error).__name__,
                error_message=error_message,
                failed_at=failed_at,
                next_attempt_at=next_attempt_at,
            )

            return DeliveryResult(
                status=(
                    DeliveryStatus.RETRY_SCHEDULED
                    if next_attempt_at is not None
                    else DeliveryStatus.FAILED
                ),
                event_id=claim.event_id,
                error=error_message,
                next_attempt_at=next_attempt_at,
            )

        published_at = self._now()
        self._store.mark_published(
            claim,
            acceptance=acceptance,
            published_at=published_at,
        )

        return DeliveryResult(
            status=DeliveryStatus.PUBLISHED,
            event_id=claim.event_id,
        )

    async def process_batch(self, *, limit: int = 100) -> list[DeliveryResult]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        results: list[DeliveryResult] = []

        for _ in range(limit):
            result = await self.process_one()

            if result.status == DeliveryStatus.NO_EVENT:
                break

            results.append(result)

        return results

    def _now(self) -> datetime:
        return _aware_utc(
            self._clock(),
            field_name="clock result",
        )

    @staticmethod
    def _safe_error_message(error: Exception) -> str:
        if isinstance(error, ProviderAuthenticationError):
            return "Automation provider authentication failed"

        if isinstance(error, ProviderTimeoutError):
            return "Automation provider request timed out"

        if isinstance(error, ProviderUnavailableError):
            return "Automation provider is unavailable"

        if isinstance(error, ProviderRejectedError):
            return (
                "Automation provider rejected the request with HTTP "
                f"{error.status_code}"
            )

        if isinstance(error, AutomationProviderError):
            return "Automation provider communication failed"

        if isinstance(error, ValidationError):
            return "Outbox event contains an invalid automation command"

        return f"{type(error).__name__} while delivering automation command"

    def _next_attempt_at(
        self,
        claim: ClaimedOutboxEvent,
        failed_at: datetime,
    ) -> datetime | None:
        if claim.attempt_count >= claim.max_attempts:
            return None

        multiplier = 2 ** (claim.attempt_count - 1)
        delay = min(
            self._retry_base_delay * multiplier,
            self._retry_max_delay,
        )
        return failed_at + delay
