import asyncio
import hashlib
import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.integrations.iiko.document_intent import (
    IikoDocumentPayloadConflictError,
    IikoDocumentReconciliationConflictError,
    IikoDocumentReconciliationOutcome,
    IikoDocumentReconciliationRequiredError,
    IikoDocumentRetryNotAllowedError,
    create_persistent_outgoing_invoice,
    reconcile_outgoing_invoice_intent,
)
from app.integrations.iiko.document_write import (
    IikoOutgoingInvoiceLineInput,
    build_controlled_outgoing_invoice,
)
from app.integrations.iiko.exceptions import (
    IikoConnectionError,
    IikoContractError,
    IikoResponseError,
)
from app.integrations.iiko.schemas import (
    IikoOutgoingInvoiceCreateResultDto,
    IikoOutgoingInvoiceDto,
    IikoOutgoingInvoiceItemDto,
)
from app.models.iiko import (
    IikoDocumentType,
    IikoDocumentWrite,
    IikoDocumentWriteStatus,
    IikoMappingStatus,
    IikoWarehouseMapping,
)
from app.models.supply import (
    Department,
    SupplyProductSourceRole,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
)
from app.models.user import User
from app.models.work_request import WorkRequest


DATE_INCOMING = datetime(
    2026,
    8,
    11,
    18,
    30,
    tzinfo=timezone(timedelta(hours=5)),
)
PRODUCT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
UNIT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def line(quantity: str = "1.250") -> IikoOutgoingInvoiceLineInput:
    return IikoOutgoingInvoiceLineInput(
        iiko_product_id=PRODUCT_ID,
        product_mapping_status=IikoMappingStatus.CONFIRMED,
        iiko_unit_id=UNIT_ID,
        quantity=Decimal(quantity),
    )


class RecordingProvider:
    def __init__(self, session_factory, *outcomes) -> None:
        self.session_factory = session_factory
        self.outcomes = list(outcomes)
        self.calls = []
        self.persisted_states = []

    async def create_outgoing_invoice(self, document):
        self.calls.append(document)
        with self.session_factory() as session:
            intent = session.scalar(select(IikoDocumentWrite).where(
                IikoDocumentWrite.iiko_document_id == document.document_id
            ))
            self.persisted_states.append(
                (intent.iiko_document_id, intent.status) if intent else None
            )
        outcome = self.outcomes.pop(0) if self.outcomes else "2709"
        if isinstance(outcome, Exception):
            raise outcome
        return IikoOutgoingInvoiceCreateResultDto(
            document_id=document.document_id,
            document_number=outcome,
            valid=True,
            warning=False,
        )


class ReconciliationProvider:
    def __init__(self, invoices=(), *, error=None, concurrent=False) -> None:
        self.invoices = list(invoices)
        self.error = error
        self.concurrent = concurrent
        self.calls = []
        self._started = 0
        self._both_started = asyncio.Event()

    async def get_outgoing_invoices(self, *, date_from, date_to):
        self.calls.append((date_from, date_to))
        if self.concurrent:
            self._started += 1
            if self._started == 2:
                self._both_started.set()
            await self._both_started.wait()
        if self.error is not None:
            raise self.error
        return self.invoices


class IikoDocumentIntentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        User.__table__.create(self.engine)
        WorkRequest.__table__.create(self.engine)
        Department.__table__.create(self.engine)
        SupplyRequestDirection.__table__.create(self.engine)
        SupplyRequestCycle.__table__.create(self.engine)
        IikoWarehouseMapping.__table__.create(self.engine)
        SupplyRequest.__table__.create(self.engine)
        IikoDocumentWrite.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.department_id = uuid4()
        self.direction_id = uuid4()
        self.request_id = uuid4()
        self.second_request_id = uuid4()
        with self.sessions.begin() as session:
            session.add(Department(
                id=self.department_id,
                tenant_id="tenant-a",
                code="М15",
                name="М15",
            ))
            session.add(SupplyRequestDirection(
                id=self.direction_id,
                tenant_id="tenant-a",
                code="MAIN",
                name="Основная",
            ))
            for request_id in (self.request_id, self.second_request_id):
                session.add(SupplyRequest(
                    id=request_id,
                    tenant_id="tenant-a",
                    public_number=f"REQ-{request_id}",
                    department_id=self.department_id,
                    direction_id=self.direction_id,
                    status="PLANNED",
                    source_type="INTERNAL",
                    raw_input="Товар 1.25",
                ))

    def tearDown(self) -> None:
        self.engine.dispose()

    async def _create(
        self,
        provider,
        *,
        request_id=None,
        lines=None,
        allow_failed_retry=False,
    ):
        with self.sessions() as session:
            return await create_persistent_outgoing_invoice(
                session,
                provider,
                supply_request_id=request_id or self.request_id,
                date_incoming=DATE_INCOMING,
                department_code="М15",
                flow=SupplyProductSourceRole.MAIN,
                lines=lines or [line()],
                allow_failed_retry=allow_failed_retry,
            )

    def _seed_reconcilable_intent(
        self,
        *,
        status=IikoDocumentWriteStatus.UNKNOWN,
        payload_hash=None,
        document_number=None,
        last_error=None,
    ):
        document = build_controlled_outgoing_invoice(
            document_id=uuid4(),
            date_incoming=DATE_INCOMING,
            department_code="М15",
            flow=SupplyProductSourceRole.MAIN,
            lines=[line()],
        )
        with self.sessions.begin() as session:
            intent = IikoDocumentWrite(
                supply_request_id=self.request_id,
                source_store_id=document.default_store_id,
                document_type=IikoDocumentType.OUTGOING_INVOICE,
                iiko_document_id=document.document_id,
                iiko_document_number=document_number,
                status=status,
                payload_hash=(
                    payload_hash
                    or hashlib.sha256(document.to_iiko_xml()).hexdigest()
                ),
                expected_payload=document.model_dump(mode="json"),
                last_error=last_error,
            )
            session.add(intent)
            session.flush()
            intent_id = intent.id
        return intent_id, document

    @staticmethod
    def _actual_invoice(document, **changes):
        values = {
            "external_id": str(document.document_id),
            "document_number": "2712",
            "date_incoming": document.date_incoming,
            "status": "NEW",
            "counteragent_id": str(document.counteragent_id),
            "default_store_id": str(document.default_store_id),
            "account_to_code": document.account_to_code,
            "revenue_account_code": document.revenue_account_code,
            "items": tuple(
                IikoOutgoingInvoiceItemDto(
                    product_id=item.product_id,
                    amount=item.amount,
                    price=Decimal(item.price),
                )
                for item in document.items
            ),
        }
        values.update(changes)
        return IikoOutgoingInvoiceDto(**values)

    async def _assert_reconciliation_conflict(self, **changes):
        intent_id, document = self._seed_reconcilable_intent()
        provider = ReconciliationProvider([
            self._actual_invoice(document, **changes)
        ])
        with self.sessions() as session:
            with self.assertRaisesRegex(
                IikoDocumentReconciliationConflictError,
                "IIKO_DOCUMENT_RECONCILIATION_CONFLICT",
            ):
                await reconcile_outgoing_invoice_intent(
                    session,
                    provider,
                    intent_id=intent_id,
                )
        with self.sessions() as session:
            intent = session.get(IikoDocumentWrite, intent_id)
            self.assertEqual(intent.status, IikoDocumentWriteStatus.UNKNOWN)
            self.assertEqual(
                intent.last_error,
                "IIKO_DOCUMENT_RECONCILIATION_CONFLICT",
            )

    async def test_unknown_found_matching_document_becomes_created(self):
        intent_id, document = self._seed_reconcilable_intent(
            last_error="IIKO_CONNECTION_ERROR"
        )
        provider = ReconciliationProvider([self._actual_invoice(document)])
        with self.sessions() as session:
            result = await reconcile_outgoing_invoice_intent(
                session, provider, intent_id=intent_id
            )
        self.assertEqual(
            result.outcome,
            IikoDocumentReconciliationOutcome.FOUND_MATCH,
        )
        self.assertEqual(result.status, IikoDocumentWriteStatus.CREATED)
        self.assertEqual(result.document_number, "2712")
        self.assertFalse(result.safe_to_retry)
        self.assertEqual(provider.calls, [(
            DATE_INCOMING.date(),
            DATE_INCOMING.date(),
        )])
        with self.sessions() as session:
            intent = session.get(IikoDocumentWrite, intent_id)
            self.assertIsNone(intent.last_error)

    async def test_pending_found_matching_document_becomes_created(self):
        intent_id, document = self._seed_reconcilable_intent(
            status=IikoDocumentWriteStatus.PENDING
        )
        provider = ReconciliationProvider([self._actual_invoice(document)])
        with self.sessions() as session:
            result = await reconcile_outgoing_invoice_intent(
                session, provider, intent_id=intent_id
            )
        self.assertEqual(result.status, IikoDocumentWriteStatus.CREATED)

    async def test_export_miss_is_uncertain_and_forbids_retry(self):
        intent_id, _ = self._seed_reconcilable_intent()
        provider = ReconciliationProvider([])
        with self.sessions() as session:
            result = await reconcile_outgoing_invoice_intent(
                session, provider, intent_id=intent_id
            )
        self.assertEqual(
            result.outcome,
            IikoDocumentReconciliationOutcome.UNCERTAIN,
        )
        self.assertFalse(result.safe_to_retry)
        with self.sessions() as session:
            intent = session.get(IikoDocumentWrite, intent_id)
            self.assertEqual(intent.status, IikoDocumentWriteStatus.UNKNOWN)

    async def test_source_store_difference_is_conflict(self):
        await self._assert_reconciliation_conflict(
            default_store_id=str(uuid4())
        )

    async def test_counteragent_difference_is_conflict(self):
        await self._assert_reconciliation_conflict(
            counteragent_id=str(uuid4())
        )

    async def test_item_product_difference_is_conflict(self):
        await self._assert_reconciliation_conflict(items=(
            IikoOutgoingInvoiceItemDto(
                product_id=uuid4(), amount=Decimal("1.250"), price=0
            ),
        ))

    async def test_item_amount_difference_is_conflict(self):
        await self._assert_reconciliation_conflict(items=(
            IikoOutgoingInvoiceItemDto(
                product_id=PRODUCT_ID, amount=Decimal("2.000"), price=0
            ),
        ))

    async def test_nonzero_price_is_conflict(self):
        await self._assert_reconciliation_conflict(items=(
            IikoOutgoingInvoiceItemDto(
                product_id=PRODUCT_ID,
                amount=Decimal("1.250"),
                price=Decimal("0.01"),
            ),
        ))

    async def test_unacceptable_iiko_status_is_conflict(self):
        await self._assert_reconciliation_conflict(status="DELETED")

    async def test_changed_payload_hash_forbids_retry(self):
        intent_id, _ = self._seed_reconcilable_intent(
            payload_hash="f" * 64
        )
        with self.sessions() as session:
            result = await reconcile_outgoing_invoice_intent(
                session,
                ReconciliationProvider([]),
                intent_id=intent_id,
            )
        self.assertFalse(result.safe_to_retry)

    async def test_transport_error_stays_unknown_and_forbids_retry(self):
        intent_id, _ = self._seed_reconcilable_intent(
            status=IikoDocumentWriteStatus.PENDING
        )
        provider = ReconciliationProvider(
            error=IikoConnectionError("IIKO_TIMEOUT")
        )
        with self.sessions() as session:
            result = await reconcile_outgoing_invoice_intent(
                session, provider, intent_id=intent_id
            )
        self.assertEqual(
            result.outcome,
            IikoDocumentReconciliationOutcome.UNCERTAIN,
        )
        self.assertEqual(result.status, IikoDocumentWriteStatus.UNKNOWN)
        self.assertFalse(result.safe_to_retry)

    async def test_created_returns_saved_result_without_get(self):
        intent_id, _ = self._seed_reconcilable_intent(
            status=IikoDocumentWriteStatus.CREATED,
            document_number="2713",
        )
        provider = ReconciliationProvider([])
        with self.sessions() as session:
            result = await reconcile_outgoing_invoice_intent(
                session, provider, intent_id=intent_id
            )
        self.assertEqual(
            result.outcome,
            IikoDocumentReconciliationOutcome.CREATED,
        )
        self.assertEqual(result.document_number, "2713")
        self.assertEqual(provider.calls, [])

    async def test_failed_reconciliation_is_not_run_by_default(self):
        intent_id, _ = self._seed_reconcilable_intent(
            status=IikoDocumentWriteStatus.FAILED
        )
        provider = ReconciliationProvider([])
        with self.sessions() as session:
            with self.assertRaisesRegex(
                IikoDocumentRetryNotAllowedError,
                "IIKO_DOCUMENT_RECONCILIATION_NOT_ALLOWED",
            ):
                await reconcile_outgoing_invoice_intent(
                    session, provider, intent_id=intent_id
                )
        self.assertEqual(provider.calls, [])

    async def test_concurrent_reconciliation_converges_on_created(self):
        intent_id, document = self._seed_reconcilable_intent()
        provider = ReconciliationProvider(
            [self._actual_invoice(document)], concurrent=True
        )

        async def reconcile_once():
            with self.sessions() as session:
                return await reconcile_outgoing_invoice_intent(
                    session, provider, intent_id=intent_id
                )

        results = await asyncio.gather(reconcile_once(), reconcile_once())
        self.assertEqual(
            {result.outcome for result in results},
            {
                IikoDocumentReconciliationOutcome.FOUND_MATCH,
                IikoDocumentReconciliationOutcome.CREATED,
            },
        )
        with self.sessions() as session:
            intent = session.get(IikoDocumentWrite, intent_id)
            self.assertEqual(intent.status, IikoDocumentWriteStatus.CREATED)
            self.assertEqual(intent.iiko_document_number, "2712")

    async def test_document_number_is_not_used_as_identity(self):
        intent_id, document = self._seed_reconcilable_intent()
        wrong_document = self._actual_invoice(
            document,
            external_id=str(uuid4()),
            document_number="same-visible-number",
        )
        provider = ReconciliationProvider([wrong_document])
        with self.sessions() as session:
            result = await reconcile_outgoing_invoice_intent(
                session, provider, intent_id=intent_id
            )
        self.assertEqual(
            result.outcome,
            IikoDocumentReconciliationOutcome.UNCERTAIN,
        )
        self.assertFalse(result.safe_to_retry)

    async def test_pending_is_committed_before_post_and_created_is_reused(
        self,
    ) -> None:
        provider = RecordingProvider(self.sessions, "2709")
        created = await self._create(provider)

        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.persisted_states, [(
            created.iiko_document_id,
            IikoDocumentWriteStatus.PENDING,
        )])
        self.assertEqual(created.status, IikoDocumentWriteStatus.CREATED)
        self.assertEqual(created.iiko_document_number, "2709")
        self.assertIsNone(created.last_error)

        with patch(
            "app.integrations.iiko.document_intent.uuid4",
            side_effect=AssertionError("repeat must not generate UUID"),
        ):
            repeated = await self._create(provider)
        self.assertEqual(repeated.id, created.id)
        self.assertEqual(repeated.iiko_document_id, created.iiko_document_id)
        self.assertEqual(repeated.iiko_document_number, "2709")
        self.assertEqual(len(provider.calls), 1)

    async def test_timeout_becomes_unknown_and_requires_reconciliation(
        self,
    ) -> None:
        provider = RecordingProvider(
            self.sessions,
            IikoConnectionError("IIKO_TIMEOUT"),
        )
        with self.assertRaises(IikoConnectionError):
            await self._create(provider)

        with self.sessions() as session:
            intent = session.scalar(select(IikoDocumentWrite))
            document_id = intent.iiko_document_id
            self.assertEqual(intent.status, IikoDocumentWriteStatus.UNKNOWN)
            self.assertEqual(intent.last_error, "IIKO_CONNECTION_ERROR")

        second_provider = RecordingProvider(self.sessions, "2710")
        with self.assertRaises(IikoDocumentReconciliationRequiredError):
            await self._create(second_provider)
        self.assertEqual(second_provider.calls, [])
        with self.sessions() as session:
            intent = session.scalar(select(IikoDocumentWrite))
            self.assertEqual(intent.iiko_document_id, document_id)

    async def test_existing_pending_requires_reconciliation_without_post(
        self,
    ) -> None:
        provider = RecordingProvider(self.sessions, "2709")
        document_id = uuid4()
        document = build_controlled_outgoing_invoice(
            document_id=document_id,
            date_incoming=DATE_INCOMING,
            department_code="М15",
            flow=SupplyProductSourceRole.MAIN,
            lines=[line()],
        )
        with self.sessions.begin() as session:
            session.add(IikoDocumentWrite(
                supply_request_id=self.request_id,
                source_store_id=document.default_store_id,
                document_type=IikoDocumentType.OUTGOING_INVOICE,
                iiko_document_id=document_id,
                status=IikoDocumentWriteStatus.PENDING,
                payload_hash=hashlib.sha256(
                    document.to_iiko_xml()
                ).hexdigest(),
            ))

        with self.assertRaises(IikoDocumentReconciliationRequiredError):
            await self._create(provider)
        self.assertEqual(provider.calls, [])

    async def test_server_validation_failure_is_failed(self) -> None:
        provider = RecordingProvider(
            self.sessions,
            IikoContractError(
                "IIKO_OUTGOING_INVOICE_VALIDATION_FAILED"
            ),
        )
        with self.assertRaises(IikoContractError):
            await self._create(provider)
        with self.sessions() as session:
            intent = session.scalar(select(IikoDocumentWrite))
            self.assertEqual(intent.status, IikoDocumentWriteStatus.FAILED)
            self.assertEqual(
                intent.last_error,
                "IIKO_OUTGOING_INVOICE_VALIDATION_FAILED",
            )

    async def test_failed_requires_explicit_retry_and_reuses_uuid(self) -> None:
        provider = RecordingProvider(self.sessions, IikoResponseError(500))
        with self.assertRaises(IikoResponseError):
            await self._create(provider)

        with self.sessions() as session:
            intent = session.scalar(select(IikoDocumentWrite))
            document_id = intent.iiko_document_id
            self.assertEqual(intent.status, IikoDocumentWriteStatus.FAILED)
            self.assertEqual(intent.last_error, "IIKO_RESPONSE_ERROR_500")

        retry_provider = RecordingProvider(self.sessions, "2711")
        with self.assertRaises(IikoDocumentRetryNotAllowedError):
            await self._create(retry_provider)
        self.assertEqual(retry_provider.calls, [])

        created = await self._create(
            retry_provider,
            allow_failed_retry=True,
        )
        self.assertEqual(created.iiko_document_id, document_id)
        self.assertEqual(created.iiko_document_number, "2711")
        self.assertEqual(created.status, IikoDocumentWriteStatus.CREATED)
        self.assertEqual(retry_provider.calls[0].document_id, document_id)

    async def test_changed_payload_is_rejected_without_post(self) -> None:
        provider = RecordingProvider(self.sessions, "2709")
        await self._create(provider)
        with self.assertRaises(IikoDocumentPayloadConflictError):
            await self._create(provider, lines=[line("2.000")])
        self.assertEqual(len(provider.calls), 1)

    def test_database_constraints_enforce_idempotency(self) -> None:
        source_store_id = uuid4()
        document_id = uuid4()
        with self.sessions.begin() as session:
            session.add(IikoDocumentWrite(
                supply_request_id=self.request_id,
                source_store_id=source_store_id,
                document_type=IikoDocumentType.OUTGOING_INVOICE,
                iiko_document_id=document_id,
                status=IikoDocumentWriteStatus.PENDING,
                payload_hash="a" * 64,
            ))

        with self.sessions() as session:
            session.add(IikoDocumentWrite(
                supply_request_id=self.request_id,
                source_store_id=source_store_id,
                document_type=IikoDocumentType.OUTGOING_INVOICE,
                iiko_document_id=uuid4(),
                status=IikoDocumentWriteStatus.PENDING,
                payload_hash="b" * 64,
            ))
            with self.assertRaises(IntegrityError):
                session.commit()

        with self.sessions() as session:
            session.add(IikoDocumentWrite(
                supply_request_id=self.second_request_id,
                source_store_id=uuid4(),
                document_type=IikoDocumentType.OUTGOING_INVOICE,
                iiko_document_id=document_id,
                status=IikoDocumentWriteStatus.PENDING,
                payload_hash="c" * 64,
            ))
            with self.assertRaises(IntegrityError):
                session.commit()


if __name__ == "__main__":
    unittest.main()
