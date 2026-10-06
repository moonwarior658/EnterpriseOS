from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Enum as SqlEnum, ForeignKey,
    ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EmployeeStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISMISSED = "DISMISSED"


class EmployeeRole(StrEnum):
    ADMIN = "ADMIN"
    DIRECTOR = "DIRECTOR"
    DEPUTY_DIRECTOR = "DEPUTY_DIRECTOR"
    ACCOUNTANT = "ACCOUNTANT"
    SUPPLY_MANAGER = "SUPPLY_MANAGER"
    DRIVER = "DRIVER"
    HANDYMAN = "HANDYMAN"
    NETWORK_MANAGER = "NETWORK_MANAGER"
    CHEF_CONFECTIONER = "CHEF_CONFECTIONER"
    CONFECTIONER = "CONFECTIONER"
    BAKER = "BAKER"
    HEAD_OF_PRODUCTION = "HEAD_OF_PRODUCTION"
    SELLER = "SELLER"


class EmployeeLifecycleEventType(StrEnum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    DISMISSED = "DISMISSED"
    REACTIVATED = "REACTIVATED"
    USER_LINKED = "USER_LINKED"
    USER_UNLINKED = "USER_UNLINKED"


class EmployeeIikoShiftStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


def enum_column(enum_type: type[StrEnum], name: str, length: int):
    return SqlEnum(
        enum_type, name=name, native_enum=False, create_constraint=True,
        values_callable=lambda enum: [member.value for member in enum], length=length,
    )


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_employees_tenant_id"),
        UniqueConstraint("linked_user_id", name="uq_employees_linked_user_id"),
        Index("ix_employees_tenant_status_name", "tenant_id", "status", "full_name"),
        CheckConstraint(
            "(status = 'ACTIVE' AND dismissal_date IS NULL AND dismissal_reason IS NULL) "
            "OR (status = 'DISMISSED' AND dismissal_date IS NOT NULL "
            "AND length(trim(dismissal_reason)) > 0)",
            name="ck_employees_lifecycle_fields",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    linked_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    full_name: Mapped[str] = mapped_column(String(240), nullable=False)
    birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    residence_address: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[EmployeeStatus] = mapped_column(
        enum_column(EmployeeStatus, "employee_status", 16),
        default=EmployeeStatus.ACTIVE, server_default=EmployeeStatus.ACTIVE.value,
        nullable=False,
    )
    dismissal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dismissal_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    role_assignments: Mapped[list["EmployeeRoleAssignment"]] = relationship(
        back_populates="employee", order_by="EmployeeRoleAssignment.valid_from"
    )
    department_assignments: Mapped[list["EmployeeDepartmentAssignment"]] = relationship(
        back_populates="employee", order_by="EmployeeDepartmentAssignment.valid_from"
    )
    lifecycle_events: Mapped[list["EmployeeLifecycleEvent"]] = relationship(
        back_populates="employee", order_by="EmployeeLifecycleEvent.created_at"
    )
    iiko_links: Mapped[list["IikoEmployeeLink"]] = relationship(
        back_populates="employee", order_by="IikoEmployeeLink.valid_from"
    )
    iiko_shifts: Mapped[list["EmployeeIikoShift"]] = relationship(
        back_populates="employee", order_by="EmployeeIikoShift.opened_at"
    )
    shift_department_confirmations: Mapped[list["ShiftDepartmentConfirmation"]] = relationship(
        back_populates="employee", order_by="ShiftDepartmentConfirmation.confirmed_at"
    )


class EmployeeRoleAssignment(Base):
    __tablename__ = "employee_role_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_employee_role_assignments_employee_tenant", ondelete="RESTRICT",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_employee_role_assignment_period"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_employee_role_assignment_reason"),
        CheckConstraint("ended_reason IS NULL OR length(trim(ended_reason)) > 0", name="ck_employee_role_assignment_ended_reason"),
        Index(
            "uq_employee_role_assignments_active", "tenant_id", "employee_id", "role",
            unique=True, postgresql_where=text("valid_to IS NULL"), sqlite_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(nullable=False)
    role: Mapped[EmployeeRole] = mapped_column(enum_column(EmployeeRole, "employee_role", 32), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    ended_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ended_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="role_assignments")


class EmployeeDepartmentAssignment(Base):
    __tablename__ = "employee_department_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_employee_department_assignments_employee_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"],
            name="fk_employee_department_assignments_department_tenant", ondelete="RESTRICT",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_employee_department_assignment_period"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_employee_department_assignment_reason"),
        CheckConstraint("ended_reason IS NULL OR length(trim(ended_reason)) > 0", name="ck_employee_department_assignment_ended_reason"),
        Index(
            "uq_employee_department_assignments_active_department", "tenant_id", "employee_id", "department_id",
            unique=True, postgresql_where=text("valid_to IS NULL"), sqlite_where=text("valid_to IS NULL"),
        ),
        Index(
            "uq_employee_department_assignments_active_primary", "tenant_id", "employee_id", unique=True,
            postgresql_where=text("valid_to IS NULL AND is_primary"),
            sqlite_where=text("valid_to IS NULL AND is_primary = 1"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(nullable=False)
    department_id: Mapped[UUID] = mapped_column(nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    assigned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    ended_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ended_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="department_assignments")


class EmployeeLifecycleEvent(Base):
    __tablename__ = "employee_lifecycle_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_employee_lifecycle_events_employee_tenant", ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="ck_employee_lifecycle_events_reason"),
        Index("ix_employee_lifecycle_events_employee", "tenant_id", "employee_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[EmployeeLifecycleEventType] = mapped_column(
        enum_column(EmployeeLifecycleEventType, "employee_lifecycle_event_type", 16), nullable=False
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="lifecycle_events")


class IikoEmployeeLink(Base):
    __tablename__ = "iiko_employee_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_iiko_employee_links_employee_tenant", ondelete="RESTRICT",
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_iiko_employee_link_period"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_iiko_employee_link_reason"),
        CheckConstraint("ended_reason IS NULL OR length(trim(ended_reason)) > 0", name="ck_iiko_employee_link_ended_reason"),
        Index(
            "uq_iiko_employee_links_active_employee", "tenant_id", "employee_id",
            unique=True, postgresql_where=text("valid_to IS NULL"), sqlite_where=text("valid_to IS NULL"),
        ),
        Index(
            "uq_iiko_employee_links_active_user", "tenant_id", "iiko_user_id",
            unique=True, postgresql_where=text("valid_to IS NULL"), sqlite_where=text("valid_to IS NULL"),
        ),
        Index("ix_iiko_employee_links_history", "tenant_id", "employee_id", "valid_from"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(nullable=False)
    iiko_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    iiko_display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    iiko_birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    ended_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ended_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="iiko_links")


class IikoDepartmentMapping(Base):
    __tablename__ = "iiko_department_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "iiko_department_id",
            name="uq_iiko_department_mappings_tenant_external",
        ),
        UniqueConstraint("tenant_id", "olap_department_id", name="uq_iiko_department_mapping_olap"),
        ForeignKeyConstraint(
            ["tenant_id", "eos_department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_iiko_department_mappings_department_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_iiko_department_mappings_reason",
        ),
    )

    # Explicit enterprise ID in SALES OLAP, distinct from personal-shift group IDs.
    olap_department_id: Mapped[UUID | None] = mapped_column(nullable=True)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    iiko_department_id: Mapped[UUID] = mapped_column(nullable=False)
    eos_department_id: Mapped[UUID] = mapped_column(nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    decided_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EmployeeIikoShift(Base):
    __tablename__ = "employee_iiko_shifts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_employee_iiko_shifts_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_employee_iiko_shifts_employee_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"],
            name="fk_employee_iiko_shifts_department_tenant", ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "reconciliation_key",
            name="uq_employee_iiko_shifts_reconciliation",
        ),
        CheckConstraint("closed_at IS NULL OR closed_at >= opened_at", name="ck_employee_iiko_shift_period"),
        CheckConstraint("(status = 'OPEN' AND closed_at IS NULL AND duration_minutes IS NULL) OR (status = 'CLOSED' AND closed_at IS NOT NULL AND duration_minutes IS NOT NULL)", name="ck_employee_iiko_shift_status"),
        Index("ix_employee_iiko_shifts_employee_opened", "tenant_id", "employee_id", "opened_at"),
        Index(
            "uq_employee_iiko_shifts_active_employee", "tenant_id", "employee_id",
            unique=True, postgresql_where=text("status = 'OPEN'"), sqlite_where=text("status = 'OPEN'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(nullable=False)
    iiko_user_id: Mapped[str] = mapped_column(String(160), nullable=False)
    external_shift_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    iiko_department_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    department_id: Mapped[UUID | None] = mapped_column(nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="IIKO", server_default="IIKO", nullable=False)
    status: Mapped[EmployeeIikoShiftStatus] = mapped_column(
        enum_column(EmployeeIikoShiftStatus, "employee_iiko_shift_status", 16), nullable=False
    )
    reconciliation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="iiko_shifts")

    @property
    def department_mapping_resolved(self) -> bool:
        return self.department_id is not None


class ShiftDepartmentConfirmation(Base):
    __tablename__ = "shift_department_confirmations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"],
            name="fk_shift_department_confirmations_employee_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "shift_id"],
            ["employee_iiko_shifts.tenant_id", "employee_iiko_shifts.id"],
            name="fk_shift_department_confirmations_shift_tenant", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "primary_department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_shift_department_confirmations_primary_department_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actual_department_id"],
            ["departments.tenant_id", "departments.id"],
            name="fk_shift_department_confirmations_actual_department_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "shift_id", "employee_id",
            name="uq_shift_department_confirmations_shift_employee",
        ),
        Index(
            "ix_shift_department_confirmations_employee_confirmed",
            "tenant_id", "employee_id", "confirmed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    employee_id: Mapped[UUID] = mapped_column(nullable=False)
    shift_id: Mapped[UUID] = mapped_column(nullable=False)
    primary_department_id: Mapped[UUID] = mapped_column(nullable=False)
    actual_department_id: Mapped[UUID] = mapped_column(nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship(back_populates="shift_department_confirmations")
    shift: Mapped[EmployeeIikoShift] = relationship(
        overlaps="employee,shift_department_confirmations"
    )
