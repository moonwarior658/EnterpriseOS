import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import UserAccountType


USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]+$")


def normalize_username(value: str) -> str:
    normalized = value.strip().lower()

    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Login may contain only latin letters, numbers, dot, dash and underscore"
        )

    return normalized


class UserRead(BaseModel):
    id: int
    username: str
    display_name: str
    avatar_url: str | None
    is_active: bool
    is_admin: bool
    can_view_requests: bool
    account_type: UserAccountType
    blocked_by_employee_dismissal: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    avatar_url: str | None = Field(default=None, max_length=500)
    is_admin: bool = False
    can_view_requests: bool = False
    account_type: UserAccountType = UserAccountType.HUMAN
    employee_id: UUID | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return normalize_username(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_password_source(self):
        if self.account_type == UserAccountType.HUMAN and self.password is not None:
            raise ValueError("Password is generated automatically for HUMAN users")
        if self.account_type == UserAccountType.SERVICE and self.password is None:
            raise ValueError("Password is required for SERVICE users")
        return self


class UserCreated(UserRead):
    temporary_password: str | None


class GeneratedCredentials(BaseModel):
    username: str
    temporary_password: str


class PasswordReset(BaseModel):
    reason: str | None = Field(default=None, min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Reason must not be blank")
        return value


class OwnPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=256)
    model_config = ConfigDict(extra="forbid")


class UserUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
    )
    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    password: str | None = Field(
        default=None,
        min_length=12,
        max_length=256,
    )
    avatar_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    is_admin: bool | None = None
    can_view_requests: bool | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Reason must not be blank")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str | None) -> str | None:
        if value is None:
            return None

        return normalize_username(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        return value.strip()
