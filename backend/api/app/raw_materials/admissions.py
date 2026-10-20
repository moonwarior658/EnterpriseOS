"""Human evidence-bound management decisions; append-only, revocable and transactional."""
from decimal import Decimal
from typing import Literal
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, exists
from sqlalchemy.orm import aliased
from app.core.authorization import authorize, Capability
from app.models.raw_material import MaterialDocumentAdmission as Decision, MaterialPurchaseSnapshot as Snapshot
from app.models.user import User
from app.audit.service import record_audit_event
from app.product_knowledge.bootstrap import digest
from app.raw_materials.admission_policy import line_hash, original, number
from app.raw_materials.purchases import SOURCE, WAREHOUSE

class DecisionCommand(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    request_id: UUID
    expected_version: int=Field(ge=1)
    expected_revision: int=Field(ge=0)
    kind: Literal['EMPLOYEE_PURCHASE','BASE_UNIT_CONTAINER']
    action: Literal['GRANT','REVOKE']
    document_id: UUID
    document_hash: str=Field(pattern=r'^[a-f0-9]{64}$')
    line_num: str=Field(default='',max_length=32,pattern=r'^([1-9][0-9]*)?$')
    evidence: str=Field(min_length=3,max_length=2000)
    comment: str=Field(min_length=3,max_length=2000)
    primary_checked: bool=False
    verified_unit_id: UUID | None=None
    verified_quantity: Decimal | None=Field(default=None,gt=0,max_digits=38,decimal_places=18)


def current_rows(db, tenant, product_id):
    newer=aliased(Decision)
    return db.scalars(select(Decision).where(Decision.tenant_id==tenant,Decision.product_id==product_id,
        ~exists(select(newer.id).where(newer.tenant_id==Decision.tenant_id,newer.product_id==Decision.product_id,newer.scope_key==Decision.scope_key,newer.revision>Decision.revision))).order_by(Decision.scope_key)).all()


def active(db, tenant, product_id):
    rows=[r for r in current_rows(db,tenant,product_id) if r.action=='GRANT']
    if len(rows)>2000:raise HTTPException(409,'Слишком много документных допусков; требуется проверка')
    return [dict(id=str(r.id),kind=r.kind,document_id=str(r.document_id),document_hash=r.document_hash,line_num=r.line_num,
        line_hash=r.line_hash,revision=r.revision,evidence=r.evidence,comment=r.comment,actor_user_id=r.actor_user_id,
        created_at=r.created_at.isoformat(),verification=r.verification) for r in rows]


def present(db,row,version=None):
    body=dict(id=str(row.id),snapshot_id=str(row.snapshot_id),kind=row.kind,action=row.action,revision=row.revision,
        document_id=str(row.document_id),document_hash=row.document_hash,line_num=row.line_num,scope_key=row.scope_key,
        evidence=row.evidence,comment=row.comment,author=db.scalar(select(User.display_name).where(User.id==row.actor_user_id,User.tenant_id==row.tenant_id)),
        created_at=row.created_at,verification=row.verification)
    if version is not None:body['version']=version
    return body


def history(db,actor,product_id,*,offset=0,limit=25):
    from app.raw_materials import service
    authorize(db,actor,Capability.MATERIAL_PURCHASE_READ);profile,_=service.find(db,actor,product_id)
    rows=db.scalars(select(Decision).where(Decision.tenant_id==actor.tenant_id,Decision.product_id==product_id).order_by(Decision.created_at.desc(),Decision.id.desc()).offset(offset).limit(limit)).all()
    latest=current_rows(db,actor.tenant_id,product_id)
    current={r.scope_key:str(r.id) for r in latest}
    return dict(items=[dict(**present(db,r),current=current.get(r.scope_key)==str(r.id)) for r in rows],version=profile.version,current_items=[present(db,r) for r in latest])


def decide(db,actor,product_id,snapshot_id,command):
    from app.raw_materials import service,purchase_refresh
    context=authorize(db,actor,Capability.MATERIAL_DOCUMENT_ADMIT,write=True)
    authorize(db,actor,Capability.MATERIAL_PURCHASE_READ)
    profile,product=service.find(db,actor,product_id,lock=True)
    request_hash=digest(dict(snapshot_id=str(snapshot_id),**command.model_dump(mode='json',exclude={'expected_version'})))
    prior=db.scalar(select(Decision).where(Decision.tenant_id==actor.tenant_id,Decision.request_id==command.request_id))
    if prior:
        if prior.product_id!=product_id or prior.request_hash!=request_hash:raise HTTPException(409,'Идентификатор запроса уже использован для другого решения')
        return present(db,prior,profile.version)
    if profile.version!=command.expected_version:raise HTTPException(409,'Карточка изменилась. Обновите данные')
    if command.action=='GRANT' and (profile.archived or not product.is_active):raise HTTPException(409,'Нельзя подтверждать архивную карточку')
    snapshot=db.scalar(select(Snapshot).where(Snapshot.tenant_id==actor.tenant_id,Snapshot.product_id==product_id,Snapshot.id==snapshot_id))
    if snapshot is None:raise HTTPException(404,'Исходный snapshot не найден')
    if snapshot.source_id!=SOURCE or snapshot.payload['result'].get('warehouse_id')!=WAREHOUSE:raise HTTPException(409,'Контур источника не подтверждён')
    docs=[d for d in snapshot.payload['result']['documents'] if d['document_id']==str(command.document_id) and d['source_hash']==command.document_hash]
    if len(docs)!=1:raise HTTPException(409,'Нужно выбрать точную неизменённую версию накладной')
    doc=docs[0];lines=[l for l in doc['lines'] if not command.line_num or l.get('num')==command.line_num]
    if not lines or (command.line_num and len(lines)!=1):raise HTTPException(409,'Строка документа не определена однозначно')
    if command.kind=='BASE_UNIT_CONTAINER' and not command.line_num:raise HTTPException(422,'Верификация упаковки относится только к выбранной строке')
    fingerprint=line_hash(lines[0]) if command.line_num else ''
    key=digest(dict(tenant=actor.tenant_id,product_id=str(product_id),source=SOURCE,warehouse=WAREHOUSE,document=str(command.document_id),hash=command.document_hash,line=command.line_num,line_hash=fingerprint,kind=command.kind))
    last=db.scalar(select(Decision).where(Decision.scope_key==key).order_by(Decision.revision.desc()).limit(1))
    if command.expected_revision!=(last.revision if last else 0):raise HTTPException(409,'Решение уже изменено другим сотрудником')
    if (last.action if last else 'REVOKE')==command.action:raise HTTPException(409,'Такое состояние допуска уже действует')
    verification={}
    if command.action=='GRANT':
        if not command.primary_checked:raise HTTPException(422,'Подтвердите проверку первичных документов')
        flags=doc['supplier_flags']
        if doc['status']!='PROCESSED' or not flags.get('is_supplier') or flags.get('is_deleted') or flags.get('represents_store'):
            raise HTTPException(409,'Допуск не отменяет запрет непроведённых, внутренних или неподтверждённых документов')
        if command.kind=='EMPLOYEE_PURCHASE':
            if not flags.get('is_employee'):raise HTTPException(409,'Документ не требует допуска контрагента-сотрудника')
            verification=dict(nature='EXTERNAL_PURCHASE',primary_checked=True)
        else:
            line=original(lines[0]);mapping=purchase_refresh.scope(db,actor.tenant_id,product_id)
            amount,actual=number(line.get('amount')),number(line.get('actualAmount'));container=line.get('containerId')
            if not container or container=='00000000-0000-0000-0000-000000000000' or line.get('amountUnit')!=mapping['unit_id']:
                raise HTTPException(409,'Нужны исходные KG/L и контейнер при неизменной учётной единице')
            if actual is None or actual<=0 or actual!=amount or command.verified_unit_id!=UUID(mapping['unit_id']) or command.verified_quantity!=actual:
                raise HTTPException(409,'Проверенное количество и единица должны точно совпасть с источником; противоречие нельзя подтвердить')
            verification=dict(quantity=str(actual),unit_id=mapping['unit_id'],container_id=container,primary_checked=True,semantics='BASE_UNIT_QUANTITY_NO_CONVERSION')
    row=Decision(tenant_id=actor.tenant_id,product_id=product_id,snapshot_id=snapshot_id,request_id=command.request_id,request_hash=request_hash,
        scope_key=key,revision=(last.revision+1 if last else 1),kind=command.kind,action=command.action,source_id=SOURCE,warehouse_id=UUID(WAREHOUSE),
        document_id=command.document_id,document_hash=command.document_hash,line_num=command.line_num,line_hash=fingerprint,evidence=command.evidence,comment=command.comment,
        verification=verification,actor_user_id=actor.id)
    db.add(row);db.flush();profile.version+=1
    record_audit_event(db,tenant_id=actor.tenant_id,entity_type='MaterialDocumentAdmission',entity_id=row.id,event_type='MATERIAL_DOCUMENT_'+command.action,
        operation=command.action,actor_user=actor,context=context,after=dict(scope_key=key,revision=row.revision,kind=row.kind,document_id=str(row.document_id),document_hash=row.document_hash,line_num=row.line_num,line_hash=row.line_hash,verification=row.verification,evidence=row.evidence,comment=row.comment),reason=command.evidence,correlation_id=str(command.request_id))
    db.flush();return present(db,row,profile.version)


def used_ids(documents):
    return {d['id'] for doc in documents for line in doc['lines'] for d in line.get('document_admissions',[])}


def validity(db,row):
    ids={d['id'] for d in active(db,row.tenant_id,row.product_id)}
    return (used_ids(row.payload['result']['candidates'])<=ids,
        used_ids(row.payload.get('analytics',{}).get('average',{}).get('documents',[]))<=ids)
