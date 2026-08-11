from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from app.integrations.iiko.schemas import (
    IikoAccountDto,
    IikoIncomingInvoiceDto,
    IikoOutgoingInvoiceCreateDto,
    IikoOrganizationDto,
    IikoOutgoingInvoiceDto,
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
    ) -> UUID:
        """Submit one controlled NEW outgoing invoice with a caller-owned ID."""
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        """Release the token/license slot and close the HTTP client."""
