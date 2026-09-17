from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.supplier_payment import SupplySupplierPaymentRead


class SupplySupplierDocumentType(StrEnum):
    INVOICE = "INVOICE"
    DELIVERY_NOTE = "DELIVERY_NOTE"
    UPD = "UPD"


class SupplySupplierDocumentStatus(StrEnum):
    DRAFT = "DRAFT"
    RECORDED = "RECORDED"
    CANCELLED = "CANCELLED"


class SupplySupplierDocumentFinancialRole(StrEnum):
    PAYABLE = "PAYABLE"
    SUPPORTING = "SUPPORTING"
    NON_FINANCIAL = "NON_FINANCIAL"


class SupplySupplierDocumentPricingBasis(StrEnum):
    PACKAGE = "PACKAGE"
    UNIT = "UNIT"
    FIXED_AMOUNT = "FIXED_AMOUNT"


def _clean(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


class SupplySupplierDocumentCreate(BaseModel):
    document_type: SupplySupplierDocumentType
    financial_role: SupplySupplierDocumentFinancialRole | None = None
    obligation_id: UUID | None = None
    create_obligation: bool = False
    document_number: str | None = Field(default=None, max_length=128)
    document_date: date | None = None
    payment_due_date: date | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("document_number", "comment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean(value)


class SupplySupplierDocumentUpdate(BaseModel):
    document_type: SupplySupplierDocumentType | None = None
    financial_role: SupplySupplierDocumentFinancialRole | None = None
    obligation_id: UUID | None = None
    create_obligation: bool = False
    document_number: str | None = Field(default=None, max_length=128)
    document_date: date | None = None
    payment_due_date: date | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("document_number", "comment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean(value)


class SupplySupplierDocumentLineCreate(BaseModel):
    supplier_order_line_id: UUID | None = None
    supplier_confirmation_line_id: UUID | None = None
    product_name_snapshot: str = Field(min_length=1, max_length=240)
    pricing_basis: SupplySupplierDocumentPricingBasis
    package_quantity_snapshot: Decimal | None = Field(default=None, gt=0)
    package_unit_id_snapshot: UUID | None = None
    packages_count: int | None = Field(default=None, gt=0)
    quantity_base: Decimal | None = Field(default=None, gt=0)
    price_per_package: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, gt=0)
    line_amount: Decimal | None = Field(default=None, gt=0)
    supplier_line_reference: str | None = Field(default=None, max_length=255)
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("product_name_snapshot")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("product name is required")
        return value

    @field_validator("supplier_line_reference", "comment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean(value)


class SupplySupplierDocumentLineUpdate(BaseModel):
    supplier_order_line_id: UUID | None = None
    supplier_confirmation_line_id: UUID | None = None
    product_name_snapshot: str | None = Field(default=None, min_length=1, max_length=240)
    pricing_basis: SupplySupplierDocumentPricingBasis | None = None
    package_quantity_snapshot: Decimal | None = Field(default=None, gt=0)
    package_unit_id_snapshot: UUID | None = None
    packages_count: int | None = Field(default=None, gt=0)
    quantity_base: Decimal | None = Field(default=None, gt=0)
    price_per_package: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, gt=0)
    line_amount: Decimal | None = Field(default=None, gt=0)
    supplier_line_reference: str | None = Field(default=None, max_length=255)
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("product_name_snapshot")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return _clean(value)

    @field_validator("supplier_line_reference", "comment")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        return _clean(value)


class SupplySupplierDocumentLineRead(BaseModel):
    id: UUID
    supplier_order_line_id: UUID | None
    supplier_confirmation_line_id: UUID | None
    product_name_snapshot: str
    pricing_basis: SupplySupplierDocumentPricingBasis
    package_quantity_snapshot: Decimal | None
    package_unit_id_snapshot: UUID | None
    unit_name_snapshot: str | None
    packages_count: int | None
    quantity_base: Decimal | None
    price_per_package: Decimal | None
    unit_price: Decimal | None
    line_amount: Decimal
    currency: str
    supplier_line_reference: str | None
    comment: str | None
    is_extra_line: bool
    created_at: datetime
    updated_at: datetime


class SupplySupplierDocumentSummary(BaseModel):
    id: UUID
    document_type: SupplySupplierDocumentType
    financial_role: SupplySupplierDocumentFinancialRole
    obligation_id: UUID | None
    document_number: str | None
    document_date: date | None
    payment_due_date: date | None
    status: SupplySupplierDocumentStatus
    total_amount: Decimal
    currency: str
    supplier_confirmation_revision: int | None
    created_at: datetime
    recorded_at: datetime | None


class SupplySupplierDocumentRead(SupplySupplierDocumentSummary):
    supplier_order_id: UUID
    supplier_order_number: str
    supplier_confirmation_id: UUID | None
    supplier_id: UUID
    supplier_display_name_snapshot: str
    supplier_inn_snapshot: str | None
    supplier_kpp_snapshot: str | None
    comment: str | None
    created_by_user_id: int
    recorded_by_user_id: int | None
    updated_at: datetime
    document_total_amount: Decimal
    recorded_payments_amount: Decimal
    remaining_to_pay: Decimal
    payment_state: str
    overdue_state: str
    payments: list[SupplySupplierPaymentRead]
    lines: list[SupplySupplierDocumentLineRead]


class SupplySupplierDocumentsSummary(BaseModel):
    total_documents: int
    invoices_count: int
    delivery_notes_count: int
    upd_count: int
    recorded_documents_count: int
    latest_document: SupplySupplierDocumentSummary | None
