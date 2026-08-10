import logging
import re
from collections import defaultdict
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import (
    IikoAccountDto,
    IikoIncomingInvoiceDto,
    IikoOutgoingInvoiceDto,
)
from app.models.iiko import (
    IikoMappingStatus,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
)
from app.models.supply import Department
from app.schemas.iiko import (
    IikoOutgoingInvoiceContractCandidateRead,
    IikoOutgoingInvoiceContractDiscoveryRead,
    IikoOutgoingInvoiceContractStatus,
    IikoOutgoingInvoiceDestinationContractRead,
)


logger = logging.getLogger(__name__)
_OUTGOING_INVOICE_OPERATIONAL_DAYS = 45
_SENSITIVE_ERROR_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pass|authorization|proxy-authorization|"
    r"cookie|set-cookie|session(?:[_-]?(?:cookie|id))?|token|"
    r"access[_-]?token|refresh[_-]?token|api[_-]?key|secret|"
    r"client[_-]?secret)\b"
    r"\s*[:=]\s*)[^\s,;&]+"
)
_AUTH_VALUE_RE = re.compile(r"(?i)\b(?:bearer|basic)\s+[^\s,;&]+")


def _safe_contract_error(error: IikoContractError) -> str:
    message = " ".join(str(error).split())
    message = _SENSITIVE_ERROR_RE.sub(r"\1[REDACTED]", message)
    message = _AUTH_VALUE_RE.sub("[REDACTED]", message)
    return message[:1000]


class IikoOutgoingInvoiceContractScopeError(ValueError):
    pass


async def discover_outgoing_invoice_contracts(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    department_id: UUID,
    date_from: date,
    date_to: date,
) -> IikoOutgoingInvoiceContractDiscoveryRead:
    today = date.today()
    effective_date_from = max(
        date_from,
        today - timedelta(days=_OUTGOING_INVOICE_OPERATIONAL_DAYS),
    )
    department = session.scalar(select(Department).where(
        Department.tenant_id == tenant_id,
        Department.id == department_id,
    ))
    if department is None:
        raise IikoOutgoingInvoiceContractScopeError("DEPARTMENT_NOT_FOUND")

    destinations = session.scalars(
        select(IikoWarehouseMapping).where(
            IikoWarehouseMapping.tenant_id == tenant_id,
            IikoWarehouseMapping.destination_type
            == IikoWarehouseDestinationType.DESTINATION,
            IikoWarehouseMapping.eos_department_id == department_id,
            IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
            IikoWarehouseMapping.is_deleted.is_(False),
        ).order_by(IikoWarehouseMapping.role, IikoWarehouseMapping.id)
    ).all()

    try:
        accounts = await provider.get_accounts()
    except IikoContractError as error:
        logger.error(
            "Outgoing invoice contract discovery failed "
            "stage=accounts department_id=%s error=%s",
            department_id,
            _safe_contract_error(error),
        )
        raise

    try:
        invoices = await provider.get_outgoing_invoices(
            date_from=effective_date_from,
            date_to=date_to,
        )
    except IikoContractError as error:
        logger.error(
            "Outgoing invoice contract discovery failed "
            "stage=outgoingInvoice department_id=%s error=%s",
            department_id,
            _safe_contract_error(error),
        )
        raise

    try:
        incoming_invoices = await provider.get_incoming_invoices(
            date_from=effective_date_from,
            date_to=date_to,
        )
    except IikoContractError as error:
        logger.error(
            "Outgoing invoice contract discovery failed "
            "stage=incomingInvoice department_id=%s error=%s",
            department_id,
            _safe_contract_error(error),
        )
        raise

    try:
        return _map_outgoing_invoice_contracts(
            department=department,
            destinations=destinations,
            accounts=accounts,
            incoming_invoices=incoming_invoices,
            invoices=invoices,
            date_from=effective_date_from,
            date_to=date_to,
        )
    except IikoContractError as error:
        logger.error(
            "Outgoing invoice contract discovery failed "
            "stage=mapping department_id=%s error=%s",
            department_id,
            _safe_contract_error(error),
        )
        raise


def _map_outgoing_invoice_contracts(
    *,
    department: Department,
    destinations: list[IikoWarehouseMapping],
    accounts: list[IikoAccountDto],
    incoming_invoices: list[IikoIncomingInvoiceDto],
    invoices: list[IikoOutgoingInvoiceDto],
    date_from: date,
    date_to: date,
) -> IikoOutgoingInvoiceContractDiscoveryRead:
    active_account_codes = {
        account.code for account in accounts if not account.is_deleted
    }
    outgoing_by_incoming_id: dict[str, list[IikoOutgoingInvoiceDto]] = (
        defaultdict(list)
    )
    for invoice in invoices:
        if invoice.status != "DELETED":
            outgoing_by_incoming_id[
                invoice.linked_incoming_invoice_id.casefold()
            ].append(invoice)

    incoming_by_destination: dict[str, list[IikoIncomingInvoiceDto]] = (
        defaultdict(list)
    )
    for invoice in incoming_invoices:
        if invoice.status != "DELETED":
            incoming_by_destination[
                invoice.default_store_id.casefold()
            ].append(invoice)

    results: list[IikoOutgoingInvoiceDestinationContractRead] = []
    for destination in destinations:
        issues: list[str] = []
        matching = [
            outgoing
            for incoming in incoming_by_destination[
                str(destination.iiko_warehouse_id).casefold()
            ]
            for outgoing in outgoing_by_incoming_id.get(
                incoming.external_id.casefold(),
                (),
            )
        ]
        grouped: dict[tuple[str, str, str], list] = defaultdict(list)
        for invoice in matching:
            grouped[(
                invoice.counteragent_id,
                invoice.account_to_code,
                invoice.revenue_account_code,
            )].append(invoice)
        candidates = [
            IikoOutgoingInvoiceContractCandidateRead(
                counteragent_id=_contract_uuid(
                    counteragent_id,
                    field="counteragentId",
                    document_number=documents[0].document_number,
                ),
                source_warehouse_ids=sorted({
                    _contract_uuid(
                        document.default_store_id,
                        field="defaultStoreId",
                        document_number=document.document_number,
                    )
                    for document in documents
                }),
                account_to_code=account_to_code,
                revenue_account_code=revenue_account_code,
                matching_documents=len(documents),
                document_numbers=sorted({
                    document.document_number for document in documents
                })[:20],
                account_to_exists=account_to_code in active_account_codes,
                revenue_account_exists=(
                    revenue_account_code in active_account_codes
                ),
            )
            for (
                counteragent_id,
                account_to_code,
                revenue_account_code,
            ), documents in sorted(grouped.items())
        ]
        destination_counteragent_ids = {
            candidate.counteragent_id for candidate in candidates
        }
        destination_counteragent_id = (
            next(iter(destination_counteragent_ids))
            if len(destination_counteragent_ids) == 1
            else None
        )
        if not candidates:
            contract_status = IikoOutgoingInvoiceContractStatus.NOT_FOUND
        elif len(candidates) > 1:
            contract_status = IikoOutgoingInvoiceContractStatus.CONFLICT
        elif not (
            candidates[0].account_to_exists
            and candidates[0].revenue_account_exists
        ):
            if not candidates[0].account_to_exists:
                issues.append("ACCOUNT_TO_CODE_NOT_FOUND")
            if not candidates[0].revenue_account_exists:
                issues.append("REVENUE_ACCOUNT_CODE_NOT_FOUND")
            contract_status = IikoOutgoingInvoiceContractStatus.INVALID_REFERENCE
        else:
            contract_status = IikoOutgoingInvoiceContractStatus.UNIQUE
        results.append(IikoOutgoingInvoiceDestinationContractRead(
            destination_mapping_id=destination.id,
            destination_warehouse_id=destination.iiko_warehouse_id,
            destination_counteragent_id=destination_counteragent_id,
            destination_name=destination.source_name,
            destination_role=(
                destination.role.value if destination.role else "OTHER"
            ),
            status=contract_status,
            issues=issues,
            candidates=candidates,
        ))

    return IikoOutgoingInvoiceContractDiscoveryRead(
        department_id=department.id,
        department_name=department.name,
        date_from=date_from,
        date_to=date_to,
        accounts_read=len(accounts),
        incoming_invoices_read=len(incoming_invoices),
        invoices_read=len(invoices),
        destinations=results,
    )


def _contract_uuid(
    value: str,
    *,
    field: str,
    document_number: str,
) -> UUID:
    try:
        return UUID(value)
    except ValueError as error:
        raise IikoContractError(
            "Invalid outgoing invoice field "
            f"document_number={document_number} field={field}"
        ) from error
