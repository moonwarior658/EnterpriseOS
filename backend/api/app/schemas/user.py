import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=256)
    avatar_url: str | None = Field(default=None, max_length=500)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return normalize_username(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return value.strip()


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
