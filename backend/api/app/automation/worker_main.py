import asyncio
import logging
import os
import signal
import socket
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.automation.outbox import OutboxWorker, SqlAlchemyOutboxStore
from app.automation.providers.n8n import N8nProvider
from app.automation.scheduler import (
    MAX_SCHEDULER_BATCH_SIZE,
    run_scheduler_once,
)
from app.automation.timeouts import expire_stale_executions
from app.core.n8n_config import get_n8n_settings
from app.db.session import SessionLocal


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("eos.automation.worker")


def positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))

    try:
        value = float(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number") from error

    if value <= 0:
        raise RuntimeError(f"{name} must be positive")

    return value


def positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error

    if value <= 0:
        raise RuntimeError(f"{name} must be positive")

    return value


async def wait_or_stop(
    stop_event: asyncio.Event,
    timeout_seconds: float,
) -> None:
    try:
        await asyncio.wait_for(
            stop_event.wait(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        pass


async def run_scheduler_loop(
    stop_event: asyncio.Event,
    *,
    poll_seconds: float,
    batch_size: int,
) -> None:
    logger.info(
        "Automation scheduler starting poll_seconds=%s batch_size=%s",
        poll_seconds,
        batch_size,
    )

    while not stop_event.is_set():
        try:
            result = run_scheduler_once(
                SessionLocal,
                batch_size=batch_size,
            )
            logger.info(
                "Automation scheduler pass scanned=%s claimed=%s "
                "created=%s failed=%s skipped=%s",
                result.scanned,
                result.claimed,
                result.created,
                result.failed,
                result.skipped,
            )
        except Exception:
            logger.exception("Unhandled automation scheduler pass error")

        await wait_or_stop(stop_event, poll_seconds)

    logger.info("Automation scheduler stopped")


def start_scheduler_task(
    stop_event: asyncio.Event,
    *,
    poll_seconds: float,
    batch_size: int,
) -> asyncio.Task[None]:
    return asyncio.create_task(
        run_scheduler_loop(
            stop_event,
            poll_seconds=poll_seconds,
            batch_size=batch_size,
        ),
        name="automation-scheduler",
    )


async def stop_scheduler_task(
    stop_event: asyncio.Event,
    scheduler_task: asyncio.Task[None],
) -> None:
    stop_event.set()
    scheduler_task.cancel()
    await asyncio.gather(scheduler_task, return_exceptions=True)


async def run_worker() -> None:
    poll_seconds = positive_float(
        "AUTOMATION_WORKER_POLL_SECONDS",
        1.0,
    )
    batch_limit = positive_int(
        "AUTOMATION_WORKER_BATCH_LIMIT",
        100,
    )
    processing_timeout_seconds = positive_float(
        "AUTOMATION_OUTBOX_PROCESSING_TIMEOUT_SECONDS",
        300.0,
    )
    execution_timeout_seconds = positive_float(
        "AUTOMATION_EXECUTION_TIMEOUT_SECONDS",
        300.0,
    )
    timeout_sweep_seconds = positive_float(
        "AUTOMATION_TIMEOUT_SWEEP_SECONDS",
        30.0,
    )
    timeout_sweep_limit = positive_int(
        "AUTOMATION_TIMEOUT_SWEEP_LIMIT",
        100,
    )
    scheduler_poll_seconds = positive_float(
        "AUTOMATION_SCHEDULER_POLL_SECONDS",
        1.0,
    )
    scheduler_batch_size = positive_int(
        "AUTOMATION_SCHEDULER_BATCH_SIZE",
        100,
    )
    if scheduler_batch_size > MAX_SCHEDULER_BATCH_SIZE:
        raise RuntimeError(
            "AUTOMATION_SCHEDULER_BATCH_SIZE must not exceed "
            f"{MAX_SCHEDULER_BATCH_SIZE}"
        )
    callback_url = os.getenv(
        "AUTOMATION_CALLBACK_URL",
        "http://api:8000/automation/callback",
    ).strip()

    if not callback_url:
        raise RuntimeError("AUTOMATION_CALLBACK_URL must not be empty")

    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    store = SqlAlchemyOutboxStore(
        SessionLocal,
        processing_timeout=timedelta(
            seconds=processing_timeout_seconds
        ),
    )

    logger.info(
        "Automation worker starting worker_id=%s poll_seconds=%s "
        "batch_limit=%s execution_timeout_seconds=%s "
        "timeout_sweep_seconds=%s",
        worker_id,
        poll_seconds,
        batch_limit,
        execution_timeout_seconds,
        timeout_sweep_seconds,
    )

    next_timeout_sweep = 0.0
    scheduler_task = start_scheduler_task(
        stop_event,
        poll_seconds=scheduler_poll_seconds,
        batch_size=scheduler_batch_size,
    )

    try:
        async with N8nProvider(get_n8n_settings()) as provider:
            worker = OutboxWorker(
                store=store,
                provider=provider,
                worker_id=worker_id,
                callback_url=callback_url,
            )

            while not stop_event.is_set():
                try:
                    monotonic_now = time.monotonic()

                    if monotonic_now >= next_timeout_sweep:
                        expired_ids = expire_stale_executions(
                            SessionLocal,
                            now=datetime.now(timezone.utc),
                            timeout=timedelta(
                                seconds=execution_timeout_seconds
                            ),
                            limit=timeout_sweep_limit,
                        )

                        if expired_ids:
                            logger.warning(
                                "Automation executions timed out count=%s",
                                len(expired_ids),
                            )

                        next_timeout_sweep = (
                            monotonic_now + timeout_sweep_seconds
                        )

                    results = await worker.process_batch(
                        limit=batch_limit
                    )

                    if results:
                        counts = Counter(
                            result.status.value for result in results
                        )
                        logger.info(
                            "Automation batch processed count=%s statuses=%s",
                            len(results),
                            dict(counts),
                        )
                        continue

                    await wait_or_stop(stop_event, poll_seconds)
                except Exception:
                    logger.exception(
                        "Unhandled automation worker iteration error"
                    )
                    await wait_or_stop(stop_event, poll_seconds)
    finally:
        await stop_scheduler_task(stop_event, scheduler_task)

    logger.info("Automation worker stopped")


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
