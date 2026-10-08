"""September selection/dry-run and one-time transactional publication."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session, defer
from app.core.authorization import Capability, authorize
from app.audit.service import record_audit_event
from app.models.iiko import IikoMappingStatus, IikoProductMapping, IikoUnitMapping
from app.models.sales import SalesDaySync, SalesFact, SalesSyncState
from app.models.supply import SupplyProduct, SupplyProductCategory, SupplyUnit
from app.models.user import User
from app.models.product_knowledge import ProductKnowledgeBatch, ProductKnowledgeProduct, ProductKnowledgePrice
from app.sales.service import retail_mappings
from app.schemas.product_knowledge import SourceSnapshot

START, END = date(2026, 9, 1), date(2026, 10, 1)


class PublicationError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def preview(db: Session, tenant: str, source: str, snapshot: SourceSnapshot) -> dict:
    """No mutations, no network. Every sold source UUID remains in the report."""
    state = db.get(SalesSyncState, (tenant, source))
    if state is None or snapshot.source_id != source:
        raise PublicationError('SOURCE_MISMATCH')
    # Existing staging/mappings are tenant-wide: reject ambiguous multiple sources.
    if len(db.scalars(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant)).all()) != 1:
        raise PublicationError('MULTIPLE_SOURCES_REQUIRE_MAPPING_REVIEW')
    days = list(db.scalars(select(SalesDaySync).where(
        SalesDaySync.tenant_id == tenant, SalesDaySync.source_id == source,
        SalesDaySync.business_date >= START, SalesDaySync.business_date < END)))
    missing = [str(START + timedelta(days=n)) for n in range(30)
               if START + timedelta(days=n) not in {d.business_date for d in days}]
    points = retail_mappings(db, tenant)
    # Positive sales events count even if subsequently refunded; returns alone do not.
    facts = list(db.scalars(select(SalesFact).options(defer(SalesFact.raw_payload)).where(
        SalesFact.tenant_id == tenant, SalesFact.source_id == source,
        SalesFact.business_date >= START, SalesFact.business_date < END,
        SalesFact.is_present.is_(True), SalesFact.is_deleted.is_(False),
        SalesFact.is_returned.is_(False), SalesFact.quantity > 0)))
    candidates, excluded = defaultdict(list), defaultdict(list)
    for fact in facts:
        if points.get(fact.iiko_department_id) == fact.department_id and fact.department_id is not None:
            candidates[str(fact.iiko_product_id)].append(fact)
        else:
            excluded[str(fact.iiko_product_id)].append(fact)
    catalog = defaultdict(list)
    for p in snapshot.products:
        catalog[str(p.id)].append(p)
    units = defaultdict(list)
    for u in snapshot.units:
        units[str(u.id)].append(u)
    mappings = {str(m.iiko_product_id): m for m in db.scalars(select(IikoProductMapping).where(IikoProductMapping.tenant_id == tenant))}
    supplies = list(db.scalars(select(SupplyProduct).where(SupplyProduct.tenant_id == tenant)))
    supply_ids = {p.id: p for p in supplies}
    supply_external = defaultdict(list)
    for p in supplies:
        if p.iiko_id:
            try:
                supply_external[str(UUID(p.iiko_id))].append(p)
            except ValueError:
                pass
    unitmaps = {str(m.iiko_unit_id): m for m in db.scalars(select(IikoUnitMapping).where(IikoUnitMapping.tenant_id == tenant))}
    eosunits = {u.id: u for u in db.scalars(select(SupplyUnit).where(SupplyUnit.tenant_id == tenant))}
    categories = {c.id: c.name for c in db.scalars(select(SupplyProductCategory).where(SupplyProductCategory.tenant_id == tenant))}
    all_rows = []
    for pid in sorted(set(candidates) | set(excluded)):
        sold = candidates.get(pid, [])
        problems, warnings = [], []
        p = catalog[pid][0] if len(catalog[pid]) == 1 else None
        if not sold:
            problems.append('UNCONFIRMED_SALES_POINT')
        if p is None:
            problems.append('CATALOG_UUID_MISSING' if not catalog[pid] else 'DUPLICATE_CATALOG_UUID')
        mapping = mappings.get(pid)
        linked = None
        if mapping:
            if mapping.status != IikoMappingStatus.CONFIRMED or mapping.is_deleted or not mapping.eos_product_id:
                problems.append('PRODUCT_MAPPING_UNRESOLVED')
            else:
                linked = supply_ids.get(mapping.eos_product_id)
                if linked is None or not linked.iiko_id or str(linked.iiko_id) != pid:
                    problems.append('PRODUCT_MAPPING_DISAGREEMENT')
        elif supply_external[pid]:
            problems.append('SUPPLY_LINK_NOT_CONFIRMED')
        if len(supply_external[pid]) > 1 or (linked and any(x.id != linked.id for x in supply_external[pid])):
            problems.append('SUPPLY_UUID_CONFLICT')
        sales_links = {f.product_id for f in sold if f.product_id is not None}
        if sales_links and (linked is None or sales_links != {linked.id}):
            problems.append('SALES_PRODUCT_MAPPING_DISAGREEMENT')
        unit = None
        weight = None
        if p:
            unitrows = units[str(p.main_unit)]
            unit = unitrows[0] if len(unitrows) == 1 else None
            if unit is None or not unit.name.strip():
                problems.append('SOURCE_UNIT_UNRESOLVED')
            um = unitmaps.get(str(p.main_unit))
            if linked and (um is None or um.status != IikoMappingStatus.CONFIRMED or um.is_deleted
                           or um.eos_unit_id != linked.default_unit_id or um.eos_unit_id not in eosunits):
                problems.append('SUPPLY_UNIT_MAPPING_UNRESOLVED')
            if p.unit_weight_kg is not None and p.unit_weight_kg > 0:
                weight = str(p.unit_weight_kg)
            else:
                warnings.append('WEIGHT_UNKNOWN')
            if p.deleted:
                warnings.append('SOURCE_DELETED')
        mode = next((x for x in snapshot.sale_modes if str(x.iiko_product_id) == pid), None)
        source_mode = ('WEIGHT' if p.use_balance_for_sell else 'PORTION') if p and p.use_balance_for_sell is not None else 'UNKNOWN'
        prices = [x.model_dump(mode='json') for x in snapshot.prices if str(x.iiko_product_id) == pid]
        for x in prices:
            if UUID(x['department_id']) not in points.values():
                problems.append('PRICE_POINT_UNCONFIRMED')
        for i, left in enumerate(prices):
            if unit and left['price_unit'] != unit.name:
                problems.append('PRICE_UNIT_MISMATCH')
            for right in prices[i+1:]:
                if left['department_id'] == right['department_id'] and left['valid_from'] < right['valid_to'] and right['valid_from'] < left['valid_to']:
                    problems.append('PRICE_INTERVAL_CONFLICT')
        if not prices:
            warnings.append('PRICE_UNCONFIRMED')
        if mode is None and source_mode == 'UNKNOWN':
            warnings.append('SALE_MODE_UNKNOWN')
        # Actual catalog name is authoritative; Sales name remains evidence if absent.
        all_rows.append(dict(iiko_product_id=pid, name=p.name if p else next((f.product_name for f in sold if f.product_name), None),
            supply_product_id=str(linked.id) if linked else None,
            sku=p.sku if p else None, unit_id=str(unit.id) if unit else None,
            unit_name=unit.name if unit else None, unit_weight_kg=weight,
            sale_mode=mode.sale_mode if mode else source_mode, sale_mode_evidence=mode.evidence if mode else ('iiko useBalanceForSell' if source_mode != 'UNKNOWN' else None),
            category_id=str(linked.category_id) if linked and linked.category_id in categories else None,
            category_name=categories.get(linked.category_id) if linked else None,
            description=p.description if p else None, source_deleted=p.deleted if p else False,
            source_type=p.source_type if p else None, sale_events=len(sold),
            points=sorted({str(f.department_id) for f in sold}),
            problems=sorted(set(problems)), warnings=warnings, prices=prices))
    counts = Counter(x['name'] for x in all_rows if x['name'])
    for row in all_rows:
        if counts[row['name']] > 1:
            row['warnings'].append('SAME_NAME_DISTINCT_UUID')
    ready = [x for x in all_rows if not x['problems']]
    report = dict(tenant_id=tenant, source_id=source, period_start=str(START), period_end_exclusive=str(END),
        observed_at=snapshot.observed_at.isoformat(), snapshot_evidence=snapshot.evidence,
        successful_days=len(days), missing_days=missing, confirmed_point_ids=sorted(str(x) for x in set(points.values())),
        point_day_coverage={str(point): sorted({str(f.business_date) for f in facts if f.department_id == point and points.get(f.iiko_department_id) == point}) for point in set(points.values())},
        point_coverage_note='SalesDaySync is source-wide; absent point/day sales are not proof of zero sales.',
        found=len(candidates), unconfirmed_only=len(set(excluded)-set(candidates)),
        ready=len(ready), conflicts=len(all_rows)-len(ready),
        complete=not missing and bool(points) and snapshot.complete and state.history_from <= START,
        fields={field: sum(bool(x.get(field)) for x in ready) for field in ('name','unit_name','unit_weight_kg','category_name','description','prices')},
        sale_modes_confirmed=sum(x['sale_mode'] != 'UNKNOWN' for x in ready), rows=all_rows)
    report['plan_hash'] = digest(report)
    return report


def publish(db: Session, actor: User, report: dict, *, expected_hash: str, initial_status: str,
            confirmed_point_ids: list[UUID]) -> ProductKnowledgeBatch:
    """Caller owns transaction. Only first bootstrap or identical retry, no expansion."""
    context = authorize(db, actor, Capability.TECHNICAL_ADMIN, write=True)
    if actor.tenant_id != report['tenant_id'] or report['plan_hash'] != expected_hash:
        raise PublicationError('PLAN_REVIEW_REQUIRED')
    original = {k: v for k, v in report.items() if k != 'plan_hash'}
    if digest(original) != expected_hash or not report['complete']:
        raise PublicationError('INCOMPLETE_OR_MODIFIED_PLAN')
    if sorted(str(x) for x in confirmed_point_ids) != report['confirmed_point_ids']:
        raise PublicationError('POINT_COVERAGE_CONFIRMATION_REQUIRED')
    if initial_status not in {'ON_SALE', 'OFF_SALE'}:
        raise PublicationError('INITIAL_STATUS_REQUIRED')
    state = db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == actor.tenant_id,
        SalesSyncState.source_id == report['source_id']).with_for_update())
    if not state:
        raise PublicationError('SOURCE_MISMATCH')
    batches = list(db.scalars(select(ProductKnowledgeBatch).where(ProductKnowledgeBatch.tenant_id == actor.tenant_id,
        ProductKnowledgeBatch.source_id == report['source_id']).with_for_update()))
    if batches:
        batch = batches[0]
        if batch.plan_hash != expected_hash or batch.initial_status != initial_status:
            raise PublicationError('BOOTSTRAP_ALREADY_EXISTS_MANUAL_MAPPING_REQUIRED')
        if batch.rolled_back_at:
            raise PublicationError('BATCH_ROLLED_BACK_REVIEW_REQUIRED')
        return batch
    now = datetime.now(timezone.utc)
    batch = ProductKnowledgeBatch(tenant_id=actor.tenant_id, source_id=report['source_id'], plan_hash=expected_hash,
        report=report, initial_status=initial_status, created_by_user_id=actor.id)
    db.add(batch); db.flush()
    for row in report['rows']:
        if row['problems']:
            continue
        product = ProductKnowledgeProduct(tenant_id=actor.tenant_id, source_id=report['source_id'],
            iiko_product_id=UUID(row['iiko_product_id']), supply_product_id=UUID(row['supply_product_id']) if row['supply_product_id'] else None,
            batch_id=batch.id, name=row['name'], sku=row['sku'], unit_id=UUID(row['unit_id']), unit_name=row['unit_name'],
            unit_weight_kg=Decimal(row['unit_weight_kg']) if row['unit_weight_kg'] else None,
            sale_mode=row['sale_mode'], sale_status=initial_status,
            category_id=UUID(row['category_id']) if row['category_id'] else None, category_name=row['category_name'],
            description=row['description'], source_deleted=row['source_deleted'], observed_at=datetime.fromisoformat(report['observed_at']),
            provenance=dict(source='iiko catalog', evidence=report['snapshot_evidence'], weight_semantics='kg per main unit',
                sale_mode_evidence=row['sale_mode_evidence'], warnings=row['warnings']), published=True)
        db.add(product); db.flush()
        for price in row['prices']:
            db.add(ProductKnowledgePrice(tenant_id=actor.tenant_id, product_id=product.id,
                department_id=UUID(price['department_id']), valid_from=date.fromisoformat(price['valid_from']),
                valid_to=date.fromisoformat(price['valid_to']), amount=Decimal(price['amount']), currency=price['currency'],
                price_unit=price['price_unit'], evidence=price['evidence'], verified_by_user_id=actor.id,
                observed_at=datetime.fromisoformat(report['observed_at'])))
    record_audit_event(db, tenant_id=actor.tenant_id, event_type='PRODUCT_KNOWLEDGE_PUBLISHED',
        entity_type='ProductKnowledgeBatch', entity_id=batch.id, operation='PUBLISH',
        context=context, actor_user=actor, after={'plan_hash':expected_hash,'count':report['ready'],'initial_status':initial_status},
        reason='Подтверждённое первичное наполнение по продажам сентября 2026')
    db.flush()
    return batch


def rollback_publication(db: Session, actor: User, batch_id: UUID):
    context = authorize(db, actor, Capability.TECHNICAL_ADMIN, write=True)
    batch = db.scalar(select(ProductKnowledgeBatch).where(ProductKnowledgeBatch.id == batch_id,
        ProductKnowledgeBatch.tenant_id == actor.tenant_id).with_for_update())
    if batch is None:
        raise PublicationError('BATCH_NOT_FOUND')
    if batch.rolled_back_at is None:
        for product in db.scalars(select(ProductKnowledgeProduct).where(
                ProductKnowledgeProduct.tenant_id == actor.tenant_id, ProductKnowledgeProduct.batch_id == batch.id)):
            product.published = False
        batch.rolled_back_at = datetime.now(timezone.utc)
        batch.rolled_back_by_user_id = actor.id
        record_audit_event(db, tenant_id=actor.tenant_id, event_type='PRODUCT_KNOWLEDGE_UNPUBLISHED',
            entity_type='ProductKnowledgeBatch', entity_id=batch.id, operation='UNPUBLISH',
            context=context, actor_user=actor, before={'published':True}, after={'published':False},
            reason='Откат публикации партии без удаления истории')
    db.flush()
    return batch
