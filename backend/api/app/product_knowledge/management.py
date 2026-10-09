"""EOS-only management; source identity and K1 publication are immutable here."""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from app.audit.service import record_audit_event
from app.core.authorization import authorize, Capability, product_knowledge_context
from app.core.action_context import ActionContextError
from app.models.audit import AuditEvent
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgeBatch as Batch
from app.models.sales import SalesSyncState, SalesFact
from app.models.iiko import IikoProductMapping, IikoUnitMapping
from app.models.supply import SupplyProduct, SupplyUnit
from app.models.supply import SupplyProductCategory
from app.product_knowledge.bootstrap import digest

LOCAL_FIELDS = ('local_photo_hash', 'local_name', 'category_id', 'category_name', 'local_description', 'characteristics',
                'composition', 'allergens', 'storage', 'training', 'sale_status', 'deleted_at',
                'verified_at', 'verified_by_employee_id', 'verified_by_name', 'version')
AUDIT_FIELDS = (*LOCAL_FIELDS, 'name', 'description')


def manage_context(db, user, *, write=True):
    return authorize(db, user, Capability.PRODUCT_KNOWLEDGE_MANAGE, write=write)


def can_manage(db, user):
    try:
        manage_context(db, user, write=False)
        return True
    except ActionContextError:
        return False


def eligible_for_production(product):
    return product.published and product.deleted_at is None and product.sale_status == 'ON_SALE'


def require_production_eligible(db, tenant_id, product_id):
    product = db.scalar(select(Product).where(Product.tenant_id == tenant_id, Product.id == product_id).with_for_update().execution_options(populate_existing=True))
    if product is None or not eligible_for_production(product):
        raise HTTPException(409, 'Изделие недоступно для производственного планирования')
    return product


def find_product(db, user, product_id, *, lock=False):
    stmt = select(Product).where(Product.tenant_id == user.tenant_id, Product.id == product_id,
                                 Product.published.is_(True))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    product = db.scalar(stmt)
    if product is None:
        raise HTTPException(404, 'Изделие не найдено')
    return product


def local_state(product):
    return {**{key: getattr(product, key) for key in LOCAL_FIELDS},
            'name': product.local_name or product.name,
            'description': product.local_description if product.local_description is not None else product.description}


def clear_verification(product):
    product.verified_at = None
    product.verified_by_employee_id = None
    product.verified_by_name = None


def audit(db, user, context, product, operation, before, reason, correlation_id=None):
    record_audit_event(db, tenant_id=user.tenant_id, event_type='PRODUCT_KNOWLEDGE_' + operation,
        entity_type='ProductKnowledgeProduct', entity_id=product.id, operation=operation,
        context=context, actor_user=user, before=before, after=local_state(product),
        reason=reason, correlation_id=correlation_id)
    db.flush()


def mutate(db, user, product_id, operation, command):
    context = manage_context(db, user)
    product = find_product(db, user, product_id, lock=True)
    command_hash = digest(dict(product_id=str(product.id), operation=operation, command=command.model_dump(mode='json')))
    if db.scalar(select(AuditEvent.id).where(AuditEvent.tenant_id == user.tenant_id,
            AuditEvent.entity_type == 'ProductKnowledgeProduct', AuditEvent.entity_id == str(product.id),
            AuditEvent.actor_user_id == user.id, AuditEvent.correlation_id == command_hash)):
        return product  # Identical retry, including a lost response: no duplicate audit/mutation.
    if product.version != command.expected_version:
        raise HTTPException(409, 'Карточка изменена другим сотрудником. Обновите её и повторите действие')
    if product.deleted_at is not None and operation != 'RESTORE':
        raise HTTPException(409, 'Сначала восстановите изделие')
    before = local_state(product)
    if operation == 'EDIT':
        category = None
        if command.category_id:
            category = db.scalar(select(SupplyProductCategory).where(SupplyProductCategory.id == command.category_id,
                SupplyProductCategory.tenant_id == user.tenant_id, SupplyProductCategory.is_active.is_(True)))
            if category is None:
                raise HTTPException(422, 'Выберите доступную категорию EOS')
        product.local_name = command.name
        product.category_id = category.id if category else None
        product.category_name = category.name if category else None
        product.local_description = command.description or ''
        for key in ('characteristics', 'composition', 'allergens', 'storage', 'training'):
            setattr(product, key, getattr(command, key))
        clear_verification(product)
    elif operation == 'STATUS':
        product.sale_status = command.sale_status
        clear_verification(product)
    elif operation == 'DELETE':
        product.deleted_at = datetime.now(timezone.utc)
        clear_verification(product)
    elif operation == 'RESTORE':
        if product.deleted_at is None:
            raise HTTPException(409, 'Изделие уже находится в справочнике')
        product.deleted_at = None
        clear_verification(product)
    elif operation == 'VERIFY':
        clear_verification(product)
        if command.verified:
            product.verified_at = datetime.now(timezone.utc)
            product.verified_by_employee_id = context.employee_id
            product.verified_by_name = context.employee_name_snapshot
    else:
        raise ValueError('Unsupported product operation')
    product.version += 1
    audit(db, user, context, product, operation, before, command.reason, command_hash)
    return product


def history(db, user, product_id, *, offset=0, limit=25):
    product_knowledge_context(db, user)
    find_product(db, user, product_id)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == user.tenant_id,
        AuditEvent.entity_type == 'ProductKnowledgeProduct', AuditEvent.entity_id == str(product_id))
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit))
    return [dict(id=row.id, operation=row.operation, occurred_at=row.occurred_at,
                 actor_name=row.actor_name_snapshot, reason=row.reason,
                 before={k:v for k,v in row.before.items() if k in AUDIT_FIELDS},
                 after={k:v for k,v in row.after.items() if k in AUDIT_FIELDS}) for row in rows]


def active_source(db, user):
    manage_context(db, user, write=False)
    sources = list(db.scalars(select(Batch.source_id).where(Batch.tenant_id == user.tenant_id,
        Batch.rolled_back_at.is_(None)).distinct()))
    if len(sources) != 1:
        raise HTTPException(409, 'Нет однозначного опубликованного источника продукции')
    return sources[0]


def candidates(db, user, snapshot, *, q='', limit=25):
    manage_context(db, user, write=False)
    if not snapshot.complete or snapshot.source_id != active_source(db, user):
        raise HTTPException(409, 'Источник продукции не подтверждён')
    units = {unit.id: unit for unit in snapshot.units}
    if len(units) != len(snapshot.units) or len({p.id for p in snapshot.products}) != len(snapshot.products):
        raise HTTPException(409, 'Конфликт идентификаторов источника')
    existing = {p.iiko_product_id: p for p in db.scalars(select(Product).where(
        Product.tenant_id == user.tenant_id, Product.source_id == snapshot.source_id))}
    result = []
    for source in snapshot.products:
        if q.strip().casefold() not in (source.name + ' ' + str(source.id)).casefold():
            continue
        unit = units.get(source.main_unit)
        product = existing.get(source.id)
        if unit is None or (product and (product.deleted_at is None or not product.published)):
            continue
        if source.deleted and not product:
            continue
        values = dict(source_id=snapshot.source_id, iiko_product_id=str(source.id), name=source.name,
                      unit_name=unit.name, source_deleted=source.deleted,
                      existing_id=str(product.id) if product else None, version=product.version if product else None)
        # Hash all source attributes + explicit unit, without observation clock.
        values['confirmation_hash'] = digest(dict(source=source.model_dump(mode='json'), unit=unit.model_dump(mode='json'),
                                                  source_id=snapshot.source_id, existing=values))
        result.append(values)
    return sorted(result, key=lambda x: (x['name'], x['iiko_product_id']))[:limit]


def confirmed_supply_link(db, tenant, source):
    """Reuse existing explicit ID mappings only; unresolved links fail closed."""
    mapping = db.scalar(select(IikoProductMapping).where(IikoProductMapping.tenant_id == tenant,
        IikoProductMapping.iiko_product_id == source.id))
    linked = None
    if mapping:
        if mapping.status != 'CONFIRMED' or mapping.is_deleted or mapping.eos_product_id is None:
            raise HTTPException(409, 'Связь изделия с Supply не подтверждена')
        linked = db.scalar(select(SupplyProduct).where(SupplyProduct.tenant_id == tenant,
            SupplyProduct.id == mapping.eos_product_id))
        try:
            identity_matches = linked is not None and linked.iiko_id and UUID(linked.iiko_id) == source.id
        except ValueError:
            identity_matches = False
        if not identity_matches:
            raise HTTPException(409, 'Связь UUID изделия противоречит Supply')
        unitmap = db.scalar(select(IikoUnitMapping).where(IikoUnitMapping.tenant_id == tenant,
            IikoUnitMapping.iiko_unit_id == source.main_unit))
        if unitmap is None or unitmap.status != 'CONFIRMED' or unitmap.is_deleted or unitmap.eos_unit_id != linked.default_unit_id:
            raise HTTPException(409, 'Единица связанного изделия не подтверждена')
        if db.scalar(select(SupplyUnit.id).where(SupplyUnit.tenant_id == tenant, SupplyUnit.id == unitmap.eos_unit_id)) is None:
            raise HTTPException(409, 'Единица связанного изделия недоступна')
    for product in db.scalars(select(SupplyProduct).where(SupplyProduct.tenant_id == tenant, SupplyProduct.iiko_id.is_not(None))):
        try:
            matches = UUID(product.iiko_id) == source.id
        except ValueError:
            matches = False
        if matches and (linked is None or linked.id != product.id):
            raise HTTPException(409, 'Связь UUID изделия с Supply требует проверки')
    sales_links = set(db.scalars(select(SalesFact.product_id).where(SalesFact.tenant_id == tenant,
        SalesFact.iiko_product_id == source.id, SalesFact.product_id.is_not(None)).distinct()))
    if sales_links and (linked is None or sales_links != {linked.id}):
        raise HTTPException(409, 'Связь изделия в продажах требует проверки')
    return linked


def add_product(db, user, command, snapshot):
    context = manage_context(db, user)
    if command.source_id != active_source(db, user):
        raise HTTPException(409, 'Источник продукции изменился')
    # Serialize additions/restorations by source. UUID uniqueness is also enforced in DB.
    db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == user.tenant_id,
        SalesSyncState.source_id == command.source_id).with_for_update())
    existing = db.scalar(select(Product).where(Product.tenant_id == user.tenant_id,
        Product.source_id == command.source_id, Product.iiko_product_id == command.iiko_product_id)
        .with_for_update().execution_options(populate_existing=True))
    command_hash = digest(dict(operation='ADD', command=command.model_dump(mode='json')))
    if existing and db.scalar(select(AuditEvent.id).where(AuditEvent.tenant_id == user.tenant_id,
        AuditEvent.entity_id == str(existing.id), AuditEvent.entity_type == 'ProductKnowledgeProduct',
        AuditEvent.actor_user_id == user.id, AuditEvent.correlation_id == command_hash)):
        return existing
    selected = next((p for p in candidates(db, user, snapshot, q=str(command.iiko_product_id), limit=100)
                     if p['iiko_product_id'] == str(command.iiko_product_id)), None)
    if selected is None or selected['confirmation_hash'] != command.confirmation_hash:
        raise HTTPException(409, 'Выбор устарел или изделие уже добавлено. Выберите UUID заново')
    if existing:
        before = local_state(existing)
        existing.deleted_at = None
        # Re-add restores the same identity and all local content; status is explicitly confirmed.
        existing.sale_status = command.sale_status
        clear_verification(existing)
        existing.version += 1
        audit(db, user, context, existing, 'READD', before, command.reason, command_hash)
        return existing
    source = next(p for p in snapshot.products if p.id == command.iiko_product_id)
    unit = next(u for u in snapshot.units if u.id == source.main_unit)
    linked = confirmed_supply_link(db, user.tenant_id, source)
    batch = Batch(tenant_id=user.tenant_id, source_id=command.source_id, plan_hash=command_hash,
        report={'kind':'MANUAL_UUID_CONFIRMATION', 'iiko_product_id':str(source.id)},
        initial_status=command.sale_status, created_by_user_id=user.id)
    db.add(batch)
    db.flush()
    product = Product(tenant_id=user.tenant_id, source_id=command.source_id, iiko_product_id=source.id,
        batch_id=batch.id, supply_product_id=linked.id if linked else None, name=source.name, sku=source.sku, unit_id=unit.id, unit_name=unit.name,
        unit_weight_kg=source.unit_weight_kg if source.unit_weight_kg and source.unit_weight_kg > 0 else None,
        sale_mode='UNKNOWN' if source.use_balance_for_sell is None else ('WEIGHT' if source.use_balance_for_sell else 'PORTION'),
        sale_status=command.sale_status, description=source.description, source_deleted=source.deleted,
        observed_at=snapshot.observed_at, provenance={'source':'iiko catalog', 'evidence':snapshot.evidence}, published=True)
    db.add(product)
    db.flush()
    audit(db, user, context, product, 'ADD', {}, command.reason, command_hash)
    return product
