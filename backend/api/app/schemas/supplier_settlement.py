from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SupplySupplierObligationRead(BaseModel):
    id: UUID
    supplier_id: UUID
    supplier_order_id: UUID
    status: str
    created_at: datetime
    updated_at: datetime


class SupplySupplierObligationCreate(BaseModel):
    supplier_id: UUID
    model_config = ConfigDict(extra="forbid")


class SupplySupplierPaymentAllocationCreate(BaseModel):
    payment_id: UUID
    supplier_document_id: UUID
    amount: Decimal = Field(gt=0)
    model_config = ConfigDict(extra="forbid")


class SupplySupplierPaymentAllocationReverse(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    amount: Decimal | None = Field(default=None, gt=0)
    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        return value.strip()


class SupplySupplierPaymentAllocationRead(BaseModel):
    id: UUID
    supplier_id: UUID
    payment_id: UUID
    supplier_document_id: UUID
    obligation_id: UUID
    amount: Decimal
    status: str
    created_by_user_id: int | None
    created_at: datetime
    reversed_amount: Decimal | None
    reversed_by_user_id: int | None
    reversed_at: datetime | None
    reverse_reason: str | None


class SupplySupplierSettlementAdjustmentType(StrEnum):
    SUPPLIER_REFUND = "SUPPLIER_REFUND"
    MANUAL_CORRECTION = "MANUAL_CORRECTION"


class SupplySupplierSettlementCorrectionDirection(StrEnum):
    INCREASE_DEBT = "INCREASE_DEBT"
    DECREASE_DEBT = "DECREASE_DEBT"


class SupplySupplierSettlementAdjustmentCreate(BaseModel):
    supplier_id: UUID
    supplier_payment_id: UUID | None = None
    type: SupplySupplierSettlementAdjustmentType
    direction: SupplySupplierSettlementCorrectionDirection | None = None
    amount: Decimal = Field(gt=0)
    effective_date: date
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.type == SupplySupplierSettlementAdjustmentType.SUPPLIER_REFUND:
            if self.supplier_payment_id is None or self.direction is not None:
                raise ValueError("refund requires payment and no direction")
        elif self.supplier_payment_id is not None or self.direction is None or not self.comment:
            raise ValueError("manual correction requires direction and comment")
        return self


class SupplySupplierSettlementAdjustmentRead(BaseModel):
    id: UUID
    supplier_id: UUID
    supplier_payment_id: UUID | None
    type: SupplySupplierSettlementAdjustmentType
    direction: SupplySupplierSettlementCorrectionDirection | None
    amount: Decimal
    effective_date: date
    comment: str | None
    status: str
    created_by_user_id: int
    created_at: datetime


class SupplySupplierPaymentSettlementRead(BaseModel):
    payment_id: UUID
    amount: Decimal
    refunded_amount: Decimal
    effective_payment_amount: Decimal
    allocated_amount: Decimal
    available_amount: Decimal
    allocation_state: str
    allocations: list[SupplySupplierPaymentAllocationRead]


class SupplySupplierDocumentSettlementRead(BaseModel):
    supplier_document_id: UUID
    document_amount: Decimal
    settled_amount: Decimal
    remaining_amount: Decimal
    payment_state: str
    allocations: list[SupplySupplierPaymentAllocationRead]


class SupplySupplierSettlementSummary(BaseModel):
    supplier_id: UUID
    documented_amount: Decimal
    recorded_payment_amount: Decimal
    allocated_payment_amount: Decimal
    unallocated_prepayment_amount: Decimal
    refund_amount: Decimal
    adjustment_amount: Decimal
    running_balance: Decimal
    current_debt: Decimal
    overdue_debt: Decimal
    overpayment: Decimal
    payment_without_supply: bool
    supply_without_payment: bool


class SupplySupplierSettlementMovement(BaseModel):
    date: date
    created_at: datetime
    type: str
    reference: str
    debit: Decimal
    credit: Decimal
    balance_delta: Decimal
    running_balance: Decimal


class SupplySupplierSettlementStatement(BaseModel):
    supplier_id: UUID
    date_from: date
    date_to: date
    opening_balance: Decimal
    movements: list[SupplySupplierSettlementMovement]
    closing_balance: Decimal
