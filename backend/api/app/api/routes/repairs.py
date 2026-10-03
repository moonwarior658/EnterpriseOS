"""Explicit repair actions and the external contractor directory."""
from pathlib import Path
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api.dependencies import get_current_user
from app.audit.service import record_audit_event
from app.core.action_context import ActionContextError, resolve_action_context
from app.core.authorization import Capability, repair_authorize
from app.core.config import settings
from app.db.session import get_db
from app.models.employee import EmployeeRole
from app.models.audit import AuditEvent
from app.models.supply import Department
from app.models.user import User
from app.models.work_request import ExternalContractor, ContractorSpecialization, ContractorSpecializationLink, WorkRequest
from app.requests.repair import RepairConflict, add_photo, create_repair, edit_details, repair_read, timeline, transition
from app.requests.service import PendingAttachment, WorkRequestNotFoundError
from app.schemas.work_request import RepairContractorAssignment, RepairCreate, RepairDetailsUpdate, RepairReopen, RepairVisit, WorkRequestAttachmentRead, WorkRequestRead

router = APIRouter(prefix="/repairs", tags=["repairs"])


class ContractorInput(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    phone: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)
    price_notes: str | None = Field(default=None, max_length=4000)
    specialization_ids: list[UUID] = Field(default_factory=list)
    model_config = {"extra": "forbid"}

    @field_validator("name", "phone")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Поле не может быть пустым")
        return value.strip()


class ContractorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    phone: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)
    price_notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None
    reason: str | None = Field(default=None, max_length=1000)
    specialization_ids: list[UUID] | None = None
    model_config = {"extra": "forbid"}

    @field_validator("name", "phone")
    @classmethod
    def nonempty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Поле не может быть пустым")
        return value.strip() if value is not None else None


class SpecializationInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Название не может быть пустым")
        return value.strip()


class SpecializationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    reason: str | None = Field(default=None, max_length=1000)
    model_config = {"extra": "forbid"}

    @field_validator("name")
    @classmethod
    def nonempty(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Название не может быть пустым")
        return value.strip() if value is not None else None


def _error(error: Exception):
    if isinstance(error, (ActionContextError, WorkRequestNotFoundError)):
        raise HTTPException(status_code=404, detail="Ремонт недоступен") from error
    if isinstance(error, RepairConflict):
        raise HTTPException(status_code=409, detail=str(error)) from error
    raise error


def _repair_read(db: Session, user: User, repair):
    return repair_read(db, user, repair)


@router.get("/departments")
def repair_departments(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    result = []
    for department in db.scalars(select(Department).where(Department.tenant_id == user.tenant_id, Department.is_active.is_(True)).order_by(Department.name)).all():
        try:
            repair_authorize(db, user, Capability.REPAIR_CREATE, department_id=department.id, write=True)
        except ActionContextError:
            continue
        result.append({"id": department.id, "name": department.name})
    return result


@router.post("", response_model=WorkRequestRead, status_code=201)
async def new_repair(request: Request, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    attachments = []
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = RepairCreate.model_validate(await request.json())
        else:
            form = await request.form()
            payload = RepairCreate.model_validate({key: form.get(key) for key in ("department_id", "description", "repair_category", "priority")})
            uploads = [item for item in form.getlist("photos") if isinstance(item, StarletteUploadFile) and item.filename]
            if len(uploads) > 5:
                for upload in uploads:
                    await upload.close()
                raise RepairConflict("Можно прикрепить не более 5 фотографий")
            for upload in uploads:
                if upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
                    for candidate in uploads:
                        await candidate.close()
                    raise RepairConflict("Допустимы только фотографии JPEG, PNG или WebP")
                content = await upload.read(8 * 1024 * 1024 + 1)
                await upload.close()
                if not content or len(content) > 8 * 1024 * 1024:
                    raise RepairConflict("Проверьте размер фотографии")
                attachments.append(PendingAttachment(Path(upload.filename).name, upload.content_type, content))
        repair = create_repair(db, user, department_id=payload.department_id,
            description=payload.description, category=payload.repair_category,
            priority=payload.priority.value, attachments=attachments,
            upload_dir=Path(settings.work_request_upload_dir))
        return _repair_read(db, user, repair)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail=error.message) from error
    except RepairConflict as error:
        _error(error)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="Проверьте поля ремонта") from error


@router.get("/contractors")
def list_contractors(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try:
        base = resolve_action_context(db, user, write=False)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail="Справочник подрядчиков недоступен") from error
    if not base.roles.intersection({EmployeeRole.ADMIN, EmployeeRole.SUPPLY_MANAGER, EmployeeRole.HANDYMAN}):
        raise HTTPException(status_code=403, detail="Справочник подрядчиков недоступен")
    query = select(ExternalContractor).where(ExternalContractor.tenant_id == user.tenant_id)
    if not base.roles.intersection({EmployeeRole.ADMIN, EmployeeRole.SUPPLY_MANAGER}):
        query = query.where(ExternalContractor.is_active.is_(True))
    contractors = db.scalars(query.order_by(ExternalContractor.name)).all()
    return [{"id": row.id, "name": row.name, "phone": row.phone, "is_active": row.is_active,
             "notes": row.notes if base.roles.intersection({EmployeeRole.ADMIN, EmployeeRole.SUPPLY_MANAGER}) else None,
             "price_notes": row.price_notes if base.roles.intersection({EmployeeRole.ADMIN, EmployeeRole.SUPPLY_MANAGER}) else None,
             "specialization_ids": list(db.scalars(select(ContractorSpecializationLink.specialization_id).where(ContractorSpecializationLink.tenant_id == user.tenant_id, ContractorSpecializationLink.contractor_id == row.id)).all())} for row in contractors]


@router.get("/specializations")
def list_specializations(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try:
        base = resolve_action_context(db, user, write=False)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail="Справочник специализаций недоступен") from error
    if not base.roles.intersection({EmployeeRole.ADMIN, EmployeeRole.SUPPLY_MANAGER, EmployeeRole.HANDYMAN}):
        raise HTTPException(status_code=403, detail="Справочник специализаций недоступен")
    return [{"id": item.id, "name": item.name, "is_active": item.is_active} for item in db.scalars(select(ContractorSpecialization).where(ContractorSpecialization.tenant_id == user.tenant_id).order_by(ContractorSpecialization.name)).all()]


def _manage_context(db: Session, user: User):
    try:
        return repair_authorize(db, user, Capability.CONTRACTOR_MANAGE, write=True)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail="Недостаточно прав") from error


def _commit_directory(db: Session):
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Запись конфликтует с существующими данными") from error


def _flush_directory(db: Session):
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Запись конфликтует с существующими данными") from error


def _links(db: Session, user: User, contractor_id: UUID, ids: list[UUID]):
    for specialization_id in set(ids):
        item = db.get(ContractorSpecialization, specialization_id)
        if item is None or item.tenant_id != user.tenant_id or not item.is_active:
            raise HTTPException(status_code=422, detail="Специализация недоступна")
    old = db.scalars(select(ContractorSpecializationLink).where(ContractorSpecializationLink.tenant_id == user.tenant_id, ContractorSpecializationLink.contractor_id == contractor_id)).all()
    existing = {item.specialization_id: item for item in old}
    for item in old:
        if item.specialization_id not in ids:
            db.delete(item)
    for item_id in set(ids) - set(existing):
        db.add(ContractorSpecializationLink(tenant_id=user.tenant_id, contractor_id=contractor_id, specialization_id=item_id))


@router.post("/specializations", status_code=201)
def create_specialization(payload: SpecializationInput, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    context = _manage_context(db, user)
    item = ContractorSpecialization(tenant_id=user.tenant_id, name=payload.name.strip())
    db.add(item)
    _flush_directory(db)
    record_audit_event(db, tenant_id=user.tenant_id, event_type="CONTRACTOR_SPECIALIZATION_CREATED", entity_type="ContractorSpecialization", entity_id=item.id, operation="CREATE", context=context, actor_user=user, after={"name": item.name})
    _commit_directory(db)
    return {"id": item.id, "name": item.name, "is_active": item.is_active}


@router.patch("/specializations/{specialization_id}")
def update_specialization(specialization_id: UUID, payload: SpecializationUpdate, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    context = _manage_context(db, user)
    item = db.get(ContractorSpecialization, specialization_id)
    if item is None or item.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Специализация не найдена")
    if payload.is_active is not None and payload.is_active != item.is_active and not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="Укажите причину изменения состояния")
    before = {"name": item.name, "is_active": item.is_active}
    if payload.name is not None: item.name = payload.name.strip()
    if payload.is_active is not None: item.is_active = payload.is_active
    record_audit_event(db, tenant_id=user.tenant_id, event_type="CONTRACTOR_SPECIALIZATION_UPDATED", entity_type="ContractorSpecialization", entity_id=item.id, operation="UPDATE", context=context, actor_user=user, before=before, after={"name": item.name, "is_active": item.is_active}, reason=payload.reason)
    _commit_directory(db)
    return {"id": item.id, "name": item.name, "is_active": item.is_active}


@router.post("/contractors", status_code=201)
def create_contractor(payload: ContractorInput, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    context = _manage_context(db, user)
    item = ExternalContractor(tenant_id=user.tenant_id, name=payload.name.strip(), phone=payload.phone.strip(), notes=payload.notes, price_notes=payload.price_notes)
    db.add(item)
    _flush_directory(db)
    _links(db, user, item.id, payload.specialization_ids)
    record_audit_event(db, tenant_id=user.tenant_id, event_type="CONTRACTOR_CREATED", entity_type="ExternalContractor", entity_id=item.id, operation="CREATE", context=context, actor_user=user, after={"name": item.name, "phone": item.phone, "price_notes": item.price_notes, "specialization_ids": payload.specialization_ids})
    _commit_directory(db)
    return {"id": item.id, "name": item.name, "phone": item.phone, "is_active": item.is_active}


@router.patch("/contractors/{contractor_id}")
def update_contractor(contractor_id: UUID, payload: ContractorUpdate, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    context = _manage_context(db, user)
    item = db.get(ExternalContractor, contractor_id)
    if item is None or item.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Подрядчик не найден")
    if payload.is_active is not None and payload.is_active != item.is_active and not (payload.reason or "").strip():
        raise HTTPException(status_code=422, detail="Укажите причину изменения состояния")
    old_specializations = list(db.scalars(select(ContractorSpecializationLink.specialization_id).where(
        ContractorSpecializationLink.tenant_id == user.tenant_id,
        ContractorSpecializationLink.contractor_id == item.id,
    )).all())
    before = {"name": item.name, "phone": item.phone, "is_active": item.is_active,
              "notes": item.notes, "price_notes": item.price_notes, "specialization_ids": old_specializations}
    if payload.name is not None: item.name = payload.name.strip()
    if payload.phone is not None: item.phone = payload.phone.strip()
    if "notes" in payload.model_fields_set: item.notes = payload.notes
    if "price_notes" in payload.model_fields_set: item.price_notes = payload.price_notes
    if payload.is_active is not None: item.is_active = payload.is_active
    if payload.specialization_ids is not None: _links(db, user, item.id, payload.specialization_ids)
    record_audit_event(db, tenant_id=user.tenant_id, event_type="CONTRACTOR_UPDATED", entity_type="ExternalContractor", entity_id=item.id, operation="UPDATE", context=context, actor_user=user, before=before, after={"name": item.name, "phone": item.phone, "is_active": item.is_active, "notes": item.notes, "price_notes": item.price_notes, "specialization_ids": payload.specialization_ids if payload.specialization_ids is not None else old_specializations}, reason=payload.reason)
    _commit_directory(db)
    return {"id": item.id, "name": item.name, "phone": item.phone, "is_active": item.is_active}


@router.get("/contractors/{contractor_id}/history")
def contractor_history(contractor_id: UUID, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try:
        base = resolve_action_context(db, user, write=False)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail="История подрядчика недоступна") from error
    if not base.roles.intersection({EmployeeRole.ADMIN, EmployeeRole.SUPPLY_MANAGER}):
        raise HTTPException(status_code=403, detail="История подрядчика недоступна")
    contractor = db.get(ExternalContractor, contractor_id)
    if contractor is None or contractor.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Подрядчик не найден")
    events = db.scalars(select(AuditEvent).where(
        AuditEvent.tenant_id == user.tenant_id,
        AuditEvent.entity_type == "WorkRequest",
        AuditEvent.operation.in_(("ASSIGN_CONTRACTOR", "SCHEDULE_EXTERNAL_VISIT")),
    ).order_by(AuditEvent.occurred_at)).all()
    historical = {
        int(event.entity_id): event.after for event in events
        if str(event.after.get("contractor_id")) == str(contractor_id)
    }
    repairs = db.scalars(select(WorkRequest).where(
        WorkRequest.tenant_id == user.tenant_id,
        WorkRequest.request_type == "repair",
    ).order_by(WorkRequest.created_at.desc(), WorkRequest.id.desc())).all()
    result = []
    for repair in repairs:
        if repair.contractor_id != contractor_id and repair.id not in historical:
            continue
        try:
            repair_authorize(db, user, Capability.REPAIR_READ, repair=repair)
        except ActionContextError:
            continue
        snapshot = historical.get(repair.id, {})
        current_assignment = repair.contractor_id == contractor_id
        specialization_id = repair.specialization_id if current_assignment else snapshot.get("specialization_id")
        specialization = db.get(ContractorSpecialization, UUID(str(specialization_id))) if specialization_id else None
        reopened = db.scalar(select(AuditEvent.id).where(
            AuditEvent.tenant_id == user.tenant_id,
            AuditEvent.entity_type == "WorkRequest",
            AuditEvent.entity_id == str(repair.id),
            AuditEvent.operation == "REOPEN",
        )) is not None
        result.append({"repair_id": repair.id, "created_at": repair.created_at,
            "department": repair.department, "category": repair.repair_category,
            "description": repair.description,
            "specialization": (specialization.name if specialization else None) or snapshot.get("specialization_name_snapshot"),
            "visit_at": repair.visit_at if current_assignment else snapshot.get("visit_at"),
            "status": repair.status, "closed_at": repair.closed_at, "reopened": reopened})
    return result


@router.get("/{repair_id}/timeline")
def repair_timeline(repair_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try:
        events = timeline(db, user, repair_id)
        labels = {"CREATE": "Заявка создана", "EDIT_DETAILS": "Описание ремонта изменено", "TAKE": "Принято в работу", "ASSIGN_CONTRACTOR": "Выбран внешний подрядчик", "SCHEDULE_EXTERNAL_VISIT": "Назначен внешний мастер", "ESCALATE_TO_SUPPLY": "Передано руководителю снабжения", "CLOSE": "Ремонт закрыт", "REOPEN": "Ремонт переоткрыт", "COMMENT": "Добавлен комментарий", "ADD_PHOTO": "Добавлена фотография"}
        def details(item: AuditEvent) -> str:
            label = labels.get(item.operation, "Событие ремонта")
            if item.operation not in {"ASSIGN_CONTRACTOR", "SCHEDULE_EXTERNAL_VISIT"}:
                return label
            old_id = item.before.get("contractor_id")
            new_id = item.after.get("contractor_id")
            old = db.get(ExternalContractor, UUID(str(old_id))) if old_id else None
            new = db.get(ExternalContractor, UUID(str(new_id))) if new_id else None
            specialization_id = item.after.get("specialization_id")
            specialization = db.get(ContractorSpecialization, UUID(str(specialization_id))) if specialization_id else None
            old_name = item.before.get("contractor_name_snapshot") or (old.name if old else None)
            new_name = item.after.get("contractor_name_snapshot") or (new.name if new else None)
            changed = f"{old_name} → {new_name}" if old_name and new_name and old_id != new_id else (new_name or "")
            parts = [label, changed]
            specialization_name = item.after.get("specialization_name_snapshot") or (specialization.name if specialization else None)
            if specialization_name:
                parts.append(specialization_name)
            if item.operation == "SCHEDULE_EXTERNAL_VISIT" and item.after.get("visit_at"):
                parts.append(datetime.fromisoformat(str(item.after["visit_at"])).strftime("%d.%m.%Y %H:%M %z"))
            return " · ".join(part for part in parts if part)
        return [{"at": item.occurred_at, "action": item.operation, "actor": item.actor_name_snapshot,
                 "role": item.authorized_as, "reason": item.reason,
                 "details": details(item)} for item in events if item.operation != "COMMENT"]
    except (ActionContextError, WorkRequestNotFoundError) as error:
        _error(error)


@router.patch("/{repair_id}/details", response_model=WorkRequestRead)
def change_details(repair_id: int, payload: RepairDetailsUpdate, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try:
        return _repair_read(db, user, edit_details(db, user, repair_id,
            description=payload.description, category=payload.repair_category,
            priority=payload.priority.value))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error:
        _error(error)


@router.post("/{repair_id}/photos", response_model=WorkRequestAttachmentRead, status_code=201)
async def upload_photo(repair_id: int, photo: Annotated[UploadFile, File()], db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    if photo.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=422, detail="Допустимы только фотографии JPEG, PNG или WebP")
    content = await photo.read(8 * 1024 * 1024 + 1)
    await photo.close()
    if not content or len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Проверьте размер фотографии")
    try:
        return add_photo(db, user, repair_id, PendingAttachment(Path(photo.filename or 'photo').name,
            photo.content_type, content), Path(settings.work_request_upload_dir))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error:
        _error(error)


@router.post("/{repair_id}/take", response_model=WorkRequestRead)
def take(repair_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try: return _repair_read(db, user, transition(db, user, repair_id, "take"))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error: _error(error)


@router.post("/{repair_id}/schedule-external-visit", response_model=WorkRequestRead)
def schedule(repair_id: int, payload: RepairVisit, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try: return _repair_read(db, user, transition(db, user, repair_id, "schedule_external_visit", contractor_id=payload.contractor_id, specialization_id=payload.specialization_id, visit_at=payload.visit_at))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error: _error(error)


@router.post("/{repair_id}/assign-contractor", response_model=WorkRequestRead)
def assign_contractor(repair_id: int, payload: RepairContractorAssignment, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try: return _repair_read(db, user, transition(db, user, repair_id, "assign_contractor", contractor_id=payload.contractor_id, specialization_id=payload.specialization_id))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error: _error(error)


@router.post("/{repair_id}/escalate-to-supply", response_model=WorkRequestRead)
def escalate(repair_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try: return _repair_read(db, user, transition(db, user, repair_id, "escalate_to_supply"))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error: _error(error)


@router.post("/{repair_id}/close", response_model=WorkRequestRead)
def close(repair_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try: return _repair_read(db, user, transition(db, user, repair_id, "close"))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error: _error(error)


@router.post("/{repair_id}/reopen", response_model=WorkRequestRead)
def reopen(repair_id: int, payload: RepairReopen, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    try: return _repair_read(db, user, transition(db, user, repair_id, "reopen", reason=payload.reason))
    except (ActionContextError, WorkRequestNotFoundError, RepairConflict) as error: _error(error)
