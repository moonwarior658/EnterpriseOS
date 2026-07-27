from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
