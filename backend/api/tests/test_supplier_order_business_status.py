import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.supplier_order import SupplySupplierOrderBusinessStatus
from app.supply.supplier_orders import _business_facts


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, receipts=()):
        self.receipts = list(receipts)

    def scalars(self, _statement):
        return _Scalars(self.receipts)


def _order(*, status="SENT", attempts=(), confirmations=(), documents=(), acceptances=()):
    return SimpleNamespace(
        id=uuid4(), tenant_id="test", status=status,
        planned_delivery_date=date(2026, 9, 30), delivery_attempts=list(attempts),
        confirmations=list(confirmations), supplier_documents=list(documents),
        acceptances=list(acceptances),
    )


class SupplierOrderBusinessStatusTests(unittest.TestCase):
    def status(self, order, receipts=()):
        return _business_facts(_Session(receipts), [order])[order.id]

    def test_raw_order_states_and_failed_delivery(self):
        self.assertEqual(self.status(_order(status="DRAFT"))[0], SupplySupplierOrderBusinessStatus.DRAFT)
        self.assertEqual(self.status(_order(status="READY"))[0], SupplySupplierOrderBusinessStatus.READY_TO_SEND)
        failed = SimpleNamespace(attempt_number=2, status="FAILED")
        self.assertEqual(self.status(_order(status="READY", attempts=[failed]))[0], SupplySupplierOrderBusinessStatus.SEND_FAILED)
        self.assertEqual(self.status(_order(status="CANCELLED"))[0], SupplySupplierOrderBusinessStatus.CANCELLED)

    def test_sent_lifecycle_uses_related_business_facts(self):
        order = _order()
        self.assertEqual(self.status(order)[0], SupplySupplierOrderBusinessStatus.AWAITING_SUPPLIER)

        confirmation = SimpleNamespace(
            status="RECORDED", revision_number=1, deviations=[],
        )
        order.confirmations = [confirmation]
        self.assertEqual(self.status(order)[0], SupplySupplierOrderBusinessStatus.AWAITING_DOCUMENT)

        confirmation.deviations = [SimpleNamespace(requires_decision=True, status="OPEN")]
        self.assertEqual(self.status(order)[0], SupplySupplierOrderBusinessStatus.REQUIRES_DECISION)
        confirmation.deviations = []

        order.supplier_documents = [SimpleNamespace(status="RECORDED")]
        self.assertEqual(self.status(order)[0], SupplySupplierOrderBusinessStatus.AWAITING_ACCEPTANCE)

        acceptance = SimpleNamespace(
            id=uuid4(), status="RECORDED",
            received_at=datetime(2026, 9, 25, 10, tzinfo=timezone.utc),
            accepted_at=None, recorded_at=None,
        )
        order.acceptances = [acceptance]
        status, delivery_date = self.status(order)
        self.assertEqual(status, SupplySupplierOrderBusinessStatus.AWAITING_RECEIPT)
        self.assertEqual(delivery_date, date(2026, 9, 25))

        failed_receipt = SimpleNamespace(
            supplier_acceptance_id=acceptance.id, status="FAILED", iiko_status="NEW",
        )
        self.assertEqual(self.status(order, [failed_receipt])[0], SupplySupplierOrderBusinessStatus.RECEIPT_FAILED)
        posted_receipt = SimpleNamespace(
            supplier_acceptance_id=acceptance.id, status="POSTED", iiko_status="PROCESSED",
        )
        self.assertEqual(self.status(order, [posted_receipt])[0], SupplySupplierOrderBusinessStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
