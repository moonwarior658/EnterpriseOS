from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Enum as SqlEnum, ForeignKey,
    ForeignKeyConstraint, Index, String, UniqueConstraint, func, text,
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
