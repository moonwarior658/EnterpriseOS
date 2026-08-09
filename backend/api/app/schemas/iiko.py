from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.iiko import IikoSyncStatus, IikoSyncType


class IikoStatusRead(BaseModel):
    enabled: bool
    configured: bool
    api_type: str
    connection_state: str
    last_successful_connection_at: datetime | None = None
    last_reference_sync_at: datetime | None = None
    last_stock_sync_at: datetime | None = None
    last_error_code: str | None = None
    last_error_at: datetime | None = None


class IikoSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sync_type: IikoSyncType
    status: IikoSyncStatus
    started_at: datetime
    finished_at: datetime | None
    source_api_type: str
    source_organization_id: str | None
    parameters: dict
    records_received: int
    records_created: int
    records_updated: int
    records_unchanged: int
    records_failed: int
    error_code: str | None
    error_message: str | None


class IikoStockBalanceSyncRequest(BaseModel):
    balance_date: date
    warehouse_external_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=160)]],
        Field(min_length=1, max_length=100),
    ]
    product_external_ids: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=160)]],
        Field(max_length=500),
    ] | None = None
    include_zero: bool = True
    include_deleted: bool = True

    @field_validator("warehouse_external_ids", "product_external_ids")
    @classmethod
    def reject_blank_ids(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and any(not value.strip() for value in values):
            raise ValueError("iiko identifiers must not be blank")
        return values


class IikoStockBalanceSnapshotSyncRequest(BaseModel):
    snapshot_at: datetime
    department_id: UUID
    source_warehouse_mapping_ids: Annotated[
        list[UUID], Field(min_length=1, max_length=100)
    ]

    @field_validator("snapshot_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("snapshot_at must include a timezone")
        return value

    @field_validator("source_warehouse_mapping_ids")
    @classmethod
    def reject_duplicate_sources(cls, values: list[UUID]) -> list[UUID]:
        if len(values) != len(set(values)):
            raise ValueError("source_warehouse_mapping_ids must be unique")
        return values


class IikoOutgoingInvoiceContractStatus(StrEnum):
    UNIQUE = "UNIQUE"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INVALID_REFERENCE = "INVALID_REFERENCE"


class IikoOutgoingInvoiceContractCandidateRead(BaseModel):
    counteragent_id: UUID
    account_to_code: str
    revenue_account_code: str
    matching_documents: int
    document_numbers: list[str]
    account_to_exists: bool
    revenue_account_exists: bool


class IikoOutgoingInvoiceDestinationContractRead(BaseModel):
    destination_mapping_id: UUID
    destination_warehouse_id: UUID
    destination_parent_corporate_id: UUID | None
    destination_name: str
    destination_role: str
    status: IikoOutgoingInvoiceContractStatus
    issues: list[str]
    candidates: list[IikoOutgoingInvoiceContractCandidateRead]


class IikoOutgoingInvoiceContractDiscoveryRead(BaseModel):
    department_id: UUID
    department_name: str
    date_from: date
    date_to: date
    accounts_read: int
    invoices_read: int
    destinations: list[IikoOutgoingInvoiceDestinationContractRead]
