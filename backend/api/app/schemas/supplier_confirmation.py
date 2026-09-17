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


class SupplySupplierConfirmationDeviationType(StrEnum):
    LINE_REJECTED = "LINE_REJECTED"
    QUANTITY_CHANGED = "QUANTITY_CHANGED"
    PRICE_CHANGED = "PRICE_CHANGED"
    DELIVERY_DATE_CHANGED = "DELIVERY_DATE_CHANGED"


class SupplySupplierConfirmationDeviationStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class SupplySupplierConfirmationDecisionType(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class SupplySupplierConfirmationReviewState(StrEnum):
    CLEAN = "CLEAN"
    REQUIRES_DECISION = "REQUIRES_DECISION"
    RESOLVED = "RESOLVED"


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


class SupplySupplierConfirmationDecisionCreate(BaseModel):
    decision: SupplySupplierConfirmationDecisionType
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        return _clean(value)


class SupplySupplierConfirmationDeviationRead(BaseModel):
    id: UUID
    confirmation_id: UUID
    confirmation_line_id: UUID | None
    supplier_order_line_id: UUID | None
    deviation_type: SupplySupplierConfirmationDeviationType
    requires_decision: bool
    status: SupplySupplierConfirmationDeviationStatus
    direction: str | None
    product_name_snapshot: str | None
    baseline_packages_count: int | None
    confirmed_packages_count: int | None
    baseline_package_quantity: Decimal | None
    confirmed_package_quantity: Decimal | None
    baseline_package_unit_id: UUID | None
    confirmed_package_unit_id: UUID | None
    package_unit_snapshot: str | None
    baseline_quantity: Decimal | None
    confirmed_quantity: Decimal | None
    quantity_delta: Decimal | None
    baseline_price: Decimal | None
    confirmed_price: Decimal | None
    price_delta: Decimal | None
    price_delta_percent: Decimal | None
    baseline_amount: Decimal | None
    confirmed_amount: Decimal | None
    baseline_delivery_date: date | None
    confirmed_delivery_date: date | None
    delivery_delta_days: int | None
    decision_type: SupplySupplierConfirmationDecisionType | None
    decision_comment: str | None
    decided_by_user_id: int | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime

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
    deviations: list[SupplySupplierConfirmationDeviationRead]
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
    supplier_confirmation_review_state: SupplySupplierConfirmationReviewState
    open_required_deviations_count: int
    deviations: list[SupplySupplierConfirmationDeviationRead]
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
    deviation_count: int
    open_required_deviations_count: int
    supplier_confirmation_review_state: SupplySupplierConfirmationReviewState
