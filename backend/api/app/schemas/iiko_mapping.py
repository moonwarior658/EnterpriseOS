from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.iiko import (
    IikoMappingAction,
    IikoMappingKind,
    IikoMappingStatus,
    IikoWarehouseRole,
)


class IikoMappingGenerateRead(BaseModel):
    products_created: int
    products_updated: int
    units_created: int
    units_updated: int
    warehouses_created: int
    warehouses_updated: int


class IikoMappingGenerateStatusRead(BaseModel):
    generation_id: UUID
    status: Literal["RUNNING", "SUCCEEDED", "FAILED", "UNKNOWN"]
    result: IikoMappingGenerateRead | None = None


class IikoProductMappingAction(BaseModel):
    eos_product_id: UUID


class IikoUnitMappingAction(BaseModel):
    eos_unit_id: UUID


class IikoWarehouseMappingAction(BaseModel):
    eos_department_id: UUID
    role: IikoWarehouseRole


class IikoProductMappingRead(BaseModel):
    id: UUID
    iiko_product_id: UUID
    source_name: str
    source_code: str | None
    source_sku: str | None
    source_unit_id: UUID | None
    is_deleted: bool
    status: IikoMappingStatus
    confidence: int | None
    reasons: list[str]
    eos_product_id: UUID | None
    eos_product_name: str | None
    decided_at: datetime | None


class IikoUnitMappingRead(BaseModel):
    id: UUID
    iiko_unit_id: UUID
    source_name: str
    source_code: str | None
    is_deleted: bool
    status: IikoMappingStatus
    confidence: int | None
    reasons: list[str]
    eos_unit_id: UUID | None
    eos_unit_name: str | None
    decided_at: datetime | None


class IikoWarehouseMappingRead(BaseModel):
    id: UUID
    iiko_warehouse_id: UUID
    source_name: str
    source_code: str | None
    is_deleted: bool
    status: IikoMappingStatus
    confidence: int | None
    reasons: list[str]
    eos_department_id: UUID | None
    eos_department_name: str | None
    role: IikoWarehouseRole | None
    decided_at: datetime | None


class IikoProductMappingPage(BaseModel):
    items: list[IikoProductMappingRead]
    total: int
    limit: int
    offset: int


class IikoUnitMappingPage(BaseModel):
    items: list[IikoUnitMappingRead]
    total: int
    limit: int
    offset: int


class IikoWarehouseMappingPage(BaseModel):
    items: list[IikoWarehouseMappingRead]
    total: int
    limit: int
    offset: int


class IikoMappingAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mapping_kind: IikoMappingKind
    mapping_id: UUID
    action: IikoMappingAction
    actor_user_id: int | None
    before: dict
    after: dict
    created_at: datetime


class IikoMappingAuditPage(BaseModel):
    items: list[IikoMappingAuditRead]
    total: int
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
