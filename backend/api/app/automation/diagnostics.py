import hashlib
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.automation.executions import classify_execution_status
from app.automation.providers.n8n import N8nProvider
from app.core.n8n_config import N8nSettings, get_n8n_settings
from app.models.automation import (
    AutomationExecution,
    AutomationRuntimeStatus,
    ExecutionStatus,
    OutboxEvent,
    OutboxStatus,
    RuntimeComponent,
)
from app.schemas.automation import (
    AutomationComponentState,
    AutomationDiagnosticAlert,
    AutomationDiagnosticsSnapshot,
    AutomationExecutionSummary,
    AutomationN8nState,
    AutomationOutboxSummary,
    AutomationSafeErrorSummary,
    AutomationSchedulerState,
)


logger = logging.getLogger("eos.automation.diagnostics")
MIN_HEARTBEAT_STALE_SECONDS = 30
HEARTBEAT_STALE_MULTIPLIER = 3
OUTBOX_STUCK_THRESHOLD = timedelta(minutes=5)
EXECUTION_LONG_RUNNING_THRESHOLD = timedelta(minutes=10)
N8N_CHECK_TTL = timedelta(seconds=30)
N8N_HEALTH_TIMEOUT_SECONDS = 2.0
ERROR_LOOKBACK = timedelta(hours=24)
WORKER_HEARTBEAT_INTERVAL_SECONDS = 10.0
SAFE_EXECUTION_ERROR_CODES = {
    "ProviderAuthenticationError": (
        "provider_authentication",
        "AUTOMATION_PROVIDER_AUTHENTICATION",
    ),
    "ProviderTimeoutError": (
        "provider_timeout",
        "AUTOMATION_PROVIDER_TIMEOUT",
    ),
    "ProviderUnavailableError": (
        "provider_unavailable",
        "AUTOMATION_PROVIDER_UNAVAILABLE",
    ),
    "ProviderRejectedError": (
        "provider_rejected",
        "AUTOMATION_PROVIDER_REJECTED",
    ),
    "OutboxClaimExpired": (
        "outbox_claim_expired",
        "AUTOMATION_OUTBOX_CLAIM_EXPIRED",
    ),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_worker_id(worker_id: str) -> str:
    digest = hashlib.sha256(worker_id.encode()).hexdigest()[:12]
    return f"worker-{digest}"


def upsert_runtime_status(
    session: Session,
    component: RuntimeComponent,
    **values: object,
) -> None:
    update_values = {**values, "updated_at": func.now()}
    statement = (
        insert(AutomationRuntimeStatus)
        .values(component_key=component.value, **values)
        .on_conflict_do_update(
            index_elements=[AutomationRuntimeStatus.component_key],
            set_=update_values,
        )
    )
    session.execute(statement)
    session.commit()


def record_runtime_status_safely(
    session_factory: Callable[[], Session],
    component: RuntimeComponent,
    **values: object,
) -> None:
    session = session_factory()
    try:
        upsert_runtime_status(session, component, **values)
    except Exception as error:
        session.rollback()
        logger.warning(
            "Automation runtime status write failed component=%s "
            "error_type=%s",
            component.value,
            type(error).__name__,
        )
    finally:
        session.close()


def _age_seconds(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((now - value.astimezone(timezone.utc)).total_seconds()))


def _stale_after(poll_interval: float | None) -> int:
    return max(
        MIN_HEARTBEAT_STALE_SECONDS,
        int((poll_interval or 0) * HEARTBEAT_STALE_MULTIPLIER),
    )


def _runtime_states(
    rows: dict[str, AutomationRuntimeStatus],
    now: datetime,
) -> tuple[AutomationComponentState, AutomationSchedulerState]:
    worker = rows.get(RuntimeComponent.WORKER.value)
    worker_age = _age_seconds(worker.heartbeat_at, now) if worker else None
    worker_status = "unknown"
    if worker and worker_age is not None:
        worker_status = (
            "degraded"
            if worker_age > _stale_after(worker.poll_interval_seconds)
            else "healthy"
        )
    worker_state = AutomationComponentState(
        status=worker_status,
        last_heartbeat_at=worker.heartbeat_at if worker else None,
        heartbeat_age_seconds=worker_age,
        worker_id=worker.worker_id_safe if worker else None,
        poll_interval_seconds=worker.poll_interval_seconds if worker else None,
    )

    scheduler = rows.get(RuntimeComponent.SCHEDULER.value)
    scheduler_age = _age_seconds(scheduler.last_run_at, now) if scheduler else None
    scheduler_status = "unknown"
    if scheduler and scheduler_age is not None:
        scheduler_status = (
            "degraded"
            if scheduler_age > _stale_after(scheduler.poll_interval_seconds)
            or bool(scheduler.failed)
            else "healthy"
        )
    scheduler_state = AutomationSchedulerState(
        status=scheduler_status,
        last_run_at=scheduler.last_run_at if scheduler else None,
        age_seconds=scheduler_age,
        scanned=scheduler.scanned or 0 if scheduler else 0,
        claimed=scheduler.claimed or 0 if scheduler else 0,
        created=scheduler.created or 0 if scheduler else 0,
        failed=scheduler.failed or 0 if scheduler else 0,
        skipped=scheduler.skipped or 0 if scheduler else 0,
        poll_interval_seconds=(
            scheduler.poll_interval_seconds if scheduler else None
        ),
    )
    return worker_state, scheduler_state


def _outbox_summary(session: Session, now: datetime) -> AutomationOutboxSummary:
    stuck_before = now - OUTBOX_STUCK_THRESHOLD
    active = (OutboxStatus.PENDING, OutboxStatus.PROCESSING)
    row = session.execute(
        select(
            func.count().filter(
                OutboxEvent.status == OutboxStatus.PENDING,
                or_(
                    OutboxEvent.next_attempt_at.is_(None),
                    OutboxEvent.next_attempt_at <= now,
                ),
            ).label("pending"),
            func.count().filter(
                OutboxEvent.status == OutboxStatus.PROCESSING
            ).label("processing"),
            func.count().filter(
                OutboxEvent.status == OutboxStatus.PENDING,
                OutboxEvent.next_attempt_at > now,
            ).label("retry_scheduled"),
            func.count().filter(
                OutboxEvent.status == OutboxStatus.PUBLISHED
            ).label("published"),
            func.count().filter(
                OutboxEvent.status == OutboxStatus.FAILED
            ).label("failed"),
            func.min(
                case(
                    (OutboxEvent.status.in_(active), OutboxEvent.created_at),
                    else_=None,
                )
            ).label("oldest_pending_at"),
            func.count().filter(
                or_(
                    and_(
                        OutboxEvent.status == OutboxStatus.PENDING,
                        OutboxEvent.created_at <= stuck_before,
                        or_(
                            OutboxEvent.next_attempt_at.is_(None),
                            OutboxEvent.next_attempt_at <= now,
                        ),
                    ),
                    and_(
                        OutboxEvent.status == OutboxStatus.PROCESSING,
                        OutboxEvent.locked_at.is_not(None),
                        OutboxEvent.locked_at <= stuck_before,
                    ),
                )
            ).label("stuck_count"),
        )
    ).one()
    oldest = row.oldest_pending_at
    return AutomationOutboxSummary(
        pending=row.pending,
        processing=row.processing,
        retry_scheduled=row.retry_scheduled,
        published=row.published,
        failed=row.failed,
        oldest_pending_at=oldest,
        oldest_pending_age_seconds=_age_seconds(oldest, now),
        stuck_count=row.stuck_count,
    )


def _execution_summary(
    session: Session,
    now: datetime,
) -> AutomationExecutionSummary:
    queued = (
        ExecutionStatus.PENDING,
        ExecutionStatus.DISPATCHING,
        ExecutionStatus.RETRYING,
    )
    long_before = now - EXECUTION_LONG_RUNNING_THRESHOLD
    counts = session.execute(
        select(
            func.count().filter(
                AutomationExecution.status.in_(queued)
            ).label("pending"),
            func.count().filter(
                AutomationExecution.status == ExecutionStatus.RUNNING
            ).label("running"),
            func.count().filter(
                AutomationExecution.status == ExecutionStatus.SUCCEEDED
            ).label("succeeded"),
            func.count().filter(
                AutomationExecution.status == ExecutionStatus.FAILED
            ).label("failed"),
            func.count().filter(
                AutomationExecution.status == ExecutionStatus.TIMED_OUT
            ).label("timed_out"),
            func.count().filter(
                AutomationExecution.status == ExecutionStatus.CANCELLED
            ).label("cancelled"),
            func.count().filter(
                AutomationExecution.status == ExecutionStatus.RUNNING,
                AutomationExecution.started_at <= long_before,
            ).label("running_too_long_count"),
        )
    ).one()
    safe_category = case(
        *(
            (
                and_(
                    AutomationExecution.status == ExecutionStatus.FAILED,
                    AutomationExecution.error_code == stored_code,
                ),
                public_values[0],
            )
            for stored_code, public_values in SAFE_EXECUTION_ERROR_CODES.items()
        ),
        (
            AutomationExecution.status == ExecutionStatus.FAILED,
            classify_execution_status(
                ExecutionStatus.FAILED
            ).error_category,
        ),
        (
            AutomationExecution.status == ExecutionStatus.TIMED_OUT,
            classify_execution_status(
                ExecutionStatus.TIMED_OUT
            ).error_category,
        ),
        (
            AutomationExecution.status == ExecutionStatus.CANCELLED,
            classify_execution_status(
                ExecutionStatus.CANCELLED
            ).error_category,
        ),
        else_=None,
    )
    safe_code = case(
        *(
            (
                and_(
                    AutomationExecution.status == ExecutionStatus.FAILED,
                    AutomationExecution.error_code == stored_code,
                ),
                public_values[1],
            )
            for stored_code, public_values in SAFE_EXECUTION_ERROR_CODES.items()
        ),
        (
            AutomationExecution.status == ExecutionStatus.FAILED,
            classify_execution_status(ExecutionStatus.FAILED).error_code,
        ),
        (
            AutomationExecution.status == ExecutionStatus.TIMED_OUT,
            classify_execution_status(ExecutionStatus.TIMED_OUT).error_code,
        ),
        (
            AutomationExecution.status == ExecutionStatus.CANCELLED,
            classify_execution_status(ExecutionStatus.CANCELLED).error_code,
        ),
        else_=None,
    )
    error_rows = session.execute(
        select(
            safe_category.label("error_category"),
            safe_code.label("error_code"),
            func.count().label("count"),
            func.max(AutomationExecution.finished_at).label("last_at"),
        )
        .where(
            AutomationExecution.status.in_(
                (
                    ExecutionStatus.FAILED,
                    ExecutionStatus.TIMED_OUT,
                    ExecutionStatus.CANCELLED,
                )
            ),
            AutomationExecution.finished_at >= now - ERROR_LOOKBACK,
        )
        .group_by(safe_category, safe_code)
    ).all()
    safe_errors = []
    for error_category, error_code, count, last_at in error_rows:
        if error_category and error_code and last_at:
            safe_errors.append(
                AutomationSafeErrorSummary(
                    error_category=error_category,
                    error_code=error_code,
                    count=count,
                    last_occurred_at=last_at,
                )
            )
    return AutomationExecutionSummary(
        pending=counts.pending,
        running=counts.running,
        succeeded=counts.succeeded,
        failed=counts.failed,
        timed_out=counts.timed_out,
        cancelled=counts.cancelled,
        running_too_long_count=counts.running_too_long_count,
        recent_system_errors=safe_errors,
    )


async def _n8n_state(
    cached: AutomationRuntimeStatus | None,
    now: datetime,
    session_factory: Callable[[], Session],
) -> AutomationN8nState:
    if cached and cached.checked_at:
        checked_age = _age_seconds(cached.checked_at, now)
        if (
            checked_age is not None
            and checked_age <= N8N_CHECK_TTL.total_seconds()
        ):
            return _stored_n8n_state(cached)

    configured = False
    reachable: bool | None = None
    latency_ms: int | None = None
    message = "Проверка n8n ещё не выполнена"
    try:
        settings = get_n8n_settings()
        configured = True
        health_settings = N8nSettings(
            dispatch_webhook_url=settings.dispatch_webhook_url,
            healthcheck_url=settings.healthcheck_url,
            service_token=settings.service_token,
            timeout_seconds=min(
                float(settings.timeout_seconds),
                N8N_HEALTH_TIMEOUT_SECONDS,
            ),
        )
        started = time.monotonic()
        async with N8nProvider(health_settings) as provider:
            reachable = await provider.check_availability()
        latency_ms = max(0, round((time.monotonic() - started) * 1000))
        message = "n8n доступен"
    except ValidationError:
        message = "n8n не настроен"
    except Exception:
        reachable = False
        message = "n8n недоступен"

    record_runtime_status_safely(
        session_factory,
        RuntimeComponent.N8N,
        configured=configured,
        reachable=reachable,
        checked_at=now,
        latency_ms=latency_ms,
        safe_message=message,
    )
    status = (
        "healthy"
        if configured and reachable
        else "unavailable"
        if configured and reachable is False
        else "unavailable"
        if not configured
        else "unknown"
    )
    return AutomationN8nState(
        configured=configured,
        reachable=reachable,
        checked_at=now,
        latency_ms=latency_ms,
        status=status,
        safe_message=message,
    )


def _stored_n8n_state(row: AutomationRuntimeStatus) -> AutomationN8nState:
    status = (
        "healthy"
        if row.configured and row.reachable
        else "unavailable"
        if row.configured and row.reachable is False
        else "unavailable"
        if not row.configured
        else "unknown"
    )
    return AutomationN8nState(
        configured=bool(row.configured),
        reachable=row.reachable,
        checked_at=row.checked_at,
        latency_ms=row.latency_ms,
        status=status,
        safe_message=row.safe_message or "Состояние n8n неизвестно",
    )


def _alerts(
    now: datetime,
    worker: AutomationComponentState,
    scheduler: AutomationSchedulerState,
    n8n: AutomationN8nState,
    outbox: AutomationOutboxSummary,
    executions: AutomationExecutionSummary,
) -> list[AutomationDiagnosticAlert]:
    alerts: list[AutomationDiagnosticAlert] = []

    def add(
        code: str,
        severity: str,
        title: str,
        message: str,
        count: int = 1,
    ) -> None:
        alerts.append(
            AutomationDiagnosticAlert(
                code=code,
                severity=severity,
                title=title,
                safe_message=message,
                count=count,
                detected_at=now,
            )
        )

    if worker.status == "degraded":
        add(
            "WORKER_HEARTBEAT_STALE",
            "critical",
            "Worker не отвечает",
            "Heartbeat worker устарел",
        )
    if scheduler.status == "degraded":
        add(
            "SCHEDULER_STALE",
            "warning",
            "Scheduler требует внимания",
            "Последний проход scheduler устарел или завершился "
            "с ошибкой",
        )
    if n8n.status == "unavailable":
        add(
            "N8N_UNAVAILABLE",
            "critical",
            "n8n недоступен",
            "Проверка доступности n8n завершилась "
            "неуспешно",
        )
    if outbox.stuck_count:
        add(
            "OUTBOX_STUCK",
            "critical",
            "События застряли в outbox",
            "Есть события, ожидающие обработки дольше "
            "допустимого",
            outbox.stuck_count,
        )
    if executions.running_too_long_count:
        add(
            "EXECUTIONS_LONG_RUNNING",
            "warning",
            "Длительные запуски",
            "Есть запуски, выполняющиеся дольше "
            "допустимого",
            executions.running_too_long_count,
        )
    if outbox.failed:
        add(
            "OUTBOX_FAILED",
            "critical",
            "Ошибки доставки",
            "Есть события outbox с окончательной "
            "ошибкой",
            outbox.failed,
        )
    return alerts


async def build_diagnostics_snapshot(
    session: Session,
    session_factory: Callable[[], Session],
    *,
    now: datetime | None = None,
) -> AutomationDiagnosticsSnapshot:
    generated_at = now or utc_now()
    runtime_rows = {
        row.component_key: row
        for row in session.scalars(select(AutomationRuntimeStatus)).all()
    }
    worker, scheduler = _runtime_states(runtime_rows, generated_at)
    outbox = _outbox_summary(session, generated_at)
    executions = _execution_summary(session, generated_at)
    n8n = await _n8n_state(
        runtime_rows.get(RuntimeComponent.N8N.value),
        generated_at,
        session_factory,
    )
    return AutomationDiagnosticsSnapshot(
        generated_at=generated_at,
        worker_state=worker,
        scheduler_state=scheduler,
        n8n_state=n8n,
        outbox_summary=outbox,
        execution_summary=executions,
        alerts=_alerts(
            generated_at,
            worker,
            scheduler,
            n8n,
            outbox,
            executions,
        ),
    )
