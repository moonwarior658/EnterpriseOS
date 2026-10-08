"""Source-first product identity; Supply and Sales remain unchanged."""
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, JSON, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class ProductKnowledgeBatch(Base):
    __tablename__ = 'product_knowledge_batches'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'id', name='uq_pk_batch_tenant_id'),
        UniqueConstraint('tenant_id', 'source_id', 'plan_hash', name='uq_pk_batch_plan'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    plan_hash: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSON)
    initial_status: Mapped[str] = mapped_column(String(16))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))


class ProductKnowledgeProduct(Base):
    __tablename__ = 'product_knowledge_products'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'id', name='uq_pk_product_tenant_id'),
        UniqueConstraint('tenant_id', 'source_id', 'iiko_product_id', name='uq_pk_product_source_uuid'),
        ForeignKeyConstraint(['tenant_id', 'source_id'], ['sales_sync_states.tenant_id', 'sales_sync_states.source_id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['tenant_id', 'supply_product_id'], ['supply_products.tenant_id', 'supply_products.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['tenant_id', 'batch_id'], ['product_knowledge_batches.tenant_id', 'product_knowledge_batches.id'], ondelete='RESTRICT'),
        CheckConstraint("sale_status IN ('ON_SALE', 'OFF_SALE')", name='ck_pk_sale_status'),
        CheckConstraint("sale_mode IN ('UNKNOWN', 'PORTION', 'WEIGHT')", name='ck_pk_sale_mode'),
        CheckConstraint('unit_weight_kg IS NULL OR unit_weight_kg > 0', name='ck_pk_weight'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    iiko_product_id: Mapped[UUID]
    supply_product_id: Mapped[UUID | None]
    batch_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(String(500))
    sku: Mapped[str | None] = mapped_column(String(160))
    unit_id: Mapped[UUID]
    unit_name: Mapped[str] = mapped_column(String(160))
    unit_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric())
    sale_mode: Mapped[str] = mapped_column(String(16), default='UNKNOWN')
    sale_status: Mapped[str] = mapped_column(String(16))
    category_id: Mapped[UUID | None]
    category_name: Mapped[str | None] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(String)
    source_deleted: Mapped[bool] = mapped_column(Boolean)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductKnowledgePrice(Base):
    """Only explicitly verified effective prices, never receipt averages/defaults."""
    __tablename__ = 'product_knowledge_prices'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'product_id'], ['product_knowledge_products.tenant_id', 'product_knowledge_products.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['tenant_id', 'department_id'], ['departments.tenant_id', 'departments.id'], ondelete='RESTRICT'),
        UniqueConstraint('tenant_id', 'product_id', 'department_id', 'valid_from', 'valid_to', name='uq_pk_price_interval'),
        CheckConstraint('amount >= 0', name='ck_pk_price_amount'),
        CheckConstraint('valid_to > valid_from', name='ck_pk_price_dates'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID]
    department_id: Mapped[UUID]
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    currency: Mapped[str] = mapped_column(String(3))
    price_unit: Mapped[str] = mapped_column(String(160))
    evidence: Mapped[str] = mapped_column(String(500))
    verified_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
