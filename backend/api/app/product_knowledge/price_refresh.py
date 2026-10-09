"""Bounded read-only collection and atomic snapshot publication for existing EOS IDs."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo
from pydantic import Field, model_validator, field_validator
from sqlalchemy import select

from app.audit.service import record_audit_event
from app.core.authorization import authorize, Capability
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.integrations.iiko.prices import PriceContext
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgePriceSnapshot as Snapshot
from app.models.sales import SalesSyncState
from app.product_knowledge.bootstrap import PublicationError, digest
from app.sales.service import retail_mappings
from app.sales.sync import source_identity
from app.schemas.product_knowledge import StrictModel
from app.models.supply import Department

ACTION = 'products.sync_iiko_prices'


class PriceRefreshPayload(StrictModel):
    source_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed_point_ids: list[UUID] = Field(min_length=1, max_length=3)
    currency: Literal['RUB']
    office_evidence: str = Field(min_length=1, max_length=500)

    @field_validator('office_evidence')
    @classmethod
    def evidence(cls, value):
        if not value.strip():
            raise ValueError('OFFICE_EVIDENCE_REQUIRED')
        return value.strip()

    @model_validator(mode='after')
    def unique_points(self):
        if len(set(self.confirmed_point_ids)) != len(self.confirmed_point_ids):
            raise ValueError('DUPLICATE_POINT')
        return self


class SourcePriceSnapshot(PriceRefreshPayload):
    observed_at: datetime
    date_from: date
    date_to: date
    products: dict[str, dict]
    point_links: dict[str, str]
    revisions: dict[str, int]
    contexts: list[PriceContext]

    @model_validator(mode='after')
    def complete(self):
        if self.observed_at.tzinfo is None or not 0 < (self.date_to - self.date_from).days <= 93:
            raise ValueError('PRICE_OBSERVATION_INVALID')
        points = {str(p) for p in self.confirmed_point_ids}
        if set(self.point_links) != points or set(self.revisions) != points or len(set(self.point_links.values())) != len(points):
            raise ValueError('PRICE_POINT_COVERAGE_INVALID')
        if len(set(self.revisions.values())) != 1:
            raise ValueError('PRICE_REVISION_CHANGED_RECOLLECT')
        if any(str(c.departmentId) not in self.point_links.values() or str(c.productId) not in self.products for c in self.contexts):
            raise ValueError('PRICE_SCOPE_INVALID')
        return self


def scope(db, tenant, payload):
    states = list(db.scalars(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant)))
    if len(states) != 1 or states[0].source_id != payload.source_id:
        raise PublicationError('SOURCE_MISMATCH')
    active = set(db.scalars(select(Department.id).where(Department.tenant_id == tenant, Department.is_active.is_(True))))
    mappings = retail_mappings(db, tenant)
    inverse = {}
    for external, local in mappings.items():
        if local in payload.confirmed_point_ids and local in active:
            if str(local) in inverse:
                raise PublicationError('AMBIGUOUS_PRICE_POINT')
            inverse[str(local)] = str(external)
    if set(inverse) != {str(p) for p in payload.confirmed_point_ids}:
        raise PublicationError('UNCONFIRMED_POINT')
    products = {str(p.iiko_product_id): dict(id=str(p.id), unit_id=str(p.unit_id), unit_name=p.unit_name)
        for p in db.scalars(select(Product).where(Product.tenant_id == tenant,
            Product.source_id == payload.source_id, Product.published.is_(True)))}
    return states[0].source_timezone, inverse, products


async def collect_prices(session_factory, *, tenant_id, payload: PriceRefreshPayload, now):
    settings = get_iiko_settings()
    if source_identity(settings) != payload.source_id:
        raise PublicationError('SOURCE_MISMATCH')
    with session_factory() as db:
        zone, links, products = scope(db, tenant_id, payload)
    today = now.astimezone(ZoneInfo(zone)).date()
    date_from, date_to = today - timedelta(days=31), today + timedelta(days=32)
    contexts, revisions = [], {}
    # No checked-out DB connection during iiko I/O. Session/auth/retries are reused.
    async with IikoServerClient(settings) as client:
        source_products = {str(p.dto.external_id): p for p in await client.get_products()}
        units = {str(u.dto.external_id): u.dto.name for u in await client.get_units()}
        for pid, p in products.items():
            source = source_products.get(pid)
            if source is None or str(source.dto.base_unit_external_id) != p['unit_id'] or units.get(p['unit_id']) != p['unit_name']:
                raise PublicationError('PRICE_UNIT_MISMATCH')
        for local, external in sorted(links.items()):
            response = await client.get_prices(date_from=date_from, date_to=date_to, department_id=UUID(external))
            revisions[local] = response.revision
            contexts.extend(c for c in response.contexts if str(c.productId) in products)
    return SourcePriceSnapshot(**payload.model_dump(), observed_at=datetime.now(timezone.utc),
        date_from=date_from, date_to=date_to, products=products, point_links=links, revisions=revisions, contexts=contexts)


def source_price_preview(db, tenant, snapshot):
    _, links, products = scope(db, tenant, snapshot)
    if links != snapshot.point_links or products != snapshot.products:
        raise PublicationError('PRICE_SCOPE_CHANGED_RECOLLECT')
    report = snapshot.model_dump(mode='json')
    return dict(tenant_id=tenant, snapshot=report, plan_hash=digest(dict(tenant_id=tenant, snapshot=report)))


def publish_source_prices(db, tenant, snapshot, *, expected_hash, actor=None, execution_id=None):
    context = authorize(db, actor, Capability.TECHNICAL_ADMIN, write=True) if actor else None
    if actor and actor.tenant_id != tenant or actor is None and execution_id is None:
        raise PublicationError('PRICE_ACTOR_REQUIRED')
    db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant,
        SalesSyncState.source_id == snapshot.source_id).with_for_update())
    report = source_price_preview(db, tenant, snapshot)
    if expected_hash != report['plan_hash']:
        raise PublicationError('PRICE_REVIEW_REQUIRED')
    previous = db.scalar(select(Snapshot).where(Snapshot.tenant_id == tenant,
        Snapshot.source_id == snapshot.source_id, Snapshot.plan_hash == expected_hash))
    if previous:
        return previous
    latest = db.scalar(select(Snapshot).where(Snapshot.tenant_id == tenant,
        Snapshot.source_id == snapshot.source_id).order_by(Snapshot.observed_at.desc(), Snapshot.id.desc()).limit(1))
    if latest and latest.payload['point_links'] == snapshot.point_links:
        if any(snapshot.revisions[p] < latest.payload['revisions'][p] for p in snapshot.revisions):
            raise PublicationError('PRICE_REVISION_STALE_RECOLLECT')
    row = Snapshot(tenant_id=tenant, source_id=snapshot.source_id, plan_hash=expected_hash,
        date_from=snapshot.date_from, date_to=snapshot.date_to, observed_at=snapshot.observed_at, payload=report['snapshot'])
    db.add(row); db.flush()
    record_audit_event(db, tenant_id=tenant, event_type='PRODUCT_KNOWLEDGE_PRICES_REFRESHED',
        entity_type='ProductKnowledgePriceSnapshot', entity_id=row.id, operation='REFRESH_PRICES',
        actor_user=actor, context=context, source='HUMAN' if actor else 'SYSTEM',
        after=dict(plan_hash=expected_hash, products=len(snapshot.products), contexts=len(snapshot.contexts),
            points=[str(p) for p in snapshot.confirmed_point_ids], revisions=snapshot.revisions),
        reason=snapshot.office_evidence, correlation_id=str(execution_id) if execution_id else expected_hash)
    db.flush()
    return row
