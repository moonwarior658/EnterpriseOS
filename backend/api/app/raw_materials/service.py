"""DB-only material projections; purchase facts come from immutable EOS snapshots."""
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func, or_
from app.audit.service import record_audit_event
from app.core.authorization import Capability, authorize
from app.core.action_context import ActionContextError
from app.models.raw_material import RawMaterialProfile as Profile, MaterialSpecificationVersion as Specification, MaterialSpecificationApproval as Approval
from app.models.supply import SupplyProduct as Product, SupplyProductAlias as Alias, SupplyProductSupplier as Relation, SupplySupplier as Supplier, SupplyProductCategory as Category
from app.models.iiko import IikoUnitMapping
from app.models.audit import AuditEvent
from app.models.user import User
from app.product_knowledge import media
from app.product_knowledge.bootstrap import digest
from app.schemas.raw_materials import Knowledge
from app.raw_materials import standards

READ = Capability.MATERIAL_KNOWLEDGE_READ
EDIT = Capability.MATERIAL_KNOWLEDGE_EDIT
CONFIRM = Capability.MATERIAL_KNOWLEDGE_CONFIRM
MONEY = Capability.MATERIAL_PURCHASE_READ
ENTITY = 'RawMaterialProfile'


def permitted(db, actor, capability):
    try:
        authorize(db, actor, capability, write=capability in (EDIT, CONFIRM, Capability.MATERIAL_PURCHASE_REFRESH, Capability.MATERIAL_DOCUMENT_ADMIT))
        return True
    except ActionContextError:
        return False


def permissions(db, actor):
    authorize(db, actor, READ)
    return dict(admit=permitted(db, actor, Capability.MATERIAL_DOCUMENT_ADMIT), edit=permitted(db, actor, EDIT), confirm=permitted(db, actor, CONFIRM), money=permitted(db, actor, MONEY), refresh=permitted(db, actor, Capability.MATERIAL_PURCHASE_REFRESH))


def find(db, actor, product_id, *, lock=False):
    stmt = select(Profile).where(Profile.tenant_id == actor.tenant_id, Profile.product_id == product_id)
    profile = db.scalar(stmt.with_for_update() if lock else stmt)
    if profile is None:
        raise HTTPException(404, 'Карточка сырья не найдена')
    product = db.scalar(select(Product).where(Product.id == product_id, Product.tenant_id == actor.tenant_id))
    return profile, product


def latest(db, profile, *, confirmed=False):
    stmt = select(Specification).where(Specification.tenant_id == profile.tenant_id, Specification.product_id == profile.product_id)
    if confirmed:
        stmt = stmt.join(Approval, Approval.specification_id == Specification.id)
    return db.scalar(stmt.order_by(Specification.revision.desc()).limit(1))


def version_read(db, row):
    if row is None:
        return None
    approval = db.scalar(select(Approval).where(Approval.tenant_id == row.tenant_id, Approval.specification_id == row.id))
    creator = db.scalar(select(User.display_name).where(User.id == row.created_by_user_id, User.tenant_id == row.tenant_id))
    approver = db.scalar(select(User.display_name).where(User.id == approval.confirmed_by_user_id, User.tenant_id == row.tenant_id)) if approval else None
    # Whitelist even historical storage: a future/injected monetary payload never leaks.
    payload = standards.safe_knowledge(row.payload)
    return dict(id=row.id, revision=row.revision, content_hash=row.content_hash, knowledge=payload,
                status='CONFIRMED' if approval else 'DRAFT', created_at=row.created_at, author=creator,
                confirmed_at=approval.confirmed_at if approval else None, approver=approver,
                primary_product_id=approval.primary_product_id if approval else None)


def suppliers(db, tenant, product_id):
    rows = db.execute(select(Relation, Supplier).join(Supplier, (Relation.supplier_id == Supplier.id) & (Relation.tenant_id == Supplier.tenant_id)).where(
        Relation.tenant_id == tenant, Relation.product_id == product_id, Relation.is_active.is_(True)).order_by(Relation.priority, Relation.id)).all()
    # Do not serialize ORM relations: they contain offer prices and historical prices.
    return [dict(id=s.id, name=s.display_name, role=r.role, priority=r.priority,
                 available=r.is_available and s.is_active, supplier_active=s.is_active) for r, s in rows]


def projection(db, profile, product, rights):
    verified = latest(db, profile, confirmed=True)
    unit = db.scalar(select(IikoUnitMapping).where(IikoUnitMapping.tenant_id == profile.tenant_id,
        IikoUnitMapping.eos_unit_id == product.default_unit_id, IikoUnitMapping.status == 'CONFIRMED', IikoUnitMapping.is_deleted.is_(False)))
    assigned = suppliers(db, profile.tenant_id, product.id)
    primary = next((s for s in assigned if s['role'] == 'PRIMARY'), None)
    backups = [s for s in assigned if s['role'] == 'BACKUP']
    backup = backups[0] if backups else None
    ambiguous = bool(backup and len([s for s in backups if s['priority'] == backup['priority']]) > 1)
    weight = verified.payload.get('unit_weight_kg') if verified else None
    body = dict(id=product.id, name=product.name, kind=profile.kind, archived=profile.archived,
        supply_active=product.is_active, category_id=product.category_id, version=profile.version,
        unit=unit.source_name if unit else None, unit_id=unit.iiko_unit_id if unit else None,
        unit_weight_kg=weight, photo_hash=profile.photo_hash, primary_supplier=primary,
        backup_supplier=backup, backup_ambiguous=ambiguous, suppliers=assigned,
        purchase_access=rights['money'], monthly_consumption=dict(status='NO_DATA', quantity=None),
        allowed_actions=(['DOCUMENT_ADMIT'] if rights.get('admit') else []) + ([ 'EDIT', 'PHOTO', 'ARCHIVE' ] if rights['edit'] else []) + (['CONFIRM'] if rights['confirm'] else []) + (['METRICS_REFRESH'] if rights['refresh'] and not profile.archived and product.is_active else []))
    from app.raw_materials.purchase_refresh import latest_snapshot, analytics_summary
    metric_row = latest_snapshot(db, profile.tenant_id, product.id)
    body['monthly_consumption'] = analytics_summary(metric_row, 'usage')
    if rights['money']:
        from app.raw_materials.purchase_refresh import summary
        current = summary(db, profile.tenant_id, product.id)
        body.update(last_purchase_price=current, six_month_average=current.get('six_month_average', analytics_summary(metric_row, 'average')), tax_basis='WITH_VAT')
    return body


def catalog(db, actor, *, q='', kind=None, archived=False, category_id=None, supplier_id=None, without_supplier=False, state=None, sort='name', direction='asc', offset=0, limit=25):
    rights = permissions(db, actor)
    from app.raw_materials import catalog_sort
    if sort not in catalog_sort.FIELDS or direction not in ('asc', 'desc'):
        raise HTTPException(422, 'Неизвестная сортировка')
    if sort in catalog_sort.MONEY and not rights['money']:
        raise HTTPException(403, 'Нет доступа к закупочным ценам')
    stmt = select(Profile, Product).join(Product, (Product.id == Profile.product_id) & (Product.tenant_id == Profile.tenant_id)).where(Profile.tenant_id == actor.tenant_id, Profile.archived == archived)
    if q:
        pattern = '%' + q.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions = [Product.normalized_name.like(pattern, escape='\\'), Product.id.in_(select(Alias.product_id).where(Alias.tenant_id == actor.tenant_id, Alias.status == 'APPROVED', Alias.normalized_alias.like(pattern, escape='\\')))]
        try:
            conditions.append(Product.id == UUID(q))
        except ValueError:
            pass
        stmt = stmt.where(or_(*conditions))
    if kind:
        stmt = stmt.where(Profile.kind == kind)
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    related = select(Relation.product_id).where(Relation.tenant_id == actor.tenant_id, Relation.is_active.is_(True))
    if supplier_id:
        stmt = stmt.where(Product.id.in_(related.where(Relation.supplier_id == supplier_id)))
    if without_supplier:
        stmt = stmt.where(Product.id.not_in(related))
    if state:
        has_approved = select(Approval.product_id).where(Approval.tenant_id == actor.tenant_id)
        stmt = stmt.where(Product.id.in_(has_approved) if state == 'CONFIRMED' else Product.id.not_in(has_approved))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    if sort == 'name':
        order = Product.normalized_name.desc() if direction == 'desc' else Product.normalized_name.asc()
        rows = db.execute(stmt.order_by(order, Product.id).offset(offset).limit(limit)).all()
        items = [projection(db, p, product, rights) for p, product in rows]
    else:
        # Sort saved, permission-filtered projections globally. In particular, the
        # current admission policy must also apply to prices used for ordering.
        rows = db.execute(stmt).all()
        items = catalog_sort.ordered([projection(db, p, product, rights) for p, product in rows], sort, direction == 'desc')[offset:offset + limit]
    return dict(items=items, total=total, offset=offset, limit=limit,
                can_enroll=rights['edit'], purchase_access=rights['money'], suppliers=[dict(id=s.id, name=s.display_name) for s in db.scalars(select(Supplier).where(Supplier.tenant_id == actor.tenant_id).order_by(Supplier.display_name))], categories=[dict(id=c.id, name=c.name) for c in db.scalars(select(Category).where(Category.tenant_id == actor.tenant_id).order_by(Category.name))])


def candidates(db, actor, *, q='', offset=0, limit=25):
    authorize(db, actor, EDIT, write=True)
    stmt = select(Product).where(Product.tenant_id == actor.tenant_id, Product.is_active.is_(True), Product.id.not_in(select(Profile.product_id).where(Profile.tenant_id == actor.tenant_id)))
    if q:
        pattern = '%' + q.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        conditions = [Product.normalized_name.like(pattern, escape='\\')]
        try:
            conditions.append(Product.id == UUID(q))
        except ValueError:
            pass
        stmt = stmt.where(or_(*conditions))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return dict(items=[dict(id=p.id, name=p.name) for p in db.scalars(stmt.order_by(Product.normalized_name, Product.id).offset(offset).limit(limit))], total=total, offset=offset, limit=limit)


def detail(db, actor, product_id):
    rights = permissions(db, actor)
    profile, product = find(db, actor, product_id)
    body = projection(db, profile, product, rights)
    confirmed = latest(db, profile, confirmed=True)
    approved = standards.products(db, actor.tenant_id, confirmed)
    selection = db.scalar(select(AuditEvent).where(AuditEvent.tenant_id==actor.tenant_id, AuditEvent.entity_type==ENTITY, AuditEvent.entity_id==str(product_id), AuditEvent.operation=='RESERVE_SELECTED').order_by(AuditEvent.occurred_at.desc(),AuditEvent.id.desc()).limit(1))
    selected = selection.after.get('selected_reserve_product_id') if selection and confirmed and selection.after.get('specification_id')==str(confirmed.id) else None
    body.update(current=version_read(db, confirmed), latest=version_read(db, latest(db, profile)),
        approved_products=approved, reserves=[p for p in approved if p['role']=='RESERVE'], reserves_status='APPROVED' if approved else 'NOT_APPROVED', selected_reserve_product_id=selected)
    return body


def audit(db, actor, auth, profile, operation, *, before=None, after=None, reason):
    record_audit_event(db, tenant_id=actor.tenant_id, event_type='MATERIAL_' + operation,
        entity_type=ENTITY, entity_id=profile.product_id, operation=operation, actor_user=actor,
        context=auth, before=before, after=after, reason=reason)


def enroll(db, actor, command):
    auth = authorize(db, actor, EDIT, write=True)
    product = db.scalar(select(Product).where(Product.tenant_id == actor.tenant_id, Product.id == command.product_id).with_for_update())
    if product is None:
        raise HTTPException(404, 'Товар Supply не найден')
    profile = db.get(Profile, product.id)
    if profile:
        if profile.tenant_id != actor.tenant_id:
            raise HTTPException(404, 'Товар Supply не найден')
        if profile.kind != command.kind:
            raise HTTPException(409, 'Товар уже включён с другим видом')
        return detail(db, actor, product.id)
    if not product.is_active:
        raise HTTPException(409, 'Товар Supply архивирован')
    profile = Profile(tenant_id=actor.tenant_id, product_id=product.id, kind=command.kind, version=1, archived=False, created_by_user_id=actor.id)
    db.add(profile); db.flush()
    audit(db, actor, auth, profile, 'ENROLLED', after=dict(kind=profile.kind), reason=command.reason)
    return detail(db, actor, product.id)


def editable(db, actor, product_id, command, capability=EDIT, *, allow_archived=False):
    auth = authorize(db, actor, capability, write=True)
    profile, product = find(db, actor, product_id, lock=True)
    if profile.version != command.expected_version:
        raise HTTPException(409, 'Карточка изменена. Обновите её и повторите действие')
    if not allow_archived and (profile.archived or not product.is_active):
        raise HTTPException(409, 'Сначала восстановите карточку и товар Supply')
    return auth, profile, product


def save(db, actor, product_id, command):
    auth, profile, product = editable(db, actor, product_id, command)
    previous = latest(db, profile)
    standards.validate(db, actor.tenant_id, product, command.knowledge)
    payload = command.knowledge.model_dump(mode='json')
    row = Specification(tenant_id=actor.tenant_id, product_id=product.id, revision=previous.revision + 1 if previous else 1,
        payload=payload, content_hash=digest(payload), created_by_user_id=actor.id)
    db.add(row); db.flush(); standards.save_links(db, row, command.knowledge); db.flush(); profile.version += 1
    audit(db, actor, auth, profile, 'DRAFT_SAVED', after=dict(specification_id=str(row.id), revision=row.revision, content_hash=row.content_hash), reason=command.reason)
    db.flush()
    return detail(db, actor, product_id)


def confirm(db, actor, product_id, command):
    auth, profile, product = editable(db, actor, product_id, command, CONFIRM)
    row = latest(db, profile)
    if row is None or row.id != command.specification_id or row.content_hash != command.content_hash or digest(row.payload) != command.content_hash:
        raise HTTPException(409, 'Черновик изменён. Повторите проверку')
    knowledge = Knowledge.model_validate(row.payload)
    standards.validate(db, actor.tenant_id, product, knowledge)
    primary = standards.primary(knowledge, product.id)
    if command.primary_product_id != primary:
        raise HTTPException(409, 'Основной товар должен совпадать с утверждаемой спецификацией')
    manufacturer = next((p.manufacturer for p in knowledge.approved_products if p.role=='PRIMARY'),knowledge.manufacturer)
    required = standards.OWNER_STANDARDS.get(str(product.id))
    if required and manufacturer != required:
        if not command.owner_standard_override or str(auth.authorized_as) != 'ADMIN':
            raise HTTPException(409, 'Изменение стандарта производителя требует отдельного решения владельца')
    if db.scalar(select(Approval.id).where(Approval.specification_id == row.id)):
        raise HTTPException(409, 'Версия уже подтверждена')
    db.add(Approval(tenant_id=actor.tenant_id, product_id=product.id, specification_id=row.id,
        primary_product_id=primary, confirmed_by_user_id=actor.id))
    profile.version += 1
    audit(db, actor, auth, profile, 'CONFIRMED', after=dict(specification_id=str(row.id), revision=row.revision, content_hash=row.content_hash, primary_product_id=str(primary), owner_standard_override=command.owner_standard_override), reason=command.reason)
    db.flush()
    return detail(db, actor, product_id)


def archive(db, actor, product_id, command):
    auth, profile, _ = editable(db, actor, product_id, command, allow_archived=True)
    old = profile.archived
    profile.archived = command.archived; profile.version += 1
    audit(db, actor, auth, profile, 'ARCHIVED' if command.archived else 'RESTORED', before=dict(archived=old), after=dict(archived=profile.archived), reason=command.reason)
    db.flush()
    return detail(db, actor, product_id)


def history(db, actor, product_id, *, offset=0, limit=25):
    authorize(db, actor, READ)
    profile, _ = find(db, actor, product_id)
    versions = select(Specification).where(Specification.tenant_id == actor.tenant_id, Specification.product_id == product_id)
    events = select(AuditEvent).where(AuditEvent.tenant_id == actor.tenant_id, AuditEvent.entity_type == ENTITY, AuditEvent.entity_id == str(product_id))
    safe_keys = {'kind', 'archived', 'photo_hash', 'specification_id', 'revision', 'content_hash', 'primary_product_id', 'selected_reserve_product_id', 'owner_standard_override'}
    def safe_state(value):
        return {k:v for k,v in (value or {}).items() if k in safe_keys}
    return dict(versions=[version_read(db, r) for r in db.scalars(versions.order_by(Specification.revision.desc()).offset(offset).limit(limit))],
        total=db.scalar(select(func.count()).select_from(versions.subquery())),
        events=[dict(id=e.id, operation=e.operation, occurred_at=e.occurred_at, author=e.actor_name_snapshot,
                     reason=e.reason, before=safe_state(e.before), after=safe_state(e.after)) for e in db.scalars(events.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit))],
        event_total=db.scalar(select(func.count()).select_from(events.subquery())), offset=offset, limit=limit)


def photo(db, actor, product_id, command, root, *, content=None, content_type=None):
    auth, profile, _ = editable(db, actor, product_id, command)
    cleaned = media.normalize(content, content_type) if content is not None else None
    photo_hash = sha256(cleaned).hexdigest() if cleaned is not None else None
    if cleaned is not None:
        try:
            media.store(media.blob_path(root, SimpleNamespace(id=product_id), photo_hash), cleaned)
        except OSError as error:
            raise HTTPException(503, 'Не удалось сохранить фотографию') from error
    old = profile.photo_hash
    profile.photo_hash = photo_hash; profile.version += 1
    audit(db, actor, auth, profile, 'PHOTO_UPLOADED' if content is not None else 'PHOTO_REMOVED', before=dict(photo_hash=old), after=dict(photo_hash=photo_hash), reason=command.reason)
    db.flush()
    return detail(db, actor, product_id)


def read_photo(db, actor, product_id, root, photo_hash=None):
    authorize(db, actor, READ)
    profile, _ = find(db, actor, product_id)
    wanted = photo_hash or profile.photo_hash
    if wanted != profile.photo_hash:
        events = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == actor.tenant_id, AuditEvent.entity_type == ENTITY, AuditEvent.entity_id == str(product_id), AuditEvent.operation.in_(['PHOTO_UPLOADED','PHOTO_REMOVED'])))
        if not any(wanted in ((e.before or {}).get('photo_hash'), (e.after or {}).get('photo_hash')) for e in events):
            raise HTTPException(404, 'Фотография не найдена')
    path = media.blob_path(root, SimpleNamespace(id=product_id), wanted)
    if not path.is_file():
        raise HTTPException(404, 'Фотография не найдена')
    return path


def select_reserve(db, actor, product_id, command):
    auth, profile, product = editable(db, actor, product_id, command)
    row = latest(db, profile, confirmed=True)
    if row is None or row.id != command.specification_id:
        raise HTTPException(409,'Утверждённая спецификация изменилась')
    allowed = [p for p in standards.products(db, actor.tenant_id, row) if p['role']=='RESERVE' and p['product_id']==str(command.target_product_id)]
    target=db.scalar(select(Product).where(Product.id==command.target_product_id,Product.tenant_id==actor.tenant_id,Product.is_active.is_(True)))
    if not allowed or target is None:raise HTTPException(409,'Выберите активный резерв из утверждённого списка')
    audit(db, actor, auth, profile, 'RESERVE_SELECTED',after=dict(specification_id=str(row.id),selected_reserve_product_id=str(target.id)),reason=command.reason)
    profile.version += 1;db.flush()
    return detail(db,actor,product_id)
