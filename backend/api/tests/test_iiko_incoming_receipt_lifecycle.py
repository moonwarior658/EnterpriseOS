import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import httpx

from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.schemas import (
    IikoIncomingInvoiceDto,
    IikoIncomingInvoiceItemDto,
    IikoIncomingInvoicePreviewDto,
    IikoIncomingInvoicePreviewItemDto,
    IikoIncomingInvoiceStatus,
)
from app.supply.iiko_incoming_receipts import _matches, _reconcile, _verify_final


DOCUMENT_ID = UUID("10000000-0000-4000-8000-000000000001")
SUPPLIER_ID = UUID("20000000-0000-4000-8000-000000000001")
STORE_ID = UUID("30000000-0000-4000-8000-000000000001")
PRODUCT_ID = UUID("40000000-0000-4000-8000-000000000001")
UNIT_ID = UUID("50000000-0000-4000-8000-000000000001")


def settings() -> IikoSettings:
    return IikoSettings(
        enabled=True,
        base_url="https://iiko.example.test/resto",
        api_type="iiko_server",
        login="user",
        password="password",
    )


def preview() -> IikoIncomingInvoicePreviewDto:
    return IikoIncomingInvoicePreviewDto(
        document_number="EOS-IN-20260917-ABCDEF123456",
        date_incoming=datetime(2026, 9, 17, 10, 30, tzinfo=timezone.utc),
        incoming_date=date(2026, 9, 17),
        supplier_id=SUPPLIER_ID,
        default_store_id=STORE_ID,
        items=(IikoIncomingInvoicePreviewItemDto(
            num=1,
            product_id=PRODUCT_ID,
            store_id=STORE_ID,
            amount=Decimal("2.000000"),
            amount_unit_id=UNIT_ID,
            price=Decimal("50.000000000"),
            sum_amount=Decimal("100.000000"),
        ),),
    )


def invoice(
    *,
    external_id: UUID = DOCUMENT_ID,
    status: IikoIncomingInvoiceStatus = IikoIncomingInvoiceStatus.NEW,
    document_number: str = "EOS-IN-20260917-ABCDEF123456",
    amount: Decimal = Decimal("2"),
) -> IikoIncomingInvoiceDto:
    return IikoIncomingInvoiceDto(
        external_id=external_id,
        document_number=document_number,
        status=status,
        supplier_id=SUPPLIER_ID,
        default_store_id=STORE_ID,
        items=(IikoIncomingInvoiceItemDto(
            product_id=PRODUCT_ID,
            store_id=STORE_ID,
            amount=amount,
            amount_unit=UNIT_ID,
            price=Decimal("50"),
            sum_amount=Decimal("100"),
        ),),
    )


class FakeProvider:
    def __init__(self, invoices):
        self.invoices = invoices

    async def get_incoming_invoices(self, **_kwargs):
        return self.invoices


class IncomingInvoiceWriteContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_posts_exact_new_import_contract_without_uuid(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return httpx.Response(200, request=request, text="token")
            if request.url.path.endswith("/documents/import/incomingInvoice"):
                return httpx.Response(200, request=request, text=(
                    "<documentValidationResult><valid>true</valid>"
                    "<warning>false</warning>"
                    "<documentNumber>EOS-IN-20260917-ABCDEF123456</documentNumber>"
                    "<otherSuggestedNumber></otherSuggestedNumber>"
                    "<errorMessage></errorMessage><additionalInfo></additionalInfo>"
                    "</documentValidationResult>"
                ))
            if request.url.path.endswith("/api/logout"):
                return httpx.Response(200, request=request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            settings(), transport=httpx.MockTransport(handler)
        ) as client:
            result = await client.create_incoming_invoice(preview())

        self.assertTrue(result.valid)
        request = next(
            value for value in requests
            if value.url.path.endswith("/documents/import/incomingInvoice")
        )
        root = ET.fromstring(request.content)
        self.assertEqual(root.findtext("status"), "NEW")
        self.assertEqual(root.findtext("documentNumber"), preview().document_number)
        self.assertIsNone(root.find("id"))
        self.assertEqual(root.findtext("items/item/amountUnit"), str(UNIT_ID))
        self.assertNotIn("+00:00", root.findtext("dateIncoming") or "")

    async def test_create_preserves_validation_warning_and_suggested_number(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return httpx.Response(200, request=request, text="token")
            if request.url.path.endswith("/documents/import/incomingInvoice"):
                return httpx.Response(200, request=request, text=(
                    "<documentValidationResult><valid>false</valid>"
                    "<warning>true</warning><documentNumber>EOS-IN</documentNumber>"
                    "<otherSuggestedNumber>EOS-IN-1</otherSuggestedNumber>"
                    "<errorMessage>confirmation required</errorMessage>"
                    "<additionalInfo>warning</additionalInfo>"
                    "</documentValidationResult>"
                ))
            return httpx.Response(200, request=request, text="ok")

        async with IikoServerClient(
            settings(), transport=httpx.MockTransport(handler)
        ) as client:
            result = await client.create_incoming_invoice(preview())

        self.assertFalse(result.valid)
        self.assertTrue(result.warning)
        self.assertEqual(result.other_suggested_number, "EOS-IN-1")
        self.assertEqual(result.error_message, "confirmation required")

    async def test_create_timeout_is_not_retried_by_provider(self):
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            if request.url.path.endswith("/api/auth"):
                return httpx.Response(200, request=request, text="token")
            if request.url.path.endswith("/documents/import/incomingInvoice"):
                attempts += 1
                raise httpx.ReadTimeout("unknown result", request=request)
            return httpx.Response(200, request=request, text="ok")

        async with IikoServerClient(
            settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(Exception):
                await client.create_incoming_invoice(preview())
        self.assertEqual(attempts, 1)

    async def test_process_reads_new_then_sends_incoming_invoice_type_once(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return httpx.Response(200, request=request, text="token")
            if request.url.path.endswith("/services/document"):
                return httpx.Response(200, request=request, text=(
                    "<result><success>true</success><resultStatus>SUCCESS</resultStatus>"
                    f'<returnValue cls="IncomingInvoice" eid="{DOCUMENT_ID}">'
                    f"<id>{DOCUMENT_ID}</id><status>NEW</status></returnValue>"
                    "<entitiesUpdate><revision>177</revision><fullUpdate>false</fullUpdate>"
                    "</entitiesUpdate></result>"
                ))
            if request.url.path.endswith("/services/documentGroupOperation"):
                return httpx.Response(200, request=request, text=(
                    "<result><returnValue><valid>true</valid><warning>false</warning>"
                    "<documentNumber>EOS-IN-20260917-ABCDEF123456</documentNumber>"
                    "<otherSuggestedNumber></otherSuggestedNumber>"
                    "<errorMessage></errorMessage><additionalInfo></additionalInfo>"
                    "</returnValue><success>true</success>"
                    "<resultStatus>SUCCESS</resultStatus></result>"
                ))
            if request.url.path.endswith("/api/logout"):
                return httpx.Response(200, request=request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            settings(), transport=httpx.MockTransport(handler)
        ) as client:
            result = await client.process_incoming_invoice(DOCUMENT_ID)

        self.assertTrue(result.valid)
        group_requests = [
            value for value in requests
            if value.url.path.endswith("/services/documentGroupOperation")
        ]
        self.assertEqual(len(group_requests), 1)
        root = ET.fromstring(group_requests[0].content.lstrip(b"\xef\xbb\xbf"))
        self.assertEqual(root.findtext("enable-warnings"), "true")
        self.assertEqual(root.findtext("documentIds/k"), str(DOCUMENT_ID))
        self.assertEqual(root.findtext("documentIds/v"), "INCOMING_INVOICE")


class IncomingInvoiceReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def test_exactly_one_match_captures_authoritative_identity(self):
        outcome, value = await _reconcile(FakeProvider([invoice()]), preview())
        self.assertEqual(outcome, "MATCH")
        self.assertEqual(value.external_id, DOCUMENT_ID)

    async def test_zero_multiple_and_mismatch_fail_closed(self):
        cases = (
            ([], "READBACK_NOT_FOUND"),
            ([invoice(), invoice(external_id=UUID("10000000-0000-4000-8000-000000000002"))], "READBACK_AMBIGUOUS"),
            ([invoice(amount=Decimal("3"))], "READBACK_MISMATCH"),
        )
        for invoices, expected in cases:
            with self.subTest(expected=expected):
                outcome, value = await _reconcile(FakeProvider(invoices), preview())
                self.assertEqual(outcome, expected)
                self.assertIsNone(value)

    def test_final_verify_requires_uuid_processed_and_exact_multiset(self):
        processed = invoice(status=IikoIncomingInvoiceStatus.PROCESSED)
        self.assertTrue(_matches(processed, preview()))
        self.assertTrue(_verify_final(processed, preview(), DOCUMENT_ID))
        self.assertFalse(_verify_final(invoice(), preview(), DOCUMENT_ID))
        self.assertFalse(_verify_final(
            invoice(status=IikoIncomingInvoiceStatus.PROCESSED, amount=Decimal("3")),
            preview(), DOCUMENT_ID,
        ))


if __name__ == "__main__":
    unittest.main()
