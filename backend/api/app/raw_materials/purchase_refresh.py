"""Manual Core command, bounded read-only collection and lease-guarded publication."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from app.audit.service import record_audit_event
from app.automation.dispatch import create_automation_execution
from app.core.authorization import authorize, Capability
from app.core.config import settings
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import get_iiko_settings
from app.models.audit import AuditEvent
from app.models.automation import AutomationExecution as Execution, ExecutionStatus
from app.models.iiko import IikoProductMapping, IikoUnitMapping
from app.models.raw_material import MaterialPurchaseSnapshot as Snapshot
from app.product_knowledge.bootstrap import digest
from app.raw_materials import service
from app.raw_materials.purchases import SOURCE, WAREHOUSE, POLICY, windows, parse_export, evaluate
from app.sales.sync import source_identity

ACTION = 'materials.sync_iiko_purchase_price'
ACTIVE = {ExecutionStatus.PENDING, ExecutionStatus.DISPATCHING, ExecutionStatus.RUNNING, ExecutionStatus.RETRYING}
PROGRESS = {'pending':'Ожидает обновления','dispatching':'Начинаем обновление','running':'Получаем данные из iiko',
    'retrying':'Повторяем попытку обновления','succeeded':'Обновление завершено',
    'failed':'Не удалось обновить. Сохранённая история доступна','timed_out':'Время ожидания истекло. Сохранённая история доступна','cancelled':'Обновление отменено'}
REASONS = {'UNIT_MISMATCH':'Единицы прихода и учёта несовместимы', 'CONTAINER_UNCONFIRMED':'Пересчёт упаковки не подтверждён',
    'SUPPLIER_UNCONFIRMED':'Внешняя природа контрагента не подтверждена', 'CURRENCY_MISMATCH':'Валюта документа не подтверждена',
    'MIXED_UNITS_BLOCKED':'В периоде есть несовместимые единицы; исторический пересчёт не подтверждён',
    'TAX_UNCONFIRMED':'Налоговая база документа не подтверждена', 'AMOUNT_UNCONFIRMED':'Количество или сумма требуют проверки',
    'LATEST_DOCUMENT_CONFLICT':'В последнюю дату есть несколько накладных', 'DOCUMENT_REVISION_CONFLICT':'Выгрузки документа различаются',
    'LINE_IDENTITY_CONFLICT':'Строки документа не имеют однозначной идентификации', 'WAREHOUSE_UNCONFIRMED':'Склад строки не подтверждён',
    'DATE_UNCONFIRMED':'Дата прихода не подтверждена', 'UNCONFIRMED_DOCUMENT':'Проведение документа не подтверждено',
    'ADDITIONAL_EXPENSE':'Строка содержит дополнительные расходы', 'NO_PURCHASE_IN_WINDOW':'В выбранном периоде закупок не найдено'}


class RefreshCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID


class RefreshPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: UUID
    source_id: str
    mapping: dict


def scope(db, tenant, product_id):
    from types import SimpleNamespace
    profile, product = service.find(db, SimpleNamespace(tenant_id=tenant), product_id, lock=True)
    if profile.archived or not product.is_active:
        raise HTTPException(409, 'Обновление архивной карточки недоступно')
    mappings = list(db.scalars(select(IikoProductMapping).where(IikoProductMapping.tenant_id == tenant,
        IikoProductMapping.eos_product_id == product_id, IikoProductMapping.status == 'CONFIRMED', IikoProductMapping.is_deleted.is_(False))))
    units = list(db.scalars(select(IikoUnitMapping).where(IikoUnitMapping.tenant_id == tenant,
        IikoUnitMapping.eos_unit_id == product.default_unit_id, IikoUnitMapping.status == 'CONFIRMED', IikoUnitMapping.is_deleted.is_(False))))
    if len(mappings) != 1 or len(units) != 1 or mappings[0].source_unit_id != units[0].iiko_unit_id:
        raise HTTPException(409, 'Сначала подтвердите UUID товара и учётную единицу iiko в Supply')
    mapping, unit = mappings[0], units[0]
    return dict(iiko_product_id=str(mapping.iiko_product_id), unit_id=str(unit.iiko_unit_id), unit=unit.source_name,
        mapping_id=str(mapping.id), mapping_updated_at=str(mapping.updated_at), unit_mapping_id=str(unit.id), unit_updated_at=str(unit.updated_at))


def attempts(db, tenant, product_id):
    return select(Execution).where(Execution.tenant_id == tenant, Execution.automation_type == ACTION,
        Execution.payload['product_id'].as_string() == str(product_id)).order_by(Execution.requested_at.desc(), Execution.execution_id.desc())


def progress(row):
    return None if row is None else dict(status=row.status, label=PROGRESS.get(row.status, 'Обновление недоступно'),
        active=row.status in ACTIVE, requested_at=row.requested_at, finished_at=row.finished_at)


def refresh(db, actor, product_id, command):
    context = authorize(db, actor, Capability.MATERIAL_PURCHASE_REFRESH, write=True)
    mapping = scope(db, actor.tenant_id, product_id)  # profile lock serializes competing human commands
    prior = db.scalar(select(AuditEvent).where(AuditEvent.tenant_id == actor.tenant_id,
        AuditEvent.entity_type == 'MaterialPurchaseRefresh', AuditEvent.correlation_id == str(command.request_id)))
    if prior:
        if prior.entity_id != str(product_id): raise HTTPException(409, 'Запрос уже использован для другой карточки')
        return progress(db.scalar(select(Execution).where(Execution.tenant_id == actor.tenant_id, Execution.execution_id == UUID(prior.after['execution_id']))))
    row = db.scalar(attempts(db, actor.tenant_id, product_id).where(Execution.status.in_(ACTIVE)).limit(1))
    if row is None:
        payload = RefreshPayload(product_id=product_id, source_id=SOURCE, mapping=mapping)
        row = create_automation_execution(db, automation_type=ACTION, tenant_id=actor.tenant_id,
            scope_type='company', scope_id=None, recipients=[], payload=payload.model_dump(mode='json'))
    record_audit_event(db, tenant_id=actor.tenant_id, entity_type='MaterialPurchaseRefresh', entity_id=product_id,
        event_type='MATERIAL_PURCHASE_REFRESH_REQUESTED', operation='REFRESH_PURCHASE', actor_user=actor, context=context,
        after=dict(execution_id=str(row.execution_id)), reason='Ручное обновление закупочной цены', correlation_id=str(command.request_id))
    db.flush()
    return progress(row)


async def collect(session_factory, *, tenant_id, payload, now):
    config = get_iiko_settings()
    if payload.source_id != SOURCE or source_identity(config) != SOURCE:
        raise ValueError('MATERIAL_PURCHASE_SOURCE_MISMATCH')
    with session_factory() as db:
        if scope(db, tenant_id, payload.product_id) != payload.mapping:
            raise ValueError('MATERIAL_PURCHASE_SCOPE_CHANGED')
    today = now.astimezone(ZoneInfo(settings.business_timezone)).date()
    bounds = list(windows(today))
    documents, manifest = [], []
    async with IikoServerClient(config) as client:
        products = {str(p.dto.external_id): p.dto for p in await client.get_products()}
        unit_names = {str(u.dto.external_id): u.dto.name for u in await client.get_units()}
        mapped = products.get(payload.mapping['iiko_product_id'])
        if mapped is None or mapped.is_deleted or str(mapped.base_unit_external_id) != payload.mapping['unit_id'] or unit_names.get(payload.mapping['unit_id']) != payload.mapping['unit']:
            raise ValueError('MATERIAL_PURCHASE_REFERENCE_CHANGED')
        suppliers = {str(s.external_id): s.model_dump(mode='json') for s in await client.get_suppliers()}
        for start, end in bounds:
            # incomingInvoice's inclusive to is converted from the canonical half-open window.
            xml = await client.get_raw_material_invoice_export(date_from=start, date_to=end - timedelta(days=1))
            rows = parse_export(xml)
            manifest.append(dict(date_from=start.isoformat(), date_to=end.isoformat(), documents=len(rows),
                hash=digest(rows), fetched_at=datetime.now(timezone.utc).isoformat()))
            documents.extend(rows)
    relevant = [d for d in documents if any(i.get('product') == payload.mapping['iiko_product_id'] for i in d['items'])]
    result = evaluate(relevant, suppliers, payload.mapping, date_from=bounds[0][0].isoformat(), date_to=bounds[-1][1].isoformat(), units=unit_names)
    return dict(product_id=str(payload.product_id), source_id=SOURCE, mapping=payload.mapping, policy=POLICY,
        observed_at=datetime.now(timezone.utc).isoformat(), manifest=manifest, result=result)


def publish(db, tenant, snapshot, *, execution_id):
    if snapshot['source_id'] != SOURCE or scope(db, tenant, UUID(snapshot['product_id'])) != snapshot['mapping']:
        raise ValueError('MATERIAL_PURCHASE_SCOPE_CHANGED')
    execution = db.scalar(select(Execution).where(Execution.execution_id == execution_id, Execution.tenant_id == tenant, Execution.automation_type == ACTION))
    if execution is None or execution.payload.get('product_id') != snapshot['product_id']:
        raise ValueError('MATERIAL_PURCHASE_EXECUTION_SCOPE')
    existing = db.scalar(select(Snapshot).where(Snapshot.tenant_id == tenant, Snapshot.product_id == UUID(snapshot['product_id']), Snapshot.execution_id == execution_id))
    if existing: return dict(snapshot_id=str(existing.id), quality=existing.status)
    result = snapshot['result']
    row = Snapshot(tenant_id=tenant, product_id=UUID(snapshot['product_id']), execution_id=execution_id,
        source_id=SOURCE, status=result['status'], amount=result['amount'], observed_at=datetime.fromisoformat(snapshot['observed_at']),
        content_hash=digest(snapshot), payload=snapshot)
    db.add(row); db.flush()
    record_audit_event(db, tenant_id=tenant, entity_type='MaterialPurchaseSnapshot', entity_id=row.id,
        event_type='MATERIAL_PURCHASE_OBSERVED', operation='OBSERVE_PURCHASE', source='SYSTEM',
        after=dict(content_hash=row.content_hash, quality=row.status), reason='Получены документные факты iiko', correlation_id=str(execution_id))
    return dict(snapshot_id=str(row.id), quality=row.status)


def metric(row):
    if row is None: return dict(status='NO_DATA', amount=None)
    result = row.payload['result']
    observed = row.observed_at if row.observed_at.tzinfo is not None else row.observed_at.replace(tzinfo=timezone.utc)
    return dict(id=row.id, status=row.status, amount=row.amount, unit=result['unit'], currency='RUB', tax_basis='WITH_VAT',
        receipt_at=result['receipt_at'], observed_at=row.observed_at, date_from=result['date_from'], date_to=result['date_to'],
        reasons=[REASONS.get(r, 'Требуется проверка исходного документа') for r in result['reasons']],
        stale=(datetime.now(timezone.utc) - observed).total_seconds() > 48*3600)


def summary(db, tenant, product_id):
    row = db.scalar(select(Snapshot).where(Snapshot.tenant_id == tenant, Snapshot.product_id == product_id).order_by(Snapshot.observed_at.desc(), Snapshot.id.desc()).limit(1))
    return metric(row)


def history(db, actor, product_id, *, offset=0, limit=25):
    authorize(db, actor, Capability.MATERIAL_PURCHASE_READ)
    service.find(db, actor, product_id)
    rows = db.scalars(select(Snapshot).where(Snapshot.tenant_id == actor.tenant_id, Snapshot.product_id == product_id).order_by(Snapshot.observed_at.desc(), Snapshot.id.desc()).offset(offset).limit(limit)).all()
    return dict(items=[metric(r) for r in rows], refresh=progress(db.scalar(attempts(db, actor.tenant_id, product_id).limit(1))))


def sources(db, actor, product_id, snapshot_id):
    authorize(db, actor, Capability.MATERIAL_PURCHASE_READ)
    service.find(db, actor, product_id)
    row = db.scalar(select(Snapshot).where(Snapshot.id == snapshot_id, Snapshot.tenant_id == actor.tenant_id, Snapshot.product_id == product_id))
    if row is None: raise HTTPException(404, 'Расшифровка не найдена')
    return dict(metric=metric(row), warehouse='Цех Производство ИП', hash=row.content_hash,
        policy=row.payload['policy'], source_id=row.source_id, source_path='/api/documents/export/incomingInvoice', mapping=row.payload['mapping'], manifest=row.payload['manifest'],
        candidates=row.payload['result']['candidates'], unit_conflicts=[dict(document_id=c['document_id'], number=c['number'], receipt_at=c['receipt_at'], lines=c['lines']) for c in row.payload['result']['documents'] if 'UNIT_MISMATCH' in c['reasons']], exclusions=row.payload['result']['exclusions'])
