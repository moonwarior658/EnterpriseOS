from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IikoDto(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class IikoOrganizationDto(IikoDto):
    external_id: str
    name: str
    code: str | None = None
    organization_type: str | None = None
    parent_external_id: str | None = None
    is_active: bool = True
    raw_updated_at: datetime | None = None


class IikoWarehouseDto(IikoDto):
    external_id: str
    organization_external_id: str | None = None
    enterprise_external_id: str | None = None
    parent_external_id: str | None = None
    name: str
    code: str | None = None
    warehouse_type: str | None = None
    is_active: bool = True
    is_deleted: bool = False
    raw_updated_at: datetime | None = None


class IikoAccountDto(IikoDto):
    external_id: str
    name: str
    code: str
    account_type: str
    parent_external_id: str | None = None
    organization_external_id: str | None = None
    is_deleted: bool = False


class IikoSupplierDto(IikoDto):
    external_id: str
    name: str
    code: str | None = None
    is_supplier: bool = False
    is_employee: bool = False
    represents_store: bool = False
    is_deleted: bool = False


class IikoOutgoingInvoiceDto(IikoDto):
    external_id: str | None = None
    document_number: str
    date_incoming: datetime | None = None
    status: str
    linked_incoming_invoice_id: str
    counteragent_id: str
    default_store_id: str
    account_to_code: str
    revenue_account_code: str


class IikoIncomingInvoiceDto(IikoDto):
    external_id: str
    document_number: str
    status: str
    default_store_id: str
    supplier_id: str | None = None


class IikoProductGroupDto(IikoDto):
    external_id: str
    parent_external_id: str | None = None
    name: str
    code: str | None = None
    is_active: bool = True
    is_deleted: bool = False


class IikoProductCategoryDto(IikoDto):
    external_id: str
    name: str
    is_active: bool = True
    is_deleted: bool = False


class IikoProductDto(IikoDto):
    external_id: str
    name: str
    code: str | None = None
    sku: str | None = None
    group_external_id: str | None = None
    category_external_id: str | None = None
    base_unit_external_id: str | None = None
    is_active: bool = True
    is_deleted: bool = False
    product_type: str | None = None
    raw_updated_at: datetime | None = None


class IikoUnitDto(IikoDto):
    external_id: str
    name: str
    short_name: str | None = None
    code: str | None = None
    precision: int | None = None
    is_active: bool = True


class IikoPackageDto(IikoDto):
    external_id: str
    product_external_id: str
    unit_external_id: str | None = None
    name: str
    coefficient: Decimal
    is_default: bool = False
    is_active: bool = True


class IikoStockBalanceDto(IikoDto):
    warehouse_external_id: str
    product_external_id: str
    quantity: Decimal
    unit_external_id: str | None = None
    calculated_at: datetime
    source_updated_at: datetime | None = None
    product_name: str | None = None
    warehouse_name: str | None = None


class IikoInternalTransferItemCreateDto(IikoDto):
    product_id: UUID
    amount: Decimal = Field(gt=0, allow_inf_nan=False)


class IikoInternalTransferCreateDto(IikoDto):
    document_id: UUID
    date_incoming: datetime
    store_from_id: UUID
    store_to_id: UUID
    status: Literal["NEW"] = "NEW"
    items: tuple[IikoInternalTransferItemCreateDto, ...] = Field(min_length=1)

    def to_iiko_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.document_id),
            "dateIncoming": self.date_incoming.replace(tzinfo=None).isoformat(
                timespec="seconds"
            ),
            "status": self.status,
            "storeFromId": str(self.store_from_id),
            "storeToId": str(self.store_to_id),
            "items": [
                {
                    "productId": str(item.product_id),
                    "amount": format(item.amount, "f"),
                }
                for item in self.items
            ],
        }


DtoT = TypeVar("DtoT", bound=IikoDto)


class IikoRecord(BaseModel, Generic[DtoT]):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    entity_type: str
    external_id: str
    parent_external_id: str | None = None
    organization_external_id: str | None = None
    is_active: bool
    dto: DtoT
    raw_payload: dict[str, Any]
    source_updated_at: datetime | None = None


class IikoPage(BaseModel, Generic[DtoT]):
    items: list[DtoT]
    total: int
    limit: int
    offset: int


class IikoMappingCandidateDto(IikoDto):
    mapping_type: str
    eos_external_id: str
    iiko_external_id: str
    conflict: bool = False
