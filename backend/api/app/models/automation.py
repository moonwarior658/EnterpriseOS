from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AutomationScope(StrEnum):
    COMPANY = "company"
    DEPARTMENT = "department"
    LOCATION = "location"
    USER = "user"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]


class AutomationSchedule(Base):
    __tablename__ = "automation_schedules"
    __table_args__ = (
        Index(
            "ix_automation_schedules_due",
            "is_enabled",
            "next_run_at",
        ),
        Index(
            "ix_automation_schedules_tenant",
            "tenant_id",
            "automation_type",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    automation_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    contract_version: Mapped[str] = mapped_column(
        String(20),
        default="1.0",
        server_default="1.0",
        nullable=False,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_type: Mapped[AutomationScope] = mapped_column(
        SqlEnum(
            AutomationScope,
            name="automation_scope",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=32,
        ),
        default=AutomationScope.COMPANY,
        server_default=AutomationScope.COMPANY.value,
        nullable=False,
    )
    scope_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    schedule_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    recipients: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="UTC",
        server_default="UTC",
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    executions: Mapped[list["AutomationExecution"]] = relationship(
        back_populates="schedule",
        passive_deletes=True,
    )


class AutomationExecution(Base):
    __tablename__ = "automation_executions"
    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_automation_executions_attempt_count",
        ),
        CheckConstraint(
            "max_attempts >= 1",
            name="ck_automation_executions_max_attempts",
        ),
        Index(
            "ix_automation_executions_status_requested",
            "status",
            "requested_at",
        ),
        Index(
            "ix_automation_executions_tenant_requested",
            "tenant_id",
            "requested_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    execution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        default=uuid4,
        unique=True,
        index=True,
        nullable=False,
    )
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "automation_schedules.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    contract_version: Mapped[str] = mapped_column(
        String(20),
        default="1.0",
        server_default="1.0",
        nullable=False,
    )
    automation_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    scope_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    recipients: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    provider: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        SqlEnum(
            ExecutionStatus,
            name="automation_execution_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=32,
        ),
        default=ExecutionStatus.PENDING,
        server_default=ExecutionStatus.PENDING.value,
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
        nullable=False,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    schedule: Mapped[AutomationSchedule | None] = relationship(
        back_populates="executions",
    )
    outbox_events: Mapped[list["OutboxEvent"]] = relationship(
        back_populates="execution",
        passive_deletes=True,
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_outbox_events_attempt_count",
        ),
        CheckConstraint(
            "max_attempts >= 1",
            name="ck_outbox_events_max_attempts",
        ),
        Index(
            "ix_outbox_events_pending",
            "status",
            "available_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        default=uuid4,
        unique=True,
        index=True,
        nullable=False,
    )
    execution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "automation_executions.execution_id",
            ondelete="RESTRICT",
        ),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    contract_version: Mapped[str] = mapped_column(
        String(20),
        default="1.0",
        server_default="1.0",
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    status: Mapped[OutboxStatus] = mapped_column(
        SqlEnum(
            OutboxStatus,
            name="outbox_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=32,
        ),
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=10,
        server_default="10",
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    execution: Mapped[AutomationExecution] = relationship(
        back_populates="outbox_events",
    )
