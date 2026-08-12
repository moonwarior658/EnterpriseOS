import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.iiko.document_write import (
    IikoOutgoingInvoiceLineInput,
    build_controlled_outgoing_invoice,
)
from app.integrations.iiko.document_routing import (
    resolve_outgoing_invoice_route,
)
from app.integrations.iiko.exceptions import (
    IikoAuthenticationError,
    IikoAuthorizationError,
    IikoConfigurationError,
    IikoConnectionError,
    IikoContractError,
    IikoError,
    IikoRateLimitError,
    IikoResponseError,
)
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import (
    IikoOutgoingInvoiceCreateDto,
    IikoOutgoingInvoiceDto,
)
from app.models.iiko import (
    IikoDocumentType,
    IikoDocumentWrite,
    IikoDocumentWriteStatus,
)
from app.models.supply import SupplyProductSourceRole, SupplyRequest


class IikoDocumentIntentError(IikoContractError):
    pass


class IikoDocumentSupplyRequestNotFoundError(IikoDocumentIntentError):
    pass


class IikoDocumentPayloadConflictError(IikoDocumentIntentError):
    pass


class IikoDocumentReconciliationRequiredError(IikoDocumentIntentError):
    pass


class IikoDocumentRetryNotAllowedError(IikoDocumentIntentError):
    pass


class IikoDocumentIntentStateError(IikoDocumentIntentError):
    pass


class IikoDocumentReconciliationConflictError(IikoDocumentIntentError):
    pass


class IikoDocumentAuthoritativeReadBackError(IikoDocumentIntentError):
    pass


class IikoDocumentReconciliationOutcome(StrEnum):
    CREATED = "CREATED"
    FOUND_MATCH = "FOUND_MATCH"
    NOT_FOUND = "NOT_FOUND"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class IikoDocumentReconciliationResult:
    outcome: IikoDocumentReconciliationOutcome
    client_document_id: UUID
    iiko_document_id: UUID | None
    document_number: str | None
    status: IikoDocumentWriteStatus
    safe_to_retry: bool


_RECONCILABLE_STATUSES = {
    IikoDocumentWriteStatus.PENDING,
    IikoDocumentWriteStatus.UNKNOWN,
}

class IikoOutgoingInvoiceReadBackOutcome(StrEnum):
    VERIFIED_MATCH = "VERIFIED_MATCH"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class IikoOutgoingInvoiceReadBackMatch:
    outcome: IikoOutgoingInvoiceReadBackOutcome
    invoice: IikoOutgoingInvoiceDto | None = None
    iiko_document_id: UUID | None = None


def _payload_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _normalized_payload(
    document: IikoOutgoingInvoiceCreateDto,
) -> dict:
    return document.model_dump(mode="json")


def _document_from_intent(
    intent: IikoDocumentWrite,
) -> IikoOutgoingInvoiceCreateDto:
    if intent.expected_payload is None:
        raise IikoDocumentIntentStateError(
            "IIKO_DOCUMENT_EXPECTED_PAYLOAD_MISSING"
        )
    try:
        document = IikoOutgoingInvoiceCreateDto.model_validate(
            intent.expected_payload
        )
    except Exception as error:
        raise IikoDocumentIntentStateError(
            "IIKO_DOCUMENT_EXPECTED_PAYLOAD_INVALID"
        ) from error
    if (
        document.document_id != intent.client_document_id
        or document.default_store_id != intent.source_store_id
    ):
        raise IikoDocumentIntentStateError(
            "IIKO_DOCUMENT_EXPECTED_PAYLOAD_INVALID"
        )
    return document


def is_outgoing_invoice_retry_safe(
    intent: IikoDocumentWrite,
    *,
    authoritative_absence_confirmed: bool,
    current_payload_hash: str,
) -> bool:
    return (
        intent.status != IikoDocumentWriteStatus.CREATED
        and authoritative_absence_confirmed
        and current_payload_hash == intent.payload_hash
    )


def _result(
    intent: IikoDocumentWrite,
    outcome: IikoDocumentReconciliationOutcome,
    *,
    safe_to_retry: bool = False,
) -> IikoDocumentReconciliationResult:
    return IikoDocumentReconciliationResult(
        outcome=outcome,
        client_document_id=intent.client_document_id,
        iiko_document_id=intent.iiko_document_id,
        document_number=intent.iiko_document_number,
        status=intent.status,
        safe_to_retry=safe_to_retry,
    )


def _matches_expected_document_payload(
    actual: IikoOutgoingInvoiceDto,
    expected: IikoOutgoingInvoiceCreateDto,
) -> bool:
    try:
        actual_store_id = UUID(actual.default_store_id)
        actual_counteragent_id = UUID(actual.counteragent_id)
    except ValueError:
        return False
    actual_items = Counter(
        (item.product_id, item.amount, item.price)
        for item in actual.items
    )
    expected_items = Counter(
        (item.product_id, item.amount, Decimal(item.price))
        for item in expected.items
    )
    return (
        actual_store_id == expected.default_store_id
        and actual_counteragent_id == expected.counteragent_id
        and actual.account_to_code == expected.account_to_code
        and actual.revenue_account_code == expected.revenue_account_code
        and actual_items == expected_items
    )


def match_authoritative_outgoing_invoice(
    intent: IikoDocumentWrite,
    expected: IikoOutgoingInvoiceCreateDto,
    invoices: Sequence[IikoOutgoingInvoiceDto],
) -> IikoOutgoingInvoiceReadBackMatch:
    document_number = intent.iiko_document_number
    if not document_number:
        return IikoOutgoingInvoiceReadBackMatch(
            outcome=IikoOutgoingInvoiceReadBackOutcome.NOT_FOUND
        )

    same_number = [
        invoice
        for invoice in invoices
        if invoice.document_number == document_number
    ]
    if not same_number:
        return IikoOutgoingInvoiceReadBackMatch(
            outcome=IikoOutgoingInvoiceReadBackOutcome.NOT_FOUND
        )

    full_matches = [
        invoice
        for invoice in same_number
        if _matches_expected_document_payload(invoice, expected)
    ]
    if not full_matches:
        return IikoOutgoingInvoiceReadBackMatch(
            outcome=IikoOutgoingInvoiceReadBackOutcome.CONFLICT
        )
    if len(full_matches) > 1:
        return IikoOutgoingInvoiceReadBackMatch(
            outcome=IikoOutgoingInvoiceReadBackOutcome.AMBIGUOUS
        )

    invoice = full_matches[0]
    try:
        iiko_document_id = UUID(invoice.external_id or "")
    except ValueError:
        return IikoOutgoingInvoiceReadBackMatch(
            outcome=IikoOutgoingInvoiceReadBackOutcome.CONFLICT
        )
    return IikoOutgoingInvoiceReadBackMatch(
        outcome=IikoOutgoingInvoiceReadBackOutcome.VERIFIED_MATCH,
        invoice=invoice,
        iiko_document_id=iiko_document_id,
    )


async def read_verified_outgoing_invoice(
    provider: IikoProvider,
    *,
    intent: IikoDocumentWrite,
) -> IikoOutgoingInvoiceDto:
    if (
        intent.document_type != IikoDocumentType.OUTGOING_INVOICE
        or intent.status != IikoDocumentWriteStatus.CREATED
        or intent.iiko_document_id is None
    ):
        raise IikoDocumentAuthoritativeReadBackError(
            "SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED"
        )
    expected = _document_from_intent(intent)
    document_date = expected.date_incoming.date()
    invoices = await provider.get_outgoing_invoices(
        date_from=document_date - timedelta(days=1),
        date_to=document_date + timedelta(days=1),
    )
    read_back = match_authoritative_outgoing_invoice(
        intent,
        expected,
        invoices,
    )
    if read_back.outcome == IikoOutgoingInvoiceReadBackOutcome.NOT_FOUND:
        raise IikoDocumentAuthoritativeReadBackError(
            "SUPPLY_IIKO_DOCUMENT_READBACK_NOT_FOUND"
        )
    if (
        read_back.outcome != IikoOutgoingInvoiceReadBackOutcome.VERIFIED_MATCH
        or read_back.invoice is None
        or read_back.iiko_document_id != intent.iiko_document_id
    ):
        raise IikoDocumentAuthoritativeReadBackError(
            "SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED"
        )
    return read_back.invoice


async def reconcile_outgoing_invoice_intent(
    session: Session,
    provider: IikoProvider,
    *,
    intent_id: UUID,
) -> IikoDocumentReconciliationResult:
    if session.in_transaction():
        raise IikoDocumentIntentStateError(
            "IIKO_DOCUMENT_SESSION_TRANSACTION_ACTIVE"
        )

    with session.begin():
        intent = session.get(IikoDocumentWrite, intent_id)
        if intent is None:
            raise IikoDocumentIntentStateError(
                "IIKO_DOCUMENT_INTENT_NOT_FOUND"
            )
        if intent.document_type != IikoDocumentType.OUTGOING_INVOICE:
            raise IikoDocumentIntentStateError(
                "IIKO_DOCUMENT_TYPE_NOT_RECONCILABLE"
            )
        if (
            intent.status == IikoDocumentWriteStatus.CREATED
            and intent.iiko_document_id is not None
        ):
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.CREATED,
            )
        if (
            intent.status not in _RECONCILABLE_STATUSES
            and intent.status != IikoDocumentWriteStatus.CREATED
        ):
            raise IikoDocumentRetryNotAllowedError(
                "IIKO_DOCUMENT_RECONCILIATION_NOT_ALLOWED"
            )
        expected = _document_from_intent(intent)
        document_date = expected.date_incoming.date()

    try:
        invoices = await provider.get_outgoing_invoices(
            date_from=document_date - timedelta(days=1),
            date_to=document_date + timedelta(days=1),
        )
    except IikoConnectionError as error:
        with session.begin():
            intent = _locked_intent(session, intent_id=intent_id)
            if intent.status == IikoDocumentWriteStatus.CREATED:
                return _result(
                    intent,
                    IikoDocumentReconciliationOutcome.UNCERTAIN,
                )
            if intent.status in _RECONCILABLE_STATUSES:
                intent.status = IikoDocumentWriteStatus.UNKNOWN
                intent.last_error = _safe_error_code(error)
                return _result(
                    intent,
                    IikoDocumentReconciliationOutcome.UNCERTAIN,
                )
            raise IikoDocumentIntentStateError(
                "IIKO_DOCUMENT_INTENT_STATE_CHANGED"
            ) from error

    reconciliation_error: str | None = None
    with session.begin():
        intent = _locked_intent(session, intent_id=intent_id)
        if (
            intent.status == IikoDocumentWriteStatus.CREATED
            and intent.iiko_document_id is not None
        ):
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.CREATED,
            )
        if (
            intent.status not in _RECONCILABLE_STATUSES
            and intent.status != IikoDocumentWriteStatus.CREATED
        ):
            raise IikoDocumentIntentStateError(
                "IIKO_DOCUMENT_INTENT_STATE_CHANGED"
            )
        current_expected = _document_from_intent(intent)
        read_back = match_authoritative_outgoing_invoice(
            intent,
            current_expected,
            invoices,
        )

        if read_back.outcome == IikoOutgoingInvoiceReadBackOutcome.NOT_FOUND:
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.UNCERTAIN,
            )

        if read_back.outcome in {
            IikoOutgoingInvoiceReadBackOutcome.CONFLICT,
            IikoOutgoingInvoiceReadBackOutcome.AMBIGUOUS,
        }:
            reconciliation_error = (
                "IIKO_DOCUMENT_RECONCILIATION_"
                f"{read_back.outcome.value}"
            )
            intent.last_error = reconciliation_error
        else:
            if read_back.invoice is None or read_back.iiko_document_id is None:
                raise IikoDocumentIntentStateError(
                    "IIKO_DOCUMENT_RECONCILIATION_INVALID_RESULT"
                )
            intent.iiko_document_id = read_back.iiko_document_id
            intent.iiko_document_number = read_back.invoice.document_number
            intent.status = IikoDocumentWriteStatus.CREATED
            intent.last_error = None
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.FOUND_MATCH,
            )

    if reconciliation_error is not None:
        raise IikoDocumentReconciliationConflictError(
            reconciliation_error
        )
    raise IikoDocumentIntentStateError(
        "IIKO_DOCUMENT_RECONCILIATION_INVALID_RESULT"
    )


def _safe_error_code(error: Exception) -> str:
    message = str(error)
    if isinstance(error, IikoResponseError):
        return f"IIKO_RESPONSE_ERROR_{error.status_code}"
    if isinstance(error, IikoContractError) and message.startswith("IIKO_"):
        return message[:160]
    if isinstance(error, IikoError):
        return error.code
    return "IIKO_INTERNAL_ERROR"


def _failure_status(error: Exception) -> IikoDocumentWriteStatus:
    if isinstance(error, IikoConnectionError):
        return IikoDocumentWriteStatus.UNKNOWN
    if isinstance(
        error,
        (
            IikoAuthenticationError,
            IikoAuthorizationError,
            IikoConfigurationError,
            IikoRateLimitError,
            IikoResponseError,
        ),
    ):
        return IikoDocumentWriteStatus.FAILED
    if (
        isinstance(error, IikoContractError)
        and str(error) == "IIKO_OUTGOING_INVOICE_VALIDATION_FAILED"
    ):
        return IikoDocumentWriteStatus.FAILED
    return IikoDocumentWriteStatus.UNKNOWN


def _locked_intent(
    session: Session,
    *,
    intent_id: UUID,
) -> IikoDocumentWrite:
    intent = session.scalar(
        select(IikoDocumentWrite)
        .where(IikoDocumentWrite.id == intent_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if intent is None:
        raise IikoDocumentIntentStateError(
            "IIKO_DOCUMENT_INTENT_NOT_FOUND"
        )
    return intent


def _record_failure(
    session: Session,
    *,
    intent_id: UUID,
    error: Exception,
) -> None:
    with session.begin():
        intent = _locked_intent(session, intent_id=intent_id)
        if intent.status != IikoDocumentWriteStatus.PENDING:
            raise IikoDocumentIntentStateError(
                "IIKO_DOCUMENT_INTENT_STATE_CHANGED"
            )
        intent.status = _failure_status(error)
        intent.last_error = _safe_error_code(error)


async def create_persistent_outgoing_invoice(
    session: Session,
    provider: IikoProvider,
    *,
    supply_request_id: UUID,
    date_incoming: datetime,
    department_code: str,
    flow: SupplyProductSourceRole | str,
    lines: Sequence[IikoOutgoingInvoiceLineInput],
    allow_failed_retry: bool = False,
) -> IikoDocumentWrite:
    if session.in_transaction():
        raise IikoDocumentIntentStateError(
            "IIKO_DOCUMENT_SESSION_TRANSACTION_ACTIVE"
        )

    route = resolve_outgoing_invoice_route(department_code, flow)
    should_submit = False
    document = None

    with session.begin():
        supply_request = session.scalar(
            select(SupplyRequest)
            .where(SupplyRequest.id == supply_request_id)
            .with_for_update(of=SupplyRequest)
        )
        if supply_request is None:
            raise IikoDocumentSupplyRequestNotFoundError(
                "IIKO_DOCUMENT_SUPPLY_REQUEST_NOT_FOUND"
            )

        existing = session.scalar(
            select(IikoDocumentWrite)
            .where(
                IikoDocumentWrite.supply_request_id == supply_request_id,
                IikoDocumentWrite.source_store_id
                == route.source_store_id,
                IikoDocumentWrite.document_type
                == IikoDocumentType.OUTGOING_INVOICE,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        document_id = (
            existing.client_document_id
            if existing is not None
            else uuid4()
        )
        document = build_controlled_outgoing_invoice(
            document_id=document_id,
            date_incoming=date_incoming,
            department_code=department_code,
            flow=flow,
            lines=lines,
        )
        digest = _payload_hash(document.to_iiko_xml())

        if existing is None:
            intent = IikoDocumentWrite(
                supply_request_id=supply_request_id,
                source_store_id=document.default_store_id,
                document_type=IikoDocumentType.OUTGOING_INVOICE,
                client_document_id=document.document_id,
                status=IikoDocumentWriteStatus.PENDING,
                payload_hash=digest,
                expected_payload=_normalized_payload(document),
            )
            session.add(intent)
            session.flush()
            should_submit = True
        else:
            intent = existing
            if intent.expected_payload is None:
                intent.expected_payload = _normalized_payload(document)
            if intent.payload_hash != digest:
                raise IikoDocumentPayloadConflictError(
                    "IIKO_DOCUMENT_PAYLOAD_CONFLICT"
                )
            if intent.status == IikoDocumentWriteStatus.CREATED:
                return intent
            if intent.status in {
                IikoDocumentWriteStatus.PENDING,
                IikoDocumentWriteStatus.UNKNOWN,
            }:
                raise IikoDocumentReconciliationRequiredError(
                    "IIKO_DOCUMENT_RECONCILIATION_REQUIRED"
                )
            if not allow_failed_retry:
                raise IikoDocumentRetryNotAllowedError(
                    "IIKO_DOCUMENT_RETRY_NOT_ALLOWED"
                )
            intent.status = IikoDocumentWriteStatus.PENDING
            intent.last_error = None
            should_submit = True

        intent_id = intent.id

    if not should_submit or document is None:
        raise IikoDocumentIntentStateError(
            "IIKO_DOCUMENT_INTENT_NOT_SUBMITTABLE"
        )

    try:
        result = await provider.create_outgoing_invoice(document)
        if (
            result.client_document_id != document.document_id
            or not result.valid
        ):
            raise IikoContractError(
                "IIKO_OUTGOING_INVOICE_RESULT_INVALID"
            )
    except Exception as error:
        _record_failure(session, intent_id=intent_id, error=error)
        raise

    with session.begin():
        intent = _locked_intent(session, intent_id=intent_id)
        if intent.status != IikoDocumentWriteStatus.PENDING:
            raise IikoDocumentIntentStateError(
                "IIKO_DOCUMENT_INTENT_STATE_CHANGED"
            )
        intent.iiko_document_number = result.document_number
        intent.status = IikoDocumentWriteStatus.CREATED
        intent.last_error = None

    return intent
