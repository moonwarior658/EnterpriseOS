from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SupplyIikoIncomingReceiptStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    CREATING = "CREATING"
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    POSTED = "POSTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SupplyIikoIncomingReceiptLineRead(BaseModel):
    id: UUID
    acceptance_line_id: UUID
    supplier_document_line_id: UUID
    product_id: UUID
    product_name: str
    unit_id: UUID
    unit_name: str
    iiko_product_id: UUID
    iiko_amount_unit_id: UUID
    iiko_store_id: UUID
    quantity: Decimal
    historical_unit_price: Decimal
    allocated_sum: Decimal
    line_no: int
    accounted_quantity: Decimal
    accounted_sum: Decimal


class SupplyIikoIncomingReceiptRead(BaseModel):
    id: UUID
    supplier_acceptance_id: UUID
    supplier_id: UUID
    supplier_name: str
    destination_mapping_id: UUID
    destination_name: str
    iiko_supplier_mapping_id: UUID
    iiko_supplier_id: UUID
    status: SupplyIikoIncomingReceiptStatus
    readiness_status: str
    readiness_reasons: list[str]
    eos_document_number: str
    date_incoming: datetime
    incoming_date: date
    iiko_document_id: UUID | None
    iiko_document_number: str | None
    iiko_status: str | None
    payload_hash: str | None
    payload_xml: str | None
    create_attempt_count: int
    process_attempt_count: int
    last_error_code: str | None
    last_error_message: str | None
    create_started_at: datetime | None
    created_in_iiko_at: datetime | None
    process_started_at: datetime | None
    posted_at: datetime | None
    total_sum: Decimal
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime
    lines: list[SupplyIikoIncomingReceiptLineRead]
    model_config = ConfigDict(from_attributes=True)
