from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Numeric,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import User


class WorkRequest(Base):
    __tablename__ = "work_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('warehouse', 'repair')",
            name="ck_work_requests_type",
        ),
        CheckConstraint("length(trim(department)) > 0", name="ck_work_requests_department"),
        CheckConstraint(
            "status IN ('new', 'in_progress', 'waiting_external', 'escalated', 'completed', 'reopened', 'cancelled')",
            name="ck_work_requests_status",
        ),
        CheckConstraint(
            "length(trim(description)) > 0 AND length(description) <= 5000",
            name="ck_work_requests_description",
        ),
        CheckConstraint(
            "("
            "request_type = 'warehouse' "
            "AND warehouse_category IN ('products', 'household', 'packaging') "
            "AND repair_category IS NULL AND priority IS NULL"
            ") OR ("
            "request_type = 'repair' "
            "AND warehouse_category IS NULL "
            "AND repair_category IN ("
            "'Сантехника', 'Электрика', 'Кассовое оборудование', "
            "'Компьютерное оборудование', 'Холодильное оборудование', "
            "'Тепловое оборудование', 'Кофемашина', 'Интернет', 'Другое'"
            ") "
            "AND priority IN ('routine', 'important', 'urgent')"
            ")",
            name="ck_work_requests_type_fields",
        ),
        ForeignKeyConstraint(["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"], name="fk_work_requests_department_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "creator_employee_id"], ["employees.tenant_id", "employees.id"], name="fk_work_requests_creator_employee_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "responsible_employee_id"], ["employees.tenant_id", "employees.id"], name="fk_work_requests_responsible_employee_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "contractor_id"], ["external_contractors.tenant_id", "external_contractors.id"], name="fk_work_requests_contractor_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "specialization_id"], ["contractor_specializations.tenant_id", "contractor_specializations.id"], name="fk_work_requests_specialization_tenant", ondelete="RESTRICT"),
        CheckConstraint("responsible_role IS NULL OR responsible_role IN ('HANDYMAN', 'SUPPLY_MANAGER')", name="ck_work_requests_responsible_role"),
        Index("ix_work_requests_tenant_department", "tenant_id", "department_id"),
        Index("ix_work_requests_tenant_contractor", "tenant_id", "contractor_id"),
        CheckConstraint("repair_cost IS NULL OR repair_cost > 0", name="ck_work_requests_repair_cost_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="eclair",
        nullable=False,
        index=True,
    )
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)
    department: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default="new",
        server_default="new",
        nullable=False,
    )
    warehouse_category: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )
    repair_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    author_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    department_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    creator_employee_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    creator_authorized_as: Mapped[str | None] = mapped_column(String(32), nullable=True)
    responsible_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    responsible_employee_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    responsibility_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contractor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    specialization_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    repair_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    attachments: Mapped[list["WorkRequestAttachment"]] = relationship(
        back_populates="work_request",
        cascade="all, delete-orphan",
        order_by="WorkRequestAttachment.created_at",
    )
    comments: Mapped[list["WorkRequestComment"]] = relationship(
        back_populates="work_request",
        cascade="all, delete-orphan",
        order_by="WorkRequestComment.created_at",
    )

    @property
    def created_by_name(self) -> str:
        if self.author_name:
            return self.author_name
        if self.created_by is not None:
            return self.created_by.display_name
        return f"Подразделение: {self.department}"

    @property
    def attachment_count(self) -> int:
        return len(self.attachments)


class WorkRequestAttachment(Base):
    __tablename__ = "work_request_attachments"
    __table_args__ = (CheckConstraint("kind IN ('PHOTO', 'INVOICE', 'ACT')", name="ck_work_request_attachments_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    work_request_id: Mapped[int] = mapped_column(
        ForeignKey("work_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PHOTO", default="PHOTO")
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    work_request: Mapped[WorkRequest] = relationship(
        back_populates="attachments",
    )


class WorkRequestComment(Base):
    __tablename__ = "work_request_comments"
    __table_args__ = (
        CheckConstraint(
            "length(trim(body)) > 0 AND length(body) <= 2000",
            name="ck_work_request_comments_body",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_request_id: Mapped[int] = mapped_column(
        ForeignKey("work_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    work_request: Mapped[WorkRequest] = relationship(
        back_populates="comments",
    )
    author: Mapped[User] = relationship()

    @property
    def author_name(self) -> str:
        return self.author.display_name


class ExternalContractor(Base):
    __tablename__ = "external_contractors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_external_contractors_tenant_id"),
        CheckConstraint("length(trim(name)) > 0 AND length(trim(phone)) > 0", name="ck_external_contractors_identity"),
        Index("ix_external_contractors_tenant_active_name", "tenant_id", "is_active", "name"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ContractorSpecialization(Base):
    __tablename__ = "contractor_specializations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_contractor_specializations_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_contractor_specializations_name"),
        CheckConstraint("length(trim(name)) > 0", name="ck_contractor_specializations_name"),
        Index("ix_contractor_specializations_tenant_active", "tenant_id", "is_active"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class ContractorSpecializationLink(Base):
    __tablename__ = "contractor_specialization_links"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "contractor_id"], ["external_contractors.tenant_id", "external_contractors.id"], name="fk_contractor_links_contractor_tenant", ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "specialization_id"], ["contractor_specializations.tenant_id", "contractor_specializations.id"], name="fk_contractor_links_specialization_tenant", ondelete="RESTRICT"),
    )
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    contractor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    specialization_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
