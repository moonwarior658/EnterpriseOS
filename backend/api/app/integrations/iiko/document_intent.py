import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
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


class IikoDocumentReconciliationOutcome(StrEnum):
    CREATED = "CREATED"
    FOUND_MATCH = "FOUND_MATCH"
    NOT_FOUND = "NOT_FOUND"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class IikoDocumentReconciliationResult:
    outcome: IikoDocumentReconciliationOutcome
    document_id: UUID
    document_number: str | None
    status: IikoDocumentWriteStatus
    safe_to_retry: bool


_RECONCILABLE_STATUSES = {
    IikoDocumentWriteStatus.PENDING,
    IikoDocumentWriteStatus.UNKNOWN,
}
_MATCHABLE_IIKO_STATUSES = {"NEW", "PROCESSED"}


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
    if document.document_id != intent.iiko_document_id:
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
        document_id=intent.iiko_document_id,
        document_number=intent.iiko_document_number,
        status=intent.status,
        safe_to_retry=safe_to_retry,
    )


def _matches_expected_document(
    actual: IikoOutgoingInvoiceDto,
    expected: IikoOutgoingInvoiceCreateDto,
) -> bool:
    try:
        actual_id = UUID(actual.external_id or "")
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
        actual_id == expected.document_id
        and actual_store_id == expected.default_store_id
        and actual_counteragent_id == expected.counteragent_id
        and actual.status in _MATCHABLE_IIKO_STATUSES
        and actual.account_to_code == expected.account_to_code
        and actual.revenue_account_code == expected.revenue_account_code
        and actual_items == expected_items
    )


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
        if intent.status == IikoDocumentWriteStatus.CREATED:
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.CREATED,
            )
        if intent.status not in _RECONCILABLE_STATUSES:
            raise IikoDocumentRetryNotAllowedError(
                "IIKO_DOCUMENT_RECONCILIATION_NOT_ALLOWED"
            )
        expected = _document_from_intent(intent)
        document_id = intent.iiko_document_id
        document_date = expected.date_incoming.date()

    try:
        invoices = await provider.get_outgoing_invoices(
            date_from=document_date,
            date_to=document_date,
        )
    except IikoConnectionError as error:
        with session.begin():
            intent = _locked_intent(session, intent_id=intent_id)
            if intent.status == IikoDocumentWriteStatus.CREATED:
                return _result(
                    intent,
                    IikoDocumentReconciliationOutcome.CREATED,
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

    matches = [
        invoice for invoice in invoices
        if invoice.external_id is not None
        and invoice.external_id.casefold() == str(document_id).casefold()
    ]

    conflict = False
    with session.begin():
        intent = _locked_intent(session, intent_id=intent_id)
        if intent.status == IikoDocumentWriteStatus.CREATED:
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.CREATED,
            )
        if intent.status not in _RECONCILABLE_STATUSES:
            raise IikoDocumentIntentStateError(
                "IIKO_DOCUMENT_INTENT_STATE_CHANGED"
            )
        current_expected = _document_from_intent(intent)
        current_payload_hash = _payload_hash(
            current_expected.to_iiko_xml()
        )

        if not matches:
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.UNCERTAIN,
                safe_to_retry=is_outgoing_invoice_retry_safe(
                    intent,
                    # export/outgoingInvoice is not authoritative for
                    # document absence: a created UUID may not be visible.
                    authoritative_absence_confirmed=False,
                    current_payload_hash=current_payload_hash,
                ),
            )

        if len(matches) != 1 or not _matches_expected_document(
            matches[0],
            current_expected,
        ):
            intent.last_error = "IIKO_DOCUMENT_RECONCILIATION_CONFLICT"
            conflict = True
        else:
            intent.iiko_document_number = matches[0].document_number
            intent.status = IikoDocumentWriteStatus.CREATED
            intent.last_error = None
            return _result(
                intent,
                IikoDocumentReconciliationOutcome.FOUND_MATCH,
            )

    if conflict:
        raise IikoDocumentReconciliationConflictError(
            "IIKO_DOCUMENT_RECONCILIATION_CONFLICT"
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
            existing.iiko_document_id
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
                iiko_document_id=document.document_id,
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
        if result.document_id != document.document_id or not result.valid:
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
