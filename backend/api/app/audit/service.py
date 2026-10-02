from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.employee import Employee, EmployeeIikoShift
from app.models.supply import Department
from app.models.user import User, UserAccountType

if TYPE_CHECKING:
    from app.core.action_context import ActionContext


FORBIDDEN_AUDIT_KEYS = (
    "password", "hashed_password", "token", "secret", "credential",
    "residence_address", "birth_date", "raw_payload", "raw_response",
)


def sanitize_audit_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                str(key): clean(child)
                for key, child in item.items()
                if not any(part in str(key).casefold() for part in FORBIDDEN_AUDIT_KEYS)
            }
        if isinstance(item, (list, tuple, set, frozenset)):
            return [clean(child) for child in item]
        return jsonable_encoder(item)

    return clean(value or {})


def record_audit_event(
    db: Session,
    *,
    tenant_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str | UUID | int,
    operation: str,
    context: "ActionContext | None" = None,
    actor_user: User | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    source: str = "HUMAN",
    correction_of_event_id: UUID | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    if reason is not None:
        reason = reason.strip()
        if not reason:
            raise ValueError("Audit reason must not be empty")
    own_password_without_employee = (
        event_type == "USER_PASSWORD_CHANGED"
        and entity_type == "User"
        and operation == "CHANGE_PASSWORD"
        and actor_user is not None
        and actor_user.account_type == UserAccountType.HUMAN
        and str(actor_user.id) == str(entity_id)
    )
    if source == "HUMAN" and (
        actor_user is None or (context is None and not own_password_without_employee)
    ):
        raise ValueError("Human audit event requires actor and ActionContext")
    if source == "SYSTEM" and actor_user is not None:
        raise ValueError("System audit event cannot have a human actor")

    shift = db.get(EmployeeIikoShift, context.shift_id) if context and context.shift_id else None
    if correction_of_event_id is not None and db.scalar(select(AuditEvent.id).where(
        AuditEvent.tenant_id == tenant_id,
        AuditEvent.id == correction_of_event_id,
    )) is None:
        raise ValueError("Corrected audit event not found")

    audit_event = AuditEvent(
        tenant_id=tenant_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        operation=operation,
        occurred_at=context.determined_at if context else datetime.now(timezone.utc),
        actor_user_id=actor_user.id if actor_user else None,
        actor_employee_id=context.employee_id if context else None,
        actor_name_snapshot=context.employee_name_snapshot if context else None,
        active_roles_snapshot=sorted(role.value for role in context.roles) if context else [],
        authorized_as=context.authorized_as.value if context and context.authorized_as else None,
        primary_department_id=context.primary_department_id if context else None,
        primary_department_name_snapshot=(context.primary_department_name_snapshot if context else None),
        actual_department_id=context.actual_department_id if context else None,
        actual_department_name_snapshot=(context.actual_department_name_snapshot if context else None),
        shift_id=context.shift_id if context else None,
        shift_context_snapshot=(
            sanitize_audit_payload({
                "opened_at": shift.opened_at,
                "external_shift_id": shift.external_shift_id,
                "substitution_confirmed": context.substitution_confirmed,
            }) if shift and context else None
        ),
        before=sanitize_audit_payload(before),
        after=sanitize_audit_payload(after),
        reason=reason,
        source=source,
        correction_of_event_id=correction_of_event_id,
        correlation_id=correlation_id,
    )
    db.add(audit_event)
    return audit_event


def record_current_action_event(
    db: Session,
    *,
    entity: Any,
    operation: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEvent | None:
    """Record an explicit service transition in the current API transaction."""
    context = db.info.get("action_context")
    actor_user = db.info.get("action_user")
    if context is None and actor_user is None:
        # Existing internal service callers have no human actor.
        return None
    if context is None or actor_user is None or context.authorized_as is None:
        raise ValueError("Business write requires a complete ActionContext")
    return record_audit_event(
        db,
        tenant_id=actor_user.tenant_id,
        event_type=f"{type(entity).__name__.upper()}_{operation}",
        entity_type=type(entity).__name__,
        entity_id=entity.id,
        operation=operation,
        context=context,
        actor_user=actor_user,
        before=before,
        after=after,
        reason=reason,
    )


def audit_query(
    *,
    tenant_id: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    employee_id: UUID | None = None,
    department_id: UUID | None = None,
    event_type: str | None = None,
    operation: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Select[tuple[AuditEvent]]:
    query = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
    filters = {
        AuditEvent.entity_type: entity_type,
        AuditEvent.entity_id: entity_id,
        AuditEvent.actor_employee_id: employee_id,
        AuditEvent.event_type: event_type,
        AuditEvent.operation: operation,
    }
    for column, value in filters.items():
        if value is not None:
            query = query.where(column == value)
    if department_id is not None:
        query = query.where(or_(
            AuditEvent.primary_department_id == department_id,
            AuditEvent.actual_department_id == department_id,
        ))
    if date_from is not None:
        query = query.where(AuditEvent.occurred_at >= date_from)
    if date_to is not None:
        query = query.where(AuditEvent.occurred_at <= date_to)
    return query
