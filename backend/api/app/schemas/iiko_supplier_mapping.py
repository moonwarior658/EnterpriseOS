from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.iiko import IikoSupplierMappingStatus


class IikoSupplierReferenceRead(BaseModel):
    external_id: UUID
    name: str
    code: str | None
    inn: str | None
    is_supplier: bool
    is_employee: bool
    represents_store: bool
    is_deleted: bool
    is_active: bool
    exact_inn_match: bool = False


class IikoSupplierReferencePage(BaseModel):
    items: list[IikoSupplierReferenceRead]
    total: int


class IikoSupplierMappingCreate(BaseModel):
    iiko_supplier_id: UUID

    model_config = ConfigDict(extra="forbid")


class IikoSupplierMappingRead(BaseModel):
    id: UUID
    supplier_id: UUID
    iiko_supplier_id: UUID
    iiko_supplier_name: str
    iiko_supplier_code: str | None
    iiko_supplier_inn: str | None
    iiko_supplier_deleted: bool
    status: IikoSupplierMappingStatus
    created_by_user_id: int | None
    confirmed_at: datetime
    archived_at: datetime | None
    archived_by_user_id: int | None
    superseded_by_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplySupplierIikoMappingState(BaseModel):
    mapping: IikoSupplierMappingRead | None
    history: list[IikoSupplierMappingRead]
    iiko_receipt_ready_supplier_mapping: bool
    warning: str | None = None
