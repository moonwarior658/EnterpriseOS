"""Append-only monetary observations and explicit Office verification records."""
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class ProductCostObservation(Base):
    __tablename__ = 'product_cost_observations'
    __table_args__ = (
        UniqueConstraint('tenant_id','id', name='uq_cost_observation_tenant'),
        UniqueConstraint('tenant_id','execution_id','product_id', name='uq_cost_execution_product'),
        ForeignKeyConstraint(['tenant_id','product_id'], ['product_knowledge_products.tenant_id','product_knowledge_products.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['tenant_id','source_id'], ['sales_sync_states.tenant_id','sales_sync_states.source_id'], ondelete='RESTRICT'),
        CheckConstraint("status IN ('UNVERIFIED','INCOMPLETE')", name='ck_cost_status'),
        Index('ix_cost_latest', 'tenant_id','product_id','stock_at','observed_at'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID]
    execution_id: Mapped[UUID]
    stock_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    context_hash: Mapped[str] = mapped_column(String(64))
    method_hash: Mapped[str | None] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class ProductCostVerification(Base):
    __tablename__ = 'product_cost_verifications'
    __table_args__ = (
        UniqueConstraint('tenant_id','observation_id', name='uq_cost_verification'),
        ForeignKeyConstraint(['tenant_id','observation_id'], ['product_cost_observations.tenant_id','product_cost_observations.id'], ondelete='RESTRICT'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    observation_id: Mapped[UUID]
    confirmed_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON)
