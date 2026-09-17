from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SupplySupplierAcceptanceStatus(StrEnum):
    DRAFT = "DRAFT"
    RECORDED = "RECORDED"
    CANCELLED = "CANCELLED"


class SupplySupplierAcceptanceRejectionReason(StrEnum):
    DAMAGED = "DAMAGED"
    QUALITY_MISMATCH = "QUALITY_MISMATCH"
    WRONG_PRODUCT = "WRONG_PRODUCT"
    WRONG_PACKAGE = "WRONG_PACKAGE"
    EXPIRED = "EXPIRED"
    OTHER = "OTHER"


class SupplyAcceptanceResolutionIssueType(StrEnum):
    SHORTAGE = "SHORTAGE"
    EXCESS = "EXCESS"
    REJECTED = "REJECTED"


class SupplyAcceptanceResolutionStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class SupplyAcceptanceResolutionType(StrEnum):
    WAIT_FOR_DELIVERY = "WAIT_FOR_DELIVERY"
    CLOSE_SHORTAGE = "CLOSE_SHORTAGE"
    RETURN_TO_PROCUREMENT = "RETURN_TO_PROCUREMENT"
    WAIT_FOR_REPLACEMENT = "WAIT_FOR_REPLACEMENT"
    CLOSE_REJECTION = "CLOSE_REJECTION"
    ACCEPT_EXCESS = "ACCEPT_EXCESS"
    REJECT_EXCESS = "REJECT_EXCESS"


class SupplySupplierAcceptanceCreate(BaseModel):
    supplier_document_id: UUID | None = None
    destination_mapping_id: UUID | None = None
    received_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")


class SupplySupplierAcceptanceUpdate(BaseModel):
    destination_mapping_id: UUID | None = None
    received_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")


class SupplySupplierAcceptanceLineCreate(BaseModel):
    product_name_snapshot: str = Field(min_length=1, max_length=240)
    product_id: UUID | None = None
    unit_id: UUID
    received_quantity: Decimal = Field(gt=0, max_digits=30, decimal_places=6)
    accepted_quantity: Decimal = Field(ge=0, max_digits=30, decimal_places=6)
    rejected_quantity: Decimal = Field(ge=0, max_digits=30, decimal_places=6)
    accepted_unit_price: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=6)
    rejection_reason: SupplySupplierAcceptanceRejectionReason | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")


class SupplySupplierAcceptanceLineUpdate(BaseModel):
    received_quantity: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=6)
    accepted_quantity: Decimal | None = Field(default=None, ge=0, max_digits=30, decimal_places=6)
    rejected_quantity: Decimal | None = Field(default=None, ge=0, max_digits=30, decimal_places=6)
    accepted_unit_price: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=6)
    rejection_reason: SupplySupplierAcceptanceRejectionReason | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")


class SupplySupplierAcceptanceLineSourceWrite(BaseModel):
    supplier_order_line_source_id: UUID
    accepted_quantity: Decimal = Field(gt=0, max_digits=30, decimal_places=6)

    model_config = ConfigDict(extra="forbid")


class SupplySupplierAcceptanceLineSourcesUpdate(BaseModel):
    sources: list[SupplySupplierAcceptanceLineSourceWrite]

    model_config = ConfigDict(extra="forbid")


class SupplySupplierAcceptanceLineSourceRead(BaseModel):
    supplier_order_line_source_id: UUID
    source_type: str
    procurement_need_id: UUID | None
    source_label: str
    planned_quantity: Decimal
    already_accepted_quantity: Decimal
    remaining_quantity: Decimal
    accepted_quantity: Decimal


class SupplySupplierAcceptanceLineRead(BaseModel):
    id: UUID
    supplier_document_line_id: UUID | None
    supplier_order_line_id: UUID | None
    supplier_confirmation_line_id: UUID | None
    product_name_snapshot: str
    product_id: UUID | None
    unit_id: UUID | None
    unit_name_snapshot: str | None
    ordered_quantity: Decimal | None
    confirmed_quantity: Decimal | None
    documented_quantity: Decimal | None
    received_quantity: Decimal
    accepted_quantity: Decimal
    rejected_quantity: Decimal
    ordered_vs_confirmed: Decimal | None
    confirmed_vs_documented: Decimal | None
    documented_vs_received: Decimal | None
    received_vs_accepted: Decimal
    shortage_quantity: Decimal
    excess_quantity: Decimal
    accepted_excess_quantity: Decimal
    downstream_accepted_quantity: Decimal
    receipt_eligible_quantity: Decimal | None
    accounted_quantity: Decimal
    accounted_sum: Decimal
    documented_unit_price: Decimal | None
    accepted_unit_price: Decimal | None
    accepted_amount: Decimal | None
    currency: str
    rejection_reason: SupplySupplierAcceptanceRejectionReason | None
    comment: str | None
    is_unmatched: bool
    traceability_status: str
    source_accepted_quantity: Decimal
    unassigned_accepted_surplus: Decimal
    sources: list[SupplySupplierAcceptanceLineSourceRead]


class SupplySupplierAcceptanceDestinationRead(BaseModel):
    mapping_id: UUID
    department_name: str
    role: str
    iiko_store_name: str
    iiko_store_code: str | None


class SupplyAcceptanceResolutionNeedRead(BaseModel):
    id: UUID
    quantity: Decimal
    need_date: date | None
    status: str
    reason: str


class SupplyAcceptanceResolutionRead(BaseModel):
    id: UUID
    supplier_acceptance_id: UUID
    acceptance_line_id: UUID
    product_name: str
    product_id: UUID | None
    issue_type: SupplyAcceptanceResolutionIssueType
    status: SupplyAcceptanceResolutionStatus
    resolution_type: SupplyAcceptanceResolutionType | None
    quantity: Decimal
    unit_id: UUID
    unit_name: str
    comment: str | None
    resolved_by_user_id: int | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    procurement_need: SupplyAcceptanceResolutionNeedRead | None
    downstream_accepted_quantity: Decimal


class SupplyAcceptanceResolutionResolve(BaseModel):
    resolution_type: SupplyAcceptanceResolutionType
    need_date: date | None = None
    comment: str | None = Field(default=None, max_length=2000)
    model_config = ConfigDict(extra="forbid")


class SupplySupplierAcceptanceRead(BaseModel):
    id: UUID
    supplier_order_id: UUID
    supplier_document_id: UUID | None
    supplier_confirmation_id: UUID | None
    destination_mapping_id: UUID | None
    destination: SupplySupplierAcceptanceDestinationRead | None
    source: str
    status: SupplySupplierAcceptanceStatus
    result: str
    accepted_at: datetime | None
    received_at: datetime | None
    comment: str | None
    recorded_by_user_id: int | None
    recorded_at: datetime | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime
    lines: list[SupplySupplierAcceptanceLineRead]
    resolution_state: str
    open_issues_count: int
    resolutions: list[SupplyAcceptanceResolutionRead]


class SupplySupplierAcceptanceCumulativeLineRead(BaseModel):
    source_type: str
    source_line_id: UUID | None
    product_name: str
    unit_name: str | None
    source_quantity: Decimal | None
    total_received: Decimal
    total_accepted: Decimal
    total_rejected: Decimal
    remaining_quantity: Decimal | None
    downstream_accepted_quantity: Decimal
    receipt_eligible_quantity: Decimal | None


class SupplySupplierAcceptanceSummary(BaseModel):
    draft_count: int
    recorded_count: int
    latest_acceptance: SupplySupplierAcceptanceRead | None
    quantities_by_unit: dict[str, dict[str, Decimal]]
    cumulative_lines: list[SupplySupplierAcceptanceCumulativeLineRead]
    open_issues_count: int
    has_shortage: bool
    has_excess: bool
