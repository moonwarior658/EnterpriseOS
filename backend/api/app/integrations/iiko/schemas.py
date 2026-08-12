import xml.etree.ElementTree as ET
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


class IikoOutgoingInvoiceItemDto(IikoDto):
    product_id: UUID
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    price: Decimal = Field(allow_inf_nan=False)


class IikoOutgoingInvoiceDto(IikoDto):
    external_id: str | None = None
    document_number: str
    date_incoming: datetime | None = None
    status: str
    linked_incoming_invoice_id: str | None = None
    counteragent_id: str
    default_store_id: str
    account_to_code: str
    revenue_account_code: str
    items: tuple[IikoOutgoingInvoiceItemDto, ...] = ()


class IikoOutgoingInvoiceItemCreateDto(IikoDto):
    product_id: UUID
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    price: Literal[0] = 0


class IikoOutgoingInvoiceCreateResultDto(IikoDto):
    client_document_id: UUID
    document_number: str = Field(min_length=1)
    valid: Literal[True]
    warning: bool


class IikoOutgoingInvoiceCreateDto(IikoDto):
    document_id: UUID
    date_incoming: datetime
    default_store_id: UUID
    counteragent_id: UUID
    account_to_code: Literal["21"] = "21"
    revenue_account_code: Literal["20"] = "20"
    status: Literal["NEW"] = "NEW"
    items: tuple[IikoOutgoingInvoiceItemCreateDto, ...] = Field(min_length=1)

    def to_iiko_xml(self) -> bytes:
        document = ET.Element("document")

        def add_text(parent: ET.Element, name: str, value: str) -> None:
            ET.SubElement(parent, name).text = value

        add_text(document, "id", str(self.document_id))
        add_text(
            document,
            "dateIncoming",
            self.date_incoming.isoformat(timespec="seconds"),
        )
        add_text(document, "useDefaultDocumentTime", "false")
        add_text(document, "status", self.status)
        add_text(document, "accountToCode", self.account_to_code)
        add_text(document, "revenueAccountCode", self.revenue_account_code)
        add_text(document, "defaultStoreId", str(self.default_store_id))
        add_text(document, "counteragentId", str(self.counteragent_id))
        items = ET.SubElement(document, "items")
        for item in self.items:
            item_element = ET.SubElement(items, "item")
            add_text(item_element, "productId", str(item.product_id))
            add_text(item_element, "amount", format(item.amount, "f"))
            add_text(item_element, "price", str(item.price))
        return ET.tostring(document, encoding="utf-8")


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
