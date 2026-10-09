"""Reviewed, append-only price import. No iiko writes or product mutations.

Input is effective-price evidence, not the raw iiko order response. Resolving
order precedence belongs before confirmation, never in this importer.
"""
from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlalchemy import select

from app.audit.service import record_audit_event
from app.core.authorization import authorize, Capability
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgePrice as Price
from app.models.sales import SalesSyncState
from app.product_knowledge.bootstrap import PublicationError, digest
from app.product_knowledge.service import points_for
from app.schemas.product_knowledge import StrictModel, ConfirmedPrice


class PriceSnapshot(StrictModel):
    source_id: str = Field(min_length=1, max_length=64)
    observed_at: datetime
    confirmed_point_ids: list[UUID] = Field(min_length=1)
    # Evidence identifies the independent Office comparison and applicability
    # rules, including currency/unit; a candidate CSV is not this input.
    office_evidence: str = Field(min_length=1, max_length=500)
    prices: list[ConfirmedPrice] = Field(min_length=1)

    @field_validator('observed_at')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('OBSERVATION_TIMEZONE_REQUIRED')
        return value

    @field_validator('office_evidence')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('OFFICE_EVIDENCE_REQUIRED')
        return value.strip()

    @model_validator(mode='after')
    def points(self):
        if len(set(self.confirmed_point_ids)) != len(self.confirmed_point_ids):
            raise ValueError('DUPLICATE_POINT')
        if any(p.department_id not in self.confirmed_point_ids for p in self.prices):
            raise ValueError('UNCONFIRMED_POINT')
        if any(not p.evidence.strip() or not p.price_unit.strip() for p in self.prices):
            raise ValueError('PRICE_EVIDENCE_AND_UNIT_REQUIRED')
        return self


def price_preview(db, actor, source_id, snapshot: PriceSnapshot):
    authorize(db, actor, Capability.TECHNICAL_ADMIN, write=False)
    if source_id != snapshot.source_id or not db.get(SalesSyncState, (actor.tenant_id, source_id)):
        raise PublicationError('SOURCE_MISMATCH')
    if len(db.scalars(select(SalesSyncState).where(SalesSyncState.tenant_id == actor.tenant_id)).all()) != 1:
        raise PublicationError('MULTIPLE_SOURCES_REQUIRE_MAPPING_REVIEW')
    if not set(snapshot.confirmed_point_ids) <= {p.id for p in points_for(db, actor)}:
        raise PublicationError('UNCONFIRMED_POINT')
    products = {p.iiko_product_id: p for p in db.scalars(select(Product).where(
        Product.tenant_id == actor.tenant_id, Product.source_id == source_id,
        Product.published.is_(True), Product.iiko_product_id.in_([p.iiko_product_id for p in snapshot.prices])))}
    existing = list(db.scalars(select(Price).where(Price.tenant_id == actor.tenant_id,
        Price.product_id.in_([p.id for p in products.values()]),
        Price.department_id.in_(snapshot.confirmed_point_ids))))
    rows = []
    for item in snapshot.prices:
        product = products.get(item.iiko_product_id)
        if product is None:
            raise PublicationError('PRICE_PRODUCT_MISSING')
        if product.unit_name != item.price_unit:
            raise PublicationError('PRICE_UNIT_MISMATCH')
        overlaps = [p for p in existing if p.product_id == product.id and p.department_id == item.department_id
                    and p.valid_from < item.valid_to and item.valid_from < p.valid_to]
        identical = len(overlaps) == 1 and all(getattr(overlaps[0], key) == getattr(item, key)
            for key in ('valid_from', 'valid_to', 'amount', 'currency', 'price_unit', 'evidence'))
        if overlaps and not identical:
            raise PublicationError('PRICE_INTERVAL_CONFLICT')
        for row in rows:
            if row['product_id'] == str(product.id) and row['department_id'] == str(item.department_id) \
                    and row['valid_from'] < item.valid_to.isoformat() and item.valid_from.isoformat() < row['valid_to']:
                raise PublicationError('PRICE_INTERVAL_CONFLICT')
        rows.append(dict(item.model_dump(mode='json'), product_id=str(product.id), action='KEEP' if identical else 'INSERT'))
    report = dict(source_id=source_id, tenant_id=actor.tenant_id,
        observed_at=snapshot.observed_at.isoformat(), office_evidence=snapshot.office_evidence,
        confirmed_point_ids=sorted(str(p) for p in snapshot.confirmed_point_ids), rows=rows)
    reviewed = dict(report, rows=[{k: v for k, v in row.items() if k != 'action'} for row in rows])
    return dict(report, plan_hash=digest(reviewed))


def import_prices(db, actor, source_id, snapshot: PriceSnapshot, *, expected_hash):
    context = authorize(db, actor, Capability.TECHNICAL_ADMIN, write=True)
    # Serialize cooperating imports/bootstrap on the existing source lock.
    state = db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == actor.tenant_id,
        SalesSyncState.source_id == source_id).with_for_update())
    if not state:
        raise PublicationError('SOURCE_MISMATCH')
    report = price_preview(db, actor, source_id, snapshot)
    if report['plan_hash'] != expected_hash:
        raise PublicationError('PRICE_REVIEW_REQUIRED')
    inserted = 0
    for row in report['rows']:
        if row['action'] == 'KEEP':
            continue
        item = ConfirmedPrice.model_validate({k: v for k, v in row.items() if k not in {'product_id', 'action'}})
        price = Price(tenant_id=actor.tenant_id, product_id=UUID(row['product_id']),
            **item.model_dump(exclude={'iiko_product_id'}), verified_by_user_id=actor.id,
            observed_at=snapshot.observed_at)
        db.add(price)
        db.flush()
        record_audit_event(db, tenant_id=actor.tenant_id, event_type='PRODUCT_KNOWLEDGE_PRICE_CONFIRMED',
            entity_type='ProductKnowledgePrice', entity_id=price.id, operation='CONFIRM_PRICE',
            context=context, actor_user=actor, after=row,
            reason=snapshot.office_evidence, correlation_id=report['plan_hash'])
        inserted += 1
    db.flush()
    return dict(inserted=inserted, retained=len(report['rows']) - inserted)
