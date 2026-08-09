from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from types import TracebackType
from typing import Any, Self
from uuid import uuid4

import httpx

from app.integrations.iiko.config import IikoSettings
from app.integrations.iiko.exceptions import (
    IikoAuthenticationError,
    IikoAuthorizationError,
    IikoConfigurationError,
    IikoConnectionError,
    IikoContractError,
    IikoRateLimitError,
    IikoResponseError,
)
from app.integrations.iiko.mapper import (
    map_collection,
    map_organization,
    map_packages,
    map_product,
    map_product_category,
    map_product_group,
    map_stock_balance,
    map_unit,
    map_warehouse,
)
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import (
    IikoOrganizationDto,
    IikoPackageDto,
    IikoProductCategoryDto,
    IikoProductDto,
    IikoProductGroupDto,
    IikoRecord,
    IikoStockBalanceDto,
    IikoUnitDto,
    IikoWarehouseDto,
)


logger = logging.getLogger(__name__)


_BALANCE_STORES_PATH = "/api/v2/reports/balance/stores"
_RESPONSE_BODY_LOG_LIMIT = 1500
_SENSITIVE_HEADER_RE = re.compile(
    r"(?im)^(\s*(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*).*$"
)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pass|authorization|proxy-authorization|"
    r"cookie|set-cookie|session(?:[_-]?(?:cookie|id))?|token|"
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|secret|"
    r"client[_-]?secret)\b\s*[\"']?\s*[:=]\s*)"
    r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;&}]+)"
)
_AUTH_SCHEME_RE = re.compile(
    r"(?i)\b(?:bearer|basic)\s+[a-z0-9._~+/=-]+"
)


def _sanitize_response_body(
    body: str,
    *,
    secret_values: Sequence[str],
) -> str:
    sanitized = _SENSITIVE_HEADER_RE.sub(r"\1[REDACTED]", body)
    sanitized = _SENSITIVE_VALUE_RE.sub(r"\1[REDACTED]", sanitized)
    sanitized = _AUTH_SCHEME_RE.sub("[REDACTED]", sanitized)
    for secret in secret_values:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = " ".join(sanitized.split())
    if not sanitized:
        return "<empty>"
    if len(sanitized) > _RESPONSE_BODY_LOG_LIMIT:
        return f"{sanitized[:_RESPONSE_BODY_LOG_LIMIT]}<truncated>"
    return sanitized


def _http_exception_type(status_code: int) -> str:
    if status_code == 401:
        return IikoAuthenticationError.__name__
    if status_code == 403:
        return IikoAuthorizationError.__name__
    if status_code == 429:
        return IikoRateLimitError.__name__
    return IikoResponseError.__name__


class _IikoAuthLogFilter(logging.Filter):
    """Remove iiko auth query parameters from httpx request logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 2:
            return True
        url = record.args[1]
        if not isinstance(url, httpx.URL) or not url.path.endswith("/api/auth"):
            return True
        args = list(record.args)
        args[1] = url.copy_with(query=None)
        record.args = tuple(args)
        return True


def _install_httpx_auth_log_filter() -> None:
    httpx_logger = logging.getLogger("httpx")
    if any(
        isinstance(filter_, _IikoAuthLogFilter)
        for filter_ in httpx_logger.filters
    ):
        return
    httpx_logger.addFilter(_IikoAuthLogFilter())


class IikoServerClient(IikoProvider):
    def __init__(
        self,
        settings: IikoSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        _install_httpx_auth_log_filter()
        self._settings = settings
        base_url = f"{str(settings.base_url or '').rstrip('/')}/"
        timeout = httpx.Timeout(
            connect=float(settings.connect_timeout_seconds),
            read=float(settings.request_timeout_seconds),
            write=float(settings.request_timeout_seconds),
            pool=float(settings.connect_timeout_seconds),
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            verify=settings.verify_tls,
            headers={
                "Accept": "application/json, text/plain",
                "User-Agent": "EnterpriseOS-iiko/1.0",
            },
            transport=transport,
        )
        self._token: str | None = None
        self._auth_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._products_cache: list[dict[str, Any]] | None = None
        self._warehouses_cache: list[dict[str, Any]] | None = None

    async def authenticate(self) -> None:
        self._settings.validate_enabled()
        if self._token:
            return
        async with self._auth_lock:
            if self._token:
                return
            login = self._settings.login
            password = self._settings.password
            if login is None or password is None:
                raise IikoConfigurationError("IIKO_NOT_CONFIGURED")
            password_hash = hashlib.sha1(
                password.get_secret_value().encode("utf-8")
            ).hexdigest()
            try:
                response = await self._raw_request(
                    "GET",
                    "/api/auth",
                    params={
                        "login": login.get_secret_value(),
                        "pass": password_hash,
                    },
                    authenticated=False,
                )
            finally:
                password_hash = ""
            if response.status_code in {401, 403}:
                raise IikoAuthenticationError("IIKO_CREDENTIALS_REJECTED")
            if not response.is_success:
                raise IikoResponseError(response.status_code)
            token = response.text.strip()
            if not token or len(token) > 512:
                raise IikoContractError("Invalid iiko auth response")
            self._token = token

    async def check_connection(self) -> bool:
        await self.authenticate()
        await self.get_units()
        return True

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        retries = self._settings.max_safe_retries if method == "GET" else 0
        correlation_id = str(uuid4())
        request_headers = dict(kwargs.pop("headers", {}) or {})
        for attempt in range(retries + 1):
            headers = dict(request_headers)
            headers["X-Resto-CorrelationId"] = correlation_id
            if authenticated and self._token:
                headers["Cookie"] = f"key={self._token}"
            try:
                # iikoServer recommends sequential API requests. The lock also
                # prevents concurrent retries from multiplying server load.
                async with self._request_lock:
                    response = await self._client.request(
                        method,
                        path.lstrip("/"),
                        headers=headers,
                        **kwargs,
                    )
            except httpx.TimeoutException as error:
                if attempt < retries:
                    continue
                raise IikoConnectionError("IIKO_TIMEOUT") from error
            except httpx.RequestError as error:
                if attempt < retries:
                    continue
                raise IikoConnectionError("IIKO_UNAVAILABLE") from error
            if response.status_code == 429:
                if attempt < retries:
                    continue
            if response.status_code >= 500 and attempt < retries:
                continue
            if path == _BALANCE_STORES_PATH and not response.is_success:
                password = self._settings.password
                logger.error(
                    "iiko balance/stores HTTP error "
                    "endpoint_path=%s status=%s timestamp=%s store=%s "
                    "response_body=%s exception_type=%s",
                    _BALANCE_STORES_PATH,
                    response.status_code,
                    response.request.url.params.get("timestamp"),
                    response.request.url.params.get_list("store"),
                    _sanitize_response_body(
                        response.text,
                        secret_values=(
                            self._token or "",
                            (
                                password.get_secret_value()
                                if password is not None
                                else ""
                            ),
                        ),
                    ),
                    _http_exception_type(response.status_code),
                )
            if response.status_code == 429:
                raise IikoRateLimitError("IIKO_RATE_LIMITED")
            return response
        raise IikoConnectionError("IIKO_RETRY_EXHAUSTED")

    async def _get_json_list(
        self,
        path: str,
        *,
        params: (
            Mapping[str, str]
            | Sequence[tuple[str, str]]
            | None
        ) = None,
        reauthenticated: bool = False,
    ) -> list[dict[str, Any]]:
        await self.authenticate()
        response = await self._raw_request("GET", path, params=params)
        if response.status_code == 401 and not reauthenticated:
            self._token = None
            await self.authenticate()
            return await self._get_json_list(
                path,
                params=params,
                reauthenticated=True,
            )
        if response.status_code == 401:
            raise IikoAuthenticationError("IIKO_TOKEN_REJECTED")
        if response.status_code == 403:
            raise IikoAuthorizationError("IIKO_ACCESS_DENIED")
        if not response.is_success:
            raise IikoResponseError(response.status_code)
        if not response.content:
            raise IikoContractError("Empty iiko response")
        try:
            payload = response.json()
        except ValueError as error:
            raise IikoContractError("Invalid iiko JSON response") from error
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise IikoContractError("Expected iiko list response")
        return payload

    async def _corporation_payloads(self) -> list[dict[str, Any]]:
        payloads = await self._get_json_list(
            "/api/corporation/departments",
            params={"revisionFrom": "-1"},
        )
        if any(not payload for payload in payloads):
            raise IikoContractError(
                "Corporation records are hidden by current iiko permissions"
            )
        return payloads

    async def get_organizations(
        self,
    ) -> list[IikoRecord[IikoOrganizationDto]]:
        return map_collection(
            await self._corporation_payloads(),
            map_organization,
        )

    async def get_enterprises(
        self,
    ) -> list[IikoRecord[IikoOrganizationDto]]:
        return [
            record
            for record in await self.get_organizations()
            if record.dto.organization_type == "DEPARTMENT"
        ]

    async def get_departments(
        self,
    ) -> list[IikoRecord[IikoOrganizationDto]]:
        payloads = await self._get_json_list(
            "/api/corporation/groups",
            params={"revisionFrom": "-1"},
        )
        if any(not payload for payload in payloads):
            raise IikoContractError(
                "Department records are hidden by current iiko permissions"
            )
        return map_collection(payloads, map_organization)

    async def get_warehouses(
        self,
    ) -> list[IikoRecord[IikoWarehouseDto]]:
        if self._warehouses_cache is None:
            accounts = await self._get_json_list(
                "/api/v2/entities/list",
                params={
                    "rootType": "Account",
                    "includeDeleted": "true",
                },
            )
            self._warehouses_cache = [
                payload
                for payload in accounts
                if payload.get("type") == "INVENTORY_ASSETS"
            ]
        return map_collection(self._warehouses_cache, map_warehouse)

    async def get_product_groups(
        self,
    ) -> list[IikoRecord[IikoProductGroupDto]]:
        return map_collection(
            await self._get_json_list(
                "/api/v2/entities/products/group/list",
                params={"includeDeleted": "true"},
            ),
            map_product_group,
        )

    async def get_product_categories(
        self,
    ) -> list[IikoRecord[IikoProductCategoryDto]]:
        return map_collection(
            await self._get_json_list(
                "/api/v2/entities/products/category/list",
                params={"includeDeleted": "true"},
            ),
            map_product_category,
        )

    async def _product_payloads(self) -> list[dict[str, Any]]:
        if self._products_cache is None:
            self._products_cache = await self._get_json_list(
                "/api/v2/entities/products/list",
                params={"includeDeleted": "true"},
            )
        return self._products_cache

    async def get_products(
        self,
    ) -> list[IikoRecord[IikoProductDto]]:
        return map_collection(await self._product_payloads(), map_product)

    async def get_units(self) -> list[IikoRecord[IikoUnitDto]]:
        return map_collection(
            await self._get_json_list(
                "/api/v2/entities/list",
                params={
                    "rootType": "MeasureUnit",
                    "includeDeleted": "true",
                },
            ),
            map_unit,
        )

    async def get_packages(
        self,
    ) -> list[IikoRecord[IikoPackageDto]]:
        records: list[IikoRecord[IikoPackageDto]] = []
        for product in await self._product_payloads():
            records.extend(map_packages(product))
        ids = [record.external_id for record in records]
        if len(ids) != len(set(ids)):
            raise IikoContractError("Duplicate package IDs in iiko response")
        return records

    async def get_stock_balances(
        self,
        *,
        warehouse_external_ids: Sequence[str],
        balance_date: date | None = None,
        snapshot_at: datetime | None = None,
        product_external_ids: Sequence[str] | None = None,
        include_zero: bool = True,
        include_deleted: bool = True,
    ) -> list[IikoRecord[IikoStockBalanceDto]]:
        warehouse_ids = list(
            dict.fromkeys(
                value.strip()
                for value in warehouse_external_ids
                if value.strip()
            )
        )
        if not warehouse_ids:
            raise IikoContractError("At least one warehouse is required")
        product_ids = list(
            dict.fromkeys(
                value.strip()
                for value in (product_external_ids or ())
                if value.strip()
            )
        )
        if snapshot_at is not None and balance_date is not None:
            raise IikoContractError(
                "Use either snapshot_at or balance_date, not both"
            )
        if snapshot_at is None:
            if balance_date is None:
                raise IikoContractError("Stock balance timestamp is required")
            calculated_at = datetime.combine(
                balance_date,
                time(23, 59, 59),
            )
        else:
            calculated_at = snapshot_at
        params: list[tuple[str, str]] = [
            ("timestamp", calculated_at.isoformat())
        ]
        params.extend(("store", value) for value in warehouse_ids)
        params.extend(("product", value) for value in product_ids)
        payloads = await self._get_json_list(
            _BALANCE_STORES_PATH,
            params=params,
        )
        products = {
            record.external_id: record.dto
            for record in await self.get_products()
        }
        warehouses = {
            record.external_id: record.dto
            for record in await self.get_warehouses()
        }
        records: list[IikoRecord[IikoStockBalanceDto]] = []
        seen: set[str] = set()
        for payload in payloads:
            product_id = payload.get("product")
            product = products.get(product_id)
            if (
                not include_deleted
                and product is not None
                and product.is_deleted
            ):
                continue
            record = map_stock_balance(
                payload,
                calculated_at=calculated_at,
                product=product,
                warehouse=warehouses.get(payload.get("store")),
            )
            if not include_zero and record.dto.quantity == 0:
                continue
            if record.external_id in seen:
                raise IikoContractError(
                    "Duplicate stock balance identity in iiko response"
                )
            seen.add(record.external_id)
            records.append(record)
        return records

    async def aclose(self) -> None:
        token = self._token
        self._token = None
        self._products_cache = None
        self._warehouses_cache = None
        if token:
            try:
                async with self._request_lock:
                    await self._client.get(
                        "api/logout",
                        headers={"Cookie": f"key={token}"},
                    )
            except httpx.RequestError:
                logger.warning(
                    "iiko logout failed",
                    extra={"integration": "iiko", "event": "logout_failed"},
                )
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
