import unittest
from datetime import datetime, timezone
from uuid import UUID

import httpx

from app.automation.providers.errors import (
    ProviderAuthenticationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.automation.providers.n8n import N8nProvider
from app.core.n8n_config import N8nSettings
from app.schemas.automation import AutomationCommand


EXECUTION_ID = UUID("41644d7a-8875-4f35-a493-371b330fb154")
DISPATCH_URL = (
    "https://n8n.example.test/webhook/automation-dispatch"
)
HEALTHCHECK_URL = "https://n8n.example.test/healthz"


def make_settings() -> N8nSettings:
    return N8nSettings(
        dispatch_webhook_url=DISPATCH_URL,
        healthcheck_url=HEALTHCHECK_URL,
        service_token="test-service-token",
        timeout_seconds=2.5,
    )


def make_command() -> AutomationCommand:
    return AutomationCommand(
        execution_id=EXECUTION_ID,
        automation_type="daily_sales_report",
        tenant_id="tenant-42",
        requested_at=datetime(
            2026,
            7,
            19,
            12,
            30,
            tzinfo=timezone.utc,
        ),
        payload={"location_ids": [10, 20]},
        callback_url=(
            "https://api.example.test/automation/callback"
        ),
    )


class N8nProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_response_means_command_was_accepted(
        self,
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), DISPATCH_URL)
            self.assertEqual(
                request.headers["Authorization"],
                "Bearer test-service-token",
            )
            payload = request.content.decode()
            self.assertIn(str(EXECUTION_ID), payload)

            return httpx.Response(
                httpx.codes.ACCEPTED,
                json={
                    "status": "succeeded",
                    "business_result": "must be ignored",
                },
            )

        transport = httpx.MockTransport(handler)

        async with N8nProvider(
            make_settings(),
            transport=transport,
        ) as provider:
            acceptance = await provider.send_command(make_command())

        self.assertTrue(acceptance.accepted)
        self.assertEqual(acceptance.provider, "n8n")
        self.assertEqual(
            acceptance.status_code,
            httpx.codes.ACCEPTED,
        )

    async def test_authentication_error_is_typed(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                httpx.codes.UNAUTHORIZED,
                request=request,
            )

        transport = httpx.MockTransport(handler)

        async with N8nProvider(
            make_settings(),
            transport=transport,
        ) as provider:
            with self.assertRaises(ProviderAuthenticationError):
                await provider.send_command(make_command())

    async def test_timeout_error_is_typed(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout(
                "n8n did not respond",
                request=request,
            )

        transport = httpx.MockTransport(handler)

        async with N8nProvider(
            make_settings(),
            transport=transport,
        ) as provider:
            with self.assertRaises(ProviderTimeoutError):
                await provider.send_command(make_command())

    async def test_unavailable_error_is_typed(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                "n8n is unavailable",
                request=request,
            )

        transport = httpx.MockTransport(handler)

        async with N8nProvider(
            make_settings(),
            transport=transport,
        ) as provider:
            with self.assertRaises(ProviderUnavailableError):
                await provider.send_command(make_command())

    async def test_healthcheck(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "GET")
            self.assertEqual(str(request.url), HEALTHCHECK_URL)
            self.assertEqual(
                request.headers["Authorization"],
                "Bearer test-service-token",
            )

            return httpx.Response(
                httpx.codes.NO_CONTENT,
                request=request,
            )

        transport = httpx.MockTransport(handler)

        async with N8nProvider(
            make_settings(),
            transport=transport,
        ) as provider:
            is_available = await provider.check_availability()

        self.assertTrue(is_available)
