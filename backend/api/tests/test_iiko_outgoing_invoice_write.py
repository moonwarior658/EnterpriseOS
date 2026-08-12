import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

import httpx

from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.document_routing import (
    IikoDocumentRouteNotConfiguredError,
    resolve_outgoing_invoice_route,
)
from app.integrations.iiko.document_write import (
    IikoOutgoingInvoiceLineInput,
    IikoOutgoingInvoiceValidationError,
    create_controlled_outgoing_invoice,
)
from app.integrations.iiko.exceptions import (
    IikoConnectionError,
    IikoContractError,
    IikoResponseError,
)
from app.models.iiko import IikoMappingStatus
from app.models.supply import SupplyProductSourceRole


DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000001")
PRODUCT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
UNIT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
DATE_INCOMING = datetime(
    2026,
    8,
    11,
    12,
    30,
    45,
    tzinfo=timezone(timedelta(hours=5)),
)


def make_settings(**changes) -> IikoSettings:
    values = {
        "enabled": True,
        "base_url": "https://iiko.example.test/resto",
        "api_type": "iiko_server",
        "login": "integration-user",
        "password": "integration-password",
        "max_safe_retries": 3,
    }
    values.update(changes)
    return IikoSettings(**values)


def response(
    request: httpx.Request,
    status_code: int = 200,
    *,
    text: str = "",
) -> httpx.Response:
    return httpx.Response(status_code, request=request, text=text)


def valid_line(**changes) -> IikoOutgoingInvoiceLineInput:
    values = {
        "iiko_product_id": PRODUCT_ID,
        "product_mapping_status": IikoMappingStatus.CONFIRMED,
        "iiko_unit_id": UNIT_ID,
        "quantity": Decimal("1.250"),
    }
    values.update(changes)
    return IikoOutgoingInvoiceLineInput(**values)


def xml_payload(request: httpx.Request) -> ET.Element:
    return ET.fromstring(request.content)


def child_text(element: ET.Element, name: str) -> str | None:
    child = element.find(name)
    return child.text if child is not None else None


def successful_import_response(
    request: httpx.Request,
    *,
    document_number: str = "2709",
    warning: str = "false",
) -> httpx.Response:
    return response(request, text=(
        "<documentValidationResult>"
        "<valid>true</valid>"
        f"<warning>{warning}</warning>"
        f"<documentNumber>{document_number}</documentNumber>"
        "</documentValidationResult>"
    ))


class IikoOutgoingInvoiceWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_exact_new_payload_with_caller_uuid_and_route(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/documents/import/outgoingInvoice"
            ):
                return successful_import_response(request)
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            result = await create_controlled_outgoing_invoice(
                client,
                document_id=DOCUMENT_ID,
                date_incoming=DATE_INCOMING,
                department_code="М15",
                flow=SupplyProductSourceRole.MAIN,
                lines=[valid_line()],
            )

        self.assertEqual(result.client_document_id, DOCUMENT_ID)
        self.assertEqual(result.document_number, "2709")
        self.assertTrue(result.valid)
        self.assertFalse(result.warning)
        writes = [request for request in requests if request.method == "POST"]
        self.assertEqual(len(writes), 1)
        request = writes[0]
        self.assertEqual(
            request.url.path,
            "/resto/api/documents/import/outgoingInvoice",
        )
        self.assertEqual(request.headers["content-type"], "application/xml")
        self.assertEqual(
            request.headers["accept"],
            "application/xml, text/plain",
        )
        self.assertEqual(request.content, (
            b"<document>"
            b"<id>00000000-0000-4000-8000-000000000001</id>"
            b"<dateIncoming>2026-08-11T12:30:45+05:00</dateIncoming>"
            b"<useDefaultDocumentTime>false</useDefaultDocumentTime>"
            b"<status>NEW</status>"
            b"<accountToCode>21</accountToCode>"
            b"<revenueAccountCode>20</revenueAccountCode>"
            b"<defaultStoreId>24b90a5f-1a58-4f6b-9b55-368d7a92ec3e"
            b"</defaultStoreId>"
            b"<counteragentId>47c6accc-4bc7-6be1-0194-ccf9367e20cd"
            b"</counteragentId>"
            b"<items><item>"
            b"<productId>aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa</productId>"
            b"<amount>1.250</amount>"
            b"<price>0</price>"
            b"</item></items>"
            b"</document>"
        ))
        root = xml_payload(request)
        for omitted_document_field in (
            "documentNumber",
            "defaultStoreCode",
            "counteragentCode",
            "linkedIncomingInvoiceId",
        ):
            self.assertIsNone(root.find(omitted_document_field))
        for export_only_field in (
            "productArticle",
            "storeId",
            "storeCode",
            "priceWithoutVat",
            "sum",
            "discountSum",
            "vatPercent",
            "vatSum",
        ):
            self.assertIsNone(root.find(f"items/item/{export_only_field}"))
        self.assertFalse(any(
            "incomingInvoice" in request.url.path for request in requests
        ))

    async def test_parses_success_warning_result(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/documents/import/outgoingInvoice"
            ):
                return successful_import_response(
                    request,
                    document_number="2710",
                    warning="true",
                )
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            result = await create_controlled_outgoing_invoice(
                client,
                document_id=DOCUMENT_ID,
                date_incoming=DATE_INCOMING,
                department_code="М15",
                flow=SupplyProductSourceRole.MAIN,
                lines=[valid_line()],
            )

        self.assertEqual(result.client_document_id, DOCUMENT_ID)
        self.assertEqual(result.document_number, "2710")
        self.assertTrue(result.valid)
        self.assertTrue(result.warning)

    async def test_validation_failure_is_not_retried(self) -> None:
        posts: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/documents/import/outgoingInvoice"
            ):
                posts.append(request)
                return response(request, text=(
                    "<documentValidationResult>"
                    "<valid>false</valid>"
                    "<warning>false</warning>"
                    "<documentNumber>2711</documentNumber>"
                    "</documentValidationResult>"
                ))
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(max_safe_retries=3),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaisesRegex(
                IikoContractError,
                "IIKO_OUTGOING_INVOICE_VALIDATION_FAILED",
            ):
                await create_controlled_outgoing_invoice(
                    client,
                    document_id=DOCUMENT_ID,
                    date_incoming=DATE_INCOMING,
                    department_code="М15",
                    flow=SupplyProductSourceRole.MAIN,
                    lines=[valid_line()],
                )

        self.assertEqual(len(posts), 1)

    async def test_all_nine_routes_supply_write_fields(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/documents/import/outgoingInvoice"
            ):
                return successful_import_response(request)
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        combinations = [
            (department, flow)
            for department in ("М15", "М35", "М6А")
            for flow in (
                SupplyProductSourceRole.MAIN,
                SupplyProductSourceRole.PACKAGING,
                SupplyProductSourceRole.HOUSEHOLD,
            )
        ]
        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            for index, (department, flow) in enumerate(
                combinations,
                start=1,
            ):
                await create_controlled_outgoing_invoice(
                    client,
                    document_id=UUID(
                        f"00000000-0000-4000-8000-{index:012d}"
                    ),
                    date_incoming=DATE_INCOMING,
                    department_code=department,
                    flow=flow,
                    lines=[valid_line()],
                )

        writes = [request for request in requests if request.method == "POST"]
        self.assertEqual(len(writes), 9)
        for request, (department, flow) in zip(writes, combinations):
            with self.subTest(department=department, flow=flow):
                route = resolve_outgoing_invoice_route(department, flow)
                payload = xml_payload(request)
                self.assertEqual(
                    child_text(payload, "defaultStoreId"),
                    str(route.source_store_id),
                )
                self.assertEqual(
                    child_text(payload, "counteragentId"),
                    str(route.counteragent_id),
                )
                self.assertEqual(child_text(payload, "accountToCode"), "21")
                self.assertEqual(
                    child_text(payload, "revenueAccountCode"),
                    "20",
                )

    async def test_unknown_route_fails_before_http(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            raise AssertionError("HTTP must not be called")

        client = IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaises(IikoDocumentRouteNotConfiguredError):
                await create_controlled_outgoing_invoice(
                    client,
                    document_id=DOCUMENT_ID,
                    date_incoming=DATE_INCOMING,
                    department_code="ЦЕХ",
                    flow=SupplyProductSourceRole.MAIN,
                    lines=[valid_line()],
                )
        finally:
            await client.aclose()
        self.assertEqual(requests, [])

    async def test_invalid_lines_fail_before_http(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            raise AssertionError("HTTP must not be called")

        invalid_documents = (
            [],
            [valid_line(iiko_product_id=None)],
            [valid_line(product_mapping_status=None)],
            [valid_line(product_mapping_status=IikoMappingStatus.UNMAPPED)],
            [valid_line(iiko_unit_id=None)],
            [valid_line(quantity=Decimal("0"))],
            [valid_line(quantity=Decimal("-1"))],
            [valid_line(quantity=Decimal("NaN"))],
            [valid_line(quantity=Decimal("Infinity"))],
        )
        client = IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        try:
            for lines in invalid_documents:
                with self.subTest(lines=lines):
                    with self.assertRaises(
                        IikoOutgoingInvoiceValidationError
                    ):
                        await create_controlled_outgoing_invoice(
                            client,
                            document_id=DOCUMENT_ID,
                            date_incoming=DATE_INCOMING,
                            department_code="М15",
                            flow=SupplyProductSourceRole.MAIN,
                            lines=lines,
                        )
        finally:
            await client.aclose()
        self.assertEqual(requests, [])

    async def test_missing_document_identity_or_date_fails_before_http(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            raise AssertionError("HTTP must not be called")

        client = IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        try:
            invalid_headers = (
                (None, DATE_INCOMING),
                (DOCUMENT_ID, None),
                (DOCUMENT_ID, datetime(2026, 8, 11, 12, 30, 45)),
            )
            for document_id, date_incoming in invalid_headers:
                with self.subTest(
                    document_id=document_id,
                    date_incoming=date_incoming,
                ):
                    with self.assertRaises(
                        IikoOutgoingInvoiceValidationError
                    ):
                        await create_controlled_outgoing_invoice(
                            client,
                            document_id=document_id,
                            date_incoming=date_incoming,
                            department_code="М15",
                            flow=SupplyProductSourceRole.MAIN,
                            lines=[valid_line()],
                        )
        finally:
            await client.aclose()
        self.assertEqual(requests, [])

    async def test_missing_route_fields_fail_before_http(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            raise AssertionError("HTTP must not be called")

        valid_route = resolve_outgoing_invoice_route(
            "М15",
            SupplyProductSourceRole.MAIN,
        )
        invalid_routes = (
            replace(valid_route, source_store_id=None),
            replace(valid_route, counteragent_id=None),
            replace(valid_route, account_to_code=""),
            replace(valid_route, revenue_account_code=""),
        )
        client = IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        try:
            for route in invalid_routes:
                with self.subTest(route=route):
                    with patch(
                        "app.integrations.iiko.document_write."
                        "resolve_outgoing_invoice_route",
                        return_value=route,
                    ):
                        with self.assertRaises(
                            IikoOutgoingInvoiceValidationError
                        ):
                            await create_controlled_outgoing_invoice(
                                client,
                                document_id=DOCUMENT_ID,
                                date_incoming=DATE_INCOMING,
                                department_code="М15",
                                flow=SupplyProductSourceRole.MAIN,
                                lines=[valid_line()],
                            )
        finally:
            await client.aclose()
        self.assertEqual(requests, [])

    async def test_timeout_is_not_retried_and_keeps_caller_uuid(self) -> None:
        posts: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/documents/import/outgoingInvoice"
            ):
                posts.append(request)
                raise httpx.ReadTimeout("timeout", request=request)
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(max_safe_retries=3),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(IikoConnectionError):
                await create_controlled_outgoing_invoice(
                    client,
                    document_id=DOCUMENT_ID,
                    date_incoming=DATE_INCOMING,
                    department_code="М15",
                    flow=SupplyProductSourceRole.MAIN,
                    lines=[valid_line()],
                )

        self.assertEqual(len(posts), 1)
        self.assertEqual(
            child_text(xml_payload(posts[0]), "id"),
            str(DOCUMENT_ID),
        )

    async def test_failed_post_is_not_retried(self) -> None:
        posts: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/documents/import/outgoingInvoice"
            ):
                posts.append(request)
                return response(request, status_code=500)
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(max_safe_retries=3),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaisesRegex(IikoResponseError, "HTTP 500"):
                await create_controlled_outgoing_invoice(
                    client,
                    document_id=DOCUMENT_ID,
                    date_incoming=DATE_INCOMING,
                    department_code="М15",
                    flow=SupplyProductSourceRole.MAIN,
                    lines=[valid_line()],
                )

        self.assertEqual(len(posts), 1)


if __name__ == "__main__":
    unittest.main()
