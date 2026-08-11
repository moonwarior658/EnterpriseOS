import json
import unittest
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import httpx

from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.document_routing import (
    IikoDocumentRouteNotConfiguredError,
)
from app.integrations.iiko.document_write import (
    IikoInternalTransferLineInput,
    IikoInternalTransferValidationError,
    create_controlled_internal_transfer,
)
from app.integrations.iiko.exceptions import IikoResponseError
from app.models.supply import SupplyProductSourceRole


def make_settings() -> IikoSettings:
    return IikoSettings(
        enabled=True,
        base_url="https://iiko.example.test/resto",
        api_type="iiko_server",
        login="integration-user",
        password="integration-password",
        max_safe_retries=0,
    )


def response(
    request: httpx.Request,
    status_code: int = 200,
    *,
    text: str = "",
) -> httpx.Response:
    return httpx.Response(status_code, request=request, text=text)


class IikoInternalTransferWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_new_payload_with_eos_id_and_routing_stores(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/v2/documents/internalTransfer"
            ):
                return response(request, status_code=204)
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        expected_routes = {
            SupplyProductSourceRole.MAIN: (
                "24b90a5f-1a58-4f6b-9b55-368d7a92ec3e",
                "1c22edc0-7ded-41c9-b781-0389462c7247",
            ),
            SupplyProductSourceRole.PACKAGING: (
                "bf44ec50-91d2-48b3-a927-2e3e2490f1d6",
                "1c22edc0-7ded-41c9-b781-0389462c7247",
            ),
            SupplyProductSourceRole.HOUSEHOLD: (
                "9ea20084-9182-4633-8c52-a968a15e0b3b",
                "db13589d-68fd-4140-b1de-550f3e07c88a",
            ),
        }
        product_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        unit_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        document_ids = {
            flow: UUID(f"00000000-0000-4000-8000-00000000000{index}")
            for index, flow in enumerate(expected_routes, start=1)
        }

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            for flow in expected_routes:
                returned_id = await create_controlled_internal_transfer(
                    client,
                    document_id=document_ids[flow],
                    date_incoming=datetime(2026, 8, 11, 12, 30, 45),
                    department_code="ЦЕХ",
                    flow=flow,
                    lines=[IikoInternalTransferLineInput(
                        iiko_product_id=product_id,
                        iiko_unit_id=unit_id,
                        quantity=Decimal("1.250"),
                    )],
                )
                self.assertEqual(returned_id, document_ids[flow])

        writes = [request for request in requests if request.method == "POST"]
        self.assertEqual(len(writes), 3)
        for request, (flow, stores) in zip(writes, expected_routes.items()):
            with self.subTest(flow=flow):
                self.assertEqual(
                    request.url.path,
                    "/resto/api/v2/documents/internalTransfer",
                )
                self.assertEqual(
                    request.headers["content-type"],
                    "application/json",
                )
                self.assertEqual(json.loads(request.content), {
                    "id": str(document_ids[flow]),
                    "dateIncoming": "2026-08-11T12:30:45",
                    "status": "NEW",
                    "storeFromId": stores[0],
                    "storeToId": stores[1],
                    "items": [{
                        "productId": str(product_id),
                        "amount": "1.250",
                    }],
                })

    async def test_unknown_route_does_not_make_http_request(self) -> None:
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
                await create_controlled_internal_transfer(
                    client,
                    document_id=UUID(
                        "00000000-0000-4000-8000-000000000001"
                    ),
                    date_incoming=datetime(2026, 8, 11, 12, 30, 45),
                    department_code="М15",
                    flow=SupplyProductSourceRole.MAIN,
                    lines=[IikoInternalTransferLineInput(
                        iiko_product_id=UUID(
                            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                        ),
                        iiko_unit_id=UUID(
                            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
                        ),
                        quantity=Decimal("1"),
                    )],
                )
        finally:
            await client.aclose()
        self.assertEqual(requests, [])

    async def test_failed_post_is_not_retried(self) -> None:
        post_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal post_count
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/v2/documents/internalTransfer"
            ):
                post_count += 1
                return response(request, status_code=500)
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(IikoResponseError):
                await create_controlled_internal_transfer(
                    client,
                    document_id=UUID(
                        "00000000-0000-4000-8000-000000000001"
                    ),
                    date_incoming=datetime(2026, 8, 11, 12, 30, 45),
                    department_code="ЦЕХ",
                    flow=SupplyProductSourceRole.MAIN,
                    lines=[IikoInternalTransferLineInput(
                        iiko_product_id=UUID(
                            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
                        ),
                        iiko_unit_id=UUID(
                            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
                        ),
                        quantity=Decimal("1"),
                    )],
                )
        self.assertEqual(post_count, 1)

    async def test_invalid_lines_do_not_make_http_request(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            raise AssertionError("HTTP must not be called")

        valid_product_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        valid_unit_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        invalid_documents = (
            [],
            [IikoInternalTransferLineInput(
                iiko_product_id=None,
                iiko_unit_id=valid_unit_id,
                quantity=Decimal("1"),
            )],
            [IikoInternalTransferLineInput(
                iiko_product_id=valid_product_id,
                iiko_unit_id=None,
                quantity=Decimal("1"),
            )],
            [IikoInternalTransferLineInput(
                iiko_product_id=valid_product_id,
                iiko_unit_id=valid_unit_id,
                quantity=Decimal("0"),
            )],
            [IikoInternalTransferLineInput(
                iiko_product_id=valid_product_id,
                iiko_unit_id=valid_unit_id,
                quantity=Decimal("-1"),
            )],
            [IikoInternalTransferLineInput(
                iiko_product_id=valid_product_id,
                iiko_unit_id=valid_unit_id,
                quantity=Decimal("NaN"),
            )],
            [IikoInternalTransferLineInput(
                iiko_product_id=valid_product_id,
                iiko_unit_id=valid_unit_id,
                quantity=Decimal("Infinity"),
            )],
        )
        client = IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        )
        try:
            for lines in invalid_documents:
                with self.subTest(lines=lines):
                    with self.assertRaises(
                        IikoInternalTransferValidationError
                    ):
                        await create_controlled_internal_transfer(
                            client,
                            document_id=UUID(
                                "00000000-0000-4000-8000-000000000001"
                            ),
                            date_incoming=datetime(
                                2026, 8, 11, 12, 30, 45
                            ),
                            department_code="ЦЕХ",
                            flow=SupplyProductSourceRole.MAIN,
                            lines=lines,
                        )
        finally:
            await client.aclose()
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
