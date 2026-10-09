"""Tenant-scoped DB reads only. Public responses deliberately exclude cost/recipes."""
from datetime import date, datetime, timezone, timedelta
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.core.authorization import product_knowledge_context
from app.models.employee import EmployeeRole
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgePrice as Price, ProductKnowledgePriceSnapshot as PriceSnapshot
from app.models.supply import Department, SupplyProductCategory
from app.product_knowledge.management import can_manage, eligible_for_production, find_product
from app.sales.service import retail_mappings


def points_for(db, user):
    context = product_knowledge_context(db, user)
    ids = set(retail_mappings(db, user.tenant_id).values())
    if context.authorized_as == EmployeeRole.SELLER:
        ids &= {context.primary_department_id}
    return list(db.scalars(select(Department).where(Department.tenant_id == user.tenant_id,
        Department.id.in_(ids), Department.is_active.is_(True)).order_by(Department.name, Department.id)))


def price_rows(db, user, ids, points, price_at):
    units = dict(db.execute(select(Product.id, Product.unit_name).where(
        Product.tenant_id == user.tenant_id, Product.id.in_(ids))).all())
    prices = list(db.scalars(select(Price).where(Price.tenant_id == user.tenant_id,
        Price.product_id.in_(ids), Price.department_id.in_([p.id for p in points]),
        Price.valid_from <= price_at, Price.valid_to > price_at)))
    names = {p.id: p.name for p in points}
    grouped = {}
    for p in prices:
        grouped.setdefault((p.product_id, p.department_id), []).append(p)
    result = {pid: [] for pid in ids}
    conflicts = {pid: [] for pid in ids}
    for (pid, point), versions in grouped.items():
        # Fail closed even for legacy/externally introduced overlaps.
        if len(versions) != 1:
            conflicts[pid].append(point)
            continue
        p = versions[0]
        if p.price_unit != units.get(pid):
            conflicts[pid].append(point)
            continue
        result[pid].append(dict(department_id=p.department_id, department_name=names[point], amount=p.amount,
            currency=p.currency, price_unit=p.price_unit, valid_from=p.valid_from, valid_to=p.valid_to,
            observed_at=p.observed_at))
    for entries in result.values():
        entries.sort(key=lambda x: (x['department_name'], str(x['department_id'])))
    # Latest complete snapshot wins, including missing/excluded/conflicting rows.
    # Old imports cannot silently resurrect a removed source price.
    from app.product_knowledge.price_resolver import resolve
    from app.integrations.iiko.prices import PriceContext
    products = list(db.scalars(select(Product).where(Product.tenant_id == user.tenant_id, Product.id.in_(ids))))
    current_links = {str(local): str(external) for external, local in retail_mappings(db, user.tenant_id).items()}
    for source_id in {p.source_id for p in products}:
        snapshot = db.scalar(select(PriceSnapshot).where(PriceSnapshot.tenant_id == user.tenant_id,
            PriceSnapshot.source_id == source_id, PriceSnapshot.date_from <= price_at,
            PriceSnapshot.date_to > price_at).order_by(PriceSnapshot.observed_at.desc(), PriceSnapshot.id.desc()).limit(1))
        if snapshot is None:
            continue
        contexts = [PriceContext.model_validate(c) for c in snapshot.payload['contexts']]
        for product in (p for p in products if p.source_id == source_id):
            result[product.id], conflicts[product.id] = [], []
            identity = snapshot.payload['products'].get(str(product.iiko_product_id))
            if identity != dict(id=str(product.id), unit_id=str(product.unit_id), unit_name=product.unit_name):
                continue
            for point in points:
                external = snapshot.payload['point_links'].get(str(point.id))
                if external != current_links.get(str(point.id)):
                    continue
                applicable = [c for c in contexts if str(c.productId) == str(product.iiko_product_id) and str(c.departmentId) == external]
                resolved = resolve(applicable, price_at)
                if resolved['state'] in {'CONFLICT', 'TIME_DEPENDENT'}:
                    conflicts[product.id].append(point.id)
                price = resolved['price']
                if price is not None:
                    result[product.id].append(dict(department_id=point.id, department_name=point.name,
                        amount=price.price, currency=snapshot.payload['currency'], price_unit=product.unit_name,
                        valid_from=max(price.dateFrom, snapshot.date_from), valid_to=min(price.dateTo, snapshot.date_to),
                        observed_at=snapshot.observed_at))
    return result, conflicts


def price_health(db, user, source_id, points, *, now=None):
    """Safe per-point freshness; execution internals never enter public responses."""
    from app.models.automation import AutomationExecution, ExecutionStatus
    now = now or datetime.now(timezone.utc)
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    attempts = list(db.scalars(select(AutomationExecution).where(
        AutomationExecution.tenant_id == user.tenant_id,
        AutomationExecution.automation_type == 'products.sync_iiko_prices',
        AutomationExecution.payload['source_id'].as_string() == source_id)
        .order_by(AutomationExecution.requested_at.desc(), AutomationExecution.id.desc())))
    result = []
    for point in points:
        snapshot = db.scalar(select(PriceSnapshot.observed_at).where(
            PriceSnapshot.tenant_id == user.tenant_id, PriceSnapshot.source_id == source_id,
            PriceSnapshot.payload['point_links'][str(point.id)].as_string().is_not(None))
            .order_by(PriceSnapshot.observed_at.desc(), PriceSnapshot.id.desc()).limit(1))
        success = utc(snapshot) if snapshot else None
        attempt = next((a for a in attempts if str(point.id) in a.payload.get('confirmed_point_ids', [])), None)
        finished = utc(attempt.finished_at) if attempt and attempt.finished_at else None
        failed = bool(attempt and attempt.status in {ExecutionStatus.FAILED, ExecutionStatus.TIMED_OUT,
            ExecutionStatus.RETRYING} and (success is None or (finished or utc(attempt.requested_at)) > success))
        result.append(dict(department_id=point.id, last_success_at=success,
            stale=success is None or now - success > timedelta(hours=2), update_failed=failed))
    return result


def projection(product, prices, point, manager=False, conflicts=(), health=()):
    return dict(id=product.id, name=product.local_name or product.name, sku=product.sku, unit_name=product.unit_name,
        unit_weight_kg=product.unit_weight_kg, sale_mode=product.sale_mode, sale_status=product.sale_status,
        category_id=product.category_id, category_name=product.category_name, description=product.local_description if product.local_description is not None else product.description,
        observed_at=product.observed_at, source_deleted=product.source_deleted,
        price=next((p for p in prices if p['department_id'] == point), None), prices=prices,
        price_conflict_points=sorted(conflicts, key=str), price_health=list(health),
        description_source='EOS' if product.local_description is not None else 'iiko',
        photo=product.local_photo_hash,
        characteristics=product.characteristics, composition=product.composition, allergens=product.allergens,
        storage=product.storage, training=product.training, version=product.version,
        deleted_at=product.deleted_at, verified_at=product.verified_at,
        verified_by_employee_id=product.verified_by_employee_id, verified_by_name=product.verified_by_name,
        eligible_for_production=eligible_for_production(product),
        allowed_actions=(['RESTORE'] if product.deleted_at else ['EDIT','STATUS','DELETE','VERIFY']) if manager else [])


def catalog(db: Session, user, *, q='', status=None, mode=None, category_id=None,
            department_id=None, price_at: date, offset=0, limit=25, deleted=False, unverified=False):
    points = points_for(db, user)
    if department_id is not None and department_id not in {p.id for p in points}:
        raise HTTPException(404, 'Точка недоступна')
    base = select(Product).where(Product.tenant_id == user.tenant_id, Product.published.is_(True))
    base = base.where(Product.deleted_at.is_not(None) if deleted else Product.deleted_at.is_(None))
    stmt = base
    if unverified:
        stmt = stmt.where(Product.verified_at.is_(None))
    if q.strip():
        # LIKE metacharacters are literal user input.
        escaped = q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        stmt = stmt.where(or_(func.coalesce(Product.local_name, Product.name).ilike(f'%{escaped}%', escape='\\'), Product.sku.ilike(f'%{escaped}%', escape='\\')))
    if status:
        stmt = stmt.where(Product.sale_status == status)
    if mode:
        stmt = stmt.where(Product.sale_mode == mode)
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(db.scalars(stmt.order_by(func.coalesce(Product.local_name, Product.name), Product.id).offset(offset).limit(limit)))
    prices, conflicts = price_rows(db, user, [p.id for p in rows], points, price_at)
    health = {source: price_health(db, user, source, points) for source in {p.source_id for p in rows}}
    category_rows = list(db.scalars(select(SupplyProductCategory).where(
        SupplyProductCategory.tenant_id == user.tenant_id, SupplyProductCategory.is_active.is_(True))
        .order_by(SupplyProductCategory.name)))
    manager = can_manage(db, user)
    active = select(Product).where(Product.tenant_id == user.tenant_id, Product.published.is_(True), Product.deleted_at.is_(None))
    return dict(items=[projection(p, prices[p.id], department_id, manager, conflicts[p.id], health[p.source_id]) for p in rows], total=total,
        offset=offset, limit=limit, points=[dict(id=p.id, name=p.name) for p in points],
        categories=[dict(id=p.id, name=p.name) for p in category_rows],
        observed_at=db.scalar(select(func.min(Product.observed_at)).where(Product.tenant_id == user.tenant_id, Product.published.is_(True))),
        active_count=db.scalar(select(func.count()).select_from(active.subquery())),
        verified_count=db.scalar(select(func.count()).select_from(active.where(Product.verified_at.is_not(None)).subquery())),
        allowed_actions=['ADD'] if manager else [])



def detail(db, user, product_id: UUID, *, department_id, price_at):
    points = points_for(db, user)
    if department_id is not None and department_id not in {p.id for p in points}:
        raise HTTPException(404, 'Точка недоступна')
    product = find_product(db, user, product_id)
    prices, conflicts = price_rows(db, user, [product.id], points, price_at)
    return projection(product, prices[product.id], department_id, can_manage(db, user), conflicts[product.id], price_health(db, user, product.source_id, points))
