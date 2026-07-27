from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
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


class SupplyUnit(Base):
    __tablename__ = "supply_units"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "code",
            name="uq_supply_units_tenant_code",
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


class SupplyProduct(Base):
    __tablename__ = "supply_products"
    __table_args__ = (
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
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(240), nullable=False)
    default_unit_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_units.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_direction_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("supply_request_directions.id", ondelete="RESTRICT"),
        nullable=True,
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

    default_unit: Mapped[SupplyUnit] = relationship()
    request_direction: Mapped[SupplyRequestDirection | None] = relationship()
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product: Mapped[SupplyProduct] = relationship(back_populates="aliases")


class SupplyRequest(Base):
    __tablename__ = "supply_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "public_number",
            name="uq_supply_requests_tenant_public_number",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'CANCELLED')",
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
    submitted_at: Mapped[datetime | None] = mapped_column(
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

    department: Mapped[Department] = relationship()
    direction: Mapped[SupplyRequestDirection] = relationship()
    lines: Mapped[list["SupplyRequestLine"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SupplyRequestLine.position",
    )

    @property
    def line_count(self) -> int:
        return len(self.lines)


class SupplyRequestLine(Base):
    __tablename__ = "supply_request_lines"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "position",
            name="uq_supply_request_lines_request_position",
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
            "match_status IN ('UNPROCESSED', 'PARSED', 'MATCHED', "
            "'NEEDS_REVIEW', 'REJECTED')",
            name="ck_supply_request_lines_match_status",
        ),
        CheckConstraint(
            "match_method IS NULL OR match_method IN "
            "('EXACT_PRODUCT', 'EXACT_ALIAS', 'MANUAL')",
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
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("supply_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_name: Mapped[str | None] = mapped_column(Text, nullable=True)
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
