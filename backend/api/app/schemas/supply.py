from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_RAW_INPUT_LENGTH = 20_000
MAX_LINE_LENGTH = 1_000
MAX_PRODUCT_NAME_LENGTH = 240


class SupplyRequestStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class SupplyRequestSourceType(StrEnum):
    INTERNAL = "INTERNAL"
    PUBLIC_FORM = "PUBLIC_FORM"
    WORK_REQUEST_MANUAL = "WORK_REQUEST_MANUAL"


class DepartmentRead(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class SupplyRequestDirectionRead(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    display_order: int

    model_config = ConfigDict(from_attributes=True)


class SupplyUnitRead(BaseModel):
    id: UUID
    code: str
    name_ru: str
    short_name_ru: str
    allows_fraction: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyProductAliasRead(BaseModel):
    id: UUID
    alias: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyProductCreate(BaseModel):
    name: str
    default_unit_id: UUID
    request_direction_id: UUID | None = None
    is_active: bool = True

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Название товара не может быть пустым")
        if len(stripped) > MAX_PRODUCT_NAME_LENGTH:
            raise ValueError(
                "Название товара не может быть длиннее "
                f"{MAX_PRODUCT_NAME_LENGTH} символов"
            )
        return stripped


class SupplyProductUpdate(BaseModel):
    name: str | None = None
    default_unit_id: UUID | None = None
    request_direction_id: UUID | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Название товара не может быть null")
        return SupplyProductCreate.validate_name(value)

    @field_validator("default_unit_id")
    @classmethod
    def validate_default_unit_id(cls, value: UUID | None) -> UUID:
        if value is None:
            raise ValueError("Базовая единица товара не может быть null")
        return value

    @field_validator("is_active")
    @classmethod
    def validate_is_active(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("Активность товара не может быть null")
        return value


class SupplyProductAliasCreate(BaseModel):
    alias: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("alias")
    @classmethod
    def validate_alias(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Алиас товара не может быть пустым")
        if len(stripped) > MAX_PRODUCT_NAME_LENGTH:
            raise ValueError(
                "Алиас товара не может быть длиннее "
                f"{MAX_PRODUCT_NAME_LENGTH} символов"
            )
        return stripped


class SupplyProductRead(BaseModel):
    id: UUID
    name: str
    default_unit: SupplyUnitRead
    request_direction: SupplyRequestDirectionRead | None
    is_active: bool
    aliases: list[SupplyProductAliasRead]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyProductPage(BaseModel):
    items: list[SupplyProductRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class SupplyRequestLineCreate(BaseModel):
    raw_text: str
    product_id: UUID | None = None
    requested_unit_id: UUID | None = None
    quantity: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=3,
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("raw_text")
    @classmethod
    def validate_raw_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Строка заявки не может быть пустой")
        if len(value) > MAX_LINE_LENGTH:
            raise ValueError(
                f"Строка заявки не может быть длиннее {MAX_LINE_LENGTH} символов"
            )
        return value

    @model_validator(mode="after")
    def validate_structured_quantity(self):
        if (self.requested_unit_id is None) != (self.quantity is None):
            raise ValueError(
                "Количество и единица измерения должны быть указаны вместе"
            )
        return self


class SupplyRequestLineRead(BaseModel):
    id: UUID
    position: int
    raw_text: str
    product_id: UUID | None
    requested_unit_id: UUID | None
    quantity: Decimal | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SupplyRequestCreate(BaseModel):
    department_id: UUID
    direction_id: UUID
    raw_input: str
    lines: list[SupplyRequestLineCreate]

    model_config = ConfigDict(extra="forbid")

    @field_validator("raw_input")
    @classmethod
    def validate_raw_input(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Исходный текст заявки не может быть пустым")
        if len(stripped) > MAX_RAW_INPUT_LENGTH:
            raise ValueError(
                "Исходный текст заявки не может быть длиннее "
                f"{MAX_RAW_INPUT_LENGTH} символов"
            )
        return stripped

    @field_validator("lines")
    @classmethod
    def validate_lines(
        cls,
        value: list[SupplyRequestLineCreate],
    ) -> list[SupplyRequestLineCreate]:
        if not value:
            raise ValueError("Добавьте хотя бы одну строку заявки")
        if len(value) > 200:
            raise ValueError("В заявке может быть не больше 200 строк")
        return value


class SupplyRequestRead(BaseModel):
    id: UUID
    public_number: str
    department: DepartmentRead
    direction: SupplyRequestDirectionRead
    status: SupplyRequestStatus
    source_type: SupplyRequestSourceType
    source_work_request_id: int | None
    raw_input: str
    version: int
    created_by_user_id: int | None
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[SupplyRequestLineRead]

    model_config = ConfigDict(from_attributes=True)


class SupplyRequestListItem(BaseModel):
    id: UUID
    public_number: str
    department: DepartmentRead
    direction: SupplyRequestDirectionRead
    status: SupplyRequestStatus
    source_type: SupplyRequestSourceType
    version: int
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    line_count: int

    model_config = ConfigDict(from_attributes=True)
