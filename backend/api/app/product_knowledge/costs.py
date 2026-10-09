"""Bounded SSN reads and append-only observations using the existing outbox seam."""
from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.audit.service import record_audit_event
from app.core.authorization import Capability, authorize
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.integrations.iiko.recipes import read_json, frozen_json
from app.models.product_cost import ProductCostObservation as Observation
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.models.sales import SalesSyncState
from app.product_knowledge.bootstrap import PublicationError, digest
from app.product_knowledge.cost_calculation import calculate, POLICY
from app.sales.sync import source_identity

ACTION = 'products.sync_iiko_costs'


class CostRefreshPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    product_ids: list[UUID] = Field(min_length=1, max_length=141)
    department_id: UUID | None = None
    # Empty means an explicitly requested aggregate of ALL source warehouses.
    warehouse_ids: list[UUID] = Field(max_length=100)
    context_label: str = Field(min_length=3, max_length=240)
    scope_evidence: str = Field(min_length=20, max_length=1000)

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.product_ids)) != len(self.product_ids) or len(set(self.warehouse_ids)) != len(self.warehouse_ids):
            raise ValueError('COST_DUPLICATE_SCOPE')
        if not self.context_label.strip() or not self.scope_evidence.strip():
            raise ValueError('COST_EMPTY_EVIDENCE')
        return self


def context(payload):
    return dict(source_id=payload.source_id, department_id=str(payload.department_id) if payload.department_id else None,
        warehouse_ids=sorted(str(p) for p in payload.warehouse_ids), context_label=payload.context_label,
        timezone='Asia/Yekaterinburg', policy=POLICY)


def scope(db, tenant, payload):
    state = db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant, SalesSyncState.source_id == payload.source_id))
    if state is None:
        raise PublicationError('COST_SOURCE_MISMATCH')
    products = {str(p.iiko_product_id):str(p.id) for p in db.scalars(select(Product).where(
        Product.tenant_id == tenant, Product.source_id == payload.source_id,
        Product.iiko_product_id.in_(payload.product_ids), Product.published.is_(True), Product.deleted_at.is_(None)))}
    if set(products) != {str(p) for p in payload.product_ids}:
        raise PublicationError('COST_EXISTING_UUID_REQUIRED')
    return products


def enqueue(db, actor, payload):
    auth = authorize(db, actor, Capability.TECHNICAL_ADMIN, write=True)
    scope(db, actor.tenant_id, payload)
    from app.automation.dispatch import create_automation_execution
    execution = create_automation_execution(db, automation_type=ACTION, tenant_id=actor.tenant_id,
        scope_type='company', scope_id=None, recipients=[], payload=payload.model_dump(mode='json'))
    record_audit_event(db, tenant_id=actor.tenant_id, event_type='PRODUCT_COSTS_REQUESTED',
        entity_type='AutomationExecution', entity_id=execution.execution_id, operation='REFRESH_COSTS',
        actor_user=actor, context=auth, source='HUMAN', after=dict(products=len(payload.product_ids)), reason=payload.scope_evidence)
    return execution


def normalize(pid, tree, references, units, balances, scales=None):
    charts = tree.get('assemblyCharts')
    if not isinstance(charts, list):
        raise PublicationError('COST_TREE_INVALID')
    if any('effectiveDirectWriteoffStoreSpecification' not in c or 'productSizeAssemblyStrategy' not in c for c in charts):
        raise PublicationError('COST_UNKNOWN_WRITEOFF_SCOPE')
    ids = {pid} | {c['assembledProductId'] for c in charts} | {i['productId'] for c in charts for i in c['items']}
    return dict(key=pid, charts=[dict(key=c['id'], root_key=c['assembledProductId'],
        assembledAmount=c.get('assembledAmount'), dateFrom=c.get('dateFrom'), dateTo=c.get('dateTo'),
        direct_spec=c.get('effectiveDirectWriteoffStoreSpecification'), size_strategy=c.get('productSizeAssemblyStrategy'),
        scale_absent=bool(scales is not None and c['assembledProductId'] in scales and scales[c['assembledProductId']] is None),
        items=[dict(product_key=i['productId'], amountIn=i.get('amountIn'), storeSpecification=i.get('storeSpecification'),
            size_specified=i.get('productSizeSpecification') is not None) for i in c['items']]) for c in charts],
        references=[dict(key=p['id'], name=p.get('name'), type=p.get('type'), deleted=p.get('deleted'),
            mainUnit_key=p.get('mainUnit'), unitWeight=p.get('unitWeight'), estimatedPurchasePrice=p.get('estimatedPurchasePrice'))
            for p in references if p['id'] in ids],
        units=[dict(key=u['id'], name=u.get('name')) for u in units if any(p.get('mainUnit') == u['id'] for p in references if p['id'] in ids)],
        balances=[dict(rows=[dict(product_key=b['product'], store_key=b['store'], amount=b.get('amount'), sum=b.get('sum'))
            for b in balances if b['product'] in ids])])


async def collect_costs(session_factory, *, tenant_id, payload, now, client_factory=IikoServerClient):
    if now.tzinfo is None or now.utcoffset() is None:
        raise PublicationError('COST_TIMEZONE_REQUIRED')
    config = get_iiko_settings()
    if payload.source_id != source_identity(config):
        raise PublicationError('COST_SOURCE_MISMATCH')
    with session_factory() as db:
        products = scope(db, tenant_id, payload)
    stock_at = now.astimezone(ZoneInfo('Asia/Yekaterinburg')).replace(microsecond=0)
    trees, ids = {}, set(products)
    async with client_factory(config) as client:
        async def tree(pid):
            params = dict(productId=pid, date=stock_at.date().isoformat())
            if payload.department_id:
                params['departmentId'] = str(payload.department_id)
            return frozen_json(await read_json(client, 'api/v2/assemblyCharts/getTree', params))
        for pid in sorted(products):
            value = await tree(pid)
            if not isinstance(value, dict) or not isinstance(value.get('assemblyCharts'), list):
                raise PublicationError('COST_TREE_INVALID')
            trees[pid] = value
            for chart in value['assemblyCharts']:
                if not isinstance(chart, dict) or not isinstance(chart.get('items'), list):
                    raise PublicationError('COST_CHART_INVALID')
                ids.add(str(UUID(chart['assembledProductId'])))
                ids.update(str(UUID(i['productId'])) for i in chart['items'])
            if len(ids) > 2000:
                raise PublicationError('COST_REFERENCE_LIMIT')
        # SPECIFIC can be a dormant flag when no size scale is assigned. Only an
        # explicit null from the documented mapping endpoint proves absence.
        scale_ids = sorted({c['assembledProductId'] for t in trees.values() for c in t['assemblyCharts']
            if c.get('productSizeAssemblyStrategy') == 'SPECIFIC'})
        scales = {}
        for offset in range(0, len(scale_ids), 50):
            chunk = scale_ids[offset:offset+50]
            result = await read_json(client, 'api/v2/entities/products/productScales', [('productId', p) for p in chunk])
            if not isinstance(result, dict) or set(result) != set(chunk) or any(v is not None and not isinstance(v, dict) for v in result.values()):
                raise PublicationError('COST_SCALES_INVALID')
            scales.update(result)
        references, balances = [], []
        ordered = sorted(ids)
        for offset in range(0,len(ordered),50):
            chunk = ordered[offset:offset+50]
            refs = await read_json(client, 'api/v2/entities/products/list', [('includeDeleted','true')] + [('ids',p) for p in chunk])
            if not isinstance(refs,list) or any(not isinstance(p,dict) or p.get('id') not in chunk for p in refs):
                raise PublicationError('COST_REFERENCES_INVALID')
            references.extend(refs)
            params = [('timestamp',stock_at.strftime('%Y-%m-%dT%H:%M:%S'))] + [('product',p) for p in chunk] + [('store',str(s)) for s in payload.warehouse_ids]
            rows = await read_json(client, 'api/v2/reports/balance/stores', params)
            if not isinstance(rows,list) or any(not isinstance(b,dict) or b.get('product') not in chunk or
                (payload.warehouse_ids and b.get('store') not in {str(s) for s in payload.warehouse_ids}) for b in rows):
                raise PublicationError('COST_BALANCES_INVALID')
            balances.extend(rows)
        units = await read_json(client,'api/v2/entities/list',dict(rootType='MeasureUnit',includeDeleted='true'))
        if not isinstance(units,list) or any(not isinstance(u,dict) or 'id' not in u for u in units):
            raise PublicationError('COST_UNITS_INVALID')
        if len({u['id'] for u in units}) != len(units) or len({p['id'] for p in references}) != len(references):
            raise PublicationError('COST_REFERENCE_CONFLICT')
        # Size assignments, like recipes, may change during collection.
        for offset in range(0, len(scale_ids), 50):
            chunk = scale_ids[offset:offset+50]
            if digest(await read_json(client, 'api/v2/entities/products/productScales', [('productId', p) for p in chunk])) != digest({p: scales[p] for p in chunk}):
                raise PublicationError('COST_SCALES_CHANGED_DURING_COLLECTION')
        # Do not combine changed recipes with earlier stock reads.
        for pid in sorted(products):
            if digest(await tree(pid)) != digest(trees[pid]):
                raise PublicationError('COST_RECIPE_CHANGED_DURING_COLLECTION')
    roots = {pid:frozen_json(normalize(pid,trees[pid],references,units,balances,scales)) for pid in products}
    return dict(products=products, roots=roots, scope=payload.model_dump(mode='json'),
        stock_at=stock_at, observed_at=datetime.now(timezone.utc))


def publish_costs(db, tenant, snapshot, *, execution_id):
    if any(snapshot[k].tzinfo is None for k in ('stock_at','observed_at')) or snapshot['stock_at'] > snapshot['observed_at']:
        raise PublicationError('COST_SNAPSHOT_TIME_INVALID')
    payload = CostRefreshPayload.model_validate(snapshot['scope'])
    db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant, SalesSyncState.source_id == payload.source_id).with_for_update())
    if scope(db,tenant,payload) != snapshot['products']:
        raise PublicationError('COST_SCOPE_CHANGED')
    counts = dict(UNVERIFIED=0, INCOMPLETE=0)
    inserted = False
    for pid, local in sorted(snapshot['products'].items()):
        previous = db.scalar(select(Observation).where(Observation.tenant_id == tenant,
            Observation.execution_id == execution_id, Observation.product_id == UUID(local)))
        root = snapshot['roots'][pid]
        if root['key'] != pid:
            raise PublicationError('COST_ROOT_MISMATCH')
        product = db.get(Product, UUID(local))
        refs = {p['key']:p for p in root['references']}
        if refs.get(pid,{}).get('mainUnit_key') != str(product.unit_id):
            raise PublicationError('COST_ROOT_UNIT_MISMATCH')
        result = calculate(root,at=snapshot['stock_at'].astimezone(ZoneInfo('Asia/Yekaterinburg')).date(),department=str(payload.department_id) if payload.department_id else None)
        report = dict(context=context(payload), scope_evidence=payload.scope_evidence, input=root, result=result,
            source='IIKO_RECIPE_AND_STOCK', method=POLICY, currency='RUB')
        if previous:
            if previous.content_hash != digest(report) or previous.context_hash != digest(context(payload)):
                raise PublicationError('COST_EXECUTION_CONTENT_CONFLICT')
            counts[previous.status] += 1
            continue
        row = Observation(tenant_id=tenant,source_id=payload.source_id,product_id=UUID(local),execution_id=execution_id,
            stock_at=snapshot['stock_at'],observed_at=snapshot['observed_at'],
            status='UNVERIFIED' if result['amount'] is not None else 'INCOMPLETE',
            context_hash=digest(context(payload)), method_hash=digest(result['signature']) if result['signature'] else None,
            content_hash=digest(report),payload=report)
        db.add(row);db.flush();counts[row.status] += 1;inserted = True
    if inserted:
        record_audit_event(db,tenant_id=tenant,event_type='PRODUCT_COSTS_OBSERVED',entity_type='AutomationExecution',
            entity_id=execution_id,operation='REFRESH_COSTS',source='SYSTEM',after=counts,correlation_id=str(execution_id))
    return dict(counts=counts,publication_allowed=False)


def require_verified_schedule(db, tenant, payload):
    """Schedule setup requires an explicit Office-reviewed method for every UUID."""
    from app.models.product_cost import ProductCostVerification as Verification
    products = scope(db,tenant,payload)
    context_hash = digest(context(payload))
    for local in products.values():
        latest = db.scalar(select(Observation).where(Observation.tenant_id == tenant,
            Observation.product_id == UUID(local),Observation.source_id == payload.source_id,
            Observation.context_hash == context_hash).order_by(Observation.stock_at.desc(),Observation.observed_at.desc(),Observation.id.desc()))
        if latest is None or latest.status == 'INCOMPLETE':
            raise PublicationError('COST_OFFICE_VERIFICATION_REQUIRED')
        approvals = list(db.execute(select(Observation,Verification).join(Verification,
            (Verification.tenant_id == Observation.tenant_id) & (Verification.observation_id == Observation.id)).where(
            Observation.tenant_id == tenant,Observation.product_id == UUID(local),Observation.context_hash == context_hash)
            .order_by(Verification.confirmed_at.desc(),Verification.id.desc())).all())
        if not approvals or not approvals[0][1].payload.get('allow_updates') or approvals[0][0].method_hash != latest.method_hash:
            raise PublicationError('COST_OFFICE_VERIFICATION_REQUIRED')
