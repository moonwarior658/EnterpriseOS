"""Bounded K5B collection and append-only publication through Automation Core."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from app.audit.service import record_audit_event
from app.core.authorization import Capability, authorize
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.integrations.iiko.recipes import read_json, frozen_json
from app.models.product_knowledge import ProductKnowledgeProduct as Product
from app.models.product_recipe import ProductRecipeVersion as Version, ProductRecipeObservation as Observation
from app.models.sales import SalesSyncState
from app.product_knowledge.bootstrap import PublicationError, digest
from app.sales.sync import source_identity

ACTION = 'products.sync_iiko_recipes'

class RecipeRefreshPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    product_ids: list[UUID] = Field(min_length=1, max_length=141)
    # Explicit source UUID, not an inferred EOS/OLAP department or warehouse.
    department_id: UUID
    effective_on: date
    warehouse_id: UUID | None = None
    size_id: UUID | None = None
    scope_evidence: str = Field(min_length=10, max_length=1000)
    pilot_observation_id: UUID | None = None

    @model_validator(mode='after')
    def unique(self):
        if len(set(self.product_ids)) != len(self.product_ids) or not self.scope_evidence.strip():
            raise ValueError('RECIPE_SCOPE_INVALID')
        if len(self.product_ids) > 5 and self.pilot_observation_id is None:
            raise ValueError('RECIPE_PILOT_REQUIRED')
        return self


def scope(db, tenant, payload):
    states = list(db.scalars(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant)))
    if len(states) != 1 or states[0].source_id != payload.source_id:
        raise PublicationError('RECIPE_SOURCE_MISMATCH')
    products = {str(p.iiko_product_id): str(p.id) for p in db.scalars(select(Product).where(
        Product.tenant_id == tenant, Product.source_id == payload.source_id,
        Product.iiko_product_id.in_(payload.product_ids), Product.published.is_(True), Product.deleted_at.is_(None)))}
    if set(products) != {str(p) for p in payload.product_ids}:
        raise PublicationError('RECIPE_EXISTING_UUID_REQUIRED')
    if payload.pilot_observation_id:
        pilot = db.get(Observation, payload.pilot_observation_id)
        if pilot is None or pilot.tenant_id != tenant or pilot.source_id != payload.source_id or pilot.status != 'UNCONFIRMED' or pilot.payload['scope']['department_id'] != str(payload.department_id):
            raise PublicationError('RECIPE_PILOT_INVALID')
    return products


def enqueue(db, actor, payload):
    context = authorize(db, actor, Capability.TECHNICAL_ADMIN, write=True)
    return enqueue_authorized(db, actor, payload, context)


def enqueue_authorized(db, actor, payload, context):
    """Shared enqueue after the caller has authorized its specific capability."""
    scope(db, actor.tenant_id, payload)
    from app.automation.dispatch import create_automation_execution
    execution = create_automation_execution(db, automation_type=ACTION, tenant_id=actor.tenant_id,
        scope_type='company', scope_id=None, recipients=[], payload=payload.model_dump(mode='json'))
    record_audit_event(db, tenant_id=actor.tenant_id, event_type='PRODUCT_RECIPES_REQUESTED',
        entity_type='AutomationExecution', entity_id=execution.execution_id, operation='REFRESH_RECIPES',
        actor_user=actor, context=context, source='HUMAN', after=dict(products=len(payload.product_ids)), reason=payload.scope_evidence)
    return execution


def chart_list(envelope, key):
    value = envelope.get(key)
    return value if isinstance(value, list) else []


def reference_ids(root_id, bundle, *, include_history=True):
    ids = {root_id}
    charts = chart_list(bundle['tree'], 'assemblyCharts') + chart_list(bundle['prepared'], 'preparedCharts')
    if include_history:
        charts += [c for history in bundle['history'].values() for c in history]
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        try:
            ids.add(str(UUID(chart['assembledProductId'])))
        except (KeyError, ValueError, TypeError):
            pass
        items = chart.get('items')
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                ids.add(str(UUID(item['productId'])))
            except (KeyError, ValueError, TypeError):
                pass
    return ids


def scoped_references(root_id, bundle, references, *, include_history=True):
    ids = reference_ids(root_id, bundle, include_history=include_history)
    products = {p: value for p, value in references['products'].items() if p in ids}
    units = {value.get('mainUnit') for value in products.values()}
    return dict(products=products, units={u: value for u, value in references['units'].items() if u in units},
        scales={p: value for p, value in references['scales'].items() if p in ids})


def effective_charts(charts, at):
    result = []
    for chart in charts:
        try:
            start = date.fromisoformat(chart['dateFrom'])
            end = date.fromisoformat(chart['dateTo']) if chart.get('dateTo') else None
            if start <= at and (end is None or at < end):
                result.append(chart)
        except (KeyError, ValueError, TypeError):
            continue
    return result


def valid_store_spec(value):
    if value is None:
        return True
    try:
        return isinstance(value, dict) and type(value['inverse']) is bool and isinstance(value['departments'], list) and all(UUID(p) for p in value['departments'])
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def assess(root_id, at, bundle, references):
    """Conservative structural quality; independent Office acceptance is always pending."""
    incomplete, conflict = set(), set()
    tree = chart_list(bundle['tree'], 'assemblyCharts')
    root = chart_list(bundle['assembled'], 'assemblyCharts')
    prepared = chart_list(bundle['prepared'], 'preparedCharts')
    if not tree or not root or not prepared:
        incomplete.add('MISSING_PROJECTION')
    if len(prepared) > 1:
        conflict.add('PREPARED_NOT_UNIQUE')
    if digest(bundle['tree'].get('preparedCharts')) != digest(bundle['prepared'].get('preparedCharts')):
        conflict.add('PREPARED_CHANGED_DURING_COLLECTION')
    by_product = {}
    for chart in tree:
        if not isinstance(chart, dict):
            incomplete.add('INVALID_CHART'); continue
        try:
            UUID(chart['id']); pid = str(UUID(chart['assembledProductId']))
            start = date.fromisoformat(chart['dateFrom'])
            if 'dateTo' not in chart:
                incomplete.add('UNKNOWN_VALIDITY_END')
            end = date.fromisoformat(chart['dateTo']) if chart.get('dateTo') else None
            if not start <= at or end is not None and at >= end:
                conflict.add('INEFFECTIVE_CHART')
            if end is not None and end <= start:
                conflict.add('INVALID_INTERVAL')
            base = Decimal(str(chart['assembledAmount']))
            if not base.is_finite() or base <= 0:
                incomplete.add('INVALID_BASE')
            if chart.get('productWriteoffStrategy') not in ('ASSEMBLE', 'DIRECT'):
                incomplete.add('UNKNOWN_WRITEOFF_STRATEGY')
            if chart.get('productSizeAssemblyStrategy') != 'COMMON':
                incomplete.add('SIZE_REQUIRES_VERIFICATION')
            if 'effectiveDirectWriteoffStoreSpecification' not in chart:
                incomplete.add('UNKNOWN_STORE_SCOPE')
            if not valid_store_spec(chart.get('effectiveDirectWriteoffStoreSpecification')):
                incomplete.add('INVALID_STORE_SCOPE')
            items = chart['items']
            if not isinstance(items, list) or not items:
                incomplete.add('MISSING_ITEMS'); items = []
            for item in items:
                ingredient = str(UUID(item['productId']))
                if ingredient not in references['products']:
                    incomplete.add('UNRESOLVED_INGREDIENT')
                for name in ('amountIn', 'amountMiddle', 'amountOut'):
                    amount = Decimal(str(item[name]))
                    if not amount.is_finite() or amount < 0:
                        incomplete.add('INVALID_NORM')
                if 'storeSpecification' not in item or 'productSizeSpecification' not in item:
                    incomplete.add('UNKNOWN_ITEM_SCOPE')
                if not valid_store_spec(item.get('storeSpecification')):
                    incomplete.add('INVALID_STORE_SCOPE')
                if item.get('productSizeSpecification') is not None:
                    incomplete.add('SIZE_REQUIRES_VERIFICATION')
            by_product.setdefault(pid, []).append(chart)
        except (ValueError, KeyError, TypeError, InvalidOperation):
            incomplete.add('INVALID_CHART')
    if len(root) != 1 or len(by_product.get(root_id, [])) != 1:
        (conflict if len(root) > 1 or len(by_product.get(root_id, [])) > 1 else incomplete).add('ROOT_NOT_UNIQUE')
    elif digest(root[0]) != digest(by_product[root_id][0]):
        conflict.add('ROOT_CHANGED_DURING_COLLECTION')
    for pid, charts in by_product.items():
        if len(charts) != 1:
            conflict.add('DEPENDENCY_NOT_UNIQUE')
        history = bundle['history'].get(pid)
        if not isinstance(history, list) or not any(digest(c) == digest(charts[0]) for c in history):
            conflict.add('HISTORY_CHANGED_DURING_COLLECTION')
        elif len(effective_charts(history, at)) != 1:
            conflict.add('HISTORY_INTERVAL_AMBIGUOUS')
    edges = []
    visited = set()
    def walk(pid, path):
        if pid in path:
            conflict.add('RECIPE_CYCLE'); return
        if pid in visited:
            return
        visited.add(pid)
        charts = by_product.get(pid, [])
        if len(charts) != 1:
            return
        items = charts[0].get('items')
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            child = item.get('productId')
            if child in by_product:
                edges.append(dict(parent=pid, ingredient=child, chart_ids=[c['id'] for c in by_product[child]]))
                walk(child, path | {pid})
            elif references['products'].get(child, {}).get('type') in ('PREPARED', 'DISH'):
                incomplete.add('MISSING_NESTED_RECIPE')
    walk(root_id, set())
    if set(by_product) - visited:
        conflict.add('UNREACHABLE_TREE_CHART')
    if root_id not in references['products'] or set(by_product) - set(references['products']):
        incomplete.add('UNRESOLVED_PRODUCT')
    for pid, product in references['products'].items():
        if product.get('type') not in ('GOODS','DISH','PREPARED','MODIFIER','SERVICE'):
            incomplete.add('UNKNOWN_PRODUCT_TYPE')
        if product.get('deleted') is True:
            incomplete.add('SOURCE_PRODUCT_DELETED')
        unit = product.get('mainUnit')
        if not unit or not references['units'].get(unit, {}).get('name'):
            incomplete.add('UNRESOLVED_UNIT')
    for chart in prepared:
        try:
            UUID(chart['id'])
            if 'dateTo' not in chart:
                incomplete.add('UNKNOWN_VALIDITY_END')
            if not chart.get('items'):
                incomplete.add('MISSING_PREPARED_ITEMS')
            if str(UUID(chart['assembledProductId'])) != root_id:
                conflict.add('PREPARED_ROOT_MISMATCH')
            if chart.get('productSizeAssemblyStrategy') != 'COMMON':
                incomplete.add('PREPARED_SIZE_REQUIRES_VERIFICATION')
            if len(effective_charts([chart], at)) != 1:
                conflict.add('PREPARED_INTERVAL_INVALID')
            for item in chart['items']:
                UUID(item['productId'])
                if 'storeSpecification' not in item or 'productSizeSpecification' not in item:
                    incomplete.add('UNKNOWN_PREPARED_SCOPE')
                if not valid_store_spec(item.get('storeSpecification')):
                    incomplete.add('INVALID_PREPARED_STORE_SCOPE')
                if item.get('productSizeSpecification') is not None:
                    incomplete.add('PREPARED_SIZE_REQUIRES_VERIFICATION')
                if item['productId'] not in references['products']:
                    incomplete.add('UNRESOLVED_PREPARED_INGREDIENT')
                amount = Decimal(str(item['amount']))
                if not amount.is_finite() or amount < 0:
                    incomplete.add('INVALID_PREPARED_NORM')
        except (ValueError, KeyError, TypeError, InvalidOperation):
            incomplete.add('INVALID_PREPARED')
    return dict(status='CONFLICT' if conflict else 'INCOMPLETE' if incomplete else 'UNCONFIRMED',
        issues=sorted(conflict | incomplete | {'OFFICE_ACCEPTANCE_PENDING', 'PRODUCTION_STORE_UNCONFIRMED'}),
        dependencies=edges, ready_for_production=False)


async def collect_recipes(session_factory, *, tenant_id, payload, now):
    settings = get_iiko_settings()
    if source_identity(settings) != payload.source_id:
        raise PublicationError('RECIPE_SOURCE_MISMATCH')
    with session_factory() as db:
        products = scope(db, tenant_id, payload)
    bundles, history_cache = {}, {}
    async with IikoServerClient(settings) as client:
        for pid in sorted(products):
            args = dict(product_id=UUID(pid), at=payload.effective_on, department_id=payload.department_id)
            bundle = {name: await client.get_recipe_charts(method, **args) for name, method in
                [('tree','getTree'), ('assembled','getAssembled'), ('prepared','getPrepared')]}
            charts = chart_list(bundle['tree'], 'assemblyCharts')
            if len(charts) > 200:
                raise PublicationError('RECIPE_TREE_LIMIT')
            ids = {pid}
            for chart in charts:
                try:
                    ids.add(str(UUID(chart['assembledProductId'])))
                except (KeyError, TypeError, ValueError):
                    pass
            if len(set(history_cache) | ids) > 2000:
                raise PublicationError('RECIPE_DEPENDENCY_LIMIT')
            for p in sorted(ids):
                if p not in history_cache:
                    history_cache[p] = await client.get_recipe_charts('getHistory', product_id=UUID(p), department_id=payload.department_id)
            bundle['history'] = {p: history_cache[p] for p in sorted(ids)}
            if any(len(h) > 200 for h in bundle['history'].values()):
                raise PublicationError('RECIPE_HISTORY_LIMIT')
            bundles[pid] = frozen_json(bundle)
        ids = set().union(*(reference_ids(pid, bundle) for pid, bundle in bundles.items()))
        if len(ids) > 2000:
            raise PublicationError('RECIPE_REFERENCE_LIMIT')
        refs = {}
        ordered = sorted(ids)
        for offset in range(0, len(ordered), 50):
            data = await read_json(client, 'api/v2/entities/products/list', [('includeDeleted','true')] + [('ids', p) for p in ordered[offset:offset+50]])
            if not isinstance(data, list): raise PublicationError('RECIPE_REFERENCE_INVALID')
            for p in data:
                if not isinstance(p, dict) or p.get('id') not in ids or p['id'] in refs:
                    raise PublicationError('RECIPE_REFERENCE_CONFLICT')
                refs[p['id']] = frozen_json({k: p[k] for k in ('id','name','type','mainUnit','unitWeight','deleted','containers') if k in p})
        data = await read_json(client, 'api/v2/entities/list', dict(rootType='MeasureUnit', includeDeleted='true'))
        if not isinstance(data, list): raise PublicationError('RECIPE_UNITS_INVALID')
        units = {}
        for unit in data:
            if not isinstance(unit, dict) or 'id' not in unit:
                continue
            if unit['id'] in units:
                raise PublicationError('RECIPE_UNIT_CONFLICT')
            units[unit['id']] = frozen_json(unit)
        scales = {}
        for offset in range(0, len(ordered), 50):
            data = await read_json(client, 'api/v2/entities/products/productScales', [('includeDeleted','true')] + [('productId', p) for p in ordered[offset:offset+50]])
            if not isinstance(data, dict) or set(data) - ids or set(data) & set(scales):
                raise PublicationError('RECIPE_SCALES_INVALID')
            scales.update(frozen_json(data))
    return dict(products=products, bundles=bundles, references=dict(products=refs, units=units, scales=frozen_json(scales)),
        scope=payload.model_dump(mode='json'), observed_at=datetime.now(timezone.utc))


def publish_recipes(db, tenant, snapshot, *, execution_id):
    payload = RecipeRefreshPayload.model_validate(snapshot['scope'])
    db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant, SalesSyncState.source_id == payload.source_id).with_for_update())
    if scope(db, tenant, payload) != snapshot['products']:
        raise PublicationError('RECIPE_SCOPE_CHANGED')
    counts = dict(INCOMPLETE=0, CONFLICT=0, UNCONFIRMED=0)
    inserted = False
    observations = []
    for pid, local in snapshot['products'].items():
        previous = db.scalar(select(Observation).where(Observation.tenant_id == tenant,
            Observation.execution_id == execution_id, Observation.product_id == UUID(local)))
        if previous:
            counts[previous.status] += 1; observations.append(str(previous.id)); continue
        inserted = True
        bundle = snapshot['bundles'][pid]
        references = scoped_references(pid, bundle, snapshot['references'])
        current_references = scoped_references(pid, bundle, snapshot['references'], include_history=False)
        quality = assess(pid, payload.effective_on, bundle, current_references)
        if reference_ids(pid, bundle, include_history=False) - set(snapshot['references']['scales']):
            quality['issues'].append('SIZE_REFERENCE_MISSING')
            if quality['status'] != 'CONFLICT':
                quality['status'] = 'INCOMPLETE'
        local_product = db.get(Product, UUID(local))
        source_unit = references['products'].get(pid, {}).get('mainUnit')
        if source_unit is not None and source_unit != str(local_product.unit_id):
            quality['status'] = 'CONFLICT'
            quality['issues'].append('ROOT_UNIT_MISMATCH')
        manifest = []
        histories = [chart for history in bundle['history'].values() for chart in history]
        for kind, role, charts in [('SOURCE','TREE',chart_list(bundle['tree'], 'assemblyCharts')),
                ('SOURCE','ASSEMBLED',chart_list(bundle['assembled'], 'assemblyCharts')),
                ('SOURCE','HISTORY',histories), ('PREPARED','PREPARED',chart_list(bundle['prepared'], 'preparedCharts'))]:
            for chart in charts:
                try: cid, product = UUID(chart['id']), UUID(chart['assembledProductId'])
                except (ValueError, KeyError, TypeError): continue
                content_hash = digest(chart)
                version = db.scalar(select(Version).where(Version.tenant_id == tenant, Version.source_id == payload.source_id,
                    Version.chart_id == cid, Version.kind == kind, Version.content_hash == content_hash))
                if version is None:
                    version = Version(tenant_id=tenant, source_id=payload.source_id, chart_id=cid,
                        source_product_id=product, kind=kind, content_hash=content_hash, payload=chart)
                    db.add(version); db.flush()
                item = dict(version_id=str(version.id), chart_id=str(cid), product_id=str(product), kind=kind, role=role, content_hash=content_hash)
                if item not in manifest: manifest.append(item)
        manifest_hash = digest(dict(manifest=manifest, references=references, scope=snapshot['scope'], dependencies=quality['dependencies']))
        report = dict(scope=snapshot['scope'], **quality, manifest=manifest, manifest_hash=manifest_hash,
            references=references, source_responses=bundle)
        row = Observation(tenant_id=tenant, source_id=payload.source_id, product_id=UUID(local), execution_id=execution_id,
            effective_on=payload.effective_on, observed_at=snapshot['observed_at'], status=quality['status'], payload=report)
        db.add(row); db.flush()
        counts[row.status] += 1; observations.append(str(row.id))
    if inserted:
        record_audit_event(db, tenant_id=tenant, event_type='PRODUCT_RECIPES_OBSERVED',
            entity_type='AutomationExecution', entity_id=execution_id, operation='REFRESH_RECIPES',
            source='SYSTEM', after=counts, correlation_id=str(execution_id))
    return dict(counts=counts, observation_ids=observations, ready_for_production=False)
