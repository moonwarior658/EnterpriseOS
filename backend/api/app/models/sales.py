"""Source events remain immutable in meaning; reconciled views are derived in EOS."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Date, DateTime, ForeignKeyConstraint, Index, JSON, Numeric, String, UniqueConstraint, event, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class SalesSyncState(Base):
    __tablename__ = "sales_sync_states"
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Must be explicitly confirmed for iiko's offset-less timestamps.
    source_timezone: Mapped[str] = mapped_column(String(64))
    history_from: Mapped[date] = mapped_column(Date)
    backfill_next: Mapped[date] = mapped_column(Date)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SalesDaySync(Base):
    __tablename__ = "sales_day_syncs"
    __table_args__ = (ForeignKeyConstraint(["tenant_id", "source_id"],
        ["sales_sync_states.tenant_id", "sales_sync_states.source_id"], ondelete="RESTRICT"),)
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_success_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int]


class SalesFact(Base):
    __tablename__ = "sales_facts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "source_id"],
            ["sales_sync_states.tenant_id", "sales_sync_states.source_id"], ondelete="RESTRICT"),
        UniqueConstraint("tenant_id", "source_id", "iiko_department_id", "iiko_order_id", "iiko_item_id", name="uq_sales_fact_source_identity"),
        ForeignKeyConstraint(["tenant_id", "employee_id"], ["employees.tenant_id", "employees.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "product_id"], ["supply_products.tenant_id", "supply_products.id"], ondelete="RESTRICT"),
        Index("ix_sales_fact_day", "tenant_id", "source_id", "business_date"),
        Index("ix_sales_fact_order_present", "tenant_id", "source_id", "iiko_order_id", postgresql_where=text("is_present")),
        Index("ix_sales_fact_item", "tenant_id", "source_id", "iiko_item_id"),
        Index("ix_sales_fact_source_order", "tenant_id", "source_id", "source_order_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    business_date: Mapped[date] = mapped_column(Date)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    iiko_department_id: Mapped[UUID]
    iiko_group_id: Mapped[UUID | None]
    iiko_order_id: Mapped[UUID]
    iiko_item_id: Mapped[UUID]
    source_order_id: Mapped[UUID | None]
    sold_with_item_id: Mapped[UUID | None]
    iiko_employee_id: Mapped[str | None] = mapped_column(String(160))
    order_waiter_id: Mapped[str | None] = mapped_column(String(160))
    item_waiter_id: Mapped[str | None] = mapped_column(String(160))
    employee_id: Mapped[UUID | None]
    department_id: Mapped[UUID | None]
    iiko_product_id: Mapped[UUID]
    product_id: Mapped[UUID | None]
    product_name: Mapped[str | None] = mapped_column(String(500))
    product_category: Mapped[str | None] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Numeric())
    amount_before_discount: Mapped[Decimal] = mapped_column(Numeric())
    amount_after_discount: Mapped[Decimal] = mapped_column(Numeric())
    return_amount: Mapped[Decimal] = mapped_column(Numeric())
    is_free: Mapped[bool] = mapped_column(Boolean)
    is_returned: Mapped[bool] = mapped_column(Boolean)
    is_deleted: Mapped[bool] = mapped_column(Boolean)
    # Disappeared from a successful authoritative daily response, retained for diagnosis.
    is_present: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SalesTarget(Base):
    """Append-only monthly network target revisions, independent of iiko source."""
    __tablename__ = "sales_targets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "metric", "month", "revision", name="uq_sales_target_revision"),
        CheckConstraint("metric IN ('average_check', 'fullness', 'revenue')", name="ck_sales_target_metric"),
        CheckConstraint("value > 0 AND value < 1000000000000000000", name="ck_sales_target_value"),
        CheckConstraint("revision > 0", name="ck_sales_target_revision"),
        CheckConstraint("EXTRACT(DAY FROM month) = 1", name="ck_sales_target_month").ddl_if(dialect="postgresql"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    metric: Mapped[str] = mapped_column(String(32))
    month: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    revision: Mapped[int]
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _immutable_sales_target(*_args, **_kwargs):
    raise RuntimeError("SalesTarget is immutable")


event.listen(SalesTarget, "before_update", _immutable_sales_target, propagate=True)
event.listen(SalesTarget, "before_delete", _immutable_sales_target, propagate=True)
