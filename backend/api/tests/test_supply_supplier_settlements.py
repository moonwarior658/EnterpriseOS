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
    SupplyPurchaseRequest, SupplySupplier, SupplySupplierConfirmation, SupplySupplierDocument,
    SupplySupplierObligation, SupplySupplierOrder, SupplySupplierPayment,
    SupplySupplierPaymentAllocation, SupplySupplierSettlementAdjustment,
    SupplySupplierAcceptance, SupplySupplierAcceptanceLine,
)
from app.models.user import User
from app.schemas.supplier_settlement import (
    SupplySupplierPaymentAllocationCreate,
    SupplySupplierSettlementAdjustmentCreate,
)
from app.supply.supplier_settlements import (
    SupplierSettlementStateError, SupplierSettlementValidationError,
    create_adjustment, create_allocation, document_settlement,
    payment_settlement, reverse_allocation, settlement_statement,
    settlement_summary,
)


class SupplySupplierSettlementsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        for table in (
            User.__table__, SupplySupplier.__table__, SupplyPurchaseRequest.__table__,
            SupplySupplierOrder.__table__, SupplySupplierConfirmation.__table__,
            SupplySupplierObligation.__table__,
            SupplySupplierDocument.__table__, SupplySupplierPayment.__table__,
            SupplySupplierPaymentAllocation.__table__, SupplySupplierSettlementAdjustment.__table__,
            SupplySupplierAcceptance.__table__, SupplySupplierAcceptanceLine.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.add_all([
                User(id=1, username="admin", display_name="Admin", hashed_password="x", tenant_id="t", is_active=True, is_admin=True),
                User(id=2, username="other", display_name="Other", hashed_password="x", tenant_id="other", is_active=True, is_admin=True),
            ])
            self.supplier = SupplySupplier(tenant_id="t", display_name="Supplier", is_active=True)
            session.add(self.supplier); session.flush()
            request = SupplyPurchaseRequest(tenant_id="t", number="ZR-SET-1", need_date=date.today(), status="READY", created_by_user_id=1)
            session.add(request); session.flush()
            self.order = SupplySupplierOrder(
                tenant_id="t", number="PO-SET-1", supplier_id=self.supplier.id,
                purchase_request_id=request.id, status="SENT", total_amount=Decimal("200"),
                currency="RUB", created_by_user_id=1, confirmed_at=now, sent_at=now,
            )
            session.add(self.order); session.flush()
            self.obligation1 = SupplySupplierObligation(tenant_id="t", supplier_id=self.supplier.id, supplier_order_id=self.order.id, status="ACTIVE", created_by_user_id=1)
            self.obligation2 = SupplySupplierObligation(tenant_id="t", supplier_id=self.supplier.id, supplier_order_id=self.order.id, status="ACTIVE", created_by_user_id=1)
            session.add_all([self.obligation1, self.obligation2]); session.flush()
            self.document1 = self._document(self.obligation1.id, "INV-1", Decimal("100"), now)
            self.document2 = self._document(self.obligation2.id, "INV-2", Decimal("80"), now)
            session.add_all([self.document1, self.document2]); session.flush()
            self.payment1 = self._payment(Decimal("120"), now)
            self.payment2 = self._payment(Decimal("60"), now)
            session.add_all([self.payment1, self.payment2])

    def _document(self, obligation_id, number, amount, now):
        return SupplySupplierDocument(
            tenant_id="t", supplier_order_id=self.order.id, supplier_id=self.supplier.id,
            obligation_id=obligation_id, document_type="INVOICE", financial_role="PAYABLE",
            document_number=number, document_date=date.today(), payment_due_date=date.today() - timedelta(days=1),
            status="RECORDED", supplier_display_name_snapshot="Supplier", currency="RUB",
            total_amount=amount, recorded_by_user_id=1, recorded_at=now, created_by_user_id=1,
        )

    def _payment(self, amount, now):
        return SupplySupplierPayment(
            tenant_id="t", supplier_id=self.supplier.id, supplier_order_id=self.order.id,
            payment_type="PREPAYMENT", status="RECORDED", payment_date=date.today(),
            amount=amount, currency="RUB", recorded_by_user_id=1, recorded_at=now,
            created_by_user_id=1,
        )

    def allocate(self, session, payment, document, amount):
        return create_allocation(session, SupplySupplierPaymentAllocationCreate(
            payment_id=payment.id, supplier_document_id=document.id, amount=Decimal(amount),
        ), tenant_id="t", user_id=1)

    def test_many_to_many_partial_full_and_overpayment(self):
        with self.sessions() as session:
            first = self.allocate(session, self.payment1, self.document1, "70")
            self.allocate(session, self.payment1, self.document2, "50")
            self.allocate(session, self.payment2, self.document1, "40")
            doc1 = document_settlement(session, self.document1.id, tenant_id="t")
            doc2 = document_settlement(session, self.document2.id, tenant_id="t")
            pay1 = payment_settlement(session, self.payment1.id, tenant_id="t")
        self.assertEqual(doc1.payment_state, "OVERPAID")
        self.assertEqual(doc1.remaining_amount, Decimal("-10.000000"))
        self.assertEqual(doc2.payment_state, "PARTIALLY_PAID")
        self.assertEqual(pay1.available_amount, Decimal("0.000000"))

    def test_overallocation_rejected(self):
        with self.sessions() as session:
            self.allocate(session, self.payment1, self.document1, "100")
            with self.assertRaises(SupplierSettlementValidationError):
                self.allocate(session, self.payment1, self.document2, "21")

    def test_reversal_restores_totals_and_repeated_conflicts(self):
        with self.sessions() as session:
            allocation = self.allocate(session, self.payment1, self.document1, "100")
            reverse_allocation(session, allocation.id, reason="Возврат", tenant_id="t", user_id=1)
            doc = document_settlement(session, self.document1.id, tenant_id="t")
            pay = payment_settlement(session, self.payment1.id, tenant_id="t")
            with self.assertRaises(SupplierSettlementStateError):
                reverse_allocation(session, allocation.id, reason="Повтор", tenant_id="t", user_id=1)
        self.assertEqual(doc.payment_state, "UNPAID")
        self.assertEqual(pay.available_amount, Decimal("120.000000"))

    def test_partial_reversal_keeps_append_only_residual(self):
        with self.sessions() as session:
            allocation = self.allocate(session, self.payment1, self.document1, "100")
            reversed_row = reverse_allocation(
                session, allocation.id, reason="Частичный возврат", amount=Decimal("20"),
                tenant_id="t", user_id=1,
            )
            doc = document_settlement(session, self.document1.id, tenant_id="t")
            pay = payment_settlement(session, self.payment1.id, tenant_id="t")
        self.assertEqual(reversed_row.status, "REVERSED")
        self.assertEqual(reversed_row.reversed_amount, Decimal("20.000000"))
        self.assertEqual(doc.settled_amount, Decimal("80.000000"))
        self.assertEqual(doc.payment_state, "PARTIALLY_PAID")
        self.assertEqual(pay.available_amount, Decimal("40.000000"))
        self.assertEqual(len([row for row in pay.allocations if row.status == "ACTIVE"]), 1)

    def test_refund_requires_unallocated_credit(self):
        with self.sessions() as session:
            allocation = self.allocate(session, self.payment1, self.document1, "100")
            with self.assertRaises(SupplierSettlementValidationError):
                create_adjustment(session, SupplySupplierSettlementAdjustmentCreate(
                    supplier_id=self.supplier.id, supplier_payment_id=self.payment1.id,
                    type="SUPPLIER_REFUND", amount=Decimal("21"), effective_date=date.today(),
                ), tenant_id="t", user_id=1)
            reverse_allocation(session, allocation.id, reason="Освободить платёж", tenant_id="t", user_id=1)
            refund = create_adjustment(session, SupplySupplierSettlementAdjustmentCreate(
                supplier_id=self.supplier.id, supplier_payment_id=self.payment1.id,
                type="SUPPLIER_REFUND", amount=Decimal("20"), effective_date=date.today(),
            ), tenant_id="t", user_id=1)
            pay = payment_settlement(session, self.payment1.id, tenant_id="t")
        self.assertEqual(refund.amount, Decimal("20.000000"))
        self.assertEqual(pay.effective_payment_amount, Decimal("100.000000"))

    def test_balance_overdue_exceptions_and_manual_correction(self):
        with self.sessions() as session:
            self.allocate(session, self.payment1, self.document1, "100")
            create_adjustment(session, SupplySupplierSettlementAdjustmentCreate(
                supplier_id=self.supplier.id, type="MANUAL_CORRECTION",
                direction="DECREASE_DEBT", amount=Decimal("10"), effective_date=date.today(),
                comment="Скидка",
            ), tenant_id="t", user_id=1)
            result = settlement_summary(session, self.supplier.id, tenant_id="t")
        self.assertEqual(result.documented_amount, Decimal("180.000000"))
        self.assertEqual(result.running_balance, Decimal("-10.000000"))
        self.assertEqual(result.overpayment, Decimal("10.000000"))
        self.assertEqual(result.overdue_debt, Decimal("80.000000"))
        self.assertTrue(result.supply_without_payment)

    def test_unallocated_prepayment_without_document_or_acceptance_is_visible(self):
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            supplier = SupplySupplier(tenant_id="t", display_name="Advance Supplier", is_active=True)
            session.add(supplier); session.flush()
            request = SupplyPurchaseRequest(
                tenant_id="t", number="ZR-SET-ADV", need_date=date.today(),
                status="READY", created_by_user_id=1,
            )
            session.add(request); session.flush()
            order = SupplySupplierOrder(
                tenant_id="t", number="PO-SET-ADV", supplier_id=supplier.id,
                purchase_request_id=request.id, status="SENT", total_amount=Decimal("50"),
                currency="RUB", created_by_user_id=1, confirmed_at=now, sent_at=now,
            )
            session.add(order); session.flush()
            session.add(SupplySupplierPayment(
                tenant_id="t", supplier_id=supplier.id, supplier_order_id=order.id,
                payment_type="PREPAYMENT", status="RECORDED", payment_date=date.today(),
                amount=Decimal("50"), currency="RUB", recorded_by_user_id=1,
                recorded_at=now, created_by_user_id=1,
            ))
        with self.sessions() as session:
            result = settlement_summary(session, supplier.id, tenant_id="t")
        self.assertEqual(result.unallocated_prepayment_amount, Decimal("50.000000"))
        self.assertTrue(result.payment_without_supply)
        self.assertFalse(result.supply_without_payment)

    def test_statement_opening_and_zero_delta_allocation(self):
        with self.sessions() as session:
            self.allocate(session, self.payment1, self.document1, "50")
            statement = settlement_statement(
                session, self.supplier.id, tenant_id="t",
                date_from=date.today(), date_to=date.today(),
            )
        allocation_rows = [row for row in statement.movements if row.type == "PAYMENT_ALLOCATION"]
        self.assertTrue(allocation_rows)
        self.assertEqual(allocation_rows[0].balance_delta, Decimal("0.000000"))
        self.assertEqual(statement.closing_balance, Decimal("0.000000"))

    def test_cross_tenant_is_not_found(self):
        with self.sessions() as session:
            with self.assertRaises(Exception):
                create_allocation(session, SupplySupplierPaymentAllocationCreate(
                    payment_id=self.payment1.id, supplier_document_id=self.document1.id, amount=Decimal("1"),
                ), tenant_id="other", user_id=2)


if __name__ == "__main__":
    unittest.main()
