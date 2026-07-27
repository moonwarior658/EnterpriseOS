from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


MAX_RAW_INPUT_LENGTH = 20_000
MAX_LINE_LENGTH = 1_000


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


class SupplyRequestLineCreate(BaseModel):
    raw_text: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("raw_text")
    @classmethod
    def validate_raw_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Строка заявки не может быть пустой")
        if len(stripped) > MAX_LINE_LENGTH:
            raise ValueError(
                f"Строка заявки не может быть длиннее {MAX_LINE_LENGTH} символов"
            )
        return stripped


class SupplyRequestLineRead(BaseModel):
    id: UUID
    position: int
    raw_text: str
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
