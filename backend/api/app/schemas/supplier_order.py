from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.supply import SupplyUnitRead
from app.schemas.supplier_confirmation import SupplySupplierConfirmationSummary
from app.schemas.supplier_document import SupplySupplierDocumentsSummary
from app.schemas.supplier_acceptance import SupplySupplierAcceptanceSummary
from app.schemas.supplier_payment import SupplySupplierOrderPrepaymentSummary


class SupplySupplierOrderStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class SupplySupplierOrderDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


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


class SupplySupplierOrderMessagePrepare(BaseModel):
    responsible_phone: str | None = Field(default=None, max_length=40)

    model_config = ConfigDict(extra="forbid")

    @field_validator("responsible_phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
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
    sent_at: datetime | None
    recipient_email_snapshot: str | None
    recipient_name_snapshot: str | None
    responsible_name_snapshot: str | None
    responsible_phone_snapshot: str | None
    latest_delivery_attempt: "SupplySupplierOrderDeliveryAttemptRead | None"
    delivery_history: list["SupplySupplierOrderDeliveryAttemptRead"]
    supplier_confirmation_state: str
    latest_confirmation: SupplySupplierConfirmationSummary | None
    draft_confirmation: SupplySupplierConfirmationSummary | None
    confirmation_history_count: int
    supplier_confirmation_review_state: str
    open_required_deviations_count: int
    supplier_documents_summary: SupplySupplierDocumentsSummary
    acceptance_summary: SupplySupplierAcceptanceSummary
    prepayment_summary: SupplySupplierOrderPrepaymentSummary


class SupplySupplierOrderDeliveryAttemptRead(BaseModel):
    id: UUID
    attempt_number: int
    status: SupplySupplierOrderDeliveryStatus
    recipient_email: str
    provider_message_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    dispatched_at: datetime | None
    completed_at: datetime | None


class SupplySupplierOrderMessageRecipient(BaseModel):
    email: str
    supplier_display_name: str


class SupplySupplierOrderMessageResponsible(BaseModel):
    name: str
    phone: str


class SupplySupplierOrderMessageOrder(BaseModel):
    id: UUID
    number: str
    planned_delivery_date: date | None
    comment: None = None
    total_amount: Decimal
    currency: str


class SupplySupplierOrderMessageLine(BaseModel):
    product_name: str
    packages_count: int
    package_quantity: Decimal
    package_unit: str
    total_quantity: Decimal
    price_per_package: Decimal
    planned_amount: Decimal
    currency: str


class SupplySupplierOrderMessagePreview(BaseModel):
    recipient: SupplySupplierOrderMessageRecipient
    subject: str
    body_text: str
    order: SupplySupplierOrderMessageOrder
    lines: list[SupplySupplierOrderMessageLine]
    responsible: SupplySupplierOrderMessageResponsible
    warnings: list[str]


class SupplySupplierOrderPage(BaseModel):
    items: list[SupplySupplierOrderListItem]
    total: int
    limit: int
    offset: int


class SupplySupplierOrderCreationResult(BaseModel):
    orders: list[SupplySupplierOrderRead]
