import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.supply.incoming_receipt_readiness import (
    AcceptanceReceiptReadinessStatus,
    ReceiptLineClassification,
    ReceiptLineReadinessInput,
    ReceiptLineStatus,
    ReceiptReadinessReason,
    allocate_document_line_amount,
    build_incoming_invoice_preview,
    evaluate_acceptance_receipt,
    evaluate_receipt_line,
)


SUPPLIER_ID = UUID("11111111-1111-4111-8111-111111111111")
STORE_ID = UUID("22222222-2222-4222-8222-222222222222")
PRODUCT_ID = UUID("33333333-3333-4333-8333-333333333333")
UNIT_ID = UUID("44444444-4444-4444-8444-444444444444")


def ready_input(**changes: object) -> ReceiptLineReadinessInput:
    values: dict[str, object] = {
        "line_id": uuid4(),
        "physical_line": True,
        "receipt_eligible_quantity": Decimal("10.000000"),
        "unresolved_excess": False,
        "pricing_basis": "UNIT",
        "supplier_document_line_id": uuid4(),
        "document_quantity": Decimal("10.000000"),
        "historical_unit_price": Decimal("12.345678"),
        "historical_line_sum": Decimal("123.456780"),
        "iiko_supplier_id": SUPPLIER_ID,
        "supplier_mapping_confirmed": True,
        "supplier_reference_current": True,
        "iiko_store_id": STORE_ID,
        "store_mapping_confirmed": True,
        "iiko_product_id": PRODUCT_ID,
        "product_mapping_confirmed": True,
        "iiko_unit_id": UNIT_ID,
        "unit_mapping_confirmed": True,
        "product_main_unit_id": UNIT_ID,
        "vat_omission_safe": True,
    }
    values.update(changes)
    return ReceiptLineReadinessInput(**values)


class ReceiptLineReadinessTests(unittest.TestCase):
    def test_ready_base_unit_uses_only_historical_document_fact(self) -> None:
        result = evaluate_receipt_line(ready_input())

        self.assertEqual(result.status, ReceiptLineStatus.READY)
        self.assertEqual(
            result.classification,
            ReceiptLineClassification.BASE_UNIT_SAFE,
        )
        self.assertEqual(result.contract.product_id, PRODUCT_ID)
        self.assertEqual(result.contract.amount, Decimal("10.000000"))
        self.assertEqual(result.contract.amount_unit_id, UNIT_ID)
        self.assertIsNone(result.contract.container_id)
        self.assertEqual(result.contract.price, Decimal("12.345678"))
        self.assertEqual(result.contract.sum_amount, Decimal("123.456780"))
        self.assertIsNone(result.contract.vat_percent)
        self.assertIsNone(result.contract.vat_sum)
        self.assertEqual(result.contract.store_id, STORE_ID)
        self.assertEqual(result.contract.supplier_id, SUPPLIER_ID)

    def test_mapping_and_unit_failures_are_explicit(self) -> None:
        cases = (
            (
                {"product_mapping_confirmed": False},
                ReceiptReadinessReason.PRODUCT_MAPPING_MISSING,
            ),
            (
                {"unit_mapping_confirmed": False},
                ReceiptReadinessReason.UNIT_MAPPING_MISSING,
            ),
            (
                {"product_main_unit_id": None},
                ReceiptReadinessReason.PRODUCT_MAIN_UNIT_MISSING,
            ),
            (
                {"product_main_unit_id": uuid4()},
                ReceiptReadinessReason.UNIT_NOT_MAIN,
            ),
            (
                {"supplier_mapping_confirmed": False},
                ReceiptReadinessReason.SUPPLIER_MAPPING_MISSING,
            ),
            (
                {"supplier_reference_current": False},
                ReceiptReadinessReason.SUPPLIER_MAPPING_STALE,
            ),
            (
                {"store_mapping_confirmed": False},
                ReceiptReadinessReason.STORE_MAPPING_MISSING,
            ),
        )
        for changes, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate_receipt_line(ready_input(**changes))
                self.assertEqual(result.status, ReceiptLineStatus.BLOCKED)
                self.assertIn(reason, result.reason_codes)

    def test_package_basis_is_safe_with_document_quantity_and_amount(self) -> None:
        result = evaluate_receipt_line(ready_input(pricing_basis="PACKAGE"))
        self.assertEqual(result.status, ReceiptLineStatus.READY)
        self.assertEqual(result.classification, ReceiptLineClassification.BASE_UNIT_SAFE)
        self.assertEqual(result.contract.sum_amount, Decimal("123.456780"))

    def test_documentless_and_order_price_fallback_are_blocked(self) -> None:
        for changes in (
            {"supplier_document_line_id": None},
            {"historical_unit_price": None},
            {"historical_line_sum": None},
        ):
            with self.subTest(changes=changes):
                result = evaluate_receipt_line(ready_input(**changes))
                self.assertIn(
                    ReceiptReadinessReason.HISTORICAL_PRICE_MISSING,
                    result.reason_codes,
                )
                self.assertIsNone(result.contract)

    def test_partial_acceptance_uses_document_amount_not_price_equation(self) -> None:
        result = evaluate_receipt_line(ready_input(
            receipt_eligible_quantity=Decimal("6"),
            historical_unit_price=Decimal("9.99"),
            historical_line_sum=Decimal("100.01"),
        ))
        self.assertEqual(result.status, ReceiptLineStatus.READY)
        self.assertEqual(result.contract.price, Decimal("9.99"))
        self.assertEqual(result.contract.sum_amount, Decimal("60.006000"))

    def test_prior_accounting_facts_are_required_when_unknown(self) -> None:
        result = evaluate_receipt_line(ready_input(
            receipt_eligible_quantity=Decimal("4"),
            previously_accounted_quantity=None,
            previously_accounted_amount=None,
        ))
        self.assertIn(
            ReceiptReadinessReason.PRIOR_ACCOUNTING_FACTS_REQUIRED,
            result.reason_codes,
        )

    def test_excess_requires_separate_commercial_source(self) -> None:
        result = evaluate_receipt_line(ready_input(
            receipt_eligible_quantity=Decimal("11"),
        ))
        self.assertIn(
            ReceiptReadinessReason.EXCESS_PRICE_SOURCE_MISSING,
            result.reason_codes,
        )
        self.assertIsNone(result.contract)

    def test_unresolved_excess_and_zero_quantity_are_blocked(self) -> None:
        unresolved = evaluate_receipt_line(ready_input(
            receipt_eligible_quantity=None,
            unresolved_excess=True,
        ))
        zero = evaluate_receipt_line(ready_input(
            receipt_eligible_quantity=Decimal("0"),
        ))
        self.assertIn(
            ReceiptReadinessReason.UNRESOLVED_EXCESS,
            unresolved.reason_codes,
        )
        self.assertIn(
            ReceiptReadinessReason.NO_RECEIPT_ELIGIBLE_QUANTITY,
            zero.reason_codes,
        )

    def test_fixed_amount_service_is_excluded(self) -> None:
        result = evaluate_receipt_line(ready_input(
            physical_line=False,
            pricing_basis="FIXED_AMOUNT",
        ))
        self.assertEqual(result.status, ReceiptLineStatus.EXCLUDED)
        self.assertIn(
            ReceiptReadinessReason.FIXED_AMOUNT_NOT_PHYSICAL,
            result.reason_codes,
        )

        physical = evaluate_receipt_line(ready_input(
            pricing_basis="FIXED_AMOUNT",
        ))
        self.assertEqual(physical.status, ReceiptLineStatus.BLOCKED)
        self.assertIn(
            ReceiptReadinessReason.FIXED_AMOUNT_NOT_PHYSICAL,
            physical.reason_codes,
        )

    def test_vat_is_blocked_when_product_card_fallback_is_not_safe(self) -> None:
        result = evaluate_receipt_line(ready_input(vat_omission_safe=False))
        self.assertIn(ReceiptReadinessReason.VAT_MISSING, result.reason_codes)


class AcceptanceReceiptReadinessTests(unittest.TestCase):
    def test_all_positive_physical_lines_must_be_ready(self) -> None:
        first = ready_input()
        second = replace(first, line_id=uuid4())
        result = evaluate_acceptance_receipt((first, second))
        self.assertEqual(result.status, AcceptanceReceiptReadinessStatus.READY)
        self.assertEqual(result.total_physical_lines, 2)
        self.assertEqual(result.ready_lines, 2)
        self.assertEqual(result.blocked_lines, 0)
        self.assertTrue(result.receipt_preview_ready)

    def test_one_blocked_line_is_only_diagnostically_partial(self) -> None:
        ready = ready_input()
        blocked = replace(
            ready,
            line_id=uuid4(),
            product_mapping_confirmed=False,
        )
        result = evaluate_acceptance_receipt((ready, blocked))
        self.assertEqual(
            result.status,
            AcceptanceReceiptReadinessStatus.PARTIALLY_READY,
        )
        self.assertEqual(result.ready_lines, 1)
        self.assertEqual(result.blocked_lines, 1)
        self.assertFalse(result.receipt_preview_ready)
        self.assertIn(
            ReceiptReadinessReason.PRODUCT_MAPPING_MISSING,
            result.reason_codes,
        )

    def test_only_excluded_service_lines_do_not_make_acceptance_ready(self) -> None:
        service = ready_input(
            physical_line=False,
            pricing_basis="FIXED_AMOUNT",
        )
        result = evaluate_acceptance_receipt((service,))
        self.assertEqual(
            result.status,
            AcceptanceReceiptReadinessStatus.BLOCKED,
        )
        self.assertEqual(result.total_physical_lines, 0)
        self.assertEqual(result.excluded_lines, 1)


class DocumentLineAmountAllocationTests(unittest.TestCase):
    def allocate(
        self,
        current: str,
        *,
        previous_quantity: str = "0",
        previous_amount: str = "0",
        line_amount: str = "100.01",
    ):
        return allocate_document_line_amount(
            document_quantity=Decimal("10"),
            document_line_amount=Decimal(line_amount),
            current_receipt_quantity=Decimal(current),
            previously_accounted_quantity=Decimal(previous_quantity),
            previously_accounted_amount=Decimal(previous_amount),
        )

    def test_full_line_receives_exact_document_amount(self) -> None:
        result = self.allocate("10")
        self.assertEqual(result.current_sum, Decimal("100.010000"))
        self.assertEqual(result.cumulative_sum, Decimal("100.010000"))
        self.assertEqual(result.remaining_amount, Decimal("0.000000"))

    def test_first_partial_and_final_residual_close_exactly(self) -> None:
        first = self.allocate("6")
        second = self.allocate(
            "4",
            previous_quantity="6",
            previous_amount=str(first.cumulative_sum),
        )
        self.assertEqual(first.current_sum, Decimal("60.006000"))
        self.assertEqual(second.current_sum, Decimal("40.004000"))
        self.assertEqual(
            first.current_sum + second.current_sum,
            Decimal("100.010000"),
        )

    def test_three_partials_use_cumulative_rounding(self) -> None:
        first = self.allocate("3", line_amount="100.000001")
        second = self.allocate(
            "2",
            previous_quantity="3",
            previous_amount=str(first.cumulative_sum),
            line_amount="100.000001",
        )
        third = self.allocate(
            "5",
            previous_quantity="5",
            previous_amount=str(second.cumulative_sum),
            line_amount="100.000001",
        )
        self.assertEqual(
            first.current_sum + second.current_sum + third.current_sum,
            Decimal("100.000001"),
        )
        self.assertEqual(third.remaining_quantity, Decimal("0"))

    def test_shortage_allocates_only_accepted_proportion(self) -> None:
        result = self.allocate("6")
        self.assertEqual(result.cumulative_sum, Decimal("60.006000"))
        self.assertEqual(result.remaining_quantity, Decimal("4"))
        self.assertEqual(result.remaining_amount, Decimal("40.004000"))

    def test_rejected_quantity_is_excluded_by_receipt_eligible_input(self) -> None:
        result = self.allocate("6")
        self.assertEqual(result.cumulative_quantity, Decimal("6"))

    def test_reject_excess_is_excluded_by_receipt_eligible_input(self) -> None:
        result = self.allocate("10")
        self.assertEqual(result.cumulative_quantity, Decimal("10"))
        self.assertEqual(result.current_sum, Decimal("100.010000"))

    def test_excess_is_blocked(self) -> None:
        with self.assertRaisesRegex(ValueError, "EXCESS_PRICE_SOURCE_MISSING"):
            self.allocate("11")

    def test_round_half_even_at_six_decimal_places(self) -> None:
        low = self.allocate("5", line_amount="0.000001")
        high = self.allocate("5", line_amount="0.000003")
        self.assertEqual(low.current_sum, Decimal("0.000000"))
        self.assertEqual(high.current_sum, Decimal("0.000002"))


class IncomingInvoicePreviewTests(unittest.TestCase):
    def test_preview_uses_import_contract_and_omits_unsupported_fields(self) -> None:
        preview = build_incoming_invoice_preview(
            (ready_input(
                receipt_eligible_quantity=Decimal("6"),
                historical_unit_price=Decimal("38.03"),
                historical_line_sum=Decimal("228.15"),
            ),),
            document_number="EOS-18C-1",
            date_incoming=datetime(
                2026, 9, 17, 10, 15, 30, tzinfo=timezone.utc
            ),
            incoming_date=date(2026, 9, 17),
            supplier_id=SUPPLIER_ID,
            default_store_id=STORE_ID,
        )
        xml = preview.to_iiko_xml()
        self.assertEqual(xml, (
            b"<document>"
            b"<documentNumber>EOS-18C-1</documentNumber>"
            b"<dateIncoming>2026-09-17T10:15:30</dateIncoming>"
            b"<incomingDate>2026-09-17</incomingDate>"
            b"<supplier>11111111-1111-4111-8111-111111111111</supplier>"
            b"<defaultStore>22222222-2222-4222-8222-222222222222"
            b"</defaultStore>"
            b"<status>NEW</status>"
            b"<items><item>"
            b"<num>1</num>"
            b"<product>33333333-3333-4333-8333-333333333333</product>"
            b"<store>22222222-2222-4222-8222-222222222222</store>"
            b"<amount>6</amount>"
            b"<amountUnit>44444444-4444-4444-8444-444444444444</amountUnit>"
            b"<price>38.03</price>"
            b"<sum>136.890000</sum>"
            b"</item></items>"
            b"</document>"
        ))
        root = ET.fromstring(xml)

        self.assertEqual(root.tag, "document")
        self.assertEqual(root.findtext("documentNumber"), "EOS-18C-1")
        self.assertEqual(root.findtext("status"), "NEW")
        self.assertEqual(root.findtext("supplier"), str(SUPPLIER_ID))
        self.assertEqual(root.findtext("defaultStore"), str(STORE_ID))
        self.assertIsNone(root.find("supplierId"))
        self.assertIsNone(root.find("defaultStoreId"))
        self.assertIsNone(root.find("dueDate"))
        item = root.find("items/item")
        self.assertIsNotNone(item)
        self.assertEqual(item.findtext("num"), "1")
        self.assertEqual(item.findtext("product"), str(PRODUCT_ID))
        self.assertEqual(item.findtext("store"), str(STORE_ID))
        self.assertIsNone(item.find("productId"))
        self.assertIsNone(item.find("storeId"))
        self.assertEqual(item.findtext("amount"), "6")
        self.assertEqual(item.findtext("amountUnit"), str(UNIT_ID))
        self.assertEqual(item.findtext("price"), "38.03")
        self.assertEqual(item.findtext("sum"), "136.890000")
        self.assertIsNone(item.find("containerId"))
        self.assertIsNone(item.find("vatPercent"))
        self.assertIsNone(item.find("vatSum"))

    def test_preview_line_numbers_follow_input_order(self) -> None:
        second_product = UUID("55555555-5555-4555-8555-555555555555")
        preview = build_incoming_invoice_preview(
            (
                ready_input(),
                ready_input(iiko_product_id=second_product),
            ),
            document_number="EOS-18C-ORDER",
            date_incoming=datetime(2026, 9, 17, tzinfo=timezone.utc),
            incoming_date=date(2026, 9, 17),
            supplier_id=SUPPLIER_ID,
            default_store_id=STORE_ID,
        )
        self.assertEqual(
            tuple((item.num, item.product_id) for item in preview.items),
            ((1, PRODUCT_ID), (2, second_product)),
        )

    def test_preview_fails_closed_when_any_physical_line_is_blocked(self) -> None:
        blocked = ready_input(product_mapping_confirmed=False)
        with self.assertRaisesRegex(ValueError, "RECEIPT_PREVIEW_BLOCKED"):
            build_incoming_invoice_preview(
                (ready_input(), blocked),
                document_number="EOS-18C-2",
                date_incoming=datetime(2026, 9, 17, tzinfo=timezone.utc),
                incoming_date=date(2026, 9, 17),
                supplier_id=SUPPLIER_ID,
                default_store_id=STORE_ID,
            )


if __name__ == "__main__":
    unittest.main()
