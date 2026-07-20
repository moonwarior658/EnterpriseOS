import asyncio
import logging
import os
import signal
import socket
from collections import Counter
from datetime import timedelta

from app.automation.outbox import OutboxWorker, SqlAlchemyOutboxStore
from app.automation.providers.n8n import N8nProvider
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
        "batch_limit=%s",
        worker_id,
        poll_seconds,
        batch_limit,
    )

    async with N8nProvider(get_n8n_settings()) as provider:
        worker = OutboxWorker(
            store=store,
            provider=provider,
            worker_id=worker_id,
            callback_url=callback_url,
        )

        while not stop_event.is_set():
            try:
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

    logger.info("Automation worker stopped")


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
