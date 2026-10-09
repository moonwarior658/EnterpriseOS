"""Append-only external recipes; never creates catalog or Supply products."""
from datetime import date, datetime
from uuid import UUID, uuid4
from sqlalchemy import String, JSON, Date, DateTime, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class ProductRecipeVersion(Base):
    __tablename__ = 'product_recipe_versions'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'source_id'], ['sales_sync_states.tenant_id', 'sales_sync_states.source_id'], ondelete='RESTRICT'),
        UniqueConstraint('tenant_id', 'source_id', 'chart_id', 'kind', 'content_hash', name='uq_recipe_content'),
        CheckConstraint("kind IN ('SOURCE','PREPARED')", name='ck_recipe_kind'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    chart_id: Mapped[UUID]
    source_product_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    # Raw intervals (including sentinels) and all norms/text/constraints retained.
    payload: Mapped[dict] = mapped_column(JSON)

class ProductRecipeObservation(Base):
    __tablename__ = 'product_recipe_observations'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'product_id'], ['product_knowledge_products.tenant_id', 'product_knowledge_products.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['tenant_id', 'source_id'], ['sales_sync_states.tenant_id', 'sales_sync_states.source_id'], ondelete='RESTRICT'),
        UniqueConstraint('tenant_id', 'execution_id', 'product_id', name='uq_recipe_execution_product'),
        CheckConstraint("status IN ('INCOMPLETE','CONFLICT','UNCONFIRMED')", name='ck_recipe_status'),
        Index('ix_recipe_observation', 'tenant_id', 'product_id', 'observed_at'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID]
    execution_id: Mapped[UUID]
    effective_on: Mapped[date] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON)
