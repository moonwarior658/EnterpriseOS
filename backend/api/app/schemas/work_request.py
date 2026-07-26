from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequestType(StrEnum):
    WAREHOUSE = "warehouse"
    REPAIR = "repair"


class RequestStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WarehouseCategory(StrEnum):
    PRODUCTS = "products"
    HOUSEHOLD = "household"
    PACKAGING = "packaging"


class RepairPriority(StrEnum):
    ROUTINE = "routine"
    IMPORTANT = "important"
    URGENT = "urgent"


DEPARTMENTS = {"М15", "М35", "М6А", "Цех ГХ", "Бар ГХ", "Кухня", "Авто"}

REPAIR_CATEGORIES = {
    "Сантехника",
    "Электрика",
    "Кассовое оборудование",
    "Компьютерное оборудование",
    "Холодильное оборудование",
    "Тепловое оборудование",
    "Кофемашина",
    "Интернет",
    "Другое",
}


class WorkRequestCreate(BaseModel):
    request_type: RequestType
    department: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=5000)
    warehouse_category: WarehouseCategory | None = None
    repair_category: str | None = Field(default=None, max_length=64)
    priority: RepairPriority | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("department", "description", "repair_category")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("department")
    @classmethod
    def validate_department(cls, value: str) -> str:
        if value not in DEPARTMENTS:
            raise ValueError("Unknown department")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        if not value:
            raise ValueError("Description must not be empty")
        return value

    @model_validator(mode="after")
    def validate_type_fields(self) -> "WorkRequestCreate":
        if self.request_type == RequestType.WAREHOUSE:
            if self.warehouse_category is None:
                raise ValueError("Warehouse category is required")
            if self.repair_category is not None or self.priority is not None:
                raise ValueError("Repair fields are not allowed")
            return self

        if self.repair_category not in REPAIR_CATEGORIES:
            raise ValueError("Unknown repair category")
        if self.priority is None:
            raise ValueError("Repair priority is required")
        if self.warehouse_category is not None:
            raise ValueError("Warehouse category is not allowed")
        return self


class PublicWorkRequestCreate(WorkRequestCreate):
    author_name: str = Field(min_length=1, max_length=128)

    @field_validator("author_name")
    @classmethod
    def validate_author_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Author name must not be empty")
        return stripped


class WorkRequestUpdate(BaseModel):
    department: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    warehouse_category: WarehouseCategory | None = None
    repair_category: str | None = Field(default=None, max_length=64)
    priority: RepairPriority | None = None
    status: RequestStatus | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("department", "description", "repair_category")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("department")
    @classmethod
    def validate_department(cls, value: str | None) -> str | None:
        if value is not None and value not in DEPARTMENTS:
            raise ValueError("Unknown department")
        return value

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is not None and not value:
            raise ValueError("Description must not be empty")
        return value


class WorkRequestStatusUpdate(BaseModel):
    status: RequestStatus


class WorkRequestAttachmentRead(BaseModel):
    id: int
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkRequestRead(BaseModel):
    id: int
    request_type: RequestType
    department: str
    description: str
    status: RequestStatus
    warehouse_category: WarehouseCategory | None
    repair_category: str | None
    priority: RepairPriority | None
    created_at: datetime
    updated_at: datetime
    created_by_name: str
    attachment_count: int
    attachments: list[WorkRequestAttachmentRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class WorkRequestCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Comment must not be empty")
        return stripped


class WorkRequestCommentRead(BaseModel):
    id: int
    body: str
    created_at: datetime
    author_name: str

    model_config = ConfigDict(from_attributes=True)
