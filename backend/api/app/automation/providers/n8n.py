from types import TracebackType
from typing import Self

import httpx

from app.automation.providers.base import (
    AutomationProvider,
    CommandAcceptance,
)
from app.automation.providers.errors import (
    ProviderAuthenticationError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.core.n8n_config import N8nSettings
from app.schemas.automation import AutomationCommand


class N8nProvider(AutomationProvider):
    name = "n8n"

    def __init__(
        self,
        settings: N8nSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._dispatch_webhook_url = str(settings.dispatch_webhook_url)
        self._healthcheck_url = str(settings.healthcheck_url)
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": (
                    "Bearer "
                    f"{settings.service_token.get_secret_value()}"
                ),
                "Accept": "application/json",
            },
            timeout=settings.timeout_seconds,
            transport=transport,
        )

    async def send_command(
        self,
        command: AutomationCommand,
    ) -> CommandAcceptance:
        response = await self._request(
            "POST",
            self._dispatch_webhook_url,
            json=command.model_dump(mode="json"),
            headers={
                "Idempotency-Key": str(command.idempotency_key),
            },
        )

        return CommandAcceptance(
            provider=self.name,
            accepted=True,
            status_code=response.status_code,
        )

    async def check_availability(self) -> bool:
        await self._request("GET", self._healthcheck_url)
        return True

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: object,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                url,
                **kwargs,
            )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(
                "Automation provider request timed out"
            ) from error
        except httpx.RequestError as error:
            raise ProviderUnavailableError(
                "Automation provider is unavailable"
            ) from error

        if response.status_code in {
            httpx.codes.UNAUTHORIZED,
            httpx.codes.FORBIDDEN,
        }:
            raise ProviderAuthenticationError(
                "Automation provider rejected service credentials"
            )

        if not response.is_success:
            raise ProviderRejectedError(response.status_code)

        return response

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
