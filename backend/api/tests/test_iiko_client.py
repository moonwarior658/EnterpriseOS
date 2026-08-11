import logging
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.exceptions import (
    IikoAuthenticationError,
    IikoAuthorizationError,
    IikoConnectionError,
    IikoContractError,
    IikoRateLimitError,
    IikoResponseError,
)


def make_settings(**changes) -> IikoSettings:
    values = {
        "enabled": True,
        "base_url": "https://iiko.example.test/resto",
        "api_type": "iiko_server",
        "login": "integration-user",
        "password": "integration-password",
        "max_safe_retries": 0,
    }
    values.update(changes)
    return IikoSettings(**values)


def response(
    request: httpx.Request,
    status_code: int = 200,
    *,
    text: str | None = None,
    json: object | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=request,
        text=text,
        json=json,
    )


class IikoServerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_xml_reports_only_sanitized_bounded_preview(
        self,
    ) -> None:
        body = (
            "<html><password>xml-secret</password> "
            "password=json-secret cookie=cookie-secret "
            "integration-user integration-password token-value "
            + ("x" * 400)
            + "tail-must-not-appear"
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token-value")
            if request.url.path.endswith(
                "/api/documents/export/outgoingInvoice"
            ):
                return httpx.Response(
                    200,
                    request=request,
                    text=body,
                    headers={"Content-Type": "text/html; charset=utf-8"},
                )
            return response(request, text="ok")

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(IikoContractError) as captured:
                await client.get_outgoing_invoices(
                    date_from=date(2026, 8, 1),
                    date_to=date(2026, 8, 10),
                )

        message = str(captured.exception)
        self.assertIn("status=200", message)
        self.assertIn("content_type='text/html; charset=utf-8'", message)
        self.assertIn(f"body_bytes={len(body.encode())}", message)
        self.assertIn("body_preview=", message)
        self.assertIn("[REDACTED]", message)
        self.assertNotIn("xml-secret", message)
        self.assertNotIn("json-secret", message)
        self.assertNotIn("cookie-secret", message)
        self.assertNotIn("integration-user", message)
        self.assertNotIn("integration-password", message)
        self.assertNotIn("token-value", message)
        self.assertNotIn("tail-must-not-appear", message)

    async def test_incomplete_historical_invoice_is_skipped_for_discovery(
        self,
    ) -> None:
        xml = """<?xml version="1.0"?>
<outgoingInvoiceDtoes><document>
<id>475e5ce1-c5bc-47a1-b7c5-d9334728e329</id>
<documentNumber>1232</documentNumber>
<dateIncoming>2020-01-01T12:00:00+05:00</dateIncoming>
<status>PROCESSED</status>
<linkedIncomingInvoiceId>aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa</linkedIncomingInvoiceId>
<defaultStoreId>8c9ddcb0-e126-4ad8-bd54-94379ddd28e7</defaultStoreId>
<counteragentId>0e3720cf-a886-4d3b-9c9f-04ad76ea17cb</counteragentId>
</document><document>
<id>69aca118-c607-4d53-9362-8fcc085aca40</id>
<documentNumber>2686</documentNumber>
<dateIncoming>2026-08-01T12:00:00+05:00</dateIncoming>
<status>PROCESSED</status>
<linkedIncomingInvoiceId>bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb</linkedIncomingInvoiceId>
<defaultStoreId>8c9ddcb0-e126-4ad8-bd54-94379ddd28e7</defaultStoreId>
<counteragentId>47c6accc-4bc7-6be1-0194-ccf9367e20cb</counteragentId>
<accountToCode>21</accountToCode>
<revenueAccountCode>20</revenueAccountCode>
</document></outgoingInvoiceDtoes>"""

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith(
                "/api/documents/export/outgoingInvoice"
            ):
                return response(request, text=xml)
            return response(request, text="ok")

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertLogs(
                "app.integrations.iiko.client",
                level=logging.WARNING,
            ) as captured:
                invoices = await client.get_outgoing_invoices(
                    date_from=date(2026, 8, 1),
                    date_to=date(2026, 8, 10),
                )

        self.assertEqual(
            [invoice.document_number for invoice in invoices],
            ["2686"],
        )
        rendered = "\n".join(captured.output)
        self.assertIn("document_number=1232", rendered)
        self.assertIn("missing_field=accountToCode", rendered)
        self.assertIn("missing_field=revenueAccountCode", rendered)

    async def test_reads_accounts_and_outgoing_invoice_contract_headers(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            if request.url.path.endswith("/api/v2/entities/accounts/list"):
                return response(request, json=[{
                    "id": "9be92cb2-f416-45e8-a36f-24118e0d6a01",
                    "name": "Задолженность покупателей",
                    "code": "7.3",
                    "type": "ACCOUNTS_RECEIVABLE",
                    "deleted": False,
                }])
            if request.url.path.endswith(
                "/api/documents/export/outgoingInvoice"
            ):
                return response(request, text="""<?xml version="1.0"?>
<outgoingInvoiceDtoes><document>
<id>475e5ce1-c5bc-47a1-b7c5-d9334728e329</id>
<documentNumber>2686</documentNumber>
<dateIncoming>2026-08-01T12:00:00+05:00</dateIncoming>
<status>PROCESSED</status><accountToCode>21</accountToCode>
<revenueAccountCode>20</revenueAccountCode>
<linkedIncomingInvoiceId>aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa</linkedIncomingInvoiceId>
<defaultStoreId>8c9ddcb0-e126-4ad8-bd54-94379ddd28e7</defaultStoreId>
<counteragentId>47c6accc-4bc7-6be1-0194-ccf9367e20cb</counteragentId>
<items><item>
<productId>aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa</productId>
<amount>1.250</amount><price>0</price>
</item></items>
</document></outgoingInvoiceDtoes>""")
            if request.url.path.endswith(
                "/api/documents/export/incomingInvoice"
            ):
                return response(request, text="""<?xml version="1.0"?>
<incomingInvoiceDtoes><document>
<id>aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa</id>
<documentNumber>ПН-2686</documentNumber>
<incomingDocumentNumber>2686</incomingDocumentNumber>
<incomingDate>2026-08-01</incomingDate>
<dateIncoming>2026-08-01T12:00:00+05:00</dateIncoming>
<defaultStore>bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb</defaultStore>
<supplier>cccccccc-cccc-4ccc-8ccc-cccccccccccc</supplier>
<status>PROCESSED</status>
</document></incomingInvoiceDtoes>""")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            accounts = await client.get_accounts()
            invoices = await client.get_outgoing_invoices(
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 10),
            )
            self.assertEqual(len(invoices[0].items), 1)
            self.assertEqual(
                str(invoices[0].items[0].product_id),
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            )
            self.assertEqual(invoices[0].items[0].amount, Decimal("1.250"))
            self.assertEqual(invoices[0].items[0].price, Decimal("0"))
            incoming = await client.get_incoming_invoices(
                date_from=date(2026, 8, 1),
                date_to=date(2026, 8, 10),
            )

        self.assertEqual(accounts[0].code, "7.3")
        self.assertEqual(invoices[0].document_number, "2686")
        self.assertEqual(invoices[0].account_to_code, "21")
        self.assertEqual(invoices[0].revenue_account_code, "20")
        self.assertEqual(
            invoices[0].counteragent_id,
            "47c6accc-4bc7-6be1-0194-ccf9367e20cb",
        )
        self.assertEqual(
            invoices[0].linked_incoming_invoice_id,
            incoming[0].external_id,
        )
        self.assertEqual(
            incoming[0].default_store_id,
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        )
        self.assertEqual(
            incoming[0].supplier_id,
            "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        )
        account_request = next(
            item for item in requests
            if item.url.path.endswith("/api/v2/entities/accounts/list")
        )
        self.assertEqual(account_request.url.params["includeDeleted"], "true")
        invoice_request = next(
            item for item in requests
            if item.url.path.endswith(
                "/api/documents/export/outgoingInvoice"
            )
        )
        self.assertEqual(invoice_request.url.params["from"], "2026-08-01")
        self.assertEqual(invoice_request.url.params["to"], "2026-08-10")
        self.assertEqual(invoice_request.headers["accept"], "application/xml")
        self.assertEqual({item.method for item in requests}, {"GET"})

    async def test_reads_suppliers_from_real_shaped_xml(self) -> None:
        requests: list[httpx.Request] = []
        supplier_id = "47c6accc-4bc7-6be1-0194-ccf9367e20cb"

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            if request.url.path.endswith("/api/suppliers"):
                return response(request, text=f"""<?xml version="1.0"?>
<employeeDtoes><employee>
<id>{supplier_id}</id>
<name>Эклер Маяковского 6а: Павильон Эклер Маяковского 6а</name>
<code>M6A</code><supplier>true</supplier><employee>false</employee>
<representsStore>true</representsStore><deleted>false</deleted>
</employee></employeeDtoes>""")
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            suppliers = await client.get_suppliers()

        self.assertEqual(len(suppliers), 1)
        self.assertEqual(suppliers[0].external_id, supplier_id)
        self.assertEqual(suppliers[0].code, "M6A")
        self.assertTrue(suppliers[0].is_supplier)
        self.assertFalse(suppliers[0].is_employee)
        self.assertTrue(suppliers[0].represents_store)
        supplier_request = next(
            item for item in requests
            if item.url.path.endswith("/api/suppliers")
        )
        self.assertEqual(supplier_request.headers["accept"], "application/xml")

    async def test_close_logs_out_and_clears_token(self) -> None:
        requests: list[httpx.Request] = []
        client = IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(
                lambda request: (
                    requests.append(request)
                    or response(
                        request,
                        text=(
                            "token" if request.url.path.endswith("/api/auth")
                            else "ok"
                        ),
                    )
                )
            ),
        )
        await client.authenticate()
        await client.aclose()

        logout = next(
            item for item in requests if item.url.path.endswith("/api/logout")
        )
        self.assertEqual(logout.headers["cookie"], "key=token")
        self.assertIsNone(client._token)

    async def test_logout_failure_does_not_mask_primary_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                raise httpx.ConnectError("logout unavailable", request=request)
            raise AssertionError(request.url.path)

        with self.assertRaisesRegex(RuntimeError, "primary flow failed"):
            async with IikoServerClient(
                make_settings(),
                transport=httpx.MockTransport(handler),
            ) as client:
                await client.authenticate()
                raise RuntimeError("primary flow failed")

    async def test_auth_query_is_redacted_from_httpx_logs(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token-value")
            return response(request, text="ok")

        with self.assertLogs("httpx", level=logging.INFO) as captured:
            async with IikoServerClient(
                make_settings(),
                transport=httpx.MockTransport(handler),
            ) as client:
                await client.authenticate()

        rendered = "\n".join(captured.output)
        self.assertNotIn("integration-user", rendered)
        self.assertNotIn("integration-password", rendered)
        self.assertNotIn("login=", rendered)
        self.assertNotIn("pass=", rendered)

    async def test_auth_and_units_use_cookie_without_leaking_password(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/api/auth"):
                self.assertEqual(
                    request.url.path,
                    "/resto/api/auth",
                )
                self.assertEqual(request.url.params["login"], "integration-user")
                self.assertNotEqual(
                    request.url.params["pass"],
                    "integration-password",
                )
                return response(request, text="token-value")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="token-value")
            self.assertEqual(request.headers["cookie"], "key=token-value")
            return response(
                request,
                json=[
                    {
                        "id": "unit-1",
                        "name": "Килограмм",
                        "code": "кг",
                        "deleted": False,
                    }
                ],
            )

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            units = await client.get_units()

        self.assertEqual(units[0].dto.external_id, "unit-1")
        rendered = "\n".join(str(request.url) for request in requests)
        self.assertNotIn("integration-password", rendered)
        self.assertNotIn("token-value", str(make_settings()))

    async def test_bad_credentials_are_typed(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return response(request, 401, text="rejected")

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(IikoAuthenticationError):
                await client.authenticate()

    async def test_401_reauthenticates_only_once(self) -> None:
        auth_count = 0
        read_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_count, read_count
            if request.url.path.endswith("/api/auth"):
                auth_count += 1
                return response(request, text=f"token-{auth_count}")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            read_count += 1
            if read_count == 1:
                return response(request, 401, text="expired")
            return response(request, json=[])

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            self.assertEqual(await client.get_units(), [])

        self.assertEqual(auth_count, 2)
        self.assertEqual(read_count, 2)

    async def test_second_401_stops_without_recursion(self) -> None:
        auth_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal auth_count
            if request.url.path.endswith("/api/auth"):
                auth_count += 1
                return response(request, text=f"token-{auth_count}")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            return response(request, 401, text="expired")

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(IikoAuthenticationError):
                await client.get_units()
        self.assertEqual(auth_count, 2)

    async def test_403_is_authorization_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            return response(request, 403, text="forbidden")

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(IikoAuthorizationError):
                await client.get_units()

    async def test_timeout_and_connection_errors_are_typed(self) -> None:
        for error in (
            httpx.ReadTimeout("timeout"),
            httpx.ConnectError("unavailable"),
        ):
            async def handler(
                request: httpx.Request,
                raised: Exception = error,
            ) -> httpx.Response:
                raise raised

            async with IikoServerClient(
                make_settings(),
                transport=httpx.MockTransport(handler),
            ) as client:
                with self.assertRaises(IikoConnectionError):
                    await client.authenticate()

    async def test_invalid_json_and_empty_response_are_contract_errors(
        self,
    ) -> None:
        for body in ("not-json", ""):
            async def handler(
                request: httpx.Request,
                content: str = body,
            ) -> httpx.Response:
                if request.url.path.endswith("/api/auth"):
                    return response(request, text="token")
                if request.url.path.endswith("/api/logout"):
                    return response(request, text="ok")
                return response(request, text=content)

            async with IikoServerClient(
                make_settings(),
                transport=httpx.MockTransport(handler),
            ) as client:
                with self.assertRaises(IikoContractError):
                    await client.get_units()

    async def test_429_and_500_are_typed(self) -> None:
        for status_code, exception in (
            (429, IikoRateLimitError),
            (500, IikoResponseError),
        ):
            async def handler(
                request: httpx.Request,
                code: int = status_code,
            ) -> httpx.Response:
                if request.url.path.endswith("/api/auth"):
                    return response(request, text="token")
                if request.url.path.endswith("/api/logout"):
                    return response(request, text="ok")
                return response(request, code, text="error")

            async with IikoServerClient(
                make_settings(),
                transport=httpx.MockTransport(handler),
            ) as client:
                with self.assertRaises(exception):
                    await client.get_units()

    async def test_500_retry_is_bounded(self) -> None:
        read_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal read_count
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            read_count += 1
            return response(request, 500, text="error")

        async with IikoServerClient(
            make_settings(max_safe_retries=1),
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(IikoResponseError):
                await client.get_units()
        self.assertEqual(read_count, 2)

    async def test_warehouses_use_inventory_accounts(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            self.assertEqual(
                request.url.path,
                "/resto/api/v2/entities/list",
            )
            self.assertEqual(request.url.params["rootType"], "Account")
            return response(
                request,
                json=[
                    {
                        "id": "warehouse-1",
                        "name": "Основной склад",
                        "type": "INVENTORY_ASSETS",
                        "parentCorporateId": None,
                        "deleted": False,
                    },
                    {
                        "id": "expense-1",
                        "name": "Расходы",
                        "type": "EXPENSES",
                        "deleted": False,
                    },
                ],
            )

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            warehouses = await client.get_warehouses()
        self.assertEqual(len(warehouses), 1)
        self.assertEqual(warehouses[0].external_id, "warehouse-1")
        self.assertIsNone(warehouses[0].dto.enterprise_external_id)

    async def test_stock_filters_are_bounded_and_decimal_safe(self) -> None:
        balance_requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            if request.url.path.endswith("/api/v2/reports/balance/stores"):
                balance_requests.append(request)
                return response(
                    request,
                    json=[
                        {
                            "store": "warehouse-1",
                            "product": "product-1",
                            "amount": "-2.500",
                            "sum": -100,
                        },
                        {
                            "store": "warehouse-1",
                            "product": "product-1-zero",
                            "amount": 0,
                            "sum": 0,
                        },
                        {
                            "store": "warehouse-1",
                            "product": "product-deleted",
                            "amount": 1,
                            "sum": 10,
                        },
                    ],
                )
            if request.url.path.endswith("/api/v2/entities/products/list"):
                return response(
                    request,
                    json=[
                        {
                            "id": "product-1",
                            "name": "Товар",
                            "mainUnit": "unit-1",
                            "deleted": False,
                        },
                        {
                            "id": "product-1-zero",
                            "name": "Нулевой товар",
                            "mainUnit": "unit-1",
                            "deleted": False,
                        },
                        {
                            "id": "product-deleted",
                            "name": "Удалённый товар",
                            "mainUnit": "unit-1",
                            "deleted": True,
                        },
                    ],
                )
            if request.url.path.endswith("/api/v2/entities/list"):
                return response(
                    request,
                    json=[
                        {
                            "id": "warehouse-1",
                            "name": "Основной склад",
                            "type": "INVENTORY_ASSETS",
                            "deleted": False,
                        }
                    ],
                )
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            records = await client.get_stock_balances(
                balance_date=date(2026, 7, 29),
                warehouse_external_ids=["warehouse-1"],
                product_external_ids=["product-1", "product-deleted"],
                include_zero=False,
                include_deleted=False,
            )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].dto.quantity, Decimal("-2.500"))
        request = balance_requests[0]
        self.assertEqual(
            request.url.params["timestamp"],
            "2026-07-29T23:59:59",
        )
        self.assertEqual(request.url.params.get_list("store"), ["warehouse-1"])
        self.assertEqual(
            request.url.params.get_list("product"),
            ["product-1", "product-deleted"],
        )

    async def test_snapshot_timestamp_uses_legacy_balance_format(self) -> None:
        balance_requests: list[httpx.Request] = []
        warehouse_id = "982b0d9b-e37e-4b40-8026-c68f724a83e9"

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="token")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            if request.url.path.endswith("/api/v2/reports/balance/stores"):
                balance_requests.append(request)
                return response(request, json=[])
            if request.url.path.endswith("/api/v2/entities/products/list"):
                return response(request, json=[])
            if request.url.path.endswith("/api/v2/entities/list"):
                return response(request, json=[])
            raise AssertionError(request.url.path)

        async with IikoServerClient(
            make_settings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.get_stock_balances(
                snapshot_at=datetime(
                    2026,
                    8,
                    9,
                    16,
                    54,
                    51,
                    697000,
                    tzinfo=timezone.utc,
                ),
                warehouse_external_ids=[warehouse_id],
            )
            await client.get_stock_balances(
                balance_date=date(2026, 8, 9),
                warehouse_external_ids=[warehouse_id],
            )

        snapshot_timestamp = balance_requests[0].url.params["timestamp"]
        legacy_timestamp = balance_requests[1].url.params["timestamp"]
        self.assertEqual(snapshot_timestamp, "2026-08-09T16:54:51")
        self.assertEqual(legacy_timestamp, "2026-08-09T23:59:59")
        for value in (snapshot_timestamp, legacy_timestamp):
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
            self.assertEqual(parsed.strftime("%Y-%m-%dT%H:%M:%S"), value)
            self.assertNotIn("+", value)
            self.assertFalse(value.endswith("Z"))
        self.assertEqual(
            [
                request.url.params.get_list("store")
                for request in balance_requests
            ],
            [[warehouse_id], [warehouse_id]],
        )

    async def test_balance_stores_success_logs_only_row_counts(self) -> None:
        warehouse_id = "982b0d9b-e37e-4b40-8026-c68f724a83e9"

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="auth-cookie-secret")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            if request.url.path.endswith("/api/v2/reports/balance/stores"):
                return response(
                    request,
                    json=[
                        {
                            "store": warehouse_id,
                            "product": "positive-product-id",
                            "amount": "2.5",
                            "internalSecret": "response-body-secret",
                        },
                        {
                            "store": warehouse_id,
                            "product": "negative-product-id",
                            "amount": "-1",
                        },
                        {
                            "store": warehouse_id,
                            "product": "zero-product-id",
                            "amount": "0",
                        },
                        {
                            "store": warehouse_id,
                            "product": "deleted-product-id",
                            "amount": "4",
                        },
                    ],
                )
            if request.url.path.endswith("/api/v2/entities/products/list"):
                return response(
                    request,
                    json=[
                        {
                            "id": product_id,
                            "name": f"secret-name-{product_id}",
                            "mainUnit": "unit-id",
                            "deleted": product_id == "deleted-product-id",
                        }
                        for product_id in (
                            "positive-product-id",
                            "negative-product-id",
                            "zero-product-id",
                            "deleted-product-id",
                        )
                    ],
                )
            if request.url.path.endswith("/api/v2/entities/list"):
                return response(
                    request,
                    json=[
                        {
                            "id": warehouse_id,
                            "name": "secret-warehouse-name",
                            "type": "INVENTORY_ASSETS",
                            "deleted": False,
                        }
                    ],
                )
            raise AssertionError(request.url.path)

        with self.assertLogs(
            "app.integrations.iiko.client",
            level=logging.WARNING,
        ) as captured:
            async with IikoServerClient(
                make_settings(),
                transport=httpx.MockTransport(handler),
            ) as client:
                records = await client.get_stock_balances(
                    snapshot_at=datetime(
                        2026,
                        8,
                        9,
                        16,
                        54,
                        51,
                        tzinfo=timezone.utc,
                    ),
                    warehouse_external_ids=[warehouse_id],
                    include_zero=True,
                    include_deleted=False,
                )

        self.assertEqual(len(records), 3)
        count_log = next(
            line for line in captured.output
            if "iiko balance/stores response counts" in line
        )
        self.assertTrue(count_log.startswith("WARNING:"))
        self.assertIn(f"store={warehouse_id}", count_log)
        self.assertIn("raw_rows=4", count_log)
        self.assertIn("deleted_filtered=1", count_log)
        self.assertIn("returned_rows=3", count_log)
        self.assertIn("positive_rows=1", count_log)
        self.assertIn("negative_rows=1", count_log)
        self.assertIn("zero_rows=1", count_log)
        for forbidden in (
            "auth-cookie-secret",
            "response-body-secret",
            "positive-product-id",
            "secret-name-",
            "secret-warehouse-name",
        ):
            self.assertNotIn(forbidden, count_log)

    async def test_balance_stores_http_error_is_safely_logged(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/api/auth"):
                return response(request, text="auth-cookie-secret")
            if request.url.path.endswith("/api/logout"):
                return response(request, text="ok")
            if request.url.path.endswith("/api/v2/reports/balance/stores"):
                return response(
                    request,
                    502,
                    text=(
                        '{"message":"balance unavailable",'
                        '"password":"integration-password",'
                        '"Authorization":"Bearer authorization-secret",'
                        '"cookie":"key=auth-cookie-secret",'
                        '"session_cookie":"session-cookie-secret",'
                        '"api_key":"other-secret"}'
                    ),
                )
            raise AssertionError(request.url.path)

        with self.assertLogs(
            "app.integrations.iiko.client",
            level=logging.ERROR,
        ) as captured:
            async with IikoServerClient(
                make_settings(),
                transport=httpx.MockTransport(handler),
            ) as client:
                with self.assertRaises(IikoResponseError):
                    await client.get_stock_balances(
                        balance_date=date(2026, 8, 9),
                        warehouse_external_ids=["store-uuid"],
                    )

        rendered = "\n".join(captured.output)
        self.assertIn(
            "endpoint_path=/api/v2/reports/balance/stores",
            rendered,
        )
        self.assertIn("status=502", rendered)
        self.assertIn("timestamp=2026-08-09T23:59:59", rendered)
        self.assertIn("store=['store-uuid']", rendered)
        self.assertIn("balance unavailable", rendered)
        self.assertIn("exception_type=IikoResponseError", rendered)
        self.assertIn("[REDACTED]", rendered)
        for secret in (
            "integration-password",
            "auth-cookie-secret",
            "authorization-secret",
            "session-cookie-secret",
            "other-secret",
        ):
            self.assertNotIn(secret, rendered)
