"""Version-bound standards. Reserve selection is knowledge only; no Supply mutation."""
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from app.models.iiko import IikoUnitMapping, IikoSupplierMapping
from app.models.raw_material import MaterialProductAllowance, MaterialUnitConversion
from app.models.supply import SupplyProduct
from app.schemas.raw_materials import Knowledge, ApprovedProduct, UnitConversion

OWNER_STANDARDS={'21fe689f-a2d0-41d4-8c6a-29b73b24e01f':'БМК','be7c1ced-755e-4fa3-b7e9-cc7851c3c07d':'Ларица'}


def safe_knowledge(payload):
    result={k:v for k,v in payload.items() if k in Knowledge.model_fields}
    for key, model in (('approved_products',ApprovedProduct),('conversions',UnitConversion)):
        if key in result:
            result[key]=[{k:v for k,v in item.items() if k in model.model_fields} for item in result[key] if isinstance(item,dict)]
    return result


def validate(db, tenant, product, knowledge):
    if knowledge.allowed_manufacturers and any(p.manufacturer not in knowledge.allowed_manufacturers for p in knowledge.approved_products):
        raise HTTPException(409,'Производитель товара отсутствует в разрешённом списке')
    targets=[p.product_id for p in knowledge.approved_products]
    existing=set(db.scalars(select(SupplyProduct.id).where(SupplyProduct.tenant_id==tenant,SupplyProduct.id.in_(targets),SupplyProduct.is_active.is_(True)))) if targets else set()
    if set(targets)!=existing:raise HTTPException(409,'Выберите существующие активные товары того же контура')
    units=set(db.scalars(select(IikoUnitMapping.iiko_unit_id).where(IikoUnitMapping.tenant_id==tenant,IikoUnitMapping.status=='CONFIRMED',IikoUnitMapping.is_deleted.is_(False))))
    base=db.scalar(select(IikoUnitMapping.iiko_unit_id).where(IikoUnitMapping.tenant_id==tenant,IikoUnitMapping.eos_unit_id==product.default_unit_id,IikoUnitMapping.status=='CONFIRMED',IikoUnitMapping.is_deleted.is_(False)))
    if knowledge.package_unit_id and knowledge.package_unit_id not in units:raise HTTPException(409,'Единица упаковки не подтверждена в iiko')
    for c in knowledge.conversions:
        if c.from_unit_id not in units or c.to_unit_id != base:raise HTTPException(409,'Пересчёт должен вести напрямую в подтверждённую учётную единицу iiko')
        known=db.scalar(select(IikoSupplierMapping.id).where(IikoSupplierMapping.tenant_id==tenant,IikoSupplierMapping.iiko_supplier_id==c.supplier_iiko_id,IikoSupplierMapping.status=='CONFIRMED',IikoSupplierMapping.iiko_supplier_deleted.is_(False)))
        if known is None:raise HTTPException(409,'Поставщик пересчёта не подтверждён в Supply')


def save_links(db, row, knowledge):
    for p in knowledge.approved_products:
        db.add(MaterialProductAllowance(tenant_id=row.tenant_id,product_id=row.product_id,specification_id=row.id,target_product_id=p.product_id,role=p.role))
    for c in knowledge.conversions:
        fields=c.model_dump(exclude={'packaging','evidence'})
        db.add(MaterialUnitConversion(tenant_id=row.tenant_id,product_id=row.product_id,specification_id=row.id,**fields))


def primary(knowledge, fallback):
    if not knowledge.approved_products:return fallback
    rows=[p.product_id for p in knowledge.approved_products if p.role=='PRIMARY']
    if len(rows)!=1:raise HTTPException(409,'Утвердите ровно один основной товар')
    return rows[0]


def products(db, tenant, row):
    if row is None:return []
    items=Knowledge.model_validate(safe_knowledge(row.payload)).approved_products
    names={p.id:p.name for p in db.scalars(select(SupplyProduct).where(SupplyProduct.tenant_id==tenant,SupplyProduct.id.in_([i.product_id for i in items])))} if items else {}
    return [dict(**i.model_dump(mode='json'),name=names.get(i.product_id,'Товар недоступен')) for i in items]


def options(db, actor, product_id, *, q=''):
    from app.raw_materials import service
    from app.core.authorization import authorize
    authorize(db,actor,service.EDIT,write=True);service.find(db,actor,product_id)
    stmt=select(SupplyProduct).where(SupplyProduct.tenant_id==actor.tenant_id,SupplyProduct.is_active.is_(True))
    if q:
        pattern='%'+q.lower().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        stmt=stmt.where(SupplyProduct.normalized_name.like(pattern,escape='\\'))
    return dict(products=[dict(id=p.id,name=p.name) for p in db.scalars(stmt.order_by(SupplyProduct.normalized_name,SupplyProduct.id).limit(100))],
        units=[dict(id=u.iiko_unit_id,name=u.source_name) for u in db.scalars(select(IikoUnitMapping).where(IikoUnitMapping.tenant_id==actor.tenant_id,IikoUnitMapping.status=='CONFIRMED',IikoUnitMapping.is_deleted.is_(False)))],
        suppliers=[dict(id=s.iiko_supplier_id,name=s.iiko_supplier_name) for s in db.scalars(select(IikoSupplierMapping).where(IikoSupplierMapping.tenant_id==actor.tenant_id,IikoSupplierMapping.status=='CONFIRMED',IikoSupplierMapping.iiko_supplier_deleted.is_(False)))])
