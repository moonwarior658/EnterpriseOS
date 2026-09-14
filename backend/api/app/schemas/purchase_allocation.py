from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.supply import SupplyUnitRead


class SupplyPurchaseAllocationStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"


class SupplyMinimumOrderStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    MET = "MET"
    BELOW_MINIMUM = "BELOW_MINIMUM"


class SupplyPurchaseAllocationCreate(BaseModel):
    product_supplier_id: UUID
    packages_count: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class SupplyPurchaseAllocationUpdate(BaseModel):
    packages_count: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class SupplyPurchaseAllocationRead(BaseModel):
    id: UUID
    product_supplier_id: UUID
    supplier_id: UUID
    supplier_display_name: str
    role: str
    priority: int
    packages_count: int
    quantity_base: Decimal
    package_quantity_snapshot: Decimal
    package_unit_id_snapshot: UUID
    package_unit_snapshot: SupplyUnitRead
    price_per_package_snapshot: Decimal
    base_unit_price_snapshot: Decimal
    currency: str
    planned_amount: Decimal
    status: SupplyPurchaseAllocationStatus
    current_terms_changed: bool
    created_at: datetime
    updated_at: datetime


class SupplyEligibleSupplierRead(BaseModel):
    product_supplier_id: UUID
    supplier_id: UUID
    supplier_display_name: str
    role: str
    priority: int
    package_quantity: Decimal
    package_unit_id: UUID
    package_unit: SupplyUnitRead
    price_per_package: Decimal
    base_unit_price: Decimal
    currency: str
    is_available: bool
    unavailable_until: date | None


class SupplyPurchaseAllocationLineRead(BaseModel):
    line_id: UUID
    product_id: UUID
    product_name: str
    required_quantity: Decimal
    unit_id: UUID
    unit: SupplyUnitRead
    allocations: list[SupplyPurchaseAllocationRead]
    eligible_suppliers: list[SupplyEligibleSupplierRead]
    allocated_quantity: Decimal
    remaining_quantity: Decimal
    overallocated_quantity: Decimal
    planned_amount: Decimal


class SupplyPurchaseAllocationSupplierSubtotalRead(BaseModel):
    supplier_id: UUID
    supplier_display_name: str
    planned_total_amount: Decimal
    minimum_order_amount: Decimal | None
    minimum_order_status: SupplyMinimumOrderStatus
    minimum_order_shortfall: Decimal
    allocation_count: int = Field(ge=1)


class SupplyPurchaseAllocationWorkspaceRead(BaseModel):
    request_id: UUID
    request_number: str
    request_status: str
    lines: list[SupplyPurchaseAllocationLineRead]
    planned_total_amount: Decimal
    supplier_subtotals: list[SupplyPurchaseAllocationSupplierSubtotalRead]
