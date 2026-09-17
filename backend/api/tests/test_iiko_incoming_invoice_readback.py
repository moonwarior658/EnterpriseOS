import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx

from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.incoming_invoice_readback import (
    reconcile_incoming_invoice,
)
from app.integrations.iiko.schemas import (
    IikoIncomingInvoiceDto,
    IikoIncomingInvoiceItemDto,
    IikoIncomingInvoiceStatus,
)


DOCUMENT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SUPPLIER_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
STORE_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
PRODUCT_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
CONTAINER_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
AMOUNT_UNIT_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
LIVE_DOCUMENT_ID = UUID("5bf2b1c7-8c91-b774-01a0-a8680eb301f5")


def settings() -> IikoSettings:
    return IikoSettings(
        enabled=True,
        base_url="https://iiko.example.test/resto",
        api_type="iiko_server",
        login="integration-user",
        password="integration-password",
        max_safe_retries=0,
    )


def response(request: httpx.Request, text: str) -> httpx.Response:
    return httpx.Response(200, request=request, text=text)


class IncomingInvoiceParserTests(unittest.IsolatedAsyncioTestCase):
    async def _read(self, xml: str) -> list[IikoIncomingInvoiceDto]:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, "token")
            if request.url.path.endswith("/api/logout"):
                return response(request, "ok")
            if request.url.path.endswith(
                "/api/documents/export/incomingInvoice"
            ):
                return response(request, xml)
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            settings(), transport=httpx.MockTransport(handler),
        ) as client:
            return await client.get_incoming_invoices(
                date_from=date(2026, 9, 1),
                date_to=date(2026, 9, 17),
            )

    async def test_parses_rich_invoice_lines_decimals_container_and_vat(
        self,
    ) -> None:
        xml = f"""<?xml version="1.0"?>
<incomingInvoiceDtoes><document>
  <id>{DOCUMENT_ID}</id><documentNumber>ПН-42</documentNumber>
  <incomingDocumentNumber>УПД-7</incomingDocumentNumber>
  <dateIncoming>2026-09-17T10:15:30+05:00</dateIncoming>
  <incomingDate>2026-09-16</incomingDate><dueDate>2026-10-01</dueDate>
  <invoice>СФ-9</invoice><comment>Поставка</comment><revision>17</revision>
  <defaultStore>{STORE_ID}</defaultStore><supplier>{SUPPLIER_ID}</supplier>
  <supplierName>ООО Поставщик</supplierName><supplierCode>SUP-1</supplierCode>
  <status>PROCESSED</status><futureField>ignored</futureField>
  <items>
    <item><num>1</num><product>{PRODUCT_ID}</product>
      <productArticle>A-1</productArticle><amount>1.2500</amount>
      <actualAmount>1.25</actualAmount><price>80.00</price>
      <sum>100.000</sum><vatPercent>20</vatPercent><vatSum>16.67</vatSum>
      <isAdditionalExpense>false</isAdditionalExpense></item>
    <item><num>2</num><product>{PRODUCT_ID}</product>
      <supplierProduct>{PRODUCT_ID}</supplierProduct>
      <supplierProductArticle>SP-2</supplierProductArticle>
      <store>{STORE_ID}</store><amount>2</amount>
      <amountUnit>{AMOUNT_UNIT_ID}</amountUnit>
      <containerId>{CONTAINER_ID}</containerId><price>50</price>
      <priceUnit>{AMOUNT_UNIT_ID}</priceUnit><sum>100</sum>
      <vatPercent>0</vatPercent><vatSum>0</vatSum>
      <isAdditionalExpense>true</isAdditionalExpense></item>
  </items>
</document></incomingInvoiceDtoes>"""

        invoice = (await self._read(xml))[0]

        self.assertEqual(invoice.external_id, DOCUMENT_ID)
        self.assertEqual(invoice.status, IikoIncomingInvoiceStatus.PROCESSED)
        self.assertIsNone(invoice.raw_status)
        self.assertEqual(invoice.supplier_id, SUPPLIER_ID)
        self.assertEqual(invoice.default_store_id, STORE_ID)
        self.assertEqual(invoice.date_incoming, datetime.fromisoformat(
            "2026-09-17T10:15:30+05:00"
        ))
        self.assertEqual(invoice.incoming_date, date(2026, 9, 16))
        self.assertEqual(invoice.revision, 17)
        self.assertEqual(len(invoice.items), 2)
        self.assertEqual(invoice.items[0].amount, Decimal("1.2500"))
        self.assertEqual(invoice.items[0].vat_sum, Decimal("16.67"))
        self.assertEqual(invoice.items[1].container_id, CONTAINER_ID)
        self.assertEqual(invoice.items[1].amount_unit, AMOUNT_UNIT_ID)
        self.assertEqual(invoice.items[1].price_unit, AMOUNT_UNIT_ID)
        self.assertTrue(invoice.items[1].is_additional_expense)

    async def test_preserves_known_deleted_and_unknown_statuses(self) -> None:
        documents = "".join(
            f"<document><id>{UUID(int=index + 1)}</id>"
            f"<documentNumber>{index}</documentNumber><status>{status}</status>"
            "</document>"
            for index, status in enumerate(("NEW", "PROCESSED", "DELETED", "VOIDED"))
        )
        invoices = await self._read(
            f"<incomingInvoiceDtoes>{documents}</incomingInvoiceDtoes>"
        )
        self.assertEqual(
            [invoice.status for invoice in invoices],
            [
                IikoIncomingInvoiceStatus.NEW,
                IikoIncomingInvoiceStatus.PROCESSED,
                IikoIncomingInvoiceStatus.DELETED,
                IikoIncomingInvoiceStatus.UNKNOWN,
            ],
        )
        self.assertEqual(invoices[-1].raw_status, "VOIDED")
        self.assertEqual(invoices[0].items, ())
        self.assertIsNone(invoices[0].supplier_id)
        self.assertIsNone(invoices[0].default_store_id)

    async def test_rejects_malformed_critical_uuid_and_decimal(self) -> None:
        documents = (
            "<document><id>not-a-uuid</id><documentNumber>1</documentNumber>"
            "<status>NEW</status></document>",
            f"<document><id>{DOCUMENT_ID}</id><documentNumber>2</documentNumber>"
            f"<status>NEW</status><items><item><product>{PRODUCT_ID}</product>"
            "<amount>not-a-decimal</amount></item></items></document>",
            f"<document><id>{DOCUMENT_ID}</id><documentNumber>3</documentNumber>"
            f"<status>NEW</status><items><item><product>{PRODUCT_ID}</product>"
            "<amount>1</amount><amountUnit>not-a-uuid</amountUnit>"
            "</item></items></document>",
        )
        for document in documents:
            with self.subTest(document=document[:50]):
                with self.assertRaises(IikoContractError):
                    await self._read(
                        f"<incomingInvoiceDtoes>{document}</incomingInvoiceDtoes>"
                    )

    async def test_by_id_uses_bounded_export_and_exact_uuid(self) -> None:
        requests: list[httpx.Request] = []
        xml = (
            f"<incomingInvoiceDtoes><document><id>{DOCUMENT_ID}</id>"
            "<documentNumber>42</documentNumber><status>NEW</status>"
            "</document></incomingInvoiceDtoes>"
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return response(request, "token")
            if request.url.path.endswith("/api/logout"):
                return response(request, "ok")
            return response(request, xml)

        async with IikoServerClient(
            settings(), transport=httpx.MockTransport(handler),
        ) as client:
            invoice = await client.get_incoming_invoice_by_id(
                DOCUMENT_ID,
                date_from=date(2026, 9, 16),
                date_to=date(2026, 9, 17),
            )

        self.assertIsNotNone(invoice)
        export = next(
            request for request in requests
            if request.url.path.endswith("/api/documents/export/incomingInvoice")
        )
        self.assertEqual(export.url.params["from"], "2026-09-16")
        self.assertEqual(export.url.params["to"], "2026-09-17")
        self.assertEqual({request.method for request in requests}, {"GET"})

    async def test_parses_sanitized_live_contract_fixture(self) -> None:
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "iiko_incoming_invoice_live.xml"
        ).read_text(encoding="utf-8")

        invoice = (await self._read(fixture))[0]

        self.assertEqual(invoice.external_id, LIVE_DOCUMENT_ID)
        self.assertEqual(invoice.document_number, "4397")
        self.assertEqual(invoice.status, IikoIncomingInvoiceStatus.PROCESSED)
        self.assertEqual(
            invoice.supplier_id,
            UUID("47c6accc-4bc7-6be1-0194-ccf9367e208c"),
        )
        self.assertEqual(
            invoice.default_store_id,
            UUID("d8ac1fa7-73d3-4164-9651-fa2c0b806d0f"),
        )
        self.assertEqual(
            invoice.date_incoming,
            datetime(2026, 9, 16, 8, 59, 25),
        )
        self.assertEqual(invoice.incoming_date, date(2026, 9, 16))
        self.assertIsNone(invoice.due_date)
        self.assertIsNone(invoice.revision)
        self.assertEqual(len(invoice.items), 3)
        first = invoice.items[0]
        self.assertEqual(first.line_no, 1)
        self.assertEqual(first.code, "12103")
        self.assertEqual(first.amount, Decimal("6.000"))
        self.assertEqual(first.actual_amount, Decimal("6.000"))
        self.assertEqual(
            first.amount_unit,
            UUID("cd19b5ea-1b32-a6e5-1df7-5d2784a0549a"),
        )
        self.assertIsNone(first.container_id)
        self.assertEqual(first.price, Decimal("38.03"))
        self.assertEqual(first.price_without_vat, Decimal("38.03"))
        self.assertIsNone(first.price_unit)
        self.assertEqual(first.sum_amount, Decimal("228.15"))
        self.assertEqual(first.discount_sum, Decimal("0.00"))
        self.assertEqual(first.vat_percent, Decimal("0.000000000"))
        self.assertEqual(first.vat_sum, Decimal("0.00"))
        self.assertFalse(first.is_additional_expense)


def item(**changes: object) -> IikoIncomingInvoiceItemDto:
    values: dict[str, object] = {
        "product_id": PRODUCT_ID,
        "store_id": STORE_ID,
        "amount": Decimal("1.00"),
        "price": Decimal("10.0"),
        "sum_amount": Decimal("10.00"),
        "container_id": CONTAINER_ID,
        "amount_unit": AMOUNT_UNIT_ID,
        "vat_percent": Decimal("20"),
        "vat_sum": Decimal("1.67"),
    }
    values.update(changes)
    return IikoIncomingInvoiceItemDto(**values)


def invoice(**changes: object) -> IikoIncomingInvoiceDto:
    values: dict[str, object] = {
        "external_id": DOCUMENT_ID,
        "document_number": "ПН-42",
        "status": "PROCESSED",
        "supplier_id": SUPPLIER_ID,
        "default_store_id": STORE_ID,
        "items": (item(), item()),
    }
    values.update(changes)
    return IikoIncomingInvoiceDto(**values)


class IncomingInvoiceReconciliationTests(unittest.TestCase):
    def test_line_order_decimal_scale_and_duplicate_lines_are_safe(self) -> None:
        expected = invoice()
        actual = invoice(items=(
            item(amount=Decimal("1"), price=Decimal("10.00")),
            item(amount=Decimal("1.000"), sum_amount=Decimal("10")),
        ))
        self.assertTrue(reconcile_incoming_invoice(expected, actual).matched)

    def test_reports_header_and_line_mismatches(self) -> None:
        cases = {
            "supplier": {"supplier_id": UUID(int=20)},
            "store": {"default_store_id": UUID(int=21)},
            "status": {"status": "NEW"},
            "quantity": {"items": (item(amount=Decimal("2")), item())},
            "price": {"items": (item(price=Decimal("11")), item())},
            "sum": {"items": (item(sum_amount=Decimal("11")), item())},
            "missing_line": {"items": (item(),)},
            "extra_line": {"items": (item(), item(), item())},
        }
        expected = invoice()
        for name, changes in cases.items():
            with self.subTest(name=name):
                result = reconcile_incoming_invoice(
                    expected, invoice(**changes),
                )
                self.assertFalse(result.matched)
                self.assertIn(
                    name if name in {"supplier", "store", "status"} else "lines",
                    result.mismatches,
                )


if __name__ == "__main__":
    unittest.main()
