import os
import re
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.supply import read_request_iiko_documents
from app.integrations.iiko.document_routing import resolve_outgoing_invoice_route
from app.integrations.iiko.exceptions import IikoConnectionError, IikoResponseError
from app.integrations.iiko.schemas import (
    IikoOutgoingInvoiceCreateResultDto,
    IikoOutgoingInvoiceDto,
    IikoOutgoingInvoiceItemDto,
)
from app.models.iiko import (
    IikoDocumentWrite,
    IikoDocumentWriteStatus,
    IikoMappingStatus,
    IikoProductMapping,
    IikoUnitMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import (
    Department,
    LegalContour,
    SupplyDepartmentDebt,
    SupplyDepartmentDebtEvent,
    SupplyDepartmentProductCorrection,
    SupplyDepartmentProductMapping,
    SupplyDepartmentProductMappingAuditEvent,
    SupplyLineAllocation,
    SupplyProduct,
    SupplyProductAlias,
    SupplyProductCategory,
    SupplyProductSourceMapping,
    SupplyProductSourceRole,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyRequestLineDebtLink,
    SupplyStorageZone,
    SupplyUnit,
)
from app.models.user import User
from app.models.work_request import WorkRequest
from app.supply.iiko_documents import (
    SupplyInternalTransferWriteUnsupportedError,
    plan_supply_request_with_iiko_documents,
)
from app.supply.iiko_document_pdf import (
    SupplyIikoDocumentPrintError,
    SupplyIikoPrintableDocument,
    SupplyIikoPrintableLine,
    build_printable_iiko_documents,
    render_iiko_documents_pdf,
)
from app.supply.service import SupplyRequestNotFoundError


TENANT_ID = "eclair"


class RecordingProvider:
    def __init__(self, sessions, outcomes=()) -> None:
        self.sessions = sessions
        self.outcomes = list(outcomes)
        self.calls = []
        self.incoming_calls = []
        self.persisted_states = []

    async def create_outgoing_invoice(self, document):
        self.calls.append(document)
        with self.sessions() as session:
            request_status = session.scalar(select(SupplyRequest.status).where(
                SupplyRequest.id == session.scalar(
                    select(IikoDocumentWrite.supply_request_id).where(
                        IikoDocumentWrite.client_document_id
                        == document.document_id
                    )
                )
            ))
            intent_status = session.scalar(select(IikoDocumentWrite.status).where(
                IikoDocumentWrite.client_document_id == document.document_id
            ))
            self.persisted_states.append((request_status, intent_status))
        outcome = self.outcomes.pop(0) if self.outcomes else str(2700 + len(self.calls))
        if isinstance(outcome, Exception):
            raise outcome
        return IikoOutgoingInvoiceCreateResultDto(
            client_document_id=document.document_id,
            document_number=outcome,
            valid=True,
            warning=False,
        )

    async def create_incoming_invoice(self, document):
        self.incoming_calls.append(document)
        raise AssertionError("EOS must not create linked incoming invoices")


class ReadBackProvider:
    def __init__(self, invoices) -> None:
        self.invoices = invoices
        self.calls = []

    async def get_outgoing_invoices(self, *, date_from, date_to):
        self.calls.append((date_from, date_to))
        return self.invoices


class SupplyIikoDocumentWorkflowTests(unittest.IsolatedAsyncioTestCase):
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
        for table in (
            User.__table__,
            WorkRequest.__table__,
            Department.__table__,
            SupplyRequestDirection.__table__,
            SupplyRequestCycle.__table__,
            SupplyUnit.__table__,
            SupplyProductCategory.__table__,
            SupplyStorageZone.__table__,
            SupplyProduct.__table__,
            SupplyProductAlias.__table__,
            SupplyDepartmentProductMapping.__table__,
            IikoWarehouseMapping.__table__,
            IikoProductMapping.__table__,
            IikoUnitMapping.__table__,
            SupplyProductSourceMapping.__table__,
            SupplyRequest.__table__,
            SupplyRequestLine.__table__,
            SupplyDepartmentProductCorrection.__table__,
            SupplyDepartmentProductMappingAuditEvent.__table__,
            SupplyLineAllocation.__table__,
            SupplyDepartmentDebt.__table__,
            SupplyDepartmentDebtEvent.__table__,
            SupplyRequestLineDebtLink.__table__,
            IikoDocumentWrite.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.user_id = 1
        self.unit_id = uuid4()
        self.iiko_unit_id = uuid4()
        self.direction_id = uuid4()
        with self.sessions.begin() as session:
            session.add(User(
                id=self.user_id,
                username="admin",
                display_name="Администратор",
                hashed_password="unused",
                is_active=True,
                is_admin=True,
                tenant_id=TENANT_ID,
            ))
            session.add(SupplyUnit(
                id=self.unit_id,
                tenant_id=TENANT_ID,
                code="KG",
                name_ru="Килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            ))
            session.add(SupplyRequestDirection(
                id=self.direction_id,
                tenant_id=TENANT_ID,
                code="MAIN",
                name="Основной",
            ))
            session.add(IikoUnitMapping(
                tenant_id=TENANT_ID,
                iiko_unit_id=self.iiko_unit_id,
                eos_unit_id=self.unit_id,
                status=IikoMappingStatus.CONFIRMED,
                source_name="кг",
                is_deleted=False,
                reasons=[],
            ))

    def tearDown(self) -> None:
        self.engine.dispose()

    def _create_request(
        self,
        flows,
        *,
        department_code="М15",
    ) -> UUID:
        request_id = uuid4()
        with self.sessions.begin() as session:
            department = session.scalar(select(Department).where(
                Department.tenant_id == TENANT_ID,
                Department.code == department_code,
            ))
            if department is None:
                department = Department(
                    id=uuid4(),
                    tenant_id=TENANT_ID,
                    code=department_code,
                    name=department_code,
                    legal_contour=LegalContour.IP,
                )
                session.add(department)
                session.flush()
            request = SupplyRequest(
                id=request_id,
                tenant_id=TENANT_ID,
                public_number=f"REQ-{request_id}",
                department_id=department.id,
                direction_id=self.direction_id,
                status="IN_REVIEW",
                source_type="INTERNAL",
                raw_input="Тест",
            )
            session.add(request)
            source_mapping_ids = {}
            for position, flow in enumerate(flows, start=1):
                product_id = uuid4()
                product = SupplyProduct(
                    id=product_id,
                    tenant_id=TENANT_ID,
                    name=f"Товар {position}",
                    normalized_name=f"товар {position} {request_id}",
                    default_unit_id=self.unit_id,
                    request_direction_id=self.direction_id,
                )
                session.add(product)
                session.flush()
                session.add(IikoProductMapping(
                    tenant_id=TENANT_ID,
                    iiko_product_id=uuid4(),
                    eos_product_id=product_id,
                    status=IikoMappingStatus.CONFIRMED,
                    source_name=f"Товар {position}",
                    source_code=f"ART-{position}",
                    source_unit_id=self.iiko_unit_id,
                    is_deleted=False,
                    reasons=[],
                ))
                if flow not in source_mapping_ids:
                    route_department_code = (
                        department_code
                        if department_code in {"М15", "М35", "М6А"}
                        else "М15"
                    )
                    route = resolve_outgoing_invoice_route(
                        route_department_code,
                        flow,
                    )
                    warehouse = session.scalar(
                        select(IikoWarehouseMapping).where(
                            IikoWarehouseMapping.tenant_id == TENANT_ID,
                            IikoWarehouseMapping.iiko_warehouse_id
                            == route.source_store_id,
                        )
                    )
                    if warehouse is None:
                        warehouse = IikoWarehouseMapping(
                            tenant_id=TENANT_ID,
                            iiko_warehouse_id=route.source_store_id,
                            destination_type=IikoWarehouseDestinationType.SOURCE,
                            role=IikoWarehouseRole(flow.value),
                            legal_contour=LegalContour.IP,
                            status=IikoMappingStatus.CONFIRMED,
                            source_name=flow.value,
                            is_deleted=False,
                            reasons=[],
                        )
                        session.add(warehouse)
                        session.flush()
                    source_mapping_ids[flow] = warehouse.id
                session.add(SupplyProductSourceMapping(
                    tenant_id=TENANT_ID,
                    eos_product_id=product_id,
                    legal_contour=LegalContour.IP,
                    role=flow,
                    source_warehouse_mapping_id=source_mapping_ids[flow],
                    assigned_by_user_id=self.user_id,
                ))
                session.add(SupplyRequestLine(
                    tenant_id=TENANT_ID,
                    request_id=request_id,
                    position=position,
                    raw_text=f"Товар {position} 1 кг",
                    parsed_name=f"Товар {position}",
                    parsed_quantity=Decimal("1"),
                    parsed_unit_id=self.unit_id,
                    product_id=product_id,
                    requested_unit_id=self.unit_id,
                    quantity=Decimal(position),
                    send_quantity=Decimal(position),
                    match_status="MATCHED",
                    match_method="MANUAL",
                    duplicate_status="NONE",
                ))
        return request_id

    async def _plan(self, request_id, provider, *, version=1):
        with self.sessions() as session:
            return await plan_supply_request_with_iiko_documents(
                session,
                provider,
                tenant_id=TENANT_ID,
                request_id=request_id,
                expected_version=version,
                user_id=self.user_id,
                simple_mode=True,
            )

    def _writes(self, request_id):
        with self.sessions() as session:
            return list(session.scalars(
                select(IikoDocumentWrite)
                .where(IikoDocumentWrite.supply_request_id == request_id)
                .order_by(IikoDocumentWrite.source_store_id)
            ).all())

    def _confirm_read_back(self, request_id):
        invoices = []
        with self.sessions.begin() as session:
            writes = list(session.scalars(select(IikoDocumentWrite).where(
                IikoDocumentWrite.supply_request_id == request_id
            )).all())
            for write in writes:
                authoritative_id = uuid4()
                write.iiko_document_id = authoritative_id
                payload = write.expected_payload
                invoices.append(IikoOutgoingInvoiceDto(
                    external_id=str(authoritative_id),
                    document_number=write.iiko_document_number,
                    date_incoming=payload["date_incoming"],
                    status="NEW",
                    counteragent_id=payload["counteragent_id"],
                    default_store_id=payload["default_store_id"],
                    account_to_code=payload["account_to_code"],
                    revenue_account_code=payload["revenue_account_code"],
                    items=tuple(
                        IikoOutgoingInvoiceItemDto(
                            product_id=item["product_id"],
                            amount=item["amount"],
                            price=item["price"],
                        )
                        for item in payload["items"]
                    ),
                ))
        return ReadBackProvider(invoices)

    async def test_groups_one_two_and_three_flows_by_source(self):
        cases = (
            ((SupplyProductSourceRole.MAIN,), 1),
            ((SupplyProductSourceRole.MAIN, SupplyProductSourceRole.PACKAGING), 2),
            ((
                SupplyProductSourceRole.MAIN,
                SupplyProductSourceRole.PACKAGING,
                SupplyProductSourceRole.HOUSEHOLD,
            ), 3),
        )
        for flows, expected_count in cases:
            with self.subTest(flows=flows):
                request_id = self._create_request(flows)
                provider = RecordingProvider(self.sessions)
                result = await self._plan(request_id, provider)
                self.assertEqual(result.status, "PLANNED")
                self.assertEqual(len(provider.calls), expected_count)
                self.assertEqual(len(self._writes(request_id)), expected_count)

    async def test_multiple_lines_of_one_flow_create_one_document(self):
        request_id = self._create_request((
            SupplyProductSourceRole.MAIN,
            SupplyProductSourceRole.MAIN,
        ))
        provider = RecordingProvider(self.sessions)
        await self._plan(request_id, provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(provider.calls[0].items), 2)
        self.assertEqual(len(self._writes(request_id)), 1)

    async def test_all_supported_departments_create_outgoing_invoice(self):
        for department_code in ("М15", "М35", "М6А"):
            with self.subTest(department_code=department_code):
                request_id = self._create_request(
                    (SupplyProductSourceRole.MAIN,),
                    department_code=department_code,
                )
                provider = RecordingProvider(self.sessions)
                await self._plan(request_id, provider)
                self.assertEqual(len(provider.calls), 1)
                self.assertEqual(len(self._writes(request_id)), 1)

    async def test_repeat_reuses_created_intent_without_post_or_new_uuid(self):
        request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        provider = RecordingProvider(self.sessions)
        planned = await self._plan(request_id, provider)
        first = self._writes(request_id)[0]
        repeated = await self._plan(
            request_id,
            provider,
            version=planned.version,
        )
        second = self._writes(request_id)[0]
        self.assertEqual(repeated.status, "PLANNED")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(
            second.client_document_id,
            first.client_document_id,
        )
        self.assertIsNone(second.iiko_document_id)

    async def test_unknown_and_failed_never_auto_retry(self):
        cases = (
            (IikoConnectionError("timeout"), IikoDocumentWriteStatus.UNKNOWN),
            (IikoResponseError(500), IikoDocumentWriteStatus.FAILED),
        )
        for outcome, expected_status in cases:
            with self.subTest(status=expected_status):
                request_id = self._create_request((SupplyProductSourceRole.MAIN,))
                provider = RecordingProvider(self.sessions, outcomes=(outcome,))
                planned = await self._plan(request_id, provider)
                self.assertEqual(self._writes(request_id)[0].status, expected_status)
                await self._plan(request_id, provider, version=planned.version)
                self.assertEqual(len(provider.calls), 1)

    async def test_pending_never_posts_on_repeat(self):
        request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        provider = RecordingProvider(self.sessions)
        planned = await self._plan(request_id, provider)
        with self.sessions.begin() as session:
            write = session.scalar(select(IikoDocumentWrite).where(
                IikoDocumentWrite.supply_request_id == request_id
            ))
            write.status = IikoDocumentWriteStatus.PENDING
            write.iiko_document_number = None
        await self._plan(request_id, provider, version=planned.version)
        self.assertEqual(len(provider.calls), 1)

    async def test_unknown_contract_uses_operator_text_and_safe_error_code(self):
        request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        provider = RecordingProvider(
            self.sessions,
            outcomes=(IikoConnectionError("secret transport detail"),),
        )
        await self._plan(request_id, provider)
        with self.sessions() as session:
            user = session.get(User, self.user_id)
            documents = read_request_iiko_documents(request_id, session, user)
        self.assertEqual(documents[0].status, IikoDocumentWriteStatus.UNKNOWN)
        self.assertEqual(documents[0].operator_message, "Требуется проверка в iiko")
        self.assertEqual(documents[0].error_code, "IIKO_CONNECTION_ERROR")
        self.assertNotIn("secret", documents[0].error_code)

    async def test_internal_transfer_is_not_replaced_with_outgoing_invoice(self):
        request_id = self._create_request(
            (SupplyProductSourceRole.MAIN,),
            department_code="ЦЕХ",
        )
        provider = RecordingProvider(self.sessions)
        with self.assertRaises(SupplyInternalTransferWriteUnsupportedError):
            await self._plan(request_id, provider)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self._writes(request_id), [])
        with self.sessions() as session:
            self.assertEqual(session.get(SupplyRequest, request_id).status, "IN_REVIEW")

    async def test_intent_and_supply_commit_precede_post_and_no_incoming_is_created(self):
        request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        provider = RecordingProvider(self.sessions)
        await self._plan(request_id, provider)
        self.assertEqual(provider.persisted_states, [
            ("PLANNED", IikoDocumentWriteStatus.PENDING),
        ])
        self.assertEqual(provider.incoming_calls, [])
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count(IikoDocumentWrite.id))),
                1,
            )
            self.assertEqual(
                session.scalar(select(IikoDocumentWrite.document_type)),
                "OUTGOING_INVOICE",
            )

    async def test_verified_read_back_builds_one_line_pdf_from_iiko_quantity(self):
        request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        await self._plan(request_id, RecordingProvider(self.sessions))
        provider = self._confirm_read_back(request_id)
        with self.sessions.begin() as session:
            line = session.scalar(select(SupplyRequestLine).where(
                SupplyRequestLine.request_id == request_id
            ))
            line.quantity = Decimal("99")
            line.send_quantity = Decimal("99")
        with self.sessions() as session:
            documents = await build_printable_iiko_documents(
                session,
                provider,
                tenant_id=TENANT_ID,
                request_id=request_id,
            )
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].lines[0].quantity, Decimal("1"))
        self.assertEqual(documents[0].lines[0].product_name, "Товар 1")
        self.assertEqual(documents[0].lines[0].product_article, "ART-1")
        self.assertEqual(documents[0].lines[0].unit_name, "кг")
        self.assertEqual(len(documents[0].version_fingerprint), 64)
        first = render_iiko_documents_pdf(documents)
        second = render_iiko_documents_pdf(documents)
        self.assertTrue(first.content.startswith(b"%PDF-"))
        self.assertEqual(first.content, second.content)
        self.assertNotIn(b"price", first.content.lower())
        self.assertNotIn(b"vat", first.content.lower())

    async def test_verified_multi_line_invoice_keeps_read_back_order(self):
        request_id = self._create_request((
            SupplyProductSourceRole.MAIN,
            SupplyProductSourceRole.MAIN,
        ))
        await self._plan(request_id, RecordingProvider(self.sessions))
        provider = self._confirm_read_back(request_id)
        with self.sessions() as session:
            documents = await build_printable_iiko_documents(
                session,
                provider,
                tenant_id=TENANT_ID,
                request_id=request_id,
            )
        self.assertEqual(
            [line.quantity for line in documents[0].lines],
            [Decimal("1"), Decimal("2")],
        )

    def test_duplicate_product_lines_are_not_aggregated(self):
        product_id = uuid4()
        document = SupplyIikoPrintableDocument(
            document_number="2713",
            document_date=datetime(2026, 8, 12, tzinfo=timezone.utc).date(),
            document_status="NEW",
            source_store_id=uuid4(),
            source_store_name="Основной склад",
            destination_department_name="Матросова 15",
            counteragent_representation="Матросова 15",
            lines=(
                SupplyIikoPrintableLine(1, product_id, "A-1", "Молоко", Decimal("3"), "шт"),
                SupplyIikoPrintableLine(2, product_id, "A-1", "Молоко", Decimal("10"), "шт"),
            ),
            iiko_document_id=uuid4(),
            supply_request_id=uuid4(),
            flow=SupplyProductSourceRole.MAIN,
            version_fingerprint="a" * 64,
        )
        self.assertEqual(len(document.lines), 2)
        self.assertEqual(
            [line.quantity for line in document.lines],
            [Decimal("3"), Decimal("10")],
        )
        self.assertTrue(render_iiko_documents_pdf((document,)).content.startswith(b"%PDF-"))

    async def test_combined_pdf_is_flow_ordered_and_starts_each_document_on_new_page(self):
        request_id = self._create_request((
            SupplyProductSourceRole.HOUSEHOLD,
            SupplyProductSourceRole.MAIN,
            SupplyProductSourceRole.PACKAGING,
        ))
        await self._plan(request_id, RecordingProvider(self.sessions))
        provider = self._confirm_read_back(request_id)
        with self.sessions() as session:
            documents = await build_printable_iiko_documents(
                session,
                provider,
                tenant_id=TENANT_ID,
                request_id=request_id,
            )
        self.assertEqual(
            [document.flow for document in documents],
            [
                SupplyProductSourceRole.MAIN,
                SupplyProductSourceRole.PACKAGING,
                SupplyProductSourceRole.HOUSEHOLD,
            ],
        )
        result = render_iiko_documents_pdf(documents)
        page_count = len(re.findall(rb"/Type\s*/Page\b", result.content))
        self.assertEqual(page_count, 3)

    async def test_pdf_fails_closed_when_authoritative_read_back_is_missing(self):
        request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        await self._plan(request_id, RecordingProvider(self.sessions))
        self._confirm_read_back(request_id)
        with self.sessions() as session:
            with self.assertRaisesRegex(
                SupplyIikoDocumentPrintError,
                "SUPPLY_IIKO_DOCUMENT_READBACK_NOT_FOUND",
            ):
                await build_printable_iiko_documents(
                    session,
                    ReadBackProvider([]),
                    tenant_id=TENANT_ID,
                    request_id=request_id,
                )

    async def test_pdf_tenant_and_document_uuid_are_request_scoped(self):
        first_request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        second_request_id = self._create_request((SupplyProductSourceRole.MAIN,))
        await self._plan(first_request_id, RecordingProvider(self.sessions))
        await self._plan(second_request_id, RecordingProvider(self.sessions))
        second_write = self._writes(second_request_id)[0]
        with self.sessions() as session:
            with self.assertRaises(SupplyRequestNotFoundError):
                await build_printable_iiko_documents(
                    session,
                    ReadBackProvider([]),
                    tenant_id="another-tenant",
                    request_id=first_request_id,
                )
        with self.sessions() as session:
            with self.assertRaises(SupplyRequestNotFoundError):
                await build_printable_iiko_documents(
                    session,
                    ReadBackProvider([]),
                    tenant_id=TENANT_ID,
                    request_id=first_request_id,
                    document_write_id=second_write.id,
                )


if __name__ == "__main__":
    unittest.main()
