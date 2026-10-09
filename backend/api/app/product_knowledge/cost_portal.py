"""Separate RBAC and allowlisted monetary projections, with no request-path iiko I/O."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func
from app.audit.service import record_audit_event
from app.core.authorization import Capability, authorize
from app.core.action_context import ActionContextError
from app.models.product_cost import ProductCostObservation as Observation, ProductCostVerification as Verification
from app.models.sales import SalesSyncState
from app.models.product_knowledge import ProductKnowledgeProduct

from app.product_knowledge.bootstrap import digest
from app.product_knowledge.management import find_product
from app.product_knowledge.cost_calculation import POLICY

# UUID hashes from independent Office article/code/UUID reconciliation evidence.
# An article rename must not silently lift the limited-release exclusion.
EXCLUDED_PRODUCT_KEYS = frozenset({'3bc212001fae4a31', 'e0d033c3e736fcba'})


def excluded_product(product):
    return sha256(str(product.iiko_product_id).encode()).hexdigest()[:16] in EXCLUDED_PRODUCT_KEYS


class CostConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    observation_id: UUID
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    office_ssn: Decimal = Field(ge=0, max_digits=20, decimal_places=2, allow_inf_nan=False)
    estimated: bool = Field(strict=True)
    warehouse_confirmed: bool = Field(default=False, strict=True)
    context_confirmed: bool = Field(strict=True)
    allow_updates: bool = False
    office_evidence: str = Field(min_length=20, max_length=1000)

    @model_validator(mode='after')
    def confirmed(self):
        if not self.context_confirmed or not self.warehouse_confirmed or not self.office_evidence.strip():
            raise ValueError('Подтвердите склады, контекст и независимую сверку iikoOffice')
        return self


def permitted(db, actor):
    try:
        authorize(db,actor,Capability.PRODUCT_COST_READ,write=False)
        return True
    except ActionContextError:
        return False


def utc(value):
    # SQLite test storage loses offset; production uses timestamptz.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def verification_map(db, tenant, rows):
    # A method approval cannot establish the estimation marker of a new
    # stock snapshot. Only the independently confirmed observation is public.
    if not rows:
        return {}
    records = db.scalars(select(Verification).where(Verification.tenant_id == tenant,
        Verification.observation_id.in_({r.id for r in rows})))
    return {v.observation_id: v for v in records}


def projection(row, verification=None, *, detailed=False, now=None, historical=False, excluded=False):
    now = now or datetime.now(timezone.utc)
    current = historical or (utc(row.stock_at) <= now and now-utc(row.stock_at) <= timedelta(hours=2))
    usable = verification is not None and row.status != 'INCOMPLETE' and current and not excluded
    result = row.payload['result']
    context = row.payload['context']
    status = 'VERIFIED' if usable else ('STALE' if not current else ('EXCLUDED' if excluded else row.status))
    notes = {'VERIFIED':'Сверено с iikoOffice', 'UNVERIFIED':'Требует сверки с iikoOffice',
        'INCOMPLETE':'Неполные исходные данные', 'STALE':'Расчёт устарел', 'EXCLUDED':'X3: метод оценки не подтверждён'}
    inputs = row.payload['input']
    root_unit = next((p.get('mainUnit_key') for p in inputs['references'] if p['key'] == inputs['key']),None)
    unit = next((u.get('name') for u in inputs['units'] if u['key'] == root_unit),None)
    body = dict(status=status, amount=result['amount'] if usable else None,
        currency='RUB', unit=unit, method='Расчёт EOS по ТТК',
        source='iiko: ТТК и складской учёт', context=context['context_label'],
        warehouse='Все склады источника' if not context['warehouse_ids'] else f"Выбранные склады: {len(context['warehouse_ids'])}",
        stock_at=row.stock_at, observed_at=row.observed_at,
        estimated=verification.payload['estimated'] if usable else None, note=notes[status])
    if detailed:
        body.update(observation_id=str(row.id), content_hash=row.content_hash, context_key=row.context_hash,
            components=[{k:c.get(k) for k in ('name','quantity','unit','unit_cost','contribution')} for c in result['components']] if usable else [],
            rounding='Цены ингредиентов — до 0,01 ₽; итог — до 0,01 ₽',
            verification_at=verification.confirmed_at if usable else None,
            verification_author=verification.payload.get('author_name') if usable else None,
            historical=historical)
    return body


def latest_rows(db, tenant, product_ids, context_key=None):
    stmt = select(Observation.id,func.row_number().over(partition_by=(Observation.product_id,Observation.context_hash),
        order_by=(Observation.stock_at.desc(),Observation.observed_at.desc(),Observation.id.desc())).label('position')).where(
        Observation.tenant_id == tenant,Observation.product_id.in_(product_ids))
    if context_key:
        stmt = stmt.where(Observation.context_hash == context_key)
    ranked = stmt.subquery()
    return list(db.scalars(select(Observation).where(Observation.id.in_(select(ranked.c.id).where(ranked.c.position == 1)))))


def cost_rows(db, actor, product_ids, *, context_key=None, now=None):
    if not permitted(db,actor):
        return False, {}
    if not product_ids:
        return True, {}
    rows = latest_rows(db,actor.tenant_id,product_ids,context_key)
    chosen, contexts = {}, {}
    for row in rows:
        if context_key and row.context_hash != context_key:
            continue
        contexts.setdefault(row.product_id,set()).add(row.context_hash)
        chosen.setdefault(row.product_id,row)
    verified = verification_map(db,actor.tenant_id,list(chosen.values()))
    excluded_ids = {p.id for p in db.scalars(select(ProductKnowledgeProduct).where(
        ProductKnowledgeProduct.tenant_id == actor.tenant_id, ProductKnowledgeProduct.id.in_(product_ids))) if excluded_product(p)}
    values = {}
    for pid,row in chosen.items():
        if len(contexts[pid]) > 1 and not context_key:
            values[pid] = dict(status='CONTEXT_REQUIRED',amount=None,note='Несколько контекстов · откройте карточку')
        else:
            values[pid] = projection(row,verified.get(row.id),now=now,excluded=pid in excluded_ids)
    return True, values


def detail(db, actor, product_id, *, context_key=None, offset=0, limit=25, now=None, review=False):
    authorize(db,actor,Capability.PRODUCT_COST_READ,write=False)
    product = find_product(db,actor,product_id)
    can_review, can_confirm = False, False
    try:
        authorize(db,actor,Capability.PRODUCT_COST_REVIEW,write=False)
        can_review = True
    except ActionContextError:
        pass
    try:
        authorize(db,actor,Capability.PRODUCT_COST_CONFIRM,write=True)
        can_confirm = True
    except ActionContextError:
        pass
    if review:
        authorize(db,actor,Capability.PRODUCT_COST_REVIEW,write=False)
    rows = latest_rows(db,actor.tenant_id,[product.id])
    choices = {row.context_hash:dict(key=row.context_hash,label=row.payload['context']['context_label'],
        warehouse='Все склады источника' if not row.payload['context']['warehouse_ids'] else 'Выбранные склады') for row in rows}
    if context_key is not None and context_key not in choices:
        raise HTTPException(404,'Контекст недоступен')
    selected = context_key or (next(iter(choices)) if len(choices)==1 else None)
    stmt = select(Observation).where(Observation.tenant_id == actor.tenant_id,
        Observation.product_id == product.id,Observation.source_id == product.source_id,Observation.context_hash == selected)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) if selected else 0
    ordered = stmt.order_by(Observation.stock_at.desc(),Observation.observed_at.desc(),Observation.id.desc())
    current = next((r for r in rows if r.context_hash == selected),None)
    page = list(db.scalars(ordered.offset(offset).limit(limit))) if selected else []
    verified = verification_map(db,actor.tenant_id,[current] + page if current else page)
    preview = None
    if review and current:
        safe = projection(current,detailed=True,now=now,excluded=excluded_product(product))
        valid = safe['status'] != 'STALE' and current.status != 'INCOMPLETE' and current.payload['result']['amount'] is not None
        excluded = excluded_product(product)
        issues = ['Складской контекст требует независимого подтверждения', 'Оценочность требует проверки в iikoOffice']
        risks = current.payload['result']['risks']
        if 'NEGATIVE_STOCK_RATIO' in risks: issues.append('Стоимость использует отрицательные складские остатки')
        if 'ZERO_VALUATION_REQUIRES_REVIEW' in risks: issues.append('Нулевая стоимость ингредиента требует отдельной сверки')
        if excluded: issues.append('X3 исключено из ограниченного выпуска: метод оценки эклера не подтверждён')
        if not valid: issues.append(safe['note'])
        preview = dict(candidate_amount=current.payload['result']['amount'] if valid else None,
            components=[{k:c.get(k) for k in ('name','quantity','unit','unit_cost','contribution')}
                for c in current.payload['result']['components']] if valid else [],
            observation_id=str(current.id),content_hash=current.content_hash,
            quality='EXCLUDED' if excluded else ('REQUIRES_REVIEW' if valid else safe['status']),
            issues=issues,can_confirm=bool(can_confirm and valid and not excluded and current.id not in verified),
            warehouse_ids=current.payload['context']['warehouse_ids'],
            department_id=current.payload['context'].get('department_id'),
            context=safe['context'],warehouse=safe['warehouse'],method='Расчёт EOS по ТТК')
    return dict(can_review=can_review,review=preview,contexts=list(choices.values()),selected_context=selected,
        current=projection(current,verified.get(current.id),detailed=True,now=now,excluded=excluded_product(product)) if current else None,
        history=[projection(row,verified.get(row.id),detailed=True,now=now,historical=True,excluded=excluded_product(product)) for row in page],
        total=total,offset=offset,limit=limit,
        note='Подтверждённых расчётов пока нет' if not rows else ('Выберите контекст расчёта' if selected is None else None))


def confirm(db, actor, product_id, command, *, now=None):
    auth = authorize(db,actor,Capability.PRODUCT_COST_CONFIRM,write=True)
    now = now or datetime.now(timezone.utc)
    product = find_product(db,actor,product_id)
    if excluded_product(product):
        raise HTTPException(409,'Упаковки X3 не допускаются к подтверждению в этом выпуске')
    db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == actor.tenant_id,
        SalesSyncState.source_id == product.source_id).with_for_update())
    row = db.scalar(select(Observation).where(Observation.tenant_id == actor.tenant_id,
        Observation.product_id == product.id, Observation.id == command.observation_id,
        Observation.source_id == product.source_id))
    if row is None:
        raise HTTPException(404,'Расчёт недоступен')
    latest = db.scalar(select(Observation).where(Observation.tenant_id == actor.tenant_id,
        Observation.product_id == product.id, Observation.context_hash == row.context_hash).order_by(
        Observation.stock_at.desc(),Observation.observed_at.desc(),Observation.id.desc()))
    if latest.id != row.id or row.content_hash != command.content_hash or digest(row.payload) != row.content_hash:
        raise HTTPException(409,'Расчёт изменился. Выполните сверку заново')
    if row.status != 'UNVERIFIED' or row.method_hash is None or row.payload.get('method') != POLICY:
        raise HTTPException(409,'Исходных данных недостаточно для подтверждения')
    if row.payload['result']['amount'] is None or Decimal(row.payload['result']['amount']) != command.office_ssn:
        raise HTTPException(409,'ССН расходится с iikoOffice')
    if not (utc(row.stock_at) <= now and now-utc(row.stock_at) <= timedelta(hours=2)):
        raise HTTPException(409,'Расчёт устарел. Сначала обновите данные')
    before = db.scalar(select(Verification).where(Verification.tenant_id == actor.tenant_id,Verification.observation_id == row.id))
    payload = dict(office_ssn=str(command.office_ssn),estimated=command.estimated,allow_updates=command.allow_updates,
        office_evidence=command.office_evidence,warehouse_confirmed=command.warehouse_confirmed,context_hash=row.context_hash,method_hash=row.method_hash,
        author_name=before.payload.get('author_name') if before else actor.display_name)
    if before:
        if before.payload != payload:
            raise HTTPException(409,'Подтверждение уже сохранено с другими параметрами')
        return before
    verification = Verification(tenant_id=actor.tenant_id,observation_id=row.id,confirmed_by_user_id=actor.id,
        confirmed_at=now,payload=payload)
    db.add(verification);db.flush()
    record_audit_event(db,tenant_id=actor.tenant_id,event_type='PRODUCT_COST_VERIFIED',entity_type='ProductCostObservation',
        entity_id=row.id,operation='VERIFY_COST',actor_user=actor,context=auth,source='HUMAN',
        after=dict(verification_id=str(verification.id),allow_updates=command.allow_updates),reason=command.office_evidence)
    return verification
