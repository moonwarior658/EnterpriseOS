from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal
from types import TracebackType
from typing import Any, Self
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

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
    IikoAccountDto,
    IikoDocumentValidationResultDto,
    IikoIncomingInvoiceDto,
    IikoOutgoingInvoiceCreateDto,
    IikoOutgoingInvoiceCreateResultDto,
    IikoOutgoingInvoiceItemDto,
    IikoOrganizationDto,
    IikoOutgoingInvoiceDto,
    IikoOutgoingInvoiceUpdateSourceDto,
    IikoPackageDto,
    IikoProductCategoryDto,
    IikoProductDto,
    IikoProductGroupDto,
    IikoRecord,
    IikoStockBalanceDto,
    IikoSupplierDto,
    IikoUnitDto,
    IikoWarehouseDto,
)


logger = logging.getLogger(__name__)


_BALANCE_STORES_PATH = "/api/v2/reports/balance/stores"
_INCOMING_INVOICE_EXPORT_PATH = "/api/documents/export/incomingInvoice"
_OUTGOING_INVOICE_EXPORT_PATH = "/api/documents/export/outgoingInvoice"
_OUTGOING_INVOICE_IMPORT_PATH = "/api/documents/import/outgoingInvoice"
_DOCUMENT_SERVICE_PATH = "/services/document"
_DOCUMENT_GROUP_OPERATION_PATH = "/services/documentGroupOperation"
_UPDATE_SERVICE_PATH = "/services/update"
_BACK_VERSION = "9.2.7014.0"
_MAX_XML_RESPONSE_BYTES = 10 * 1024 * 1024
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
_SENSITIVE_XML_ELEMENT_RE = re.compile(
    r"(?is)(<\s*(password|passwd|pass|authorization|proxy-authorization|"
    r"cookie|set-cookie|session(?:[_-]?(?:cookie|id))?|token|"
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|secret|"
    r"client[_-]?secret)\b[^>]*>).*?(</\s*\2\s*>)"
)


def _sanitize_response_body(
    body: str,
    *,
    secret_values: Sequence[str],
) -> str:
    sanitized = _SENSITIVE_HEADER_RE.sub(r"\1[REDACTED]", body)
    sanitized = _SENSITIVE_VALUE_RE.sub(r"\1[REDACTED]", sanitized)
    sanitized = _AUTH_SCHEME_RE.sub("[REDACTED]", sanitized)
    sanitized = _SENSITIVE_XML_ELEMENT_RE.sub(
        r"\1[REDACTED]\3",
        sanitized,
    )
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


def _serialize_balance_stores_timestamp(value: datetime) -> str:
    return value.replace(tzinfo=None).isoformat(timespec="seconds")


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
        request_headers = dict(kwargs.pop("headers", {}) or {})
        correlation_id = request_headers.get("X-Resto-CorrelationId", str(uuid4()))
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

    async def _get_xml(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> ET.Element:
        await self.authenticate()
        response = await self._raw_request(
            "GET",
            path,
            params=params,
            headers={"Accept": "application/xml"},
        )
        if response.status_code == 401:
            raise IikoAuthenticationError("IIKO_TOKEN_REJECTED")
        if response.status_code == 403:
            raise IikoAuthorizationError("IIKO_ACCESS_DENIED")
        if not response.is_success:
            raise IikoResponseError(response.status_code)
        return self._parse_xml_response(response)

    def _parse_xml_response(self, response: httpx.Response) -> ET.Element:
        if not response.content or len(response.content) > _MAX_XML_RESPONSE_BYTES:
            raise IikoContractError("Invalid iiko XML response size")
        upper_prefix = response.content[:4096].upper()
        if b"<!DOCTYPE" in upper_prefix or b"<!ENTITY" in upper_prefix:
            raise IikoContractError("Unsafe iiko XML response")
        try:
            return ET.fromstring(response.content)
        except ET.ParseError as error:
            password = self._settings.password
            login = self._settings.login
            preview = _sanitize_response_body(
                response.text,
                secret_values=(
                    self._token or "",
                    login.get_secret_value() if login is not None else "",
                    password.get_secret_value() if password is not None else "",
                ),
            )[:300]
            content_type = " ".join(
                response.headers.get("content-type", "<missing>").split()
            )[:200]
            raise IikoContractError(
                "Invalid iiko XML response "
                f"status={response.status_code} "
                f"content_type={content_type!r} "
                f"body_bytes={len(response.content)} "
                f"body_preview={preview!r}"
            ) from error

    async def get_suppliers(self) -> list[IikoSupplierDto]:
        root = await self._get_xml("/api/suppliers")
        return self._parse_people_xml(root, endpoint="suppliers")

    async def get_employees(self) -> list[IikoSupplierDto]:
        root = await self._get_xml("/api/employees")
        return self._parse_people_xml(root, endpoint="employees")

    @staticmethod
    def _parse_people_xml(
        root: ET.Element,
        *,
        endpoint: str,
    ) -> list[IikoSupplierDto]:
        def optional_text(element: ET.Element, name: str) -> str | None:
            child = next(
                (
                    item for item in element
                    if item.tag.rsplit("}", 1)[-1] == name
                ),
                None,
            )
            value = child.text.strip() if child is not None and child.text else ""
            return value or None

        def boolean(element: ET.Element, name: str) -> bool:
            value = optional_text(element, name)
            if value is None:
                return False
            if value.casefold() not in {"true", "false"}:
                raise IikoContractError(
                    f"Invalid iiko {endpoint} field field={name}"
                )
            return value.casefold() == "true"

        records: list[IikoSupplierDto] = []
        for element in root.iter():
            external_id = optional_text(element, "id")
            name = optional_text(element, "name")
            if external_id is None and name is None:
                continue
            if external_id is None or name is None:
                raise IikoContractError(
                    f"Missing iiko {endpoint} field field="
                    f"{'id' if external_id is None else 'name'}"
                )
            try:
                records.append(IikoSupplierDto(
                    external_id=external_id,
                    name=name,
                    code=optional_text(element, "code"),
                    is_supplier=boolean(element, "supplier"),
                    is_employee=boolean(element, "employee"),
                    represents_store=boolean(element, "representsStore"),
                    is_deleted=boolean(element, "deleted"),
                ))
            except ValidationError as error:
                field = ".".join(str(item) for item in error.errors()[0]["loc"])
                raise IikoContractError(
                    f"Invalid iiko {endpoint} field field={field}"
                ) from error
        return records

    async def get_accounts(self) -> list[IikoAccountDto]:
        payloads = await self._get_json_list(
            "/api/v2/entities/accounts/list",
            params={"includeDeleted": "true", "revisionFrom": "-1"},
        )
        accounts: list[IikoAccountDto] = []
        for index, payload in enumerate(payloads):
            account_id = str(payload.get("id") or "<unknown>")
            try:
                accounts.append(IikoAccountDto(
                    external_id=str(payload["id"]),
                    name=str(payload["name"]),
                    code=str(payload["code"]),
                    account_type=str(payload["type"]),
                    parent_external_id=(
                        str(payload["accountParentId"])
                        if payload.get("accountParentId") else None
                    ),
                    organization_external_id=(
                        str(payload["parentCorporateId"])
                        if payload.get("parentCorporateId") else None
                    ),
                    is_deleted=bool(payload.get("deleted", False)),
                ))
            except KeyError as error:
                raise IikoContractError(
                    "Missing iiko account field "
                    f"account_id={account_id} index={index} field={error.args[0]}"
                ) from error
            except ValidationError as error:
                field = ".".join(str(item) for item in error.errors()[0]["loc"])
                raise IikoContractError(
                    "Invalid iiko account field "
                    f"account_id={account_id} index={index} field={field}"
                ) from error
            except (TypeError, ValueError) as error:
                raise IikoContractError(
                    "Invalid iiko account contract "
                    f"account_id={account_id} index={index}: {error}"
                ) from error
        return accounts

    async def get_outgoing_invoices(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> list[IikoOutgoingInvoiceDto]:
        root = await self._get_xml(
            _OUTGOING_INVOICE_EXPORT_PATH,
            params={"from": date_from.isoformat(), "to": date_to.isoformat()},
        )

        def optional_text(document: ET.Element, name: str) -> str | None:
            element = next(
                (child for child in document if child.tag.rsplit("}", 1)[-1] == name),
                None,
            )
            value = (
                element.text.strip()
                if element is not None and element.text
                else ""
            )
            return value or None

        invoices: list[IikoOutgoingInvoiceDto] = []
        for document in root.iter():
            if document.tag.rsplit("}", 1)[-1] != "document":
                continue
            document_number = (
                optional_text(document, "documentNumber") or "<unknown>"
            )
            required_values = {
                field: optional_text(document, field)
                for field in (
                    "documentNumber",
                    "status",
                    "counteragentId",
                    "defaultStoreId",
                    "accountToCode",
                    "revenueAccountCode",
                )
            }
            missing_fields = [
                field for field, value in required_values.items() if not value
            ]
            if missing_fields:
                for field in missing_fields:
                    logger.warning(
                        "Skipping unusable historical outgoing invoice "
                        "document_number=%s missing_field=%s",
                        document_number,
                        field,
                    )
                continue
            try:
                items: list[IikoOutgoingInvoiceItemDto] = []
                items_element = next(
                    (
                        child for child in document
                        if child.tag.rsplit("}", 1)[-1] == "items"
                    ),
                    None,
                )
                if items_element is not None:
                    for item in items_element:
                        if item.tag.rsplit("}", 1)[-1] != "item":
                            continue
                        items.append(IikoOutgoingInvoiceItemDto(
                            product_id=optional_text(item, "productId"),
                            amount=optional_text(item, "amount"),
                            price=optional_text(item, "price"),
                        ))
                invoices.append(IikoOutgoingInvoiceDto(
                    external_id=optional_text(document, "id"),
                    document_number=required_values["documentNumber"],
                    date_incoming=optional_text(document, "dateIncoming"),
                    status=required_values["status"],
                    linked_incoming_invoice_id=(
                        optional_text(document, "linkedIncomingInvoiceId")
                    ),
                    counteragent_id=required_values["counteragentId"],
                    default_store_id=required_values["defaultStoreId"],
                    account_to_code=required_values["accountToCode"],
                    revenue_account_code=required_values["revenueAccountCode"],
                    revision=optional_text(document, "revision"),
                    items=tuple(items),
                    raw_document_xml=ET.tostring(document, encoding="utf-8"),
                ))
            except ValidationError as error:
                field = ".".join(str(item) for item in error.errors()[0]["loc"])
                raise IikoContractError(
                    "Invalid outgoing invoice field "
                    f"document_number={document_number} field={field}"
                ) from error
        return invoices

    @staticmethod
    def _validation_results(root: ET.Element) -> tuple[
        IikoDocumentValidationResultDto, ...
    ]:
        def local_name(element: ET.Element) -> str:
            return element.tag.rsplit("}", 1)[-1]

        def optional_text(element: ET.Element, name: str) -> str | None:
            child = next(
                (item for item in element if local_name(item) == name),
                None,
            )
            value = child.text.strip() if child is not None and child.text else ""
            return value or None

        candidates = [
            element for element in root.iter()
            if local_name(element) == "documentValidationResult"
        ]
        if local_name(root) == "documentValidationResult" and root not in candidates:
            candidates.insert(0, root)
        if not candidates:
            raise IikoContractError("IIKO_DOCUMENT_VALIDATION_RESPONSE_INVALID")

        results: list[IikoDocumentValidationResultDto] = []
        for element in candidates:
            bool_values: dict[str, bool] = {}
            for name in ("valid", "warning"):
                value = optional_text(element, name)
                if value is None or value.lower() not in {"true", "false"}:
                    raise IikoContractError(
                        f"IIKO_DOCUMENT_VALIDATION_RESPONSE_INVALID field={name}"
                    )
                bool_values[name] = value.lower() == "true"
            results.append(IikoDocumentValidationResultDto(
                valid=bool_values["valid"],
                warning=bool_values["warning"],
                document_number=optional_text(element, "documentNumber"),
                error_message=optional_text(element, "errorMessage"),
                additional_info=optional_text(element, "additionalInfo"),
            ))
        return tuple(results)

    def _log_validation_result(
        self,
        *,
        operation: str,
        result: IikoDocumentValidationResultDto,
    ) -> None:
        password = self._settings.password
        login = self._settings.login
        secrets = (
            self._token or "",
            password.get_secret_value() if password is not None else "",
            login.get_secret_value() if login is not None else "",
        )
        logger.info(
            "iiko document validation operation=%s valid=%s warning=%s "
            "document_number=%s error_message=%s additional_info=%s",
            operation,
            result.valid,
            result.warning,
            result.document_number,
            _sanitize_response_body(result.error_message or "", secret_values=secrets),
            _sanitize_response_body(result.additional_info or "", secret_values=secrets),
        )

    async def _post_legacy_document_rpc(
        self,
        path: str,
        *,
        params: Sequence[tuple[str, str]],
        content: bytes,
        call_id: UUID | None = None,
    ) -> ET.Element:
        await self.authenticate()
        login = self._settings.login
        password = self._settings.password
        if login is None or password is None:
            raise IikoConfigurationError("IIKO_NOT_CONFIGURED")
        password_hash = hashlib.sha1(
            password.get_secret_value().encode("utf-8")
        ).hexdigest()
        try:
            response = await self._raw_request(
                "POST",
                path,
                params=params,
                content=content,
                headers={
                    "Accept": "application/xml, text/plain",
                    "Content-Type": "text/xml",
                    "X-Resto-CorrelationId": str(call_id or uuid4()),
                    "X-Resto-LoginName": login.get_secret_value(),
                    "X-Resto-PasswordHash": password_hash,
                    "X-Resto-BackVersion": _BACK_VERSION,
                    "X-Resto-AuthType": "BACK",
                    "X-Resto-ServerEdition": "CHAIN",
                },
            )
        finally:
            password_hash = ""
        if response.status_code == 401:
            raise IikoAuthenticationError("IIKO_TOKEN_REJECTED")
        if response.status_code == 403:
            raise IikoAuthorizationError("IIKO_ACCESS_DENIED")
        if not response.is_success:
            raise IikoResponseError(response.status_code)
        return self._parse_xml_response(response)

    @staticmethod
    def _rpc_direct_text(element: ET.Element, *names: str) -> str | None:
        for child in element:
            if child.tag.rsplit("}", 1)[-1] in names:
                value = (child.text or "").strip()
                if value:
                    return value
        return None

    async def _get_current_rpc_entities_version(self) -> int:
        seed = self._settings.rpc_entities_version_seed
        expected_instance_id = self._settings.rpc_server_instance_id
        if seed is None or expected_instance_id is None:
            raise IikoConfigurationError("IIKO_RPC_ENTITY_SYNC_NOT_CONFIGURED")

        call_id = uuid4()
        args = ET.Element("args")
        for name, value in (
            ("entities-version", str(seed)),
            ("client-type", "BACK"),
            ("enable-warnings", "true"),
            ("client-call-id", str(call_id)),
            ("use-raw-entities", "true"),
            ("fromRevision", str(seed)),
            ("timeoutMillis", "0"),
            ("useRawEntities", "true"),
        ):
            ET.SubElement(args, name).text = value
        response = await self._post_legacy_document_rpc(
            _UPDATE_SERVICE_PATH,
            params=(("methodName", "getEntitiesUpdate"),),
            content=b"\xef\xbb\xbf" + ET.tostring(
                args, encoding="utf-8", xml_declaration=True
            ),
            call_id=call_id,
        )
        success = self._rpc_direct_text(response, "success")
        result_status = self._rpc_direct_text(response, "resultStatus")
        updates = [
            element for element in response.iter()
            if element.tag.rsplit("}", 1)[-1] == "returnValue"
            and self._rpc_direct_text(element, "serverInstanceId") is not None
            and self._rpc_direct_text(element, "revision") is not None
        ]
        if success != "true" or result_status != "SUCCESS" or len(updates) != 1:
            raise IikoContractError("IIKO_RPC_ENTITY_SYNC_INVALID")
        update = updates[0]
        instance_id = self._rpc_direct_text(update, "serverInstanceId")
        revision = self._rpc_direct_text(update, "revision")
        full_update = self._rpc_direct_text(update, "fullUpdate")
        try:
            parsed_instance_id = UUID(instance_id or "")
            parsed_revision = int(revision or "")
        except (TypeError, ValueError) as error:
            raise IikoContractError("IIKO_RPC_ENTITY_SYNC_INVALID") from error
        if parsed_instance_id != expected_instance_id:
            raise IikoContractError("IIKO_RPC_SERVER_INSTANCE_MISMATCH")
        if full_update != "false":
            raise IikoContractError("IIKO_RPC_FULL_SYNC_REQUIRED")
        if parsed_revision < seed:
            raise IikoContractError("IIKO_RPC_ENTITY_REVISION_INVALID")
        return parsed_revision

    async def get_outgoing_invoice_for_update(
        self,
        document_id: UUID,
    ) -> IikoOutgoingInvoiceUpdateSourceDto:
        current_entities_version = await self._get_current_rpc_entities_version()
        call_id = uuid4()
        args = ET.Element("args")
        for name, value in (
            ("entities-version", str(current_entities_version)),
            ("client-type", "BACK"),
            ("enable-warnings", "true"),
            ("client-call-id", str(call_id)),
            ("use-raw-entities", "true"),
            ("id", str(document_id)),
        ):
            ET.SubElement(args, name).text = value
        response = await self._post_legacy_document_rpc(
            _DOCUMENT_SERVICE_PATH,
            params=(("methodName", "getAbstractDocument"),),
            content=b"\xef\xbb\xbf" + ET.tostring(
                args, encoding="utf-8", xml_declaration=True
            ),
            call_id=call_id,
        )

        def local_name(element: ET.Element) -> str:
            return element.tag.rsplit("}", 1)[-1]

        direct_text = self._rpc_direct_text

        success = direct_text(response, "success")
        result_status = direct_text(response, "resultStatus")
        documents = [
            element for element in response.iter()
            if local_name(element) == "returnValue"
            and element.attrib.get("cls") == "OutgoingInvoice"
        ]
        if success != "true" or result_status != "SUCCESS" or len(documents) != 1:
            raise IikoContractError("IIKO_OUTGOING_INVOICE_RPC_READ_INVALID")
        document = documents[0]
        external_id = direct_text(document, "id") or document.attrib.get("eid")
        document_number = direct_text(document, "documentNumber")
        status = direct_text(document, "status")
        revision = direct_text(document, "revision")
        entities_update = next(
            (
                element for element in response.iter()
                if local_name(element) == "entitiesUpdate"
            ),
            None,
        )
        entities_version = (
            direct_text(entities_update, "revision")
            if entities_update is not None else None
        )
        entities_instance_id = (
            direct_text(entities_update, "serverInstanceId")
            if entities_update is not None else None
        )
        full_update = (
            direct_text(entities_update, "fullUpdate")
            if entities_update is not None else None
        )
        if (
            external_id is None
            or document_number is None
            or status is None
            or revision is None
            or entities_version is None
        ):
            raise IikoContractError("IIKO_OUTGOING_INVOICE_RPC_READ_INVALID")
        try:
            if UUID(external_id) != document_id:
                raise ValueError
            parsed_revision = int(revision)
            parsed_entities_version = int(entities_version)
            parsed_entities_instance_id = UUID(entities_instance_id or "")
            items_element = next(
                (child for child in document if local_name(child) == "items"),
                None,
            )
            items = tuple(
                IikoOutgoingInvoiceItemDto(
                    product_id=direct_text(item, "productId", "product"),
                    amount=direct_text(item, "amount"),
                    price=direct_text(item, "price") or "0",
                )
                for item in (() if items_element is None else items_element)
                if local_name(item) == "item"
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise IikoContractError(
                "IIKO_OUTGOING_INVOICE_RPC_READ_INVALID"
            ) from error
        if (
            parsed_entities_instance_id
            != self._settings.rpc_server_instance_id
        ):
            raise IikoContractError("IIKO_RPC_SERVER_INSTANCE_MISMATCH")
        if full_update != "false":
            raise IikoContractError("IIKO_RPC_FULL_SYNC_REQUIRED")
        if parsed_entities_version < current_entities_version:
            raise IikoContractError("IIKO_RPC_ENTITY_REVISION_INVALID")
        update_document = deepcopy(document)
        update_document.tag = "document"
        return IikoOutgoingInvoiceUpdateSourceDto(
            external_id=str(document_id),
            document_number=document_number,
            status=status,
            revision=parsed_revision,
            entities_version=parsed_entities_version,
            items=items,
            raw_document_xml=ET.tostring(update_document, encoding="utf-8"),
        )

    async def update_outgoing_invoice(
        self,
        document: IikoOutgoingInvoiceUpdateSourceDto,
        *,
        actual_quantities: Sequence[Decimal],
    ) -> IikoDocumentValidationResultDto:
        if document.status != "NEW":
            raise IikoContractError("IIKO_OUTGOING_INVOICE_NOT_NEW")
        if document.revision is None or document.raw_document_xml is None:
            raise IikoContractError("IIKO_OUTGOING_INVOICE_REVISION_REQUIRED")
        try:
            document_id = UUID(document.external_id or "")
            root = ET.fromstring(document.raw_document_xml)
        except (ValueError, ET.ParseError) as error:
            raise IikoContractError("IIKO_OUTGOING_INVOICE_UPDATE_INVALID") from error
        id_element = next(
            (item for item in root if item.tag.rsplit("}", 1)[-1] == "id"),
            None,
        )
        revision_element = next(
            (item for item in root if item.tag.rsplit("}", 1)[-1] == "revision"),
            None,
        )
        if (
            id_element is None
            or (id_element.text or "").strip() != str(document_id)
            or revision_element is None
            or (revision_element.text or "").strip() != str(document.revision)
        ):
            raise IikoContractError("IIKO_OUTGOING_INVOICE_UPDATE_IDENTITY_INVALID")
        items_element = next(
            (item for item in root if item.tag.rsplit("}", 1)[-1] == "items"),
            None,
        )
        item_elements = [] if items_element is None else [
            item for item in items_element
            if item.tag.rsplit("}", 1)[-1] == "item"
        ]
        if len(item_elements) != len(actual_quantities):
            raise IikoContractError("IIKO_OUTGOING_INVOICE_ITEMS_MISMATCH")
        update_root = deepcopy(root)
        update_items_element = next(
            item for item in update_root
            if item.tag.rsplit("}", 1)[-1] == "items"
        )
        update_items = [
            item for item in update_items_element
            if item.tag.rsplit("}", 1)[-1] == "item"
        ]
        for item, quantity in zip(update_items, actual_quantities, strict=True):
            if not quantity.is_finite() or quantity < 0:
                raise IikoContractError("IIKO_OUTGOING_INVOICE_QUANTITY_INVALID")
            amount = next(
                (child for child in item if child.tag.rsplit("}", 1)[-1] == "amount"),
                None,
            )
            if amount is None:
                raise IikoContractError("IIKO_OUTGOING_INVOICE_ITEMS_MISMATCH")
            amount.text = format(quantity, "f")
        call_id = uuid4()
        args = ET.Element("args")
        for name, value in (
            ("entities-version", str(document.entities_version)),
            ("client-type", "BACK"),
            ("enable-warnings", "true"),
            ("client-call-id", str(call_id)),
            ("use-raw-entities", "true"),
        ):
            ET.SubElement(args, name).text = value
        args.append(update_root)
        ET.SubElement(args, "suppressWarnings", {"cls": "java.util.ArrayList"})
        response = await self._post_legacy_document_rpc(
            _DOCUMENT_SERVICE_PATH,
            params=(("methodName", "saveOrUpdateDocument"),),
            content=b"\xef\xbb\xbf" + ET.tostring(
                args, encoding="utf-8", xml_declaration=True
            ),
            call_id=call_id,
        )
        results = self._validation_results(response)
        if len(results) != 1:
            raise IikoContractError("IIKO_DOCUMENT_VALIDATION_RESPONSE_INVALID")
        result = results[0]
        self._log_validation_result(operation="update", result=result)
        return result

    async def process_outgoing_invoices(
        self,
        document_ids: Sequence[UUID],
        *,
        enable_warnings: bool,
    ) -> tuple[IikoDocumentValidationResultDto, ...]:
        if not document_ids or len(set(document_ids)) != len(document_ids):
            raise IikoContractError("IIKO_DOCUMENT_IDS_INVALID")
        root = ET.Element("documentIds")
        for document_id in document_ids:
            ET.SubElement(root, "documentId").text = str(document_id)
        response = await self._post_legacy_document_rpc(
            _DOCUMENT_GROUP_OPERATION_PATH,
            params=(
                ("methodName", "processDocuments"),
                ("enable-warnings", "true" if enable_warnings else "false"),
            ),
            content=ET.tostring(root, encoding="utf-8"),
        )
        results = self._validation_results(response)
        for result in results:
            self._log_validation_result(operation="process", result=result)
        return results

    async def create_outgoing_invoice(
        self,
        document: IikoOutgoingInvoiceCreateDto,
    ) -> IikoOutgoingInvoiceCreateResultDto:
        if document.status != "NEW":
            raise IikoContractError("IIKO_OUTGOING_INVOICE_STATUS_INVALID")
        await self.authenticate()
        response = await self._raw_request(
            "POST",
            _OUTGOING_INVOICE_IMPORT_PATH,
            content=document.to_iiko_xml(),
            headers={
                "Accept": "application/xml, text/plain",
                "Content-Type": "application/xml",
            },
        )
        if response.status_code == 401:
            raise IikoAuthenticationError("IIKO_TOKEN_REJECTED")
        if response.status_code == 403:
            raise IikoAuthorizationError("IIKO_ACCESS_DENIED")
        if not response.is_success:
            raise IikoResponseError(response.status_code)
        results = self._validation_results(self._parse_xml_response(response))
        if len(results) != 1 or results[0].document_number is None:
            raise IikoContractError("IIKO_OUTGOING_INVOICE_RESPONSE_INVALID")
        validation = results[0]
        self._log_validation_result(operation="create", result=validation)
        if not validation.valid:
            raise IikoContractError(
                "IIKO_OUTGOING_INVOICE_VALIDATION_FAILED"
            )
        return IikoOutgoingInvoiceCreateResultDto(
            client_document_id=document.document_id,
            document_number=validation.document_number,
            valid=True,
            warning=validation.warning,
        )

    async def get_incoming_invoices(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> list[IikoIncomingInvoiceDto]:
        root = await self._get_xml(
            _INCOMING_INVOICE_EXPORT_PATH,
            params={"from": date_from.isoformat(), "to": date_to.isoformat()},
        )

        def optional_text(document: ET.Element, name: str) -> str | None:
            element = next(
                (
                    child for child in document
                    if child.tag.rsplit("}", 1)[-1] == name
                ),
                None,
            )
            value = (
                element.text.strip()
                if element is not None and element.text
                else ""
            )
            return value or None

        invoices: list[IikoIncomingInvoiceDto] = []
        for document in root.iter():
            if document.tag.rsplit("}", 1)[-1] != "document":
                continue
            document_number = (
                optional_text(document, "documentNumber") or "<unknown>"
            )
            required_values = {
                field: optional_text(document, field)
                for field in (
                    "id",
                    "documentNumber",
                    "status",
                    "defaultStore",
                )
            }
            missing_fields = [
                field for field, value in required_values.items() if not value
            ]
            if missing_fields:
                for field in missing_fields:
                    logger.warning(
                        "Skipping unusable historical incoming invoice "
                        "document_number=%s missing_field=%s",
                        document_number,
                        field,
                    )
                continue
            try:
                invoices.append(IikoIncomingInvoiceDto(
                    external_id=required_values["id"],
                    document_number=required_values["documentNumber"],
                    status=required_values["status"],
                    default_store_id=required_values["defaultStore"],
                    supplier_id=optional_text(document, "supplier"),
                ))
            except ValidationError as error:
                field = ".".join(str(item) for item in error.errors()[0]["loc"])
                raise IikoContractError(
                    "Invalid incoming invoice field "
                    f"document_number={document_number} field={field}"
                ) from error
        return invoices

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
            ("timestamp", _serialize_balance_stores_timestamp(calculated_at))
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
        deleted_filtered = 0
        for payload in payloads:
            product_id = payload.get("product")
            product = products.get(product_id)
            if (
                not include_deleted
                and product is not None
                and product.is_deleted
            ):
                deleted_filtered += 1
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
        logger.warning(
            "iiko balance/stores response counts "
            "store=%s raw_rows=%s deleted_filtered=%s returned_rows=%s "
            "positive_rows=%s negative_rows=%s zero_rows=%s",
            ",".join(warehouse_ids),
            len(payloads),
            deleted_filtered,
            len(records),
            sum(record.dto.quantity > 0 for record in records),
            sum(record.dto.quantity < 0 for record in records),
            sum(record.dto.quantity == 0 for record in records),
        )
        return records

    async def aclose(self) -> None:
        token = self._token
        self._products_cache = None
        self._warehouses_cache = None
        if token:
            try:
                async with self._request_lock:
                    await self._client.get(
                        "api/logout",
                        headers={"Cookie": f"key={token}"},
                    )
            except Exception:
                logger.warning(
                    "iiko logout failed",
                    extra={"integration": "iiko", "event": "logout_failed"},
                )
            finally:
                self._token = None
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
