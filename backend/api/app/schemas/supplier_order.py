from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.supply import SupplyUnitRead


class SupplySupplierOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    CANCELLED = "CANCELLED"


class SupplySupplierOrderMinimumStatus(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    MET = "MET"
    BELOW_MINIMUM = "BELOW_MINIMUM"


class SupplySupplierOrderUpdate(BaseModel):
    planned_delivery_date: date | None = None
    comment: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SupplySupplierOrderLineRead(BaseModel):
    id: UUID
    product_name: str
    packages_count: int
    package_quantity_snapshot: Decimal
    package_unit: SupplyUnitRead
    quantity_base: Decimal
    price_per_package_snapshot: Decimal
    base_unit_price_snapshot: Decimal
    planned_amount: Decimal
    currency: str
    created_at: datetime


class SupplySupplierOrderListItem(BaseModel):
    id: UUID
    number: str
    supplier_id: UUID
    supplier_display_name: str
    purchase_request_id: UUID
    purchase_request_number: str
    status: SupplySupplierOrderStatus
    planned_delivery_date: date | None
    line_count: int
    total_amount: Decimal
    currency: str
    updated_at: datetime


class SupplySupplierOrderRead(SupplySupplierOrderListItem):
    comment: str | None
    minimum_order_amount: Decimal | None
    minimum_order_status: SupplySupplierOrderMinimumStatus
    minimum_order_shortfall: Decimal
    lines: list[SupplySupplierOrderLineRead]
    created_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None


class SupplySupplierOrderPage(BaseModel):
    items: list[SupplySupplierOrderListItem]
    total: int
    limit: int
    offset: int


class SupplySupplierOrderCreationResult(BaseModel):
    orders: list[SupplySupplierOrderRead]

