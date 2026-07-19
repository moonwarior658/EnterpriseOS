from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

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
