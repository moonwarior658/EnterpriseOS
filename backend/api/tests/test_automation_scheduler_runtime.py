import asyncio
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from app.automation.scheduler import SchedulerRunResult
from app.automation.worker_main import (
    run_scheduler_loop,
    start_scheduler_task,
    stop_scheduler_task,
)


class SchedulerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_loop_runs_pass_and_sleeps_between_passes(self) -> None:
        stop_event = asyncio.Event()

        async def stop_after_wait(
            event: asyncio.Event,
            timeout_seconds: float,
        ) -> None:
            self.assertEqual(timeout_seconds, 2.5)
            event.set()

        with (
            patch(
                "app.automation.worker_main.run_scheduler_once",
                return_value=SchedulerRunResult(created=1),
            ) as run_once,
            patch(
                "app.automation.worker_main.wait_or_stop",
                side_effect=stop_after_wait,
            ) as wait,
        ):
            await run_scheduler_loop(
                stop_event,
                poll_seconds=2.5,
                batch_size=10,
            )

        run_once.assert_called_once()
        wait.assert_awaited_once()

    async def test_pass_error_is_logged_and_loop_continues(self) -> None:
        stop_event = asyncio.Event()
        waits = 0

        async def stop_after_second_wait(
            event: asyncio.Event,
            timeout_seconds: float,
        ) -> None:
            nonlocal waits
            waits += 1
            if waits == 2:
                event.set()

        with (
            patch(
                "app.automation.worker_main.run_scheduler_once",
                side_effect=[
                    RuntimeError("database unavailable"),
                    SchedulerRunResult(),
                ],
            ) as run_once,
            patch(
                "app.automation.worker_main.wait_or_stop",
                side_effect=stop_after_second_wait,
            ),
            patch("app.automation.worker_main.logger.exception") as logged,
        ):
            await run_scheduler_loop(
                stop_event,
                poll_seconds=1.0,
                batch_size=10,
            )

        self.assertEqual(run_once.call_count, 2)
        logged.assert_called_once_with(
            "Unhandled automation scheduler pass error"
        )

    async def test_cancellation_stops_loop(self) -> None:
        stop_event = asyncio.Event()
        blocker = asyncio.Event()

        async def wait_forever(*args: object) -> None:
            await blocker.wait()

        with (
            patch(
                "app.automation.worker_main.run_scheduler_once",
                return_value=SchedulerRunResult(),
            ),
            patch(
                "app.automation.worker_main.wait_or_stop",
                side_effect=wait_forever,
            ),
        ):
            task = asyncio.create_task(
                run_scheduler_loop(
                    stop_event,
                    poll_seconds=1.0,
                    batch_size=10,
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_start_creates_one_named_task(self) -> None:
        stop_event = asyncio.Event()
        sentinel = Mock()

        with patch(
            "app.automation.worker_main.asyncio.create_task",
            return_value=sentinel,
        ) as create_task:
            result = start_scheduler_task(
                stop_event,
                poll_seconds=1.0,
                batch_size=10,
            )
            coroutine = create_task.call_args.args[0]
            coroutine.close()

        self.assertIs(result, sentinel)
        create_task.assert_called_once()
        self.assertEqual(
            create_task.call_args.kwargs["name"],
            "automation-scheduler",
        )

    async def test_shutdown_sets_stop_and_cancels_task(self) -> None:
        stop_event = asyncio.Event()
        task = asyncio.create_task(asyncio.Event().wait())

        await stop_scheduler_task(stop_event, task)

        self.assertTrue(stop_event.is_set())
        self.assertTrue(task.cancelled())


if __name__ == "__main__":
    unittest.main()
