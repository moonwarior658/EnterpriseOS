from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.provider import IikoProvider
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

    accounts = await provider.get_accounts()
    invoices = await provider.get_outgoing_invoices(
        date_from=date_from,
        date_to=date_to,
    )
    active_accounts_by_id = {
        account.external_id.casefold(): account
        for account in accounts if not account.is_deleted
    }
    active_account_codes = {
        account.code for account in accounts if not account.is_deleted
    }

    by_counteragent: dict[str, list] = defaultdict(list)
    for invoice in invoices:
        if invoice.status != "DELETED":
            by_counteragent[invoice.counteragent_id.casefold()].append(invoice)

    results: list[IikoOutgoingInvoiceDestinationContractRead] = []
    for destination in destinations:
        issues: list[str] = []
        destination_account = active_accounts_by_id.get(
            str(destination.iiko_warehouse_id).casefold()
        )
        parent_corporate_id: UUID | None = None
        if destination_account is None:
            issues.append("DESTINATION_ACCOUNT_NOT_FOUND")
        elif not destination_account.organization_external_id:
            issues.append("DESTINATION_PARENT_CORPORATE_ID_NOT_FOUND")
        else:
            try:
                parent_corporate_id = UUID(
                    destination_account.organization_external_id
                )
            except ValueError as error:
                raise IikoContractError(
                    "Invalid destination parent corporate id"
                ) from error

        matching = (
            by_counteragent[str(parent_corporate_id).casefold()]
            if parent_corporate_id is not None else []
        )
        grouped: dict[tuple[str, str, str], list] = defaultdict(list)
        for invoice in matching:
            grouped[(
                invoice.counteragent_id,
                invoice.account_to_code,
                invoice.revenue_account_code,
            )].append(invoice)
        candidates = [
            IikoOutgoingInvoiceContractCandidateRead(
                counteragent_id=UUID(counteragent_id),
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
        if issues:
            contract_status = IikoOutgoingInvoiceContractStatus.INVALID_REFERENCE
        elif not candidates:
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
            destination_parent_corporate_id=parent_corporate_id,
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
        invoices_read=len(invoices),
        destinations=results,
    )
