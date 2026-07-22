from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from app.automation.catalog import require_available_automation_type


AUTOMATION_CONTRACT_VERSION = "1.0"
ContractVersion = Literal["1.0"]
AutomationScopeType = Literal[
    "company",
    "department",
    "location",
    "user",
]
ScheduleTime = Annotated[
    str,
    Field(strict=True, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"),
]


class DailyScheduleConfig(BaseModel):
    type: Literal["daily"]
    time: ScheduleTime

    model_config = ConfigDict(extra="forbid")


class WeeklyScheduleConfig(BaseModel):
    type: Literal["weekly"]
    weekdays: list[
        Annotated[StrictInt, Field(ge=0, le=6)]
    ] = Field(min_length=1)
    time: ScheduleTime

    model_config = ConfigDict(extra="forbid")

    @field_validator("weekdays")
    @classmethod
    def normalize_weekdays(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("weekdays must not contain duplicates")

        return sorted(value)


class IntervalScheduleConfig(BaseModel):
    type: Literal["interval"]
    minutes: Annotated[StrictInt, Field(ge=1, le=10080)]

    model_config = ConfigDict(extra="forbid")


ScheduleConfig = Annotated[
    DailyScheduleConfig | WeeklyScheduleConfig | IntervalScheduleConfig,
    Field(discriminator="type"),
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
    schedule_config: ScheduleConfig
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
    @field_validator("automation_type")
    @classmethod
    def validate_automation_type(cls, value: str) -> str:
        require_available_automation_type(value)
        return value


class AutomationScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    automation_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
    scope_type: AutomationScopeType | None = None
    scope_id: str | None = Field(default=None, max_length=64)
    schedule_config: ScheduleConfig | None = None
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

    @field_validator("automation_type")
    @classmethod
    def validate_automation_type(cls, value: str | None) -> str | None:
        if value is not None:
            require_available_automation_type(value)
        return value

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


class AutomationCallbackStatus(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class AutomationTypeRead(BaseModel):
    key: str
    display_name: str
    description: str
    category: str
    is_system: bool
    supports_manual_run: bool


class AutomationScheduleRead(AutomationScheduleBase):
    id: int
    contract_version: str = Field(max_length=20)
    tenant_id: str = Field(min_length=1, max_length=64)
    next_run_at: datetime | None
    created_by_user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AutomationScheduleAuditItem(BaseModel):
    id: int
    event_type: Literal[
        "automation_schedule_created",
        "automation_schedule_updated",
        "automation_schedule_enabled",
        "automation_schedule_disabled",
        "automation_schedule_run_requested",
    ]
    actor_user_id: int
    actor_display_name: str | None
    occurred_at: datetime
    metadata: dict[str, Any]


class AutomationScheduleAuditPage(BaseModel):
    items: list[AutomationScheduleAuditItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AutomationExecutionRead(BaseModel):
    id: int
    execution_id: UUID
    schedule_id: int | None
    automation_type: str
    scope_type: AutomationScopeType
    scope_id: str | None
    recipients: list[Any]
    status: AutomationCallbackStatus
    provider: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AutomationExecutionHistoryItem(BaseModel):
    status: AutomationCallbackStatus
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None = Field(ge=0)
    user_status: str
    user_message: str
    error_category: str | None
    error_code: str | None
    error_message: str | None


class AutomationLatestExecutionItem(BaseModel):
    schedule_id: int
    status: AutomationCallbackStatus | None
    requested_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: float | None = Field(ge=0)
    user_status: str
    user_message: str
    error_category: str | None
    error_code: str | None


class AutomationExecutionHistoryPage(BaseModel):
    items: list[AutomationExecutionHistoryItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class AutomationComponentState(BaseModel):
    status: Literal["unknown", "healthy", "degraded"]
    last_heartbeat_at: datetime | None
    heartbeat_age_seconds: int | None = Field(ge=0)
    worker_id: str | None = None
    poll_interval_seconds: float | None = Field(default=None, gt=0)


class AutomationSchedulerState(BaseModel):
    status: Literal["healthy", "degraded", "unknown"]
    last_run_at: datetime | None
    age_seconds: int | None = Field(ge=0)
    scanned: int = Field(ge=0)
    claimed: int = Field(ge=0)
    created: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)
    poll_interval_seconds: float | None = Field(default=None, gt=0)


class AutomationN8nState(BaseModel):
    configured: bool
    reachable: bool | None
    checked_at: datetime | None
    latency_ms: int | None = Field(default=None, ge=0)
    status: Literal["healthy", "degraded", "unavailable", "unknown"]
    safe_message: str


class AutomationOutboxSummary(BaseModel):
    pending: int = Field(ge=0)
    processing: int = Field(ge=0)
    retry_scheduled: int = Field(ge=0)
    published: int = Field(ge=0)
    failed: int = Field(ge=0)
    oldest_pending_at: datetime | None
    oldest_pending_age_seconds: int | None = Field(ge=0)
    stuck_count: int = Field(ge=0)


class AutomationSafeErrorSummary(BaseModel):
    error_category: str
    error_code: str
    count: int = Field(ge=1)
    last_occurred_at: datetime


class AutomationExecutionSummary(BaseModel):
    pending: int = Field(ge=0)
    running: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    timed_out: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    running_too_long_count: int = Field(ge=0)
    recent_system_errors: list[AutomationSafeErrorSummary]


class AutomationDiagnosticAlert(BaseModel):
    code: str
    severity: Literal["warning", "critical"]
    title: str
    safe_message: str
    count: int = Field(ge=1)
    detected_at: datetime


class AutomationDiagnosticsSnapshot(BaseModel):
    generated_at: datetime
    worker_state: AutomationComponentState
    scheduler_state: AutomationSchedulerState
    n8n_state: AutomationN8nState
    outbox_summary: AutomationOutboxSummary
    execution_summary: AutomationExecutionSummary
    alerts: list[AutomationDiagnosticAlert]


class AutomationCommand(BaseModel):
    contract_version: ContractVersion = AUTOMATION_CONTRACT_VERSION
    execution_id: UUID
    idempotency_key: UUID
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

    @model_validator(mode="after")
    def require_execution_id_as_idempotency_key(
        self,
    ) -> "AutomationCommand":
        if self.idempotency_key != self.execution_id:
            raise ValueError(
                "idempotency_key must match execution_id"
            )

        return self


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
