import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
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
    amount: Decimal = Field(ge=0, allow_inf_nan=False)
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
    revision: int | None = Field(default=None, ge=0)
    items: tuple[IikoOutgoingInvoiceItemDto, ...] = ()
    raw_document_xml: bytes | None = Field(default=None, exclude=True, repr=False)


class IikoOutgoingInvoiceUpdateSourceDto(IikoDto):
    external_id: str
    document_number: str
    status: str
    revision: int = Field(ge=0)
    entities_version: int = Field(ge=0)
    items: tuple[IikoOutgoingInvoiceItemDto, ...] = ()
    raw_document_xml: bytes = Field(exclude=True, repr=False)


class IikoOutgoingInvoiceItemCreateDto(IikoDto):
    product_id: UUID
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    price: Literal[0] = 0


class IikoOutgoingInvoiceCreateResultDto(IikoDto):
    client_document_id: UUID
    document_number: str = Field(min_length=1)
    valid: Literal[True]
    warning: bool


class IikoDocumentValidationResultDto(IikoDto):
    valid: bool
    warning: bool
    document_number: str | None = None
    other_suggested_number: str | None = None
    error_message: str | None = None
    additional_info: str | None = None


class InternalTransferItemDto(IikoDto):
    product_id: UUID
    amount: Decimal = Field(ge=0, allow_inf_nan=False)
    num: int | None = Field(default=None, ge=1)
    measure_unit_id: UUID | None = None
    container_id: UUID | None = None
    cost: Decimal | None = Field(default=None, allow_inf_nan=False)

    @staticmethod
    def _json_number(value: Decimal) -> int | float:
        if value == value.to_integral_value():
            return int(value)
        return float(value)

    def to_create_payload(self) -> dict[str, Any]:
        return {
            "productId": str(self.product_id),
            "amount": self._json_number(self.amount),
        }

    def to_update_payload(self) -> dict[str, Any]:
        return {
            "num": self.num,
            "productId": str(self.product_id),
            "amount": self._json_number(self.amount),
            "measureUnitId": (
                str(self.measure_unit_id) if self.measure_unit_id else None
            ),
            "containerId": str(self.container_id) if self.container_id else None,
            "cost": (
                self._json_number(self.cost) if self.cost is not None else None
            ),
        }


class InternalTransferDto(IikoDto):
    id: UUID | None = None
    date_incoming: datetime
    document_number: str | None = None
    status: Literal["NEW", "PROCESSED", "DELETED"]
    conception_id: UUID | None = None
    comment: str | None = None
    store_from_id: UUID
    store_to_id: UUID
    items: tuple[InternalTransferItemDto, ...] = Field(min_length=1)

    def _date_incoming_payload(self) -> str:
        # The confirmed REST contract uses a local date-time without an offset.
        return self.date_incoming.replace(tzinfo=None).isoformat(
            timespec="seconds"
        )

    def to_create_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dateIncoming": self._date_incoming_payload(),
            "status": self.status,
            "storeFromId": str(self.store_from_id),
            "storeToId": str(self.store_to_id),
            "items": [item.to_create_payload() for item in self.items],
        }
        if self.conception_id is not None:
            payload["conceptionId"] = str(self.conception_id)
        if self.comment is not None:
            payload["comment"] = self.comment
        return payload

    def to_update_payload(self) -> dict[str, Any]:
        if self.id is None or not self.document_number:
            raise ValueError("Authoritative internal transfer identity required")
        return {
            "id": str(self.id),
            "dateIncoming": self._date_incoming_payload(),
            "documentNumber": self.document_number,
            "status": self.status,
            "conceptionId": (
                str(self.conception_id) if self.conception_id else None
            ),
            "comment": self.comment,
            "storeFromId": str(self.store_from_id),
            "storeToId": str(self.store_to_id),
            "items": [item.to_update_payload() for item in self.items],
        }


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


class IikoIncomingInvoicePreviewItemDto(IikoDto):
    num: int = Field(ge=1)
    product_id: UUID
    store_id: UUID
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    amount_unit_id: UUID
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    sum_amount: Decimal = Field(ge=0, allow_inf_nan=False)


class IikoIncomingInvoicePreviewDto(IikoDto):
    document_number: str = Field(min_length=1)
    date_incoming: datetime
    incoming_date: date
    supplier_id: UUID
    default_store_id: UUID
    status: Literal["NEW"] = "NEW"
    items: tuple[IikoIncomingInvoicePreviewItemDto, ...] = Field(min_length=1)

    def to_iiko_xml(self) -> bytes:
        """Build the import DTO only; sending it is a separate operation."""
        document = ET.Element("document")

        def add_text(parent: ET.Element, name: str, value: str) -> None:
            ET.SubElement(parent, name).text = value

        add_text(document, "documentNumber", self.document_number)
        add_text(
            document,
            "dateIncoming",
            self.date_incoming.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        add_text(document, "incomingDate", self.incoming_date.isoformat())
        add_text(document, "supplier", str(self.supplier_id))
        add_text(document, "defaultStore", str(self.default_store_id))
        add_text(document, "status", self.status)
        items = ET.SubElement(document, "items")
        for item in self.items:
            item_element = ET.SubElement(items, "item")
            add_text(item_element, "num", str(item.num))
            add_text(item_element, "product", str(item.product_id))
            add_text(item_element, "store", str(item.store_id))
            add_text(item_element, "amount", format(item.amount, "f"))
            add_text(item_element, "amountUnit", str(item.amount_unit_id))
            add_text(item_element, "price", format(item.price, "f"))
            add_text(item_element, "sum", format(item.sum_amount, "f"))
        return ET.tostring(document, encoding="utf-8")


class IikoIncomingInvoiceStatus(StrEnum):
    NEW = "NEW"
    PROCESSED = "PROCESSED"
    DELETED = "DELETED"
    UNKNOWN = "UNKNOWN"


class IikoIncomingInvoiceItemDto(IikoDto):
    external_id: UUID | None = None
    line_no: int | None = Field(default=None, ge=0)
    code: str | None = None
    product_id: UUID
    product_article: str | None = None
    supplier_product_id: UUID | None = None
    supplier_product_article: str | None = None
    store_id: UUID | None = None
    amount: Decimal = Field(allow_inf_nan=False)
    actual_amount: Decimal | None = Field(default=None, allow_inf_nan=False)
    amount_unit: UUID | None = None
    container_id: UUID | None = None
    price: Decimal | None = Field(default=None, allow_inf_nan=False)
    price_without_vat: Decimal | None = Field(
        default=None, allow_inf_nan=False
    )
    price_unit: UUID | None = None
    sum_amount: Decimal | None = Field(default=None, allow_inf_nan=False)
    discount_sum: Decimal | None = Field(default=None, allow_inf_nan=False)
    vat_percent: Decimal | None = Field(default=None, allow_inf_nan=False)
    vat_sum: Decimal | None = Field(default=None, allow_inf_nan=False)
    is_additional_expense: bool | None = None


class IikoIncomingInvoiceDto(IikoDto):
    external_id: UUID
    document_number: str
    status: IikoIncomingInvoiceStatus
    raw_status: str | None = None
    supplier_id: UUID | None = None
    supplier_name: str | None = None
    supplier_code: str | None = None
    default_store_id: UUID | None = None
    date_incoming: datetime | None = None
    incoming_date: date | datetime | None = None
    due_date: date | datetime | None = None
    invoice: str | None = None
    incoming_document_number: str | None = None
    comment: str | None = None
    revision: int | None = Field(default=None, ge=0)
    items: tuple[IikoIncomingInvoiceItemDto, ...] = ()


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
