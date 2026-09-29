from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    id: UUID
    tenant_id: str
    event_type: str
    entity_type: str
    entity_id: str
    operation: str
    occurred_at: datetime
    actor_user_id: int | None
    actor_employee_id: UUID | None
    actor_name_snapshot: str | None
    active_roles_snapshot: list[str]
    authorized_as: str | None
    primary_department_id: UUID | None
    primary_department_name_snapshot: str | None
    actual_department_id: UUID | None
    actual_department_name_snapshot: str | None
    shift_id: UUID | None
    shift_context_snapshot: dict[str, Any] | None
    before: dict[str, Any]
    after: dict[str, Any]
    reason: str | None
    source: str
    correction_of_event_id: UUID | None
    correlation_id: str | None

    model_config = ConfigDict(from_attributes=True)


class SupplyRequestHistoryRead(BaseModel):
    id: UUID
    occurred_at: datetime
    actor_name: str | None
    operation: str
    before: dict[str, Any]
    after: dict[str, Any]
    reason: str | None
