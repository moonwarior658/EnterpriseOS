import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.automation import AutomationExecution, OutboxEvent
from app.models.supply import (
    Department,
    SupplyPrintJob,
    SupplyPrintJobStatus,
    SupplyPrintPurpose,
    SupplyRequest,
    SupplyRequestDirection,
)
from app.models.user import User
from app.schemas.supply import SupplyPrintCallback
from app.supply.iiko_document_pdf import SupplyIikoPdfResult
from app.supply.iiko_document_pdf import SupplyIikoDocumentPrintError
from app.supply.printing import (
    PRODUCTION_PRINTER,
    SupplyPrintError,
    apply_supply_print_callback,
    create_supply_print_job,
    list_supply_print_jobs,
    retrieve_supply_print_job_pdf,
)
from app.supply.service import SupplyRequestNotFoundError


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class SupplyPrintingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        for table in (
            User.__table__,
            Department.__table__,
            SupplyRequestDirection.__table__,
            SupplyRequest.__table__,
        ):
            table.create(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("""
                CREATE TABLE automation_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id CHAR(32) UNIQUE NOT NULL,
                    schedule_id INTEGER,
                    contract_version VARCHAR(20) NOT NULL,
                    automation_type VARCHAR(100) NOT NULL,
                    tenant_id VARCHAR(64) NOT NULL,
                    scope_type VARCHAR(32) NOT NULL,
                    scope_id VARCHAR(64),
                    recipients JSON NOT NULL,
                    provider VARCHAR(64),
                    status VARCHAR(32) NOT NULL,
                    requested_at DATETIME NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    payload JSON NOT NULL,
                    result JSON,
                    error_code VARCHAR(100),
                    error_message TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    next_retry_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.exec_driver_sql("""
                CREATE TABLE outbox_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id CHAR(32) UNIQUE NOT NULL,
                    execution_id CHAR(32) NOT NULL,
                    event_type VARCHAR(100) NOT NULL,
                    contract_version VARCHAR(20) NOT NULL,
                    payload JSON NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 10,
                    available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    next_attempt_at DATETIME,
                    locked_at DATETIME,
                    locked_by VARCHAR(128),
                    published_at DATETIME,
                    last_error TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(execution_id) REFERENCES automation_executions(execution_id)
                )
            """)
        SupplyPrintJob.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.request_id = uuid4()
        with self.sessions.begin() as session:
            user = User(
                id=1,
                username="admin",
                display_name="Admin",
                hashed_password="unused",
                is_active=True,
                is_admin=True,
                tenant_id="eclair",
            )
            department = Department(
                id=uuid4(), tenant_id="eclair", code="M15", name="M15"
            )
            direction = SupplyRequestDirection(
                id=uuid4(), tenant_id="eclair", code="MAIN", name="Main"
            )
            session.add_all([user, department, direction])
            session.flush()
            session.add(SupplyRequest(
                id=self.request_id,
                tenant_id="eclair",
                public_number="REQ-PRINT",
                department_id=department.id,
                direction_id=direction.id,
                status="PLANNED",
                source_type="INTERNAL",
                raw_input="test",
            ))
        self.pdf = SupplyIikoPdfResult(
            content=b"%PDF-1.4\ncanonical",
            version_fingerprint="a" * 64,
        )

    def tearDown(self) -> None:
        self.engine.dispose()

    async def _create(self, *, purpose=SupplyPrintPurpose.NORMAL):
        with self.sessions() as session, patch(
            "app.supply.printing.create_iiko_documents_pdf",
            new=AsyncMock(return_value=self.pdf),
        ):
            return await create_supply_print_job(
                session,
                object(),
                tenant_id="eclair",
                request_id=self.request_id,
                requested_by_user_id=1,
                printer_name=PRODUCTION_PRINTER,
                purpose=purpose,
            )

    async def test_create_persists_fixed_contract_and_outbox_atomically(self) -> None:
        job = await self._create()
        self.assertEqual(job.copies, 2)
        self.assertEqual(job.printer_name, PRODUCTION_PRINTER)
        self.assertEqual(job.status, SupplyPrintJobStatus.QUEUED_FOR_PRINT)
        self.assertEqual(job.document_fingerprint, "a" * 64)
        self.assertEqual(len(job.pdf_fingerprint), 64)
        self.assertEqual(job.idempotency_key, job.automation_execution_id)
        with self.sessions() as session:
            execution = session.scalar(select(AutomationExecution).where(
                AutomationExecution.execution_id == job.automation_execution_id
            ))
            event_row = session.scalar(select(OutboxEvent).where(
                OutboxEvent.execution_id == job.automation_execution_id
            ))
            self.assertIsNotNone(execution)
            self.assertIsNotNone(event_row)
            self.assertEqual(event_row.payload["copies"], 2)
            self.assertNotIn("pdf", event_row.payload)

    def test_api_contract_has_no_printer_or_copies_body(self) -> None:
        from app.main import app

        paths = app.openapi()["paths"]
        create_operation = paths[
            "/supply/requests/{request_id}/print"
        ]["post"]
        self.assertNotIn("requestBody", create_operation)
        self.assertIn(
            "/supply/requests/{request_id}/print-jobs", paths
        )
        self.assertIn(
            "/supply/requests/{request_id}/print-jobs/{print_job_id}/reprint",
            paths,
        )
        self.assertIn("/supply/print-jobs/{print_job_id}/pdf", paths)
        self.assertIn("/supply/print-jobs/{print_job_id}/callback", paths)

    async def test_normal_duplicate_reuses_job_and_reprint_creates_new_key(self) -> None:
        first = await self._create()
        duplicate = await self._create()
        reprint = await self._create(purpose=SupplyPrintPurpose.REPRINT)
        self.assertEqual(duplicate.id, first.id)
        self.assertNotEqual(reprint.id, first.id)
        self.assertNotEqual(reprint.idempotency_key, first.idempotency_key)
        self.assertEqual(reprint.pdf_fingerprint, first.pdf_fingerprint)

    async def test_wrong_tenant_is_blocked_and_list_is_scoped(self) -> None:
        await self._create()
        with self.sessions() as session:
            self.assertEqual(len(list_supply_print_jobs(
                session, tenant_id="eclair", request_id=self.request_id
            )), 1)
            with self.assertRaises(SupplyRequestNotFoundError):
                list_supply_print_jobs(
                    session, tenant_id="other", request_id=self.request_id
                )

    async def test_changed_regenerated_pdf_is_blocked(self) -> None:
        job = await self._create()
        changed = SupplyIikoPdfResult(
            content=b"%PDF-1.4\nchanged",
            version_fingerprint=self.pdf.version_fingerprint,
        )
        with self.sessions() as session, patch(
            "app.supply.printing.create_iiko_documents_pdf",
            new=AsyncMock(return_value=changed),
        ):
            with self.assertRaisesRegex(SupplyPrintError, "SUPPLY_PRINT_PDF_CHANGED"):
                await retrieve_supply_print_job_pdf(session, object(), job_id=job.id)

    async def test_no_verified_documents_fails_closed_without_outbox(self) -> None:
        with self.sessions() as session, patch(
            "app.supply.printing.create_iiko_documents_pdf",
            new=AsyncMock(side_effect=SupplyIikoDocumentPrintError(
                "SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED"
            )),
        ):
            with self.assertRaisesRegex(
                SupplyPrintError, "SUPPLY_PRINT_NO_PRINTABLE_DOCUMENTS"
            ):
                await create_supply_print_job(
                    session,
                    object(),
                    tenant_id="eclair",
                    request_id=self.request_id,
                    requested_by_user_id=1,
                    printer_name=PRODUCTION_PRINTER,
                )
        with self.sessions() as session:
            self.assertEqual(session.query(SupplyPrintJob).count(), 0)
            self.assertEqual(session.query(OutboxEvent).count(), 0)

    async def test_callback_is_idempotent_and_printed_is_terminal(self) -> None:
        job = await self._create()
        now = datetime.now(timezone.utc)
        printed = SupplyPrintCallback(
            tenant_id="eclair",
            status=SupplyPrintJobStatus.PRINTED,
            attempt_count=1,
            started_at=now,
            finished_at=now,
        )
        with self.sessions() as session:
            apply_supply_print_callback(session, job_id=job.id, callback=printed)
            apply_supply_print_callback(session, job_id=job.id, callback=printed)
            late_failure = SupplyPrintCallback(
                tenant_id="eclair",
                status=SupplyPrintJobStatus.PRINT_FAILED,
                attempt_count=2,
                error_code="SUPPLY_PRINT_FAILED",
                finished_at=now,
            )
            result = apply_supply_print_callback(
                session, job_id=job.id, callback=late_failure
            )
            self.assertEqual(result.status, SupplyPrintJobStatus.PRINTED)


if __name__ == "__main__":
    unittest.main()
