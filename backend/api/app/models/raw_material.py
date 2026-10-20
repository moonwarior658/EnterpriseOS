"""Supply-owned identity with additive knowledge, immutable revisions and approvals."""
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, Numeric, Date, Index, text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class RawMaterialProfile(Base):
    __tablename__ = 'raw_material_profiles'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'product_id', name='uq_material_profile_tenant'),
        ForeignKeyConstraint(['tenant_id', 'product_id'], ['supply_products.tenant_id', 'supply_products.id'], ondelete='RESTRICT'),
        CheckConstraint("kind IN ('RAW_MATERIAL','PACKAGING')", name='ck_material_kind'),
        CheckConstraint('version > 0', name='ck_material_version'),
    )
    product_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_hash: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaterialSpecificationVersion(Base):
    __tablename__ = 'material_specification_versions'
    __table_args__ = (
        UniqueConstraint('tenant_id', 'product_id', 'id', name='uq_material_spec_owner'),
        UniqueConstraint('tenant_id', 'product_id', 'revision', name='uq_material_spec_revision'),
        ForeignKeyConstraint(['tenant_id', 'product_id'], ['raw_material_profiles.tenant_id', 'raw_material_profiles.product_id'], ondelete='RESTRICT'),
        CheckConstraint('revision > 0', name='ck_material_spec_revision'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaterialSpecificationApproval(Base):
    __tablename__ = 'material_specification_approvals'
    __table_args__ = (
        UniqueConstraint('specification_id', name='uq_material_spec_approval'),
        ForeignKeyConstraint(['tenant_id', 'product_id', 'specification_id'], ['material_specification_versions.tenant_id', 'material_specification_versions.product_id', 'material_specification_versions.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['tenant_id', 'primary_product_id'], ['supply_products.tenant_id', 'supply_products.id'], ondelete='RESTRICT'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID]
    specification_id: Mapped[UUID]
    primary_product_id: Mapped[UUID]
    confirmed_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT'))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MaterialPurchaseSnapshot(Base):
    __tablename__ = 'material_purchase_snapshots'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id', 'product_id'], ['raw_material_profiles.tenant_id', 'raw_material_profiles.product_id'], ondelete='RESTRICT'),
        UniqueConstraint('tenant_id', 'product_id', 'execution_id', name='uq_material_purchase_execution'),
        CheckConstraint("status IN ('READY','BLOCKED','NO_DATA')", name='ck_material_purchase_status'),
        CheckConstraint("(status = 'READY' AND amount IS NOT NULL) OR (status <> 'READY' AND amount IS NULL)", name='ck_material_purchase_amount'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    product_id: Mapped[UUID] = mapped_column(index=True)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey('automation_executions.execution_id', ondelete='RESTRICT'))
    source_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    amount: Mapped[str | None] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class MaterialProductAllowance(Base):
    __tablename__ = 'material_product_allowances'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id','product_id','specification_id'], ['material_specification_versions.tenant_id','material_specification_versions.product_id','material_specification_versions.id'], ondelete='RESTRICT'),
        ForeignKeyConstraint(['tenant_id','target_product_id'], ['supply_products.tenant_id','supply_products.id'], ondelete='RESTRICT'),
        UniqueConstraint('specification_id','target_product_id', name='uq_material_allowance_target'),
        Index('uq_material_single_primary','specification_id',unique=True,postgresql_where=text("role='PRIMARY'"),sqlite_where=text("role='PRIMARY'")),
        CheckConstraint("role IN ('PRIMARY','RESERVE')", name='ck_material_allowance_role'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID]
    specification_id: Mapped[UUID]
    target_product_id: Mapped[UUID]
    role: Mapped[str] = mapped_column(String(16))


class MaterialUnitConversion(Base):
    __tablename__ = 'material_unit_conversions'
    __table_args__ = (
        ForeignKeyConstraint(['tenant_id','product_id','specification_id'], ['material_specification_versions.tenant_id','material_specification_versions.product_id','material_specification_versions.id'], ondelete='RESTRICT'),
        CheckConstraint('factor > 0 AND factor <= 100000', name='ck_material_conversion_factor'),
        CheckConstraint('valid_to > valid_from AND from_unit_id <> to_unit_id', name='ck_material_conversion_period'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[UUID]
    specification_id: Mapped[UUID]
    from_unit_id: Mapped[UUID]
    to_unit_id: Mapped[UUID]
    supplier_iiko_id: Mapped[UUID]
    container_id: Mapped[UUID | None]
    factor: Mapped[Decimal] = mapped_column(Numeric(24,12))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
