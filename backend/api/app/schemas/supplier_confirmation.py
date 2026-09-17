from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SupplySupplierConfirmationStatus(StrEnum):
    DRAFT = "DRAFT"
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class SupplySupplierConfirmationResponseType(StrEnum):
    CONFIRMED = "CONFIRMED"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    REJECTED = "REJECTED"


class SupplySupplierConfirmationLineStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CHANGED = "CHANGED"
    REJECTED = "REJECTED"


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


class SupplySupplierConfirmationUpdate(BaseModel):
    supplier_reference: str | None = Field(default=None, max_length=255)
    supplier_comment: str | None = Field(default=None, max_length=4000)
    confirmed_delivery_date: date | None = None
    responded_at: datetime | None = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("supplier_reference", "supplier_comment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("responded_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("responded_at must include timezone")
        return value


class SupplySupplierConfirmationLineUpdate(BaseModel):
    response_status: SupplySupplierConfirmationLineStatus | None = None
    confirmed_packages_count: int | None = Field(default=None, gt=0)
    confirmed_package_quantity: Decimal | None = Field(default=None, gt=0)
    confirmed_package_unit_id: UUID | None = None
    confirmed_quantity_base: Decimal | None = Field(default=None, gt=0)
    confirmed_price_per_package: Decimal | None = Field(default=None, gt=0)
    supplier_line_comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("supplier_line_comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        return _clean(value)

class SupplySupplierConfirmationLineRead(BaseModel):
    id: UUID
    supplier_order_line_id: UUID
    response_status: SupplySupplierConfirmationLineStatus
    product_name_snapshot: str
    ordered_packages_count: int
    ordered_package_quantity: Decimal
    ordered_package_unit_id: UUID
    ordered_package_unit: str
    ordered_quantity_base: Decimal
    ordered_price_per_package: Decimal
    ordered_planned_amount: Decimal
    confirmed_packages_count: int | None
    confirmed_package_quantity: Decimal | None
    confirmed_package_unit_id: UUID | None
    confirmed_package_unit: str | None
    confirmed_quantity_base: Decimal | None
    confirmed_price_per_package: Decimal | None
    confirmed_planned_amount: Decimal | None
    currency: str
    supplier_line_comment: str | None
    created_at: datetime
    updated_at: datetime


class SupplySupplierConfirmationRead(BaseModel):
    id: UUID
    supplier_order_id: UUID
    revision_number: int
    status: SupplySupplierConfirmationStatus
    response_type: SupplySupplierConfirmationResponseType | None
    supplier_id: UUID
    supplier_display_name: str
    order_number: str
    supplier_reference: str | None
    supplier_comment: str | None
    planned_delivery_date: date | None
    confirmed_delivery_date: date | None
    responded_at: datetime | None
    recorded_at: datetime | None
    created_at: datetime
    updated_at: datetime
    ordered_total_amount: Decimal
    confirmed_total_amount: Decimal
    currency: str
    lines: list[SupplySupplierConfirmationLineRead]


class SupplySupplierConfirmationSummary(BaseModel):
    id: UUID
    revision_number: int
    status: SupplySupplierConfirmationStatus
    response_type: SupplySupplierConfirmationResponseType | None
    confirmed_delivery_date: date | None
    responded_at: datetime | None
    recorded_at: datetime | None
    confirmed_total_amount: Decimal
