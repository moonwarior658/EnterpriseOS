from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.supply import SupplyUnitRead


class SupplyPurchaseRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    CANCELLED = "CANCELLED"


class SupplyPurchaseRequestSourceType(StrEnum):
    SUPPLY_REQUEST = "SUPPLY_REQUEST"
    DEPARTMENT_DEBT = "DEPARTMENT_DEBT"
    MANUAL_FUTURE = "MANUAL_FUTURE"


def _clean_comment(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > 2_000:
        raise ValueError("Комментарий не может быть длиннее 2000 символов")
    return value or None


class SupplyPurchaseRequestCreate(BaseModel):
    need_date: date
    comment: str | None = None

    model_config = ConfigDict(extra="forbid")

    _validate_comment = field_validator("comment")(_clean_comment)


class SupplyPurchaseRequestUpdate(BaseModel):
    need_date: date | None = None
    comment: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("need_date")
    @classmethod
    def reject_null_need_date(cls, value: date | None) -> date:
        if value is None:
            raise ValueError("Дата потребности не может быть null")
        return value

    _validate_comment = field_validator("comment")(_clean_comment)


class SupplyPurchaseRequestLineCreate(BaseModel):
    product_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    unit_id: UUID
    manual_future_quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=3
    )
    comment: str | None = None

    model_config = ConfigDict(extra="forbid")

    _validate_comment = field_validator("comment")(_clean_comment)

    @model_validator(mode="after")
    def manual_source_must_cover_manual_line(self):
        if (
            self.manual_future_quantity is not None
            and self.manual_future_quantity != self.quantity
        ):
            raise ValueError(
                "В ручном запросе будущая потребность должна совпадать с количеством"
            )
        return self


class SupplyPurchaseRequestLineUpdate(BaseModel):
    quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=3
    )
    unit_id: UUID | None = None
    manual_future_quantity: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=3
    )
    comment: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("quantity", "unit_id")
    @classmethod
    def reject_null_required_fields(cls, value):
        if value is None:
            raise ValueError("Поле не может быть null")
        return value

    _validate_comment = field_validator("comment")(_clean_comment)


class SupplyPurchaseRequestLineSourceRead(BaseModel):
    id: UUID
    source_type: SupplyPurchaseRequestSourceType
    source_id: UUID | None
    quantity: Decimal
    unit: SupplyUnitRead
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyPurchaseRequestProductRead(BaseModel):
    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class SupplyPurchaseRequestLineRead(BaseModel):
    id: UUID
    product: SupplyPurchaseRequestProductRead
    product_id: UUID
    quantity: Decimal
    unit: SupplyUnitRead
    unit_id: UUID
    manual_future_quantity: Decimal
    comment: str | None
    sources: list[SupplyPurchaseRequestLineSourceRead]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyPurchaseRequestListItem(BaseModel):
    id: UUID
    number: str
    need_date: date
    status: SupplyPurchaseRequestStatus
    comment: str | None
    line_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyPurchaseRequestRead(SupplyPurchaseRequestListItem):
    created_by_user_id: int
    lines: list[SupplyPurchaseRequestLineRead]


class SupplyPurchaseRequestPage(BaseModel):
    items: list[SupplyPurchaseRequestListItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
