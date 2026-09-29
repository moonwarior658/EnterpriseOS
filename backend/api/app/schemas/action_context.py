from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.employee import EmployeeRole


class ActionContextRead(BaseModel):
    user_id: int
    employee_id: UUID
    roles: list[EmployeeRole]
    authorized_as: EmployeeRole | None
    primary_department_id: UUID | None
    actual_department_id: UUID | None
    shift_id: UUID | None
    shift_opened_at: datetime | None
    substitution_confirmed: bool
    determined_at: datetime


class ShiftSubstitutionConfirm(BaseModel):
    shift_id: UUID

    model_config = ConfigDict(extra="forbid")
