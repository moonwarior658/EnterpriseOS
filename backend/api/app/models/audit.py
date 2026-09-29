from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, JSON,
    String, UniqueConstraint, event, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


json_type = JSON().with_variant(JSONB(), "postgresql")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_audit_events_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "actor_employee_id"],
            ["employees.tenant_id", "employees.id"],
            name="fk_audit_events_actor_employee_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "primary_department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_audit_events_primary_department_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actual_department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_audit_events_actual_department_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "shift_id"],
            ["employee_iiko_shifts.tenant_id", "employee_iiko_shifts.id"],
            name="fk_audit_events_shift_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "correction_of_event_id"],
            ["audit_events.tenant_id", "audit_events.id"],
            name="fk_audit_events_correction_tenant", ondelete="RESTRICT",
        ),
        CheckConstraint(
            "reason IS NULL OR length(trim(reason)) > 0",
            name="ck_audit_events_reason",
        ),
        CheckConstraint("source IN ('HUMAN', 'SYSTEM')", name="ck_audit_events_source"),
        CheckConstraint(
            "(source = 'HUMAN' AND actor_user_id IS NOT NULL) "
            "OR (source = 'SYSTEM' AND actor_user_id IS NULL)",
            name="ck_audit_events_actor_source",
        ),
        Index("ix_audit_events_tenant_occurred", "tenant_id", "occurred_at", "id"),
        Index("ix_audit_events_entity", "tenant_id", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_events_employee", "tenant_id", "actor_employee_id", "occurred_at"),
        Index("ix_audit_events_department", "tenant_id", "actual_department_id", "occurred_at"),
        Index("ix_audit_events_type", "tenant_id", "event_type", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    actor_employee_id: Mapped[UUID | None] = mapped_column(nullable=True)
    actor_name_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    active_roles_snapshot: Mapped[list[str]] = mapped_column(json_type, default=list, nullable=False)
    authorized_as: Mapped[str | None] = mapped_column(String(32), nullable=True)
    primary_department_id: Mapped[UUID | None] = mapped_column(nullable=True)
    primary_department_name_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    actual_department_id: Mapped[UUID | None] = mapped_column(nullable=True)
    actual_department_name_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    shift_id: Mapped[UUID | None] = mapped_column(nullable=True)
    shift_context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(json_type, nullable=True)
    before: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    correction_of_event_id: Mapped[UUID | None] = mapped_column(nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(160), nullable=True)


def _immutable_audit_event(*_args, **_kwargs) -> None:
    raise RuntimeError("AuditEvent is immutable")


event.listen(AuditEvent, "before_update", _immutable_audit_event, propagate=True)
event.listen(AuditEvent, "before_delete", _immutable_audit_event, propagate=True)
