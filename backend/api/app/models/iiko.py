from datetime import datetime
from decimal import Decimal
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
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.supply import LegalContour


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
    STOCK_BALANCE_SNAPSHOT = "STOCK_BALANCE_SNAPSHOT"
    FULL_REFERENCE_SNAPSHOT = "FULL_REFERENCE_SNAPSHOT"


class IikoStockBalanceSnapshotSourceStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class IikoMappingStatus(StrEnum):
    UNMAPPED = "UNMAPPED"
    SUGGESTED = "SUGGESTED"
    CONFIRMED = "CONFIRMED"
    CONFLICT = "CONFLICT"
    IGNORED = "IGNORED"


class IikoWarehouseRole(StrEnum):
    MAIN = "MAIN"
    PACKAGING = "PACKAGING"
    HOUSEHOLD = "HOUSEHOLD"
    FIXED_ASSETS = "FIXED_ASSETS"
    OTHER = "OTHER"


class IikoWarehouseDestinationType(StrEnum):
    DESTINATION = "DESTINATION"
    SOURCE = "SOURCE"


class IikoMappingKind(StrEnum):
    PRODUCT = "PRODUCT"
    UNIT = "UNIT"
    WAREHOUSE = "WAREHOUSE"


class IikoMappingAction(StrEnum):
    GENERATED = "GENERATED"
    CONFIRMED = "CONFIRMED"
    REPLACED = "REPLACED"
    IGNORED = "IGNORED"
    UNMAPPED = "UNMAPPED"


def enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [item.value for item in enum_class]


json_type = JSON().with_variant(JSONB(), "postgresql")


class IikoSyncRun(Base):
    __tablename__ = "iiko_sync_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_iiko_sync_runs_tenant_id",
        ),
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
    stock_balance_sources: Mapped[
        list["IikoStockBalanceSnapshotSource"]
    ] = (
        relationship(back_populates="sync_run")
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


class IikoStockBalanceSnapshotSource(Base):
    __tablename__ = "iiko_stock_balance_snapshot_sources"
    __table_args__ = (
        UniqueConstraint(
            "sync_run_id",
            "source_warehouse_mapping_id",
            name="uq_iiko_stock_snapshot_source_run_source",
        ),
        UniqueConstraint(
            "tenant_id",
            "sync_run_id",
            "department_id",
            "source_warehouse_mapping_id",
            name="uq_iiko_stock_snapshot_source_tenant_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "sync_run_id"],
            ["iiko_sync_runs.tenant_id", "iiko_sync_runs.id"],
            name="fk_iiko_stock_snapshot_tenant_run",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_iiko_stock_snapshot_tenant_department",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_warehouse_mapping_id"],
            ["iiko_warehouse_mappings.tenant_id", "iiko_warehouse_mappings.id"],
            name="fk_iiko_stock_snapshot_tenant_source",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_iiko_stock_snapshot_source_latest",
            "tenant_id",
            "source_warehouse_mapping_id",
            "status",
            "snapshot_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    department_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_warehouse_mapping_id: Mapped[UUID] = mapped_column(
        Uuid, nullable=False,
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    status: Mapped[IikoStockBalanceSnapshotSourceStatus] = mapped_column(
        SqlEnum(
            IikoStockBalanceSnapshotSourceStatus,
            name="iiko_stock_snapshot_source_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=16,
        ),
        nullable=False,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    sync_run: Mapped[IikoSyncRun] = relationship(
        back_populates="stock_balance_sources",
    )
    lines: Mapped[list["IikoStockBalanceSnapshotLine"]] = relationship(
        back_populates="snapshot_source",
    )


class IikoStockBalanceSnapshotLine(Base):
    __tablename__ = "iiko_stock_balance_snapshot_lines"
    __table_args__ = (
        UniqueConstraint(
            "sync_run_id",
            "source_warehouse_mapping_id",
            "iiko_product_id",
            name="uq_iiko_stock_snapshot_run_source_product",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "sync_run_id",
                "department_id",
                "source_warehouse_mapping_id",
            ],
            [
                "iiko_stock_balance_snapshot_sources.tenant_id",
                "iiko_stock_balance_snapshot_sources.sync_run_id",
                "iiko_stock_balance_snapshot_sources.department_id",
                "iiko_stock_balance_snapshot_sources.source_warehouse_mapping_id",
            ],
            name="fk_iiko_stock_snapshot_line_source_scope",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_iiko_stock_snapshot_line_run_product",
            "tenant_id",
            "sync_run_id",
            "iiko_product_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    department_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_warehouse_mapping_id: Mapped[UUID] = mapped_column(
        Uuid, nullable=False,
    )
    iiko_warehouse_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    iiko_product_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    iiko_unit_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    snapshot_source: Mapped[IikoStockBalanceSnapshotSource] = relationship(
        back_populates="lines",
    )


class IikoProductMapping(Base):
    __tablename__ = "iiko_product_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "iiko_product_id",
            name="uq_iiko_product_mappings_tenant_external",
        ),
        Index(
            "ix_iiko_product_mappings_queue",
            "tenant_id",
            "status",
            "is_deleted",
            "source_name",
        ),
        Index(
            "uq_iiko_product_mappings_confirmed_eos",
            "tenant_id",
            "eos_product_id",
            unique=True,
            postgresql_where=text(
                "status = 'CONFIRMED' AND is_deleted = false "
                "AND eos_product_id IS NOT NULL"
            ),
            sqlite_where=text(
                "status = 'CONFIRMED' AND is_deleted = false "
                "AND eos_product_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iiko_product_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    eos_product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_products.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[IikoMappingStatus] = mapped_column(
        SqlEnum(
            IikoMappingStatus,
            name="iiko_mapping_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=16,
        ),
        default=IikoMappingStatus.UNMAPPED,
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(String(240), nullable=False)
    source_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_sku: Mapped[str | None] = mapped_column(String(160), nullable=True)
    source_unit_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasons: Mapped[list[str]] = mapped_column(json_type, default=list, nullable=False)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    eos_product: Mapped[Any | None] = relationship("SupplyProduct")


class IikoUnitMapping(Base):
    __tablename__ = "iiko_unit_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "iiko_unit_id",
            name="uq_iiko_unit_mappings_tenant_external",
        ),
        Index(
            "ix_iiko_unit_mappings_queue",
            "tenant_id",
            "status",
            "is_deleted",
            "source_name",
        ),
        Index(
            "uq_iiko_unit_mappings_confirmed_eos",
            "tenant_id",
            "eos_unit_id",
            unique=True,
            postgresql_where=text(
                "status = 'CONFIRMED' AND is_deleted = false "
                "AND eos_unit_id IS NOT NULL"
            ),
            sqlite_where=text(
                "status = 'CONFIRMED' AND is_deleted = false "
                "AND eos_unit_id IS NOT NULL"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iiko_unit_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    eos_unit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[IikoMappingStatus] = mapped_column(
        SqlEnum(
            IikoMappingStatus,
            name="iiko_mapping_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=16,
        ),
        default=IikoMappingStatus.UNMAPPED,
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasons: Mapped[list[str]] = mapped_column(json_type, default=list, nullable=False)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    eos_unit: Mapped[Any | None] = relationship("SupplyUnit")


class IikoWarehouseMapping(Base):
    __tablename__ = "iiko_warehouse_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "iiko_warehouse_id",
            name="uq_iiko_warehouse_mappings_tenant_external",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_iiko_warehouse_mappings_tenant_id",
        ),
        Index(
            "ix_iiko_warehouse_mappings_queue",
            "tenant_id",
            "status",
            "is_deleted",
            "source_name",
        ),
        Index(
            "uq_iiko_warehouse_mappings_confirmed_role",
            "tenant_id",
            "eos_department_id",
            "role",
            unique=True,
            postgresql_where=text(
                "status = 'CONFIRMED' "
                "AND destination_type = 'DESTINATION' "
                "AND eos_department_id IS NOT NULL "
                "AND role IS NOT NULL AND is_deleted = false"
            ),
            sqlite_where=text(
                "status = 'CONFIRMED' "
                "AND destination_type = 'DESTINATION' "
                "AND eos_department_id IS NOT NULL "
                "AND role IS NOT NULL AND is_deleted = false"
            ),
        ),
        CheckConstraint(
            "status != 'CONFIRMED' OR "
            "(destination_type = 'DESTINATION' "
            "AND eos_department_id IS NOT NULL AND role IS NOT NULL "
            "AND legal_contour IS NULL) OR "
            "(destination_type = 'SOURCE' "
            "AND eos_department_id IS NULL AND role IS NOT NULL "
            "AND legal_contour IS NOT NULL)",
            name="ck_iiko_warehouse_mapping_confirmed_target",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iiko_warehouse_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    eos_department_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    destination_type: Mapped[IikoWarehouseDestinationType] = mapped_column(
        SqlEnum(
            IikoWarehouseDestinationType,
            name="iiko_warehouse_destination_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=16,
        ),
        default=IikoWarehouseDestinationType.DESTINATION,
        nullable=False,
    )
    role: Mapped[IikoWarehouseRole | None] = mapped_column(
        SqlEnum(
            IikoWarehouseRole,
            name="iiko_warehouse_role",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=24,
        ),
        nullable=True,
    )
    legal_contour: Mapped[LegalContour | None] = mapped_column(
        SqlEnum(
            LegalContour,
            name="iiko_warehouse_mapping_legal_contour",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=8,
        ),
        nullable=True,
    )
    status: Mapped[IikoMappingStatus] = mapped_column(
        SqlEnum(
            IikoMappingStatus,
            name="iiko_mapping_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=16,
        ),
        default=IikoMappingStatus.UNMAPPED,
        nullable=False,
    )
    source_name: Mapped[str] = mapped_column(String(240), nullable=False)
    source_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasons: Mapped[list[str]] = mapped_column(json_type, default=list, nullable=False)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    eos_department: Mapped[Any | None] = relationship("Department")


class IikoMappingAuditEvent(Base):
    __tablename__ = "iiko_mapping_audit_events"
    __table_args__ = (
        Index(
            "ix_iiko_mapping_audit_tenant_mapping",
            "tenant_id",
            "mapping_kind",
            "mapping_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_kind: Mapped[IikoMappingKind] = mapped_column(
        SqlEnum(
            IikoMappingKind,
            name="iiko_mapping_kind",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=16,
        ),
        nullable=False,
    )
    mapping_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    action: Mapped[IikoMappingAction] = mapped_column(
        SqlEnum(
            IikoMappingAction,
            name="iiko_mapping_action",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            length=16,
        ),
        nullable=False,
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    before: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(json_type, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
