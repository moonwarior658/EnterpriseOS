from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.iiko import (
    IikoMappingAction,
    IikoMappingKind,
    IikoMappingStatus,
    IikoWarehouseDestinationType,
    IikoWarehouseRole,
)
from app.models.supply import LegalContour


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
    destination_type: IikoWarehouseDestinationType
    eos_department_id: UUID | None = None
    role: IikoWarehouseRole | None = None
    legal_contour: LegalContour | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "IikoWarehouseMappingAction":
        if self.destination_type == IikoWarehouseDestinationType.DESTINATION:
            if self.eos_department_id is None or self.role is None:
                raise ValueError(
                    "Для склада подразделения нужны подразделение и роль"
                )
            if self.legal_contour is not None:
                raise ValueError(
                    "Контур склада подразделения определяется автоматически"
                )
        else:
            if self.legal_contour is None or self.role is None:
                raise ValueError(
                    "Для источника снабжения нужны контур и роль"
                )
            if self.eos_department_id is not None:
                raise ValueError(
                    "Для источника снабжения нельзя задавать подразделение"
                )
        return self


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
    destination_type: IikoWarehouseDestinationType
    role: IikoWarehouseRole | None
    legal_contour: LegalContour | None
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
