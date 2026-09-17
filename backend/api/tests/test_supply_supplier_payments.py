import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.supply import (
    SupplyPurchaseRequest,
    SupplySupplier,
    SupplySupplierConfirmation,
    SupplySupplierDocument,
    SupplySupplierDocumentLine,
    SupplySupplierObligation,
    SupplySupplierOrder,
    SupplySupplierPayment,
    SupplySupplierPaymentAllocation,
    SupplySupplierSettlementAdjustment,
)
from app.models.user import User
from app.schemas.supplier_payment import SupplySupplierPaymentCreate, SupplySupplierPaymentUpdate
from app.supply.supplier_documents import read_document
from app.supply.supplier_payments import (
    SupplierPaymentConflictError,
    SupplierPaymentLinkError,
    SupplierPaymentStateError,
    cancel_payment,
    create_payment,
    order_prepayment_summary,
    record_payment,
    update_payment,
)


class SupplySupplierPaymentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        event.listen(
            self.engine, "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        for table in (
            User.__table__, SupplySupplier.__table__, SupplyPurchaseRequest.__table__,
            SupplySupplierOrder.__table__, SupplySupplierConfirmation.__table__,
            SupplySupplierObligation.__table__,
            SupplySupplierDocument.__table__,
            SupplySupplierDocumentLine.__table__, SupplySupplierPayment.__table__,
            SupplySupplierPaymentAllocation.__table__, SupplySupplierSettlementAdjustment.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.add_all([
                User(id=1, username="payment-admin", display_name="Payment Admin", hashed_password="x", tenant_id="payment-test", is_active=True, is_admin=True),
                User(id=2, username="other-admin", display_name="Other Admin", hashed_password="x", tenant_id="other", is_active=True, is_admin=True),
            ])
            self.supplier = SupplySupplier(tenant_id="payment-test", display_name="Main Supplier", is_active=True)
            self.other_supplier = SupplySupplier(tenant_id="payment-test", display_name="Other Supplier", is_active=True)
            session.add_all([self.supplier, self.other_supplier]); session.flush()
            request = SupplyPurchaseRequest(tenant_id="payment-test", number="ZR-PAY-1", need_date=date.today(), status="READY", created_by_user_id=1)
            session.add(request); session.flush()
            self.order = SupplySupplierOrder(
                tenant_id="payment-test", number="PO-PAY-1", supplier_id=self.supplier.id,
                purchase_request_id=request.id, status="SENT", total_amount=Decimal("100.000000"),
                currency="RUB", created_by_user_id=1, confirmed_at=now, sent_at=now,
            )
            session.add(self.order); session.flush()
            self.obligation = SupplySupplierObligation(
                tenant_id="payment-test", supplier_id=self.supplier.id,
                supplier_order_id=self.order.id, status="ACTIVE", created_by_user_id=1,
            )
            session.add(self.obligation); session.flush()
            self.document = SupplySupplierDocument(
                tenant_id="payment-test", supplier_order_id=self.order.id,
                supplier_id=self.supplier.id, document_type="INVOICE", document_number="INV-1",
                financial_role="PAYABLE", obligation_id=self.obligation.id,
                document_date=date.today(), payment_due_date=date.today() - timedelta(days=1),
                status="RECORDED", supplier_display_name_snapshot=self.supplier.display_name,
                currency="RUB", total_amount=Decimal("100.000000"), recorded_by_user_id=1,
                recorded_at=now, created_by_user_id=1,
            )
            session.add(self.document)

    def payload(self, amount: str, *, payment_type: str = "POSTPAYMENT", order_number: str | None = None):
        return SupplySupplierPaymentCreate(
            supplier_id=self.supplier.id,
            supplier_document_id=self.document.id if payment_type == "POSTPAYMENT" else None,
            supplier_order_id=self.order.id,
            payment_type=payment_type,
            payment_date=date.today(),
            amount=Decimal(amount),
            payment_order_number=order_number,
            payment_order_date=date.today() if order_number else None,
        )

    def test_prepayment_without_document_and_order_summary(self) -> None:
        with self.sessions() as session:
            payment = create_payment(session, self.payload("50", payment_type="PREPAYMENT"), tenant_id="payment-test", user_id=1)
            recorded = record_payment(session, payment.id, tenant_id="payment-test", user_id=1)
            rows = session.query(SupplySupplierPayment).all()
            summary = order_prepayment_summary(rows)
        self.assertEqual(recorded.amount, Decimal("50.000000"))
        self.assertEqual(summary.prepayment_total, Decimal("50.000000"))
        self.assertEqual(summary.unallocated_prepayment_count, 1)
        self.assertEqual(summary.unallocated_prepayment_amount, Decimal("50.000000"))

    def test_postpayment_requires_document(self) -> None:
        with self.assertRaises(ValidationError):
            SupplySupplierPaymentCreate(
                supplier_id=self.supplier.id, supplier_order_id=self.order.id,
                payment_type="POSTPAYMENT", payment_date=date.today(), amount=Decimal("1"),
            )

    def test_cross_supplier_document_is_rejected(self) -> None:
        payload = self.payload("10")
        payload.supplier_id = self.other_supplier.id
        with self.sessions() as session, self.assertRaises(SupplierPaymentLinkError):
            create_payment(session, payload, tenant_id="payment-test", user_id=1)

    def test_cross_tenant_links_are_rejected(self) -> None:
        with self.sessions() as session, self.assertRaises(SupplierPaymentLinkError):
            create_payment(session, self.payload("10"), tenant_id="other", user_id=2)

    def test_partial_paid_overpaid_and_overdue_read_model(self) -> None:
        with self.sessions() as session:
            first = create_payment(session, self.payload("30", order_number="101"), tenant_id="payment-test", user_id=1)
            record_payment(session, first.id, tenant_id="payment-test", user_id=1)
            partial = read_document(session, self.document.id, tenant_id="payment-test")
            second = create_payment(session, self.payload("70", order_number="102"), tenant_id="payment-test", user_id=1)
            record_payment(session, second.id, tenant_id="payment-test", user_id=1)
            paid = read_document(session, self.document.id, tenant_id="payment-test")
            third = create_payment(session, self.payload("5", order_number="103"), tenant_id="payment-test", user_id=1)
            record_payment(session, third.id, tenant_id="payment-test", user_id=1)
            overpaid = read_document(session, self.document.id, tenant_id="payment-test")
        self.assertEqual(partial.payment_state, "PARTIALLY_PAID")
        self.assertEqual(partial.remaining_to_pay, Decimal("70.000000"))
        self.assertEqual(partial.overdue_state, "OVERDUE")
        self.assertEqual(paid.payment_state, "PAID")
        self.assertEqual(paid.overdue_state, "SETTLED")
        self.assertEqual(overpaid.payment_state, "OVERPAID")
        self.assertEqual(overpaid.remaining_to_pay, Decimal("-5.000000"))

    def test_recorded_is_immutable_and_cannot_be_cancelled(self) -> None:
        with self.sessions() as session:
            draft = create_payment(session, self.payload("10"), tenant_id="payment-test", user_id=1)
            record_payment(session, draft.id, tenant_id="payment-test", user_id=1)
            with self.assertRaises(SupplierPaymentStateError):
                update_payment(session, draft.id, SupplySupplierPaymentUpdate(amount=Decimal("11")), tenant_id="payment-test")
            with self.assertRaises(SupplierPaymentStateError):
                cancel_payment(session, draft.id, tenant_id="payment-test")

    def test_duplicate_payment_order_is_rejected_and_cancelled_draft_releases_identity(self) -> None:
        with self.sessions() as session:
            first = create_payment(session, self.payload("10", order_number="777"), tenant_id="payment-test", user_id=1)
            with self.assertRaises(SupplierPaymentConflictError):
                create_payment(session, self.payload("10", order_number="777"), tenant_id="payment-test", user_id=1)
            cancel_payment(session, first.id, tenant_id="payment-test")
            replacement = create_payment(session, self.payload("10", order_number="777"), tenant_id="payment-test", user_id=1)
        self.assertEqual(replacement.status, "DRAFT")

    def test_nullable_due_date_has_unknown_overdue_state(self) -> None:
        with self.sessions() as session:
            document = session.get(SupplySupplierDocument, self.document.id)
            document.payment_due_date = None
            session.commit()
            result = read_document(session, self.document.id, tenant_id="payment-test")
        self.assertEqual(result.payment_state, "UNPAID")
        self.assertEqual(result.overdue_state, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
