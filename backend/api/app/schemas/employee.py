from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.employee import EmployeeLifecycleEventType, EmployeeRole, EmployeeStatus


def strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Value must not be blank")
    return value


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=240)
    birth_date: date
    photo_url: str | None = Field(default=None, max_length=500)
    phone: str = Field(min_length=1, max_length=64)
    residence_address: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")
    _strip_required = field_validator("full_name", "phone", "residence_address", "reason")(strip_required)


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=240)
    birth_date: date | None = None
    photo_url: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, min_length=1, max_length=64)
    residence_address: str | None = Field(default=None, min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")

    @field_validator("full_name", "phone", "residence_address", "reason")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return None if value is None else strip_required(value)

    @model_validator(mode="after")
    def require_change(self):
        changed = self.model_fields_set - {"reason"}
        if not changed:
            raise ValueError("At least one employee field must be provided")
        return self


class EmployeeRoleAssignmentCreate(BaseModel):
    role: EmployeeRole
    valid_from: datetime
    reason: str = Field(min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")
    _strip_reason = field_validator("reason")(strip_required)


class EmployeeDepartmentAssignmentCreate(BaseModel):
    department_id: UUID
    is_primary: bool = False
    valid_from: datetime
    reason: str = Field(min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")
    _strip_reason = field_validator("reason")(strip_required)


class AssignmentEnd(BaseModel):
    valid_to: datetime
    reason: str = Field(min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")
    _strip_reason = field_validator("reason")(strip_required)


class EmployeeDismiss(BaseModel):
    dismissal_date: date
    reason: str = Field(min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")
    _strip_reason = field_validator("reason")(strip_required)


class EmployeeReactivate(BaseModel):
    effective_date: date
    reason: str = Field(min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")
    _strip_reason = field_validator("reason")(strip_required)


class EmployeeUserLink(BaseModel):
    user_id: int
    reason: str = Field(min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")
    _strip_reason = field_validator("reason")(strip_required)


class EmployeeUserUnlink(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    model_config = ConfigDict(extra="forbid")
    _strip_reason = field_validator("reason")(strip_required)


class RoleAssignmentRead(BaseModel):
    id: UUID
    role: EmployeeRole
    valid_from: datetime
    valid_to: datetime | None
    reason: str
    assigned_by_user_id: int
    ended_reason: str | None
    ended_by_user_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DepartmentAssignmentRead(BaseModel):
    id: UUID
    department_id: UUID
    is_primary: bool
    valid_from: datetime
    valid_to: datetime | None
    reason: str
    assigned_by_user_id: int
    ended_reason: str | None
    ended_by_user_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LifecycleEventRead(BaseModel):
    id: UUID
    event_type: EmployeeLifecycleEventType
    effective_date: date
    reason: str
    actor_user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmployeeRead(BaseModel):
    id: UUID
    full_name: str
    birth_date: date
    photo_url: str | None
    phone: str
    residence_address: str
    status: EmployeeStatus
    dismissal_date: date | None
    dismissal_reason: str | None
    linked_user_id: int | None = None
    created_at: datetime
    updated_at: datetime
    role_assignments: list[RoleAssignmentRead] = Field(default_factory=list)
    department_assignments: list[DepartmentAssignmentRead] = Field(default_factory=list)
    lifecycle_events: list[LifecycleEventRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
