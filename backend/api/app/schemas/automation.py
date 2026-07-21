from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


AUTOMATION_CONTRACT_VERSION = "1.0"
ContractVersion = Literal["1.0"]
AutomationScopeType = Literal[
    "company",
    "department",
    "location",
    "user",
]


def strip_non_empty_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    normalized = value.strip()

    if not normalized:
        raise ValueError("Value must not be empty")

    return normalized


def normalize_timezone(value: Any) -> Any:
    normalized = strip_non_empty_string(value)

    if not isinstance(normalized, str):
        return normalized

    try:
        return ZoneInfo(normalized).key
    except ZoneInfoNotFoundError as error:
        raise ValueError("Unknown timezone") from error


def validate_scope_pair(
    scope_type: AutomationScopeType,
    scope_id: str | None,
) -> None:
    if scope_type == "company":
        if scope_id is not None:
            raise ValueError("company scope requires scope_id to be null")
        return

    if scope_id is None:
        raise ValueError(f"{scope_type} scope requires a non-empty scope_id")


class AutomationScheduleBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    automation_type: str = Field(min_length=1, max_length=100)
    scope_type: AutomationScopeType = "company"
    scope_id: str | None = Field(default=None, max_length=64)
    schedule_config: dict[str, Any] = Field(strict=True)
    payload: dict[str, Any] = Field(strict=True)
    recipients: list[Any] = Field(strict=True)
    timezone: str = Field(default="UTC", max_length=64)
    is_enabled: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "name",
        "automation_type",
        "scope_type",
        mode="before",
    )
    @classmethod
    def strip_required_strings(cls, value: Any) -> Any:
        return strip_non_empty_string(value)

    @field_validator("scope_id", mode="before")
    @classmethod
    def strip_optional_scope_id(cls, value: Any) -> Any:
        if value is None:
            return None

        return strip_non_empty_string(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, value: Any) -> Any:
        return normalize_timezone(value)

    @model_validator(mode="after")
    def validate_complete_scope(self) -> "AutomationScheduleBase":
        validate_scope_pair(self.scope_type, self.scope_id)
        return self


class AutomationScheduleCreate(AutomationScheduleBase):
    pass


class AutomationScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    automation_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    scope_type: AutomationScopeType | None = None
    scope_id: str | None = Field(default=None, max_length=64)
    schedule_config: dict[str, Any] | None = Field(
        default=None,
        strict=True,
    )
    payload: dict[str, Any] | None = Field(default=None, strict=True)
    recipients: list[Any] | None = Field(default=None, strict=True)
    timezone: str | None = Field(default=None, max_length=64)
    is_enabled: bool | None = None

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_null_for_not_null_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        not_null_fields = {
            "name",
            "automation_type",
            "scope_type",
            "schedule_config",
            "payload",
            "recipients",
            "timezone",
            "is_enabled",
        }
        null_fields = sorted(
            field
            for field in not_null_fields
            if field in data and data[field] is None
        )

        if null_fields:
            fields = ", ".join(null_fields)
            raise ValueError(f"Explicit null is not allowed for: {fields}")

        return data

    @field_validator(
        "name",
        "automation_type",
        "scope_type",
        mode="before",
    )
    @classmethod
    def strip_present_strings(cls, value: Any) -> Any:
        if value is None:
            return None

        return strip_non_empty_string(value)

    @field_validator("scope_id", mode="before")
    @classmethod
    def strip_present_scope_id(cls, value: Any) -> Any:
        if value is None:
            return None

        return strip_non_empty_string(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_present_timezone(cls, value: Any) -> Any:
        if value is None:
            return None

        return normalize_timezone(value)

    @model_validator(mode="after")
    def validate_present_scope_pair(self) -> "AutomationScheduleUpdate":
        if {"scope_type", "scope_id"}.issubset(self.model_fields_set):
            if self.scope_type is None:
                raise ValueError("scope_type must not be null")

            validate_scope_pair(self.scope_type, self.scope_id)

        return self


class AutomationScheduleRead(AutomationScheduleBase):
    id: int
    contract_version: str = Field(max_length=20)
    tenant_id: str = Field(min_length=1, max_length=64)
    next_run_at: datetime | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AutomationCallbackStatus(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class AutomationCommand(BaseModel):
    contract_version: ContractVersion = AUTOMATION_CONTRACT_VERSION
    execution_id: UUID
    automation_type: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=64)
    requested_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    callback_url: AnyHttpUrl

    model_config = ConfigDict(extra="forbid")

    @field_validator("automation_type", "tenant_id")
    @classmethod
    def strip_non_empty_strings(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("Value must not be empty")

        return normalized

    @field_validator("requested_at")
    @classmethod
    def require_aware_requested_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requested_at must include a timezone")

        return value


class AutomationCallbackResult(BaseModel):
    contract_version: ContractVersion = AUTOMATION_CONTRACT_VERSION
    execution_id: UUID
    status: AutomationCallbackStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_aware_timestamps(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("Callback timestamps must include a timezone")

        return value

    @model_validator(mode="after")
    def validate_timestamp_order(self) -> "AutomationCallbackResult":
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at must not precede started_at")

        return self
