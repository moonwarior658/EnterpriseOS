from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SupplySupplierPaymentType(StrEnum):
    PREPAYMENT = "PREPAYMENT"
    POSTPAYMENT = "POSTPAYMENT"


class SupplySupplierPaymentStatus(StrEnum):
    DRAFT = "DRAFT"
    RECORDED = "RECORDED"
    CANCELLED = "CANCELLED"


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


class _PaymentFields(BaseModel):
    payment_date: date
    amount: Decimal = Field(gt=0)
    payment_order_number: str | None = Field(default=None, max_length=128)
    payment_order_date: date | None = None
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("payment_order_number", "comment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean(value)

    @model_validator(mode="after")
    def validate_payment_order_pair(self):
        if (self.payment_order_number is None) != (self.payment_order_date is None):
            raise ValueError("payment order number and date must be provided together")
        return self


class SupplySupplierPaymentCreate(_PaymentFields):
    supplier_id: UUID
    supplier_document_id: UUID | None = None
    supplier_order_id: UUID | None = None
    payment_type: SupplySupplierPaymentType
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_type_reference(self):
        if self.payment_type == SupplySupplierPaymentType.POSTPAYMENT and self.supplier_document_id is None:
            raise ValueError("postpayment requires supplier document")
        return self


class SupplySupplierPaymentUpdate(BaseModel):
    supplier_document_id: UUID | None = None
    supplier_order_id: UUID | None = None
    payment_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    payment_order_number: str | None = Field(default=None, max_length=128)
    payment_order_date: date | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("payment_order_number", "comment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean(value)


class SupplySupplierPaymentRead(BaseModel):
    id: UUID
    supplier_id: UUID
    supplier_display_name: str
    supplier_document_id: UUID | None
    supplier_document_number: str | None
    supplier_order_id: UUID | None
    supplier_order_number: str | None
    payment_type: SupplySupplierPaymentType
    status: SupplySupplierPaymentStatus
    payment_date: date
    amount: Decimal
    refunded_amount: Decimal
    effective_payment_amount: Decimal
    allocated_amount: Decimal
    available_amount: Decimal
    allocation_state: str
    currency: str
    payment_order_number: str | None
    payment_order_date: date | None
    comment: str | None
    recorded_by_user_id: int | None
    recorded_by_display_name: str | None
    recorded_at: datetime | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime


class SupplySupplierPaymentPage(BaseModel):
    items: list[SupplySupplierPaymentRead]
    total: int
    limit: int
    offset: int


class SupplySupplierOrderPrepaymentSummary(BaseModel):
    prepayment_total: Decimal
    unallocated_prepayment_count: int
    unallocated_prepayment_amount: Decimal
