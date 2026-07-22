import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.dialects import postgresql

from app.api.dependencies import get_current_admin
from app.automation.diagnostics import (
    build_diagnostics_snapshot,
    record_runtime_status_safely,
)
from app.automation.scheduler import SchedulerRunResult
from app.automation.worker_main import run_scheduler_loop
from app.core.n8n_config import N8nSettings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.automation import (
    AutomationRuntimeStatus,
    ExecutionStatus,
    RuntimeComponent,
)
from app.models.user import User


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, *, one=None, all=None) -> None:
        self._one = one
        self._all = all or []

    def one(self):
        return self._one

    def all(self):
        return self._all


def runtime_row(component: str, **values: object) -> AutomationRuntimeStatus:
    defaults = {
        "component_key": component,
        "heartbeat_at": None,
        "worker_id_safe": None,
        "poll_interval_seconds": None,
        "last_run_at": None,
        "scanned": None,
        "claimed": None,
        "created": None,
        "failed": None,
        "skipped": None,
        "configured": None,
        "reachable": None,
        "checked_at": None,
        "latency_ms": None,
        "safe_message": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    defaults.update(values)
    return AutomationRuntimeStatus(**defaults)


def diagnostics_session(
    *,
    stale_worker: bool = False,
    stale_scheduler: bool = False,
    stuck: int = 0,
    long_running: int = 0,
    failed_outbox: int = 0,
    error_rows: list[tuple[object, ...]] | None = None,
) -> Mock:
    session = Mock()
    worker_time = NOW - timedelta(minutes=2) if stale_worker else NOW
    scheduler_time = NOW - timedelta(minutes=2) if stale_scheduler else NOW
    runtime = [
        runtime_row(
            "worker",
            heartbeat_at=worker_time,
            worker_id_safe="worker-123456789abc",
            poll_interval_seconds=1.0,
        ),
        runtime_row(
            "scheduler",
            heartbeat_at=scheduler_time,
            last_run_at=scheduler_time,
            poll_interval_seconds=1.0,
            scanned=2,
            claimed=1,
            created=1,
            failed=0,
            skipped=1,
        ),
        runtime_row(
            "n8n",
            configured=True,
            reachable=True,
            checked_at=NOW,
            latency_ms=15,
            safe_message="n8n доступен",
        ),
    ]
    session.scalars.return_value.all.return_value = runtime
    oldest = NOW - timedelta(minutes=6) if stuck else None
    session.execute.side_effect = [
        Result(
            one=SimpleNamespace(
                pending=2,
                processing=1,
                retry_scheduled=1,
                published=10,
                failed=failed_outbox,
                oldest_pending_at=oldest,
                stuck_count=stuck,
            )
        ),
        Result(
            one=SimpleNamespace(
                pending=2,
                running=1,
                succeeded=8,
                failed=1,
                timed_out=1,
                cancelled=1,
                running_too_long_count=long_running,
            )
        ),
        Result(
            all=error_rows
            or [
                (
                    "execution_failed",
                    "AUTOMATION_FAILED",
                    3,
                    NOW - timedelta(minutes=1),
                ),
                (
                    "timeout",
                    "AUTOMATION_TIMED_OUT",
                    2,
                    NOW - timedelta(minutes=2),
                ),
            ],
        ),
    ]
    return session


class DiagnosticsSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_snapshot_is_aggregated_with_four_queries(self) -> None:
        session = diagnostics_session()
        snapshot = await build_diagnostics_snapshot(
            session,
            Mock(),
            now=NOW,
        )

        self.assertEqual(snapshot.worker_state.status, "healthy")
        self.assertEqual(snapshot.scheduler_state.status, "healthy")
        self.assertEqual(snapshot.n8n_state.status, "healthy")
        self.assertEqual(snapshot.outbox_summary.retry_scheduled, 1)
        self.assertEqual(snapshot.execution_summary.cancelled, 1)
        self.assertEqual(
            snapshot.execution_summary.recent_system_errors[0].error_code,
            "AUTOMATION_FAILED",
        )
        self.assertEqual(snapshot.alerts, [])
        self.assertEqual(session.scalars.call_count, 1)
        self.assertEqual(session.execute.call_count, 3)

    async def test_stale_and_backlog_alerts_are_formed(self) -> None:
        snapshot = await build_diagnostics_snapshot(
            diagnostics_session(
                stale_worker=True,
                stale_scheduler=True,
                stuck=4,
                long_running=2,
                failed_outbox=3,
            ),
            Mock(),
            now=NOW,
        )

        self.assertEqual(snapshot.worker_state.status, "degraded")
        self.assertEqual(snapshot.scheduler_state.status, "degraded")
        self.assertEqual(snapshot.outbox_summary.stuck_count, 4)
        self.assertEqual(snapshot.execution_summary.running_too_long_count, 2)
        self.assertEqual(
            {alert.code for alert in snapshot.alerts},
            {
                "WORKER_HEARTBEAT_STALE",
                "SCHEDULER_STALE",
                "OUTBOX_STUCK",
                "EXECUTIONS_LONG_RUNNING",
                "OUTBOX_FAILED",
            },
        )

    async def test_old_pending_in_retry_backoff_is_not_stuck(self) -> None:
        session = diagnostics_session(stuck=0)
        snapshot = await build_diagnostics_snapshot(
            session,
            Mock(),
            now=NOW,
        )

        self.assertNotIn("OUTBOX_STUCK", {a.code for a in snapshot.alerts})
        statement = session.execute.call_args_list[0].args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("outbox_events.next_attempt_at IS NULL", sql)
        self.assertIn("outbox_events.next_attempt_at <=", sql)
        self.assertIn("outbox_events.locked_at <=", sql)

    async def test_old_due_pending_is_stuck(self) -> None:
        snapshot = await build_diagnostics_snapshot(
            diagnostics_session(stuck=1),
            Mock(),
            now=NOW,
        )

        stuck_alert = next(
            alert
            for alert in snapshot.alerts
            if alert.code == "OUTBOX_STUCK"
        )
        self.assertEqual(stuck_alert.count, 1)

    async def test_distinct_safe_error_pairs_are_separate_aggregates(
        self,
    ) -> None:
        session = diagnostics_session(
            error_rows=[
                (
                    "provider_timeout",
                    "AUTOMATION_PROVIDER_TIMEOUT",
                    2,
                    NOW - timedelta(minutes=1),
                ),
                (
                    "provider_unavailable",
                    "AUTOMATION_PROVIDER_UNAVAILABLE",
                    1,
                    NOW - timedelta(minutes=2),
                ),
            ]
        )
        snapshot = await build_diagnostics_snapshot(
            session,
            Mock(),
            now=NOW,
        )

        self.assertEqual(
            {
                (item.error_category, item.error_code)
                for item in snapshot.execution_summary.recent_system_errors
            },
            {
                ("provider_timeout", "AUTOMATION_PROVIDER_TIMEOUT"),
                (
                    "provider_unavailable",
                    "AUTOMATION_PROVIDER_UNAVAILABLE",
                ),
            },
        )
        statement = session.execute.call_args_list[2].args[0]
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("GROUP BY CASE", sql)
        self.assertIn("ProviderTimeoutError", sql)
        self.assertIn("ProviderUnavailableError", sql)

    async def test_response_contract_contains_no_sensitive_fields(self) -> None:
        snapshot = await build_diagnostics_snapshot(
            diagnostics_session(stuck=1),
            Mock(),
            now=NOW,
        )
        body = snapshot.model_dump_json()

        for forbidden in (
            "webhook",
            "token",
            "payload",
            "recipients",
            "stack",
            "hostname",
        ):
            self.assertNotIn(forbidden, body.lower())

    async def test_n8n_unavailable_is_returned_without_error(self) -> None:
        session = diagnostics_session()
        runtime = session.scalars.return_value.all.return_value
        runtime.pop()

        class UnavailableProvider:
            def __init__(self, settings) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args) -> None:
                return None

            async def check_availability(self) -> bool:
                raise RuntimeError("internal response body")

        settings = N8nSettings(
            dispatch_webhook_url="https://n8n.test/webhook",
            healthcheck_url="https://n8n.test/healthz",
            service_token=SecretStr("secret"),
            timeout_seconds=10,
        )
        with (
            patch(
                "app.automation.diagnostics.get_n8n_settings",
                return_value=settings,
            ),
            patch(
                "app.automation.diagnostics.N8nProvider",
                UnavailableProvider,
            ),
            patch("app.automation.diagnostics.record_runtime_status_safely"),
        ):
            snapshot = await build_diagnostics_snapshot(
                session,
                Mock(),
                now=NOW,
            )

        self.assertEqual(snapshot.n8n_state.status, "unavailable")
        self.assertEqual(snapshot.n8n_state.safe_message, "n8n недоступен")
        self.assertIn("N8N_UNAVAILABLE", {a.code for a in snapshot.alerts})


class RuntimeHeartbeatSafetyTests(unittest.TestCase):
    def test_worker_and_scheduler_write_failures_are_swallowed(self) -> None:
        for component in (
            RuntimeComponent.WORKER,
            RuntimeComponent.SCHEDULER,
        ):
            session = Mock()
            factory = Mock(return_value=session)
            with patch(
                "app.automation.diagnostics.upsert_runtime_status",
                side_effect=RuntimeError("database unavailable"),
            ):
                record_runtime_status_safely(
                    factory,
                    component,
                    heartbeat_at=NOW,
                )
            session.rollback.assert_called_once()
            session.close.assert_called_once()


class SchedulerHeartbeatFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_heartbeat_failure_does_not_stop_scheduler(self) -> None:
        stop_event = asyncio.Event()
        passes = 0

        def run_once(*args, **kwargs):
            nonlocal passes
            passes += 1
            return SchedulerRunResult()

        async def stop_after_second_wait(event, timeout_seconds):
            if passes == 2:
                event.set()

        bad_session = Mock()
        with (
            patch(
                "app.automation.worker_main.run_scheduler_once",
                side_effect=run_once,
            ),
            patch("app.automation.worker_main.SessionLocal", return_value=bad_session),
            patch(
                "app.automation.diagnostics.upsert_runtime_status",
                side_effect=RuntimeError("database unavailable"),
            ),
            patch(
                "app.automation.worker_main.wait_or_stop",
                side_effect=stop_after_second_wait,
            ),
        ):
            await run_scheduler_loop(
                stop_event,
                poll_seconds=1,
                batch_size=10,
            )

        self.assertEqual(passes, 2)


class DiagnosticsAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        self.session = Mock()

        def override_db():
            yield self.session

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_admin_access(self) -> None:
        admin = User(
            id=1,
            username="admin",
            display_name="Administrator",
            hashed_password="unused",
            is_active=True,
            is_admin=True,
            created_at=NOW,
        )
        app.dependency_overrides[get_current_admin] = lambda: admin
        expected = asyncio.run(
            build_diagnostics_snapshot(
                diagnostics_session(),
                Mock(),
                now=NOW,
            )
        )
        with patch(
            "app.api.routes.automation.build_diagnostics_snapshot",
            return_value=expected,
        ):
            response = self.client.get("/automation/diagnostics")

        self.assertEqual(response.status_code, 200)

    def test_non_admin_gets_403(self) -> None:
        user = User(
            id=2,
            username="employee",
            display_name="Employee",
            hashed_password="unused",
            is_active=True,
            is_admin=False,
            created_at=NOW,
        )
        self.session.get.return_value = user
        response = self.client.get(
            "/automation/diagnostics",
            headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
