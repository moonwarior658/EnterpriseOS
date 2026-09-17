import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.supply import (
    SupplyAcceptanceResolution, SupplyProduct, SupplyProductCategory, SupplyProductSupplier,
    SupplyPurchaseAllocation, SupplyPurchaseRequest, SupplyPurchaseRequestLine,
    SupplySupplier, SupplySupplierAcceptance, SupplySupplierAcceptanceLine,
    SupplySupplierConfirmation, SupplySupplierConfirmationDeviation,
    SupplySupplierConfirmationLine, SupplySupplierDocument,
    SupplySupplierDocumentLine, SupplySupplierObligation, SupplySupplierOrder,
    SupplySupplierOrderLine, SupplySupplierPayment, SupplySupplierPaymentAllocation,
    SupplySupplierSettlementAdjustment, SupplyStorageZone, SupplyRequestDirection, SupplyUnit,
)
from app.models.user import User
from app.models.iiko import IikoWarehouseMapping
from app.models.supply import Department
from app.supply.procurement_cash_flow import purchase_request_cash_flow, supplier_cash_flow


class SupplyProcurementCashFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        for table in (
            User.__table__, Department.__table__, IikoWarehouseMapping.__table__,
            SupplyUnit.__table__, SupplyProductCategory.__table__,
            SupplyStorageZone.__table__, SupplyRequestDirection.__table__,
            SupplyProduct.__table__, SupplySupplier.__table__,
            SupplyProductSupplier.__table__, SupplyPurchaseRequest.__table__, SupplyPurchaseRequestLine.__table__,
            SupplyPurchaseAllocation.__table__, SupplySupplierOrder.__table__, SupplySupplierOrderLine.__table__,
            SupplySupplierConfirmation.__table__, SupplySupplierConfirmationLine.__table__,
            SupplySupplierConfirmationDeviation.__table__, SupplySupplierObligation.__table__,
            SupplySupplierDocument.__table__, SupplySupplierDocumentLine.__table__,
            SupplySupplierPayment.__table__, SupplySupplierPaymentAllocation.__table__,
            SupplySupplierSettlementAdjustment.__table__, SupplySupplierAcceptance.__table__,
            SupplySupplierAcceptanceLine.__table__, SupplyAcceptanceResolution.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.add(User(id=1, username="admin", display_name="Admin", hashed_password="x", tenant_id="t", is_active=True, is_admin=True))
            unit = SupplyUnit(tenant_id="t", code="KG", name_ru="Килограмм", short_name_ru="кг", allows_fraction=True, is_active=True)
            session.add(unit); session.flush()
            product = SupplyProduct(tenant_id="t", name="Товар", normalized_name="товар", default_unit_id=unit.id, is_active=True)
            supplier = SupplySupplier(tenant_id="t", display_name="Supplier", is_active=True)
            session.add_all([product, supplier]); session.flush()
            relation = SupplyProductSupplier(
                tenant_id="t", product_id=product.id, supplier_id=supplier.id, role="PRIMARY", priority=1,
                package_quantity=Decimal("10"), package_unit_id=unit.id,
                price_per_package=Decimal("100"), currency="RUB", is_available=True, is_active=True,
            )
            request = SupplyPurchaseRequest(tenant_id="t", number="ZR-CF-1", need_date=date.today(), status="READY", created_by_user_id=1)
            session.add_all([relation, request]); session.flush()
            request_line = SupplyPurchaseRequestLine(
                tenant_id="t", purchase_request_id=request.id, product_id=product.id,
                quantity=Decimal("10"), manual_future_quantity=Decimal("10"), unit_id=unit.id,
            )
            session.add(request_line); session.flush()
            allocation = SupplyPurchaseAllocation(
                tenant_id="t", purchase_request_line_id=request_line.id, product_supplier_id=relation.id,
                quantity_base=Decimal("10"), package_quantity_snapshot=Decimal("10"), package_unit_id_snapshot=unit.id,
                packages_count=1, price_per_package_snapshot=Decimal("100"), base_unit_price_snapshot=Decimal("10"),
                currency="RUB", planned_amount=Decimal("100"), status="CONFIRMED",
            )
            session.add(allocation); session.flush()
            order = SupplySupplierOrder(
                tenant_id="t", number="PO-CF-1", supplier_id=supplier.id, purchase_request_id=request.id,
                status="SENT", total_amount=Decimal("100"), currency="RUB", created_by_user_id=1,
                confirmed_at=now, sent_at=now,
            )
            session.add(order); session.flush()
            order_line = SupplySupplierOrderLine(
                tenant_id="t", supplier_order_id=order.id, source_allocation_id=allocation.id,
                product_id=product.id, product_name_snapshot="Товар", packages_count=1,
                package_quantity_snapshot=Decimal("10"), package_unit_id_snapshot=unit.id,
                quantity_base=Decimal("10"), price_per_package_snapshot=Decimal("100"),
                base_unit_price_snapshot=Decimal("10"), planned_amount=Decimal("100"), currency="RUB", is_active_owner=True,
            )
            session.add(order_line); session.flush()
            confirmation = SupplySupplierConfirmation(
                tenant_id="t", supplier_order_id=order.id, revision_number=1, status="RECORDED",
                response_type="PARTIALLY_CONFIRMED", responded_at=now, recorded_by_user_id=1,
                recorded_at=now, created_by_user_id=1,
            )
            session.add(confirmation); session.flush()
            confirmation_line = SupplySupplierConfirmationLine(
                tenant_id="t", confirmation_id=confirmation.id, supplier_order_line_id=order_line.id,
                response_status="CHANGED", product_name_snapshot="Товар", confirmed_packages_count=1,
                confirmed_package_quantity=Decimal("10"), confirmed_package_unit_id=unit.id,
                confirmed_quantity_base=Decimal("10"), confirmed_price_per_package=Decimal("110"),
                confirmed_planned_amount=Decimal("110"), currency="RUB",
            )
            session.add(confirmation_line); session.flush()
            session.add(SupplySupplierConfirmationDeviation(
                tenant_id="t", confirmation_id=confirmation.id, confirmation_line_id=confirmation_line.id,
                supplier_order_line_id=order_line.id, deviation_type="PRICE_CHANGED", requires_decision=True,
                status="OPEN", direction="INCREASED", baseline_price=Decimal("100"), confirmed_price=Decimal("110"),
                price_delta=Decimal("10"), price_delta_percent=Decimal("10"), baseline_amount=Decimal("100"),
                confirmed_amount=Decimal("110"), product_name_snapshot="Товар",
            ))
            obligation = SupplySupplierObligation(tenant_id="t", supplier_id=supplier.id, supplier_order_id=order.id, status="ACTIVE", created_by_user_id=1)
            session.add(obligation); session.flush()
            payable = SupplySupplierDocument(
                tenant_id="t", supplier_order_id=order.id, supplier_confirmation_id=confirmation.id,
                supplier_id=supplier.id, obligation_id=obligation.id, document_type="INVOICE", financial_role="PAYABLE",
                document_number="INV-1", document_date=date.today(), payment_due_date=date.today() - timedelta(days=1),
                status="RECORDED", supplier_display_name_snapshot="Supplier", currency="RUB", total_amount=Decimal("105"),
                recorded_by_user_id=1, recorded_at=now, created_by_user_id=1,
            )
            supporting = SupplySupplierDocument(
                tenant_id="t", supplier_order_id=order.id, supplier_confirmation_id=confirmation.id,
                supplier_id=supplier.id, document_type="DELIVERY_NOTE", financial_role="SUPPORTING",
                document_number="DN-1", document_date=date.today(), status="RECORDED",
                supplier_display_name_snapshot="Supplier", currency="RUB", total_amount=Decimal("105"),
                recorded_by_user_id=1, recorded_at=now, created_by_user_id=1,
            )
            session.add_all([payable, supporting]); session.flush()
            goods_line = SupplySupplierDocumentLine(
                tenant_id="t", supplier_document_id=payable.id, supplier_order_id=order.id,
                supplier_confirmation_id=confirmation.id, supplier_order_line_id=order_line.id,
                supplier_confirmation_line_id=confirmation_line.id, product_name_snapshot="Товар", pricing_basis="UNIT",
                package_unit_id_snapshot=unit.id, unit_name_snapshot="кг", quantity_base=Decimal("10"),
                unit_price=Decimal("10"), line_amount=Decimal("100"), currency="RUB",
            )
            service_line = SupplySupplierDocumentLine(
                tenant_id="t", supplier_document_id=payable.id, supplier_order_id=order.id,
                product_name_snapshot="Доставка", pricing_basis="FIXED_AMOUNT",
                line_amount=Decimal("5"), currency="RUB",
            )
            session.add_all([goods_line, service_line]); session.flush()
            acceptance = SupplySupplierAcceptance(
                tenant_id="t", supplier_order_id=order.id, supplier_document_id=payable.id,
                supplier_confirmation_id=confirmation.id, status="RECORDED", accepted_at=now,
                recorded_by_user_id=1, recorded_at=now, created_by_user_id=1,
            )
            session.add(acceptance); session.flush()
            acceptance_line = SupplySupplierAcceptanceLine(
                tenant_id="t", acceptance_id=acceptance.id, supplier_order_id=order.id,
                supplier_confirmation_id=confirmation.id, supplier_document_line_id=goods_line.id,
                supplier_order_line_id=order_line.id, supplier_confirmation_line_id=confirmation_line.id,
                product_name_snapshot="Товар", product_id=product.id, unit_id=unit.id, unit_name_snapshot="кг",
                documented_quantity=Decimal("10"), received_quantity=Decimal("10"), accepted_quantity=Decimal("8"),
                rejected_quantity=Decimal("2"), documented_unit_price=Decimal("10"), accepted_unit_price=Decimal("10"),
                accepted_amount=Decimal("80"), currency="RUB", rejection_reason="DAMAGED",
            )
            session.add(acceptance_line); session.flush()
            payment = SupplySupplierPayment(
                tenant_id="t", supplier_id=supplier.id, supplier_order_id=order.id,
                payment_type="PREPAYMENT", status="RECORDED", payment_date=date.today(), amount=Decimal("80"),
                currency="RUB", recorded_by_user_id=1, recorded_at=now, created_by_user_id=1,
            )
            session.add(payment); session.flush()
            session.add_all([
                SupplySupplierPaymentAllocation(
                    tenant_id="t", supplier_id=supplier.id, payment_id=payment.id,
                    supplier_document_id=payable.id, obligation_id=obligation.id,
                    amount=Decimal("70"), status="ACTIVE", created_by_user_id=1,
                ),
                SupplySupplierSettlementAdjustment(
                    tenant_id="t", supplier_id=supplier.id, supplier_payment_id=payment.id,
                    type="SUPPLIER_REFUND", amount=Decimal("5"), effective_date=date.today(),
                    status="RECORDED", created_by_user_id=1,
                ),
            ])
            self.supplier_id = supplier.id
            self.request_id = request.id
            self.acceptance_id = acceptance.id
            self.acceptance_line_id = acceptance_line.id
            self.unit_id = unit.id

    def tearDown(self):
        self.engine.dispose()

    def test_supplier_pipeline_uses_snapshots_and_canonical_settlement(self):
        with self.sessions() as session:
            result = supplier_cash_flow(
                session, self.supplier_id, tenant_id="t",
                date_from=date.today() - timedelta(days=1), date_to=date.today(),
            )
        self.assertEqual(result.planned_amount, Decimal("100.000000"))
        self.assertEqual(result.ordered_amount, Decimal("100.000000"))
        self.assertEqual(result.committed_order_amount, Decimal("100.000000"))
        self.assertEqual(result.confirmed_amount, Decimal("110.000000"))
        self.assertEqual(result.payable_documented_amount, Decimal("105.000000"))
        self.assertEqual(result.accepted_goods_amount, Decimal("80.000000"))
        self.assertEqual(result.gross_paid_amount, Decimal("80.000000"))
        self.assertEqual(result.supplier_refund_amount, Decimal("5.000000"))
        self.assertEqual(result.net_paid_amount, Decimal("75.000000"))
        self.assertEqual(result.current_debt_amount, Decimal("30.000000"))
        self.assertEqual(result.overdue_debt_amount, Decimal("35.000000"))
        self.assertEqual(result.price_deviation_open_count, 1)
        self.assertNotIn("savings", result.model_dump())

    def test_purchase_request_is_traceable_and_read_only(self):
        with self.sessions() as session:
            before = session.get(SupplyPurchaseRequest, self.request_id).lines[0].quantity
            result = purchase_request_cash_flow(session, self.request_id, tenant_id="t")
            after = session.get(SupplyPurchaseRequest, self.request_id).lines[0].quantity
        self.assertEqual(result.scope, "PURCHASE_REQUEST")
        self.assertEqual(result.gross_paid_amount, Decimal("80.000000"))
        self.assertEqual(result.payable_documented_amount, Decimal("105.000000"))
        self.assertEqual(before, after)

    def test_resolved_rejected_excess_reduces_accepted_goods_value(self):
        with self.sessions.begin() as session:
            session.add(SupplyAcceptanceResolution(
                tenant_id="t", supplier_acceptance_id=self.acceptance_id,
                acceptance_line_id=self.acceptance_line_id, issue_type="EXCESS",
                status="RESOLVED", resolution_type="REJECT_EXCESS", quantity=Decimal("2"),
                unit_id=self.unit_id, resolved_by_user_id=1, resolved_at=datetime.now(timezone.utc),
            ))
        with self.sessions() as session:
            result = supplier_cash_flow(session, self.supplier_id, tenant_id="t", date_from=None, date_to=None)
        self.assertEqual(result.accepted_goods_amount, Decimal("60.000000"))

    def test_missing_historical_acceptance_price_is_explicitly_unavailable(self):
        with self.sessions.begin() as session:
            line = session.get(SupplySupplierAcceptanceLine, self.acceptance_line_id)
            line.accepted_unit_price = None
            line.accepted_amount = None
        with self.sessions() as session:
            result = supplier_cash_flow(session, self.supplier_id, tenant_id="t", date_from=None, date_to=None)
        self.assertIsNone(result.accepted_goods_amount)
        self.assertEqual(result.accepted_goods_amount_status, "UNAVAILABLE")

    def test_empty_supplier_has_no_invented_planned_cost(self):
        with self.sessions.begin() as session:
            empty = SupplySupplier(tenant_id="t", display_name="Empty", is_active=True)
            session.add(empty); session.flush(); empty_id = empty.id
        with self.sessions() as session:
            result = supplier_cash_flow(session, empty_id, tenant_id="t", date_from=None, date_to=None)
        self.assertIsNone(result.planned_amount)
        self.assertEqual(result.planned_amount_status, "UNAVAILABLE")
        self.assertEqual(result.ordered_amount, Decimal("0.000000"))
        self.assertEqual(result.gross_paid_amount, Decimal("0.000000"))
