from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SellerDepartmentRead(BaseModel):
    id: UUID
    name: str


class SellerRequestRead(BaseModel):
    id: UUID
    status: str
    version: int
    raw_input: str


class SellerWindowRead(BaseModel):
    is_open: bool
    can_write: bool
    department_label: str = 'Подразделение'
    allowed_actions: list[str] = Field(default_factory=list)
    closes_at: datetime | None = None
    need_date: date | None = None
    cycle_id: UUID | None = None
    department: SellerDepartmentRead | None = None
    allowed_departments: list[SellerDepartmentRead] = Field(default_factory=list)
    supported_units: list[str] = Field(default_factory=list)
    request: SellerRequestRead | None = None
    reason: str | None = None


class SellerRequestSave(BaseModel):
    department_id: UUID | None = None
    raw_input: str = Field(min_length=1, max_length=10000)
    expected_version: int | None = Field(default=None, ge=1)
    model_config = ConfigDict(extra='forbid')

    @field_validator('raw_input')
    @classmethod
    def clean_lines(cls, value: str) -> str:
        result = value.strip()
        lines = [line.strip() for line in result.splitlines() if line.strip()]
        if not lines or len(lines) > 200:
            raise ValueError('Укажите от 1 до 200 товаров')
        return '\n'.join(lines)


class SellerRequestConfirm(BaseModel):
    department_id: UUID | None = None
    expected_version: int = Field(ge=1)
    model_config = ConfigDict(extra='forbid')
