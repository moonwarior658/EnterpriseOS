from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LegalContour(StrEnum):
    IP = "IP"
    OOO = "OOO"


class SupplyProductSourceRole(StrEnum):
    MAIN = "MAIN"
    PACKAGING = "PACKAGING"
    HOUSEHOLD = "HOUSEHOLD"


class SupplyProductSourceAuditAction(StrEnum):
    BOOTSTRAPPED = "BOOTSTRAPPED"
    ASSIGNED = "ASSIGNED"
    REPLACED = "REPLACED"


class SupplyStockCalculationStatus(StrEnum):
    PRELIMINARY = "PRELIMINARY"
    CONFIRMED = "CONFIRMED"


class SupplyStockCalculationAuditAction(StrEnum):
    AUTO_CALCULATED = "AUTO_CALCULATED"
    MANUALLY_ADJUSTED = "MANUALLY_ADJUSTED"
    CONFIRMED = "CONFIRMED"
    RECALCULATED = "RECALCULATED"


class SupplyContextMappingAuditAction(StrEnum):
    CREATED = "CREATED"
    REPLACED = "REPLACED"
    DELETED = "DELETED"


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_departments_tenant_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_departments_tenant_code",
        ),
        Index(
            "ix_departments_tenant_active_order",
            "tenant_id",
            "is_active",
            "display_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    legal_contour: Mapped[LegalContour | None] = mapped_column(
        SqlEnum(
            LegalContour,
            name="department_legal_contour",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            length=8,
        ),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
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


class SupplyRequestDirection(Base):
    __tablename__ = "supply_request_directions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_supply_request_directions_tenant_code",
        ),
        Index(
            "ix_supply_request_directions_tenant_active_order",
            "tenant_id",
            "is_active",
            "display_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
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


class SupplyRequestCycle(Base):
    __tablename__ = "supply_request_cycles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "direction_id",
            "cycle_date",
            name="uq_supply_request_cycles_tenant_direction_date",
        ),
        CheckConstraint(
            "status IN ('SCHEDULED', 'OPEN', 'CLOSED', 'CANCELLED')",
            name="ck_supply_request_cycles_status",
        ),
        CheckConstraint(
            "closes_at > opens_at",
            name="ck_supply_request_cycles_time_window",
        ),
        CheckConstraint(
            "hard_closes_at IS NULL OR hard_closes_at >= closes_at",
            name="ck_supply_request_cycles_hard_close",
        ),
        Index(
            "ix_supply_request_cycles_tenant_date_status",
            "tenant_id",
            "cycle_date",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    direction_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_request_directions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cycle_date: Mapped[date] = mapped_column(Date, nullable=False)
    opens_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    closes_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    hard_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="SCHEDULED",
        server_default="SCHEDULED",
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

    direction: Mapped[SupplyRequestDirection] = relationship()


class SupplyUnit(Base):
    __tablename__ = "supply_units"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_supply_units_tenant_code",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_supply_units_tenant_id"
        ),
        Index(
            "ix_supply_units_tenant_active_code",
            "tenant_id",
            "is_active",
            "code",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name_ru: Mapped[str] = mapped_column(String(120), nullable=False)
    short_name_ru: Mapped[str] = mapped_column(String(32), nullable=False)
    allows_fraction: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
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


class SupplyProductCategory(Base):
    __tablename__ = "supply_product_categories"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_supply_product_categories_tenant_code",
        ),
        UniqueConstraint(
            "tenant_id",
            "normalized_name",
            name="uq_supply_product_categories_tenant_normalized_name",
        ),
        Index(
            "ix_supply_product_categories_tenant_active_order",
            "tenant_id",
            "is_active",
            "sort_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
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


class SupplyStorageZone(Base):
    __tablename__ = "supply_storage_zones"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_supply_storage_zones_tenant_code",
        ),
        UniqueConstraint(
            "tenant_id",
            "normalized_name",
            name="uq_supply_storage_zones_tenant_normalized_name",
        ),
        Index(
            "ix_supply_storage_zones_tenant_active_order",
            "tenant_id",
            "is_active",
            "sort_order",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
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


class SupplyProduct(Base):
    __tablename__ = "supply_products"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "id", name="uq_supply_products_tenant_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "normalized_name",
            name="uq_supply_products_tenant_normalized_name",
        ),
        Index(
            "ix_supply_products_tenant_active_name",
            "tenant_id",
            "is_active",
            "normalized_name",
        ),
        Index(
            "uq_supply_products_tenant_iiko_id",
            "tenant_id",
            "iiko_id",
            unique=True,
            postgresql_where=text("iiko_id IS NOT NULL"),
            sqlite_where=text("iiko_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(is_active = true AND archived_at IS NULL AND "
            "archived_by_user_id IS NULL) OR "
            "(is_active = false AND archived_at IS NOT NULL AND "
            "archived_by_user_id IS NOT NULL)",
            name="ck_supply_products_archive_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    iiko_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    default_unit_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_units.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_direction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_request_directions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_product_categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    storage_zone_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_storage_zones.id", ondelete="RESTRICT"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
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

    default_unit: Mapped[SupplyUnit] = relationship()
    request_direction: Mapped[SupplyRequestDirection | None] = relationship()
    category: Mapped[SupplyProductCategory | None] = relationship()
    storage_zone: Mapped[SupplyStorageZone | None] = relationship()
    aliases: Mapped[list["SupplyProductAlias"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplyProductAlias.created_at",
    )


class SupplyProductAlias(Base):
    __tablename__ = "supply_product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "normalized_alias",
            name="uq_supply_product_aliases_tenant_normalized_alias",
        ),
        Index(
            "ix_supply_product_aliases_product",
            "product_id",
            "created_at",
        ),
        CheckConstraint(
            "status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'DISABLED')",
            name="ck_supply_product_aliases_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="APPROVED", server_default="APPROVED", nullable=False
    )
    successful_application_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    last_applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product: Mapped[SupplyProduct] = relationship(back_populates="aliases")


class SupplyDepartmentProductMapping(Base):
    __tablename__ = "supply_department_product_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "department_id", "normalized_phrase",
            name="uq_supply_department_product_mapping_context",
        ),
        Index(
            "ix_supply_department_product_mapping_phrase",
            "tenant_id", "normalized_phrase",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_supply_context_mapping_tenant_department",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_context_mapping_tenant_product",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "version >= 1", name="ck_supply_context_mapping_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    phrase: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_phrase: Mapped[str] = mapped_column(String(240), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    is_permanent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    department: Mapped[Department] = relationship(overlaps="product")
    product: Mapped[SupplyProduct] = relationship(overlaps="department")


class SupplyDepartmentProductCorrection(Base):
    __tablename__ = "supply_department_product_corrections"
    __table_args__ = (
        UniqueConstraint(
            "request_line_id", "product_id",
            name="uq_supply_department_product_correction_line_product",
        ),
        Index(
            "ix_supply_department_product_correction_count",
            "tenant_id", "department_id", "normalized_phrase", "product_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_supply_context_correction_tenant_department",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_context_correction_tenant_product",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    normalized_phrase: Mapped[str] = mapped_column(String(240), nullable=False)
    product_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    request_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_request_lines.id", ondelete="CASCADE"),
        nullable=False,
    )
    corrected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SupplyDepartmentProductMappingAuditEvent(Base):
    __tablename__ = "supply_department_product_mapping_audit_events"
    __table_args__ = (
        Index(
            "ix_supply_department_product_mapping_audit",
            "tenant_id", "mapping_id", "created_at",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_supply_context_audit_tenant_department",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mapping_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[SupplyContextMappingAuditAction] = mapped_column(
        SqlEnum(
            SupplyContextMappingAuditAction,
            name="supply_context_mapping_audit_action",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        nullable=False,
    )
    department_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    normalized_phrase: Mapped[str] = mapped_column(String(240), nullable=False)
    previous_product_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    product_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SupplyProductSourceMapping(Base):
    __tablename__ = "supply_product_source_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "eos_product_id",
            "legal_contour",
            name="uq_supply_product_source_mapping_product_contour",
        ),
        Index(
            "ix_supply_product_source_mapping_source",
            "tenant_id",
            "source_warehouse_mapping_id",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_supply_product_source_mapping_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    eos_product_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_products.id", ondelete="RESTRICT"), nullable=False
    )
    legal_contour: Mapped[LegalContour] = mapped_column(
        SqlEnum(
            LegalContour,
            name="supply_product_source_legal_contour",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            length=8,
        ),
        nullable=False,
    )
    role: Mapped[SupplyProductSourceRole] = mapped_column(
        SqlEnum(
            SupplyProductSourceRole,
            name="supply_product_source_role",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        nullable=False,
    )
    source_warehouse_mapping_id: Mapped[UUID] = mapped_column(
        ForeignKey("iiko_warehouse_mappings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    assigned_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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

    product: Mapped[SupplyProduct] = relationship()


class SupplyProductSourceMappingAuditEvent(Base):
    __tablename__ = "supply_product_source_mapping_audit_events"
    __table_args__ = (
        Index(
            "ix_supply_product_source_audit_mapping_created",
            "tenant_id",
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
    mapping_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_product_source_mappings.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[SupplyProductSourceAuditAction] = mapped_column(
        SqlEnum(
            SupplyProductSourceAuditAction,
            name="supply_product_source_audit_action",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        nullable=False,
    )
    previous_source_warehouse_mapping_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    source_warehouse_mapping_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SupplyStockCalculation(Base):
    __tablename__ = "supply_stock_calculations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "request_id", "revision",
            name="uq_supply_stock_calculation_request_revision",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_supply_stock_calculation_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id", "id", "request_id",
            name="uq_supply_stock_calculation_tenant_id_request",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["supply_requests.tenant_id", "supply_requests.id"],
            name="fk_supply_stock_calculation_tenant_request",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision >= 1", name="ck_supply_stock_calculation_revision",
        ),
        CheckConstraint(
            "version >= 1", name="ck_supply_stock_calculation_version",
        ),
        CheckConstraint(
            "(status = 'PRELIMINARY' AND confirmed_at IS NULL "
            "AND confirmed_by_user_id IS NULL) OR "
            "(status = 'CONFIRMED' AND confirmed_at IS NOT NULL "
            "AND confirmed_by_user_id IS NOT NULL)",
            name="ck_supply_stock_calculation_confirmation_state",
        ),
        Index(
            "ix_supply_stock_calculation_request_revision",
            "request_id", "revision",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    status: Mapped[SupplyStockCalculationStatus] = mapped_column(
        SqlEnum(
            SupplyStockCalculationStatus,
            name="supply_stock_calculation_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        default=SupplyStockCalculationStatus.PRELIMINARY,
        nullable=False,
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    calculated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lines: Mapped[list["SupplyStockCalculationLine"]] = relationship(
        back_populates="calculation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplyStockCalculationLine.position",
    )


class SupplyStockCalculationLine(Base):
    __tablename__ = "supply_stock_calculation_lines"
    __table_args__ = (
        UniqueConstraint(
            "calculation_id", "request_line_id",
            name="uq_supply_stock_calculation_line_request_line",
        ),
        UniqueConstraint(
            "tenant_id", "calculation_id", "id",
            name="uq_supply_stock_calculation_line_tenant_calculation_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "calculation_id", "request_id"],
            [
                "supply_stock_calculations.tenant_id",
                "supply_stock_calculations.id",
                "supply_stock_calculations.request_id",
            ],
            name="fk_supply_stock_line_tenant_calculation_request",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "request_id", "request_line_id"],
            [
                "supply_request_lines.tenant_id",
                "supply_request_lines.request_id",
                "supply_request_lines.id",
            ],
            name="fk_supply_stock_line_tenant_request_line",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            ["supply_products.tenant_id", "supply_products.id"],
            name="fk_supply_stock_line_tenant_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "requested_unit_id"],
            ["supply_units.tenant_id", "supply_units.id"],
            name="fk_supply_stock_line_tenant_unit",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_warehouse_mapping_id"],
            ["iiko_warehouse_mappings.tenant_id", "iiko_warehouse_mappings.id"],
            name="fk_supply_stock_line_tenant_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "requested_quantity IS NULL OR requested_quantity >= 0",
            name="ck_supply_stock_calculation_line_requested_nonnegative",
        ),
        CheckConstraint(
            "transferable_quantity IS NULL OR transferable_quantity >= 0",
            name="ck_supply_stock_calculation_line_transferable_nonnegative",
        ),
        CheckConstraint(
            "deficit_quantity IS NULL OR deficit_quantity >= 0",
            name="ck_supply_stock_calculation_line_deficit_nonnegative",
        ),
        CheckConstraint(
            "transferable_quantity IS NULL OR "
            "transferable_quantity <= requested_quantity",
            name="ck_supply_stock_calculation_line_transferable_requested",
        ),
        CheckConstraint(
            "(unavailable_reason IS NOT NULL "
            "AND transferable_quantity IS NULL AND deficit_quantity IS NULL) "
            "OR (unavailable_reason IS NULL "
            "AND requested_quantity IS NOT NULL "
            "AND available_quantity IS NOT NULL "
            "AND transferable_quantity IS NOT NULL "
            "AND deficit_quantity IS NOT NULL "
            "AND deficit_quantity = requested_quantity - transferable_quantity)",
            name="ck_supply_stock_calculation_line_state",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_supply_stock_calculation_line_version",
        ),
        Index(
            "ix_supply_stock_calculation_line_position",
            "calculation_id", "position",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_line_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    product_name: Mapped[str] = mapped_column(String(240), nullable=False)
    requested_unit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    requested_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    source_warehouse_mapping_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    source_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    iiko_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    transferable_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    deficit_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    unavailable_reason: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    calculation: Mapped[SupplyStockCalculation] = relationship(
        back_populates="lines"
    )
    requested_unit: Mapped[SupplyUnit | None] = relationship(
        overlaps="calculation,lines"
    )


class SupplyStockCalculationAuditEvent(Base):
    __tablename__ = "supply_stock_calculation_audit_events"
    __table_args__ = (
        Index(
            "ix_supply_stock_calculation_audit_created",
            "tenant_id", "calculation_id", "created_at",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "calculation_id"],
            [
                "supply_stock_calculations.tenant_id",
                "supply_stock_calculations.id",
            ],
            name="fk_supply_stock_audit_tenant_calculation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "calculation_id", "calculation_line_id"],
            [
                "supply_stock_calculation_lines.tenant_id",
                "supply_stock_calculation_lines.calculation_id",
                "supply_stock_calculation_lines.id",
            ],
            name="fk_supply_stock_audit_tenant_calculation_line",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    calculation_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[SupplyStockCalculationAuditAction] = mapped_column(
        SqlEnum(
            SupplyStockCalculationAuditAction,
            name="supply_stock_calculation_audit_action",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum: [member.value for member in enum],
            length=24,
        ),
        nullable=False,
    )
    calculation_line_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )
    previous_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SupplyRequest(Base):
    __tablename__ = "supply_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["iiko_source_warehouse_mapping_id"],
            ["iiko_warehouse_mappings.id"],
            name="fk_supply_requests_iiko_source_warehouse_mapping",
            ondelete="RESTRICT",
        ).ddl_if(dialect="postgresql"),
        UniqueConstraint(
            "tenant_id",
            "public_number",
            name="uq_supply_requests_tenant_public_number",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_supply_requests_tenant_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "department_id",
            "direction_id",
            "cycle_id",
            name="uq_supply_requests_tenant_department_direction_cycle",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'IN_REVIEW', 'PLANNED', "
            "'PARTIALLY_FULFILLED', 'FULFILLED', 'CANCELLED')",
            name="ck_supply_requests_status",
        ),
        CheckConstraint(
            "source_type IN ('INTERNAL', 'PUBLIC_FORM', "
            "'WORK_REQUEST_MANUAL')",
            name="ck_supply_requests_source_type",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_supply_requests_version",
        ),
        Index(
            "ix_supply_requests_tenant_created",
            "tenant_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_supply_requests_source_ip_created",
            "source_ip_hash",
            "public_created_at",
        ),
        Index(
            "uq_supply_requests_public_token_hash",
            "public_token_hash",
            unique=True,
            postgresql_where=text("public_token_hash IS NOT NULL"),
            sqlite_where=text("public_token_hash IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    public_number: Mapped[str] = mapped_column(String(160), nullable=False)
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    direction_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_request_directions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_request_cycles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    iiko_source_warehouse_mapping_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="DRAFT",
        server_default="DRAFT",
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(
        String(32),
        default="INTERNAL",
        server_default="INTERNAL",
        nullable=False,
    )
    source_work_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_requests.id", ondelete="RESTRICT"),
        nullable=True,
    )
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    public_token_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    public_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    public_author_name: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    public_author_phone: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )
    source_ip_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    public_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    planned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planned_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fulfilled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
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

    department: Mapped[Department] = relationship()
    direction: Mapped[SupplyRequestDirection] = relationship()
    cycle: Mapped[SupplyRequestCycle | None] = relationship()
    lines: Mapped[list["SupplyRequestLine"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplyRequestLine.position",
    )

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def lines_total(self) -> int:
        return len(self.lines)

    @property
    def lines_matched(self) -> int:
        return sum(line.match_status == "MATCHED" for line in self.lines)

    @property
    def lines_needs_review(self) -> int:
        return sum(
            line.match_status in {"UNPROCESSED", "PARSED", "NEEDS_REVIEW"}
            for line in self.lines
        )

    @property
    def duplicate_groups(self) -> int:
        return len({
            line.duplicate_group_id for line in self.lines
            if line.duplicate_group_id is not None
            and line.duplicate_status in {"SUSPECTED", "CONFIRMED"}
        })

    @property
    def planning_complete_lines(self) -> int:
        return sum(line.planning_status == "COMPLETE" for line in self.lines)

    @property
    def planning_incomplete_lines(self) -> int:
        return sum(line.planning_status == "INCOMPLETE" for line in self.lines)

    @property
    def total_unallocated_lines(self) -> int:
        return sum(line.unallocated_quantity > 0 for line in self.lines)

    @property
    def can_start_review(self) -> bool:
        return self.status == "SUBMITTED"

    @property
    def can_plan(self) -> bool:
        return (
            self.status == "IN_REVIEW"
            and self.duplicate_groups == 0
            and bool(self.lines)
            and self.planning_complete_lines == len(self.lines)
        )


class SupplyRequestLine(Base):
    __tablename__ = "supply_request_lines"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "position",
            name="uq_supply_request_lines_request_position",
        ),
        UniqueConstraint(
            "tenant_id", "id", name="uq_supply_request_lines_tenant_id",
        ),
        UniqueConstraint(
            "tenant_id", "request_id", "id",
            name="uq_supply_request_lines_tenant_request_id",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["supply_requests.tenant_id", "supply_requests.id"],
            name="fk_supply_request_lines_tenant_request",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "position >= 1",
            name="ck_supply_request_lines_position",
        ),
        CheckConstraint(
            "length(trim(raw_text)) > 0",
            name="ck_supply_request_lines_raw_text",
        ),
        CheckConstraint(
            "send_quantity IS NULL OR send_quantity >= 0",
            name="ck_supply_request_lines_send_quantity_nonnegative",
        ),
        CheckConstraint(
            "match_status IN ('UNPROCESSED', 'PARSED', 'MATCHED', "
            "'NEEDS_REVIEW', 'REJECTED')",
            name="ck_supply_request_lines_match_status",
        ),
        CheckConstraint(
            "match_method IS NULL OR match_method IN "
            "('CONTEXT_MAPPING', 'EXACT_PRODUCT', 'EXACT_ALIAS', 'MANUAL')",
            name="ck_supply_request_lines_match_method",
        ),
        CheckConstraint(
            "parsed_quantity IS NULL OR parsed_quantity > 0",
            name="ck_supply_request_lines_parsed_quantity_positive",
        ),
        CheckConstraint(
            "match_confidence IS NULL OR "
            "(match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_supply_request_lines_match_confidence",
        ),
        CheckConstraint(
            "duplicate_status IN ('NONE', 'SUSPECTED', 'CONFIRMED', "
            "'RESOLVED')",
            name="ck_supply_request_lines_duplicate_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    working_name_override: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    parsed_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3),
        nullable=True,
    )
    parsed_unit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_products.id", ondelete="RESTRICT"),
        nullable=True,
    )
    requested_unit_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_units.id", ondelete="RESTRICT"),
        nullable=True,
    )
    quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3),
        nullable=True,
    )
    send_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3),
        nullable=True,
    )
    match_status: Mapped[str] = mapped_column(
        String(24),
        default="UNPROCESSED",
        server_default="UNPROCESSED",
        nullable=False,
    )
    match_method: Mapped[str | None] = mapped_column(
        String(24),
        nullable=True,
    )
    matched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    matched_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    match_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    match_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    duplicate_group_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    duplicate_status: Mapped[str] = mapped_column(
        String(24),
        default="NONE",
        server_default="NONE",
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

    request: Mapped[SupplyRequest] = relationship(back_populates="lines")
    parsed_unit: Mapped[SupplyUnit | None] = relationship(
        foreign_keys=[parsed_unit_id]
    )
    product: Mapped[SupplyProduct | None] = relationship()
    requested_unit: Mapped[SupplyUnit | None] = relationship(
        foreign_keys=[requested_unit_id]
    )
    allocations: Mapped[list["SupplyLineAllocation"]] = relationship(
        back_populates="request_line",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplyLineAllocation.created_at",
    )
    debt_link: Mapped["SupplyRequestLineDebtLink | None"] = relationship(
        back_populates="request_line",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def _planned_for(self, action: str) -> Decimal:
        return sum(
            (allocation.planned_quantity for allocation in self.allocations
             if allocation.action == action),
            Decimal("0"),
        )

    @property
    def planned_transfer(self) -> Decimal:
        return self._planned_for("TRANSFER")

    @property
    def planned_purchase(self) -> Decimal:
        return self._planned_for("PURCHASE")

    @property
    def planned_cancel(self) -> Decimal:
        return self._planned_for("CANCEL")

    @property
    def planned_total(self) -> Decimal:
        return self.planned_transfer + self.planned_purchase + self.planned_cancel

    def _fulfilled_for(self, action: str) -> Decimal:
        return sum(
            (allocation.fulfilled_quantity for allocation in self.allocations
             if allocation.action == action),
            Decimal("0"),
        )

    @property
    def fulfilled_transfer(self) -> Decimal:
        return self._fulfilled_for("TRANSFER")

    @property
    def fulfilled_purchase(self) -> Decimal:
        return self._fulfilled_for("PURCHASE")

    @property
    def fulfilled_total(self) -> Decimal:
        return self.fulfilled_transfer + self.fulfilled_purchase

    @property
    def unresolved_quantity(self) -> Decimal:
        return max(
            self.effective_quantity
            - self.fulfilled_total
            - self.planned_cancel,
            Decimal("0"),
        )

    @property
    def effective_quantity(self) -> Decimal:
        if self.debt_link and self.debt_link.inclusion_confirmed:
            return self.debt_link.included_quantity
        return self.quantity or Decimal("0")

    @property
    def active_debt(self) -> "SupplyDepartmentDebt | None":
        transient = getattr(self, "_active_debt", None)
        if transient is not None:
            return transient
        if self.debt_link is None:
            return None
        included = self.debt_link.included_debt
        if included is not None and included.status == "ACTIVE":
            return included
        contributed = self.debt_link.debt
        if contributed is not None and contributed.status == "ACTIVE":
            return contributed
        return None

    @property
    def active_debt_id(self) -> UUID | None:
        return self.active_debt.id if self.active_debt else None

    @property
    def active_debt_quantity(self) -> Decimal:
        return (
            self.active_debt.outstanding_quantity
            if self.active_debt else Decimal("0")
        )

    @property
    def active_debt_requires_matching(self) -> bool:
        return self.active_debt is not None and self.active_debt.product_id is None

    @property
    def debt_quantity_included(self) -> Decimal:
        return (
            self.debt_link.included_quantity
            if self.debt_link else Decimal("0")
        )

    @property
    def debt_inclusion_status(self) -> str:
        if self.debt_link and self.debt_link.included_quantity > 0:
            if self.debt_link.inclusion_confirmed:
                return "CONFIRMED_PARTIAL"
            return "COVERED_BY_REQUEST"
        debt = self.active_debt
        if debt is None or self.quantity is None:
            return "NONE"
        if self.quantity >= debt.outstanding_quantity:
            return "COVERED_BY_REQUEST"
        return "REQUEST_BELOW_DEBT"

    @property
    def requires_debt_confirmation(self) -> bool:
        return self.debt_inclusion_status == "REQUEST_BELOW_DEBT"

    @property
    def unallocated_quantity(self) -> Decimal:
        return max((self.quantity or Decimal("0")) - self.planned_total, Decimal("0"))

    @property
    def planning_status(self) -> str:
        return "COMPLETE" if self.quantity is not None and self.unallocated_quantity == 0 else "INCOMPLETE"

    @property
    def working_name(self) -> str:
        if self.working_name_override:
            return self.working_name_override
        return self.product.name if self.product else (self.parsed_name or self.raw_text)


class SupplyLineAllocation(Base):
    __tablename__ = "supply_line_allocations"
    __table_args__ = (
        CheckConstraint(
            "action IN ('TRANSFER', 'PURCHASE', 'CANCEL')",
            name="ck_supply_line_allocations_action",
        ),
        CheckConstraint(
            "planned_quantity > 0",
            name="ck_supply_line_allocations_quantity_positive",
        ),
        CheckConstraint(
            "fulfilled_quantity >= 0",
            name="ck_supply_line_allocations_fulfilled_quantity",
        ),
        UniqueConstraint(
            "request_line_id", "action",
            name="uq_supply_line_allocations_line_action",
        ),
        Index(
            "ix_supply_line_allocations_tenant_request",
            "tenant_id", "request_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_requests.id", ondelete="CASCADE"), nullable=False
    )
    request_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_request_lines.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    unit_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_units.id", ondelete="RESTRICT"), nullable=False
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    fulfilled_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0"), server_default="0", nullable=False
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fulfilled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    fulfillment_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    request_line: Mapped[SupplyRequestLine] = relationship(back_populates="allocations")
    unit: Mapped[SupplyUnit] = relationship()


class SupplyDepartmentDebt(Base):
    __tablename__ = "supply_department_debts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'CLOSED', 'CANCELLED')",
            name="ck_supply_department_debts_status",
        ),
        CheckConstraint(
            "outstanding_quantity >= 0 AND original_quantity > 0",
            name="ck_supply_department_debts_quantities",
        ),
        CheckConstraint(
            "version >= 1 AND cycle_count >= 0",
            name="ck_supply_department_debts_version_cycles",
        ),
        Index(
            "uq_supply_department_debts_active",
            "tenant_id", "department_id", "product_id", "unit_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "ix_supply_department_debts_tenant_status_updated",
            "tenant_id", "status", "updated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    department_id: Mapped[UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_products.id", ondelete="RESTRICT"), nullable=True
    )
    working_name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_units.id", ondelete="RESTRICT"), nullable=False
    )
    outstanding_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    original_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="ACTIVE", server_default="ACTIVE", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    first_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_requests.id", ondelete="RESTRICT"), nullable=False
    )
    latest_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_requests.id", ondelete="RESTRICT"), nullable=False
    )
    first_request_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_request_lines.id", ondelete="RESTRICT"), nullable=False
    )
    latest_request_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_request_lines.id", ondelete="RESTRICT"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    cancelled_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    close_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_request_cycles.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    department: Mapped[Department] = relationship()
    product: Mapped[SupplyProduct | None] = relationship()
    unit: Mapped[SupplyUnit] = relationship()
    first_request: Mapped[SupplyRequest] = relationship(foreign_keys=[first_request_id])
    latest_request: Mapped[SupplyRequest] = relationship(foreign_keys=[latest_request_id])
    events: Mapped[list["SupplyDepartmentDebtEvent"]] = relationship(
        back_populates="debt", order_by="SupplyDepartmentDebtEvent.created_at",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    @property
    def severity(self) -> str:
        if self.cycle_count <= 1:
            return "NONE"
        if self.cycle_count == 2:
            return "YELLOW"
        return "RED"


class SupplyDepartmentDebtEvent(Base):
    __tablename__ = "supply_department_debt_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('CREATED', 'INCREASED', 'INCLUDED_IN_REQUEST', "
            "'PARTIALLY_CLOSED', 'CLOSED', 'CANCELLED', 'REOPENED', 'ADJUSTED')",
            name="ck_supply_department_debt_events_type",
        ),
        Index("ix_supply_department_debt_events_debt_created", "debt_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    debt_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_department_debts.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    quantity_before: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(18, 3), nullable=False)
    request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_requests.id", ondelete="RESTRICT"), nullable=True
    )
    request_line_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_request_lines.id", ondelete="RESTRICT"), nullable=True
    )
    cycle_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_request_cycles.id", ondelete="RESTRICT"), nullable=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    debt: Mapped[SupplyDepartmentDebt] = relationship(back_populates="events")


class SupplyRequestLineDebtLink(Base):
    __tablename__ = "supply_request_line_debt_links"
    __table_args__ = (
        CheckConstraint(
            "contributed_quantity >= 0 AND included_quantity >= 0 AND "
            "applied_included_quantity >= 0 AND "
            "applied_included_quantity <= included_quantity",
            name="ck_supply_request_line_debt_links_quantities",
        ),
        Index("ix_supply_request_line_debt_links_tenant_debt", "tenant_id", "debt_id"),
    )

    request_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_request_lines.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    debt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_department_debts.id", ondelete="RESTRICT"), nullable=True
    )
    contributed_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0"), server_default="0", nullable=False
    )
    included_debt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_department_debts.id", ondelete="RESTRICT"), nullable=True
    )
    included_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0"), server_default="0", nullable=False
    )
    applied_included_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0"), server_default="0", nullable=False
    )
    inclusion_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    request_line: Mapped[SupplyRequestLine] = relationship(back_populates="debt_link")
    debt: Mapped[SupplyDepartmentDebt | None] = relationship(foreign_keys=[debt_id])
    included_debt: Mapped[SupplyDepartmentDebt | None] = relationship(
        foreign_keys=[included_debt_id]
    )
