from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class IikoSyncStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIALLY_SUCCEEDED = "PARTIALLY_SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IikoSyncType(StrEnum):
    CONNECTION_CHECK = "CONNECTION_CHECK"
    ORGANIZATIONS = "ORGANIZATIONS"
    ENTERPRISES = "ENTERPRISES"
    WAREHOUSES = "WAREHOUSES"
    PRODUCT_GROUPS = "PRODUCT_GROUPS"
    PRODUCTS = "PRODUCTS"
    UNITS = "UNITS"
    PACKAGES = "PACKAGES"
    STOCK_BALANCES = "STOCK_BALANCES"
    FULL_REFERENCE_SNAPSHOT = "FULL_REFERENCE_SNAPSHOT"


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]


json_type = JSON().with_variant(JSONB(), "postgresql")


class IikoSyncRun(Base):
    __tablename__ = "iiko_sync_runs"
    __table_args__ = (
        Index(
            "ix_iiko_sync_runs_tenant_type_started",
            "tenant_id",
            "sync_type",
            "started_at",
        ),
        Index(
            "ix_iiko_sync_runs_tenant_status_started",
            "tenant_id",
            "status",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_type: Mapped[IikoSyncType] = mapped_column(
        SqlEnum(
            IikoSyncType,
            name="iiko_sync_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=40,
        ),
        nullable=False,
    )
    status: Mapped[IikoSyncStatus] = mapped_column(
        SqlEnum(
            IikoSyncStatus,
            name="iiko_sync_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=32,
        ),
        default=IikoSyncStatus.PENDING,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_api_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
    )
    source_organization_id: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        json_type,
        default=dict,
        nullable=False,
    )
    records_received: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    records_created: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    records_updated: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    records_unchanged: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    records_failed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        String(500),
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

    raw_entities: Mapped[list["IikoRawEntity"]] = relationship(
        back_populates="sync_run",
    )


class IikoRawEntity(Base):
    __tablename__ = "iiko_raw_entities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            "external_id",
            "payload_hash",
            name="uq_iiko_raw_entity_version",
        ),
        Index(
            "ix_iiko_raw_entities_tenant_entity_external",
            "tenant_id",
            "entity_type",
            "external_id",
        ),
        Index(
            "ix_iiko_raw_entities_sync_run",
            "sync_run_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("iiko_sync_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    organization_external_id: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        json_type,
        nullable=False,
    )
    payload_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    sync_run: Mapped[IikoSyncRun] = relationship(
        back_populates="raw_entities",
    )
