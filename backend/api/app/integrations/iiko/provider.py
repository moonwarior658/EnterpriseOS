from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.schemas import (
    IikoAccountDto,
    IikoIncomingInvoiceDto,
    IikoIncomingInvoicePreviewDto,
    InternalTransferDto,
    IikoDocumentValidationResultDto,
    IikoOutgoingInvoiceCreateDto,
    IikoOutgoingInvoiceCreateResultDto,
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


class IikoProvider(ABC):
    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate without exposing the returned token."""

    @abstractmethod
    async def check_connection(self) -> bool:
        """Authenticate and execute one minimal read request."""

    @abstractmethod
    async def get_organizations(
        self,
    ) -> list[IikoRecord[IikoOrganizationDto]]:
        """Return corporation hierarchy records."""

    @abstractmethod
    async def get_enterprises(
        self,
    ) -> list[IikoRecord[IikoOrganizationDto]]:
        """Return trading enterprises from corporation hierarchy."""

    @abstractmethod
    async def get_departments(
        self,
    ) -> list[IikoRecord[IikoOrganizationDto]]:
        """Return department/group data if supported."""

    @abstractmethod
    async def get_warehouses(
        self,
    ) -> list[IikoRecord[IikoWarehouseDto]]:
        """Return warehouses."""

    @abstractmethod
    async def get_product_groups(
        self,
    ) -> list[IikoRecord[IikoProductGroupDto]]:
        """Return nomenclature groups."""

    @abstractmethod
    async def get_product_categories(
        self,
    ) -> list[IikoRecord[IikoProductCategoryDto]]:
        """Return user product categories."""

    @abstractmethod
    async def get_products(
        self,
    ) -> list[IikoRecord[IikoProductDto]]:
        """Return products."""

    @abstractmethod
    async def get_units(self) -> list[IikoRecord[IikoUnitDto]]:
        """Return measurement units."""

    @abstractmethod
    async def get_packages(
        self,
    ) -> list[IikoRecord[IikoPackageDto]]:
        """Return packages embedded in products."""

    @abstractmethod
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
        """Return stock balances for an explicit scope and timestamp."""

    async def get_accounts(self) -> list[IikoAccountDto]:
        """Return the read-only chart of accounts."""
        raise NotImplementedError

    async def get_suppliers(self) -> list[IikoSupplierDto]:
        """Return read-only supplier/user records."""
        raise NotImplementedError

    async def get_incoming_invoices(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> list[IikoIncomingInvoiceDto]:
        """Return existing incoming invoices for contract discovery."""
        raise NotImplementedError

    async def get_incoming_invoice_by_id(
        self,
        document_id: UUID,
        *,
        date_from: date,
        date_to: date,
    ) -> IikoIncomingInvoiceDto | None:
        """Return one invoice from a bounded export by authoritative UUID."""
        invoices = await self.get_incoming_invoices(
            date_from=date_from,
            date_to=date_to,
        )
        matches = [
            invoice for invoice in invoices
            if invoice.external_id == document_id
        ]
        if len(matches) > 1:
            raise IikoContractError("IIKO_INCOMING_INVOICE_ID_AMBIGUOUS")
        return matches[0] if matches else None

    async def create_incoming_invoice(
        self,
        document: IikoIncomingInvoicePreviewDto,
    ) -> IikoDocumentValidationResultDto:
        """Submit one controlled NEW incoming invoice without assuming UUID."""
        raise NotImplementedError

    async def process_incoming_invoice(
        self,
        document_id: UUID,
        *,
        enable_warnings: bool,
    ) -> IikoDocumentValidationResultDto:
        """Process one authoritative NEW incoming invoice through BackOffice RPC."""
        raise NotImplementedError

    async def get_outgoing_invoices(
        self,
        *,
        date_from: date,
        date_to: date,
    ) -> list[IikoOutgoingInvoiceDto]:
        """Return existing outgoing invoices for contract discovery."""
        raise NotImplementedError

    async def create_outgoing_invoice(
        self,
        document: IikoOutgoingInvoiceCreateDto,
    ) -> IikoOutgoingInvoiceCreateResultDto:
        """Submit one controlled NEW outgoing invoice with a caller-owned ID."""
        raise NotImplementedError

    async def update_outgoing_invoice(
        self,
        document: IikoOutgoingInvoiceUpdateSourceDto,
        *,
        actual_quantities: Sequence[Decimal],
    ) -> IikoDocumentValidationResultDto:
        """Update one authoritative NEW invoice through legacy RPC."""
        raise NotImplementedError

    async def get_outgoing_invoice_for_update(
        self,
        document_id: UUID,
    ) -> IikoOutgoingInvoiceUpdateSourceDto:
        """Return one full fresh legacy-RPC invoice with its revision."""
        raise NotImplementedError

    async def process_outgoing_invoices(
        self,
        document_ids: Sequence[UUID],
        *,
        enable_warnings: bool,
        entities_version: int,
    ) -> tuple[IikoDocumentValidationResultDto, ...]:
        """Process existing invoices through the confirmed BackOffice RPC."""
        raise NotImplementedError

    async def get_internal_transfer_by_id(
        self,
        document_id: UUID,
    ) -> InternalTransferDto:
        """Return one authoritative internal transfer through REST byId."""
        raise NotImplementedError

    async def create_internal_transfer(
        self,
        document: InternalTransferDto,
    ) -> InternalTransferDto:
        """Create one NEW transfer without a caller-owned iiko document ID."""
        raise NotImplementedError

    async def update_internal_transfer(
        self,
        document: InternalTransferDto,
        *,
        actual_quantities: Sequence[Decimal],
    ) -> InternalTransferDto:
        """Update one existing NEW transfer while preserving its identity."""
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        """Release the token/license slot and close the HTTP client."""
