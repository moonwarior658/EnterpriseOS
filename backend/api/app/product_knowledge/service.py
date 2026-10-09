"""Tenant-scoped DB reads only. Public responses deliberately exclude cost/recipes."""
from datetime import date
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from app.core.authorization import product_knowledge_context
from app.models.employee import EmployeeRole
from app.models.product_knowledge import ProductKnowledgeProduct as Product, ProductKnowledgePrice as Price
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
    prices = list(db.scalars(select(Price).where(Price.tenant_id == user.tenant_id,
        Price.product_id.in_(ids), Price.department_id.in_([p.id for p in points]),
        Price.valid_from <= price_at, Price.valid_to > price_at)))
    names = {p.id: p.name for p in points}
    grouped = {}
    for p in prices:
        grouped.setdefault((p.product_id, p.department_id), []).append(p)
    result = {pid: [] for pid in ids}
    for (pid, point), versions in grouped.items():
        # Fail closed even for legacy/externally introduced overlaps.
        if len(versions) != 1:
            continue
        p = versions[0]
        result[pid].append(dict(department_id=p.department_id, department_name=names[point], amount=p.amount,
            currency=p.currency, price_unit=p.price_unit, valid_from=p.valid_from, valid_to=p.valid_to,
            observed_at=p.observed_at))
    for entries in result.values():
        entries.sort(key=lambda x: (x['department_name'], str(x['department_id'])))
    return result


def projection(product, prices, point, manager=False):
    return dict(id=product.id, name=product.local_name or product.name, sku=product.sku, unit_name=product.unit_name,
        unit_weight_kg=product.unit_weight_kg, sale_mode=product.sale_mode, sale_status=product.sale_status,
        category_id=product.category_id, category_name=product.category_name, description=product.local_description if product.local_description is not None else product.description,
        observed_at=product.observed_at, source_deleted=product.source_deleted,
        price=next((p for p in prices if p['department_id'] == point), None), prices=prices,
        description_source='EOS' if product.local_description is not None else 'iiko',
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
    prices = price_rows(db, user, [p.id for p in rows], points, price_at)
    category_rows = list(db.scalars(select(SupplyProductCategory).where(
        SupplyProductCategory.tenant_id == user.tenant_id, SupplyProductCategory.is_active.is_(True))
        .order_by(SupplyProductCategory.name)))
    manager = can_manage(db, user)
    active = select(Product).where(Product.tenant_id == user.tenant_id, Product.published.is_(True), Product.deleted_at.is_(None))
    return dict(items=[projection(p, prices[p.id], department_id, manager) for p in rows], total=total,
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
    prices = price_rows(db, user, [product.id], points, price_at)
    return projection(product, prices[product.id], department_id, can_manage(db, user))
