"""Authorized repair workflow on the historical work_requests table."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.core.action_context import ActionContextError, resolve_action_context
from app.core.authorization import Capability, GRANTS, repair_authorize
from app.models.audit import AuditEvent
from app.models.employee import Employee, EmployeeRole, EmployeeStatus
from app.models.supply import Department
from app.models.user import User
from app.models.work_request import (
    ContractorSpecialization, ContractorSpecializationLink, ExternalContractor,
    WorkRequest, WorkRequestComment,
    WorkRequestAttachment,
)
from app.requests.service import PendingAttachment, get_work_request
from app.schemas.work_request import WorkRequestRead


class RepairConflict(ValueError):
    pass


def _details_context(db: Session, user: User, repair: WorkRequest):
    try:
        return repair_authorize(db, user, Capability.REPAIR_CREATE,
            department_id=repair.department_id, write=True,
            only_roles=frozenset({EmployeeRole.ADMIN}))
    except ActionContextError:
        seller = repair_authorize(db, user, Capability.REPAIR_CREATE,
            department_id=repair.department_id, write=True,
            only_roles=frozenset({EmployeeRole.SELLER}))
        if repair.creator_employee_id != seller.employee_id:
            raise ActionContextError("PERMISSION_DENIED", "Можно изменить только свою заявку")
        return seller


def repair_read(db: Session, user: User, repair: WorkRequest) -> dict:
    contractor = db.get(ExternalContractor, repair.contractor_id) if repair.contractor_id else None
    specialization = db.get(ContractorSpecialization, repair.specialization_id) if repair.specialization_id else None
    responsible = db.get(Employee, repair.responsible_employee_id) if repair.responsible_employee_id else None
    return dict(WorkRequestRead.model_validate(repair).model_dump(),
        allowed_actions=allowed_actions(db, user, repair),
        contractor_name=contractor.name if contractor else None,
        contractor_phone=contractor.phone if contractor else None,
        specialization_name=specialization.name if specialization else None,
        responsible_employee_name=responsible.full_name if responsible else None)


def visible_repairs(db: Session, user: User) -> list[WorkRequest]:
    base = resolve_action_context(db, user, write=False)
    if not any(role in base.roles for role, _scope in GRANTS[Capability.REPAIR_READ]):
        raise ActionContextError("PERMISSION_DENIED", "Недостаточно прав для просмотра ремонтов")
    repairs = db.scalars(select(WorkRequest).where(
        WorkRequest.tenant_id == user.tenant_id,
        WorkRequest.request_type == "repair",
    ).order_by(WorkRequest.created_at.desc(), WorkRequest.id.desc())).all()
    result = []
    for repair in repairs:
        try:
            repair_authorize(db, user, Capability.REPAIR_READ, repair=repair)
        except ActionContextError:
            continue
        result.append(repair)
    return result


def visible_repair(db: Session, user: User, request_id: int) -> WorkRequest:
    repair = get_work_request(db, request_id, tenant_id=user.tenant_id)
    repair_authorize(db, user, Capability.REPAIR_READ, repair=repair)
    return repair


def allowed_actions(db: Session, user: User, repair: WorkRequest) -> list[str]:
    base = resolve_action_context(db, user, write=False)
    if repair.responsible_role is None and EmployeeRole.ADMIN not in base.roles:
        return []
    result = []
    for action, capability in (
        ("take", Capability.REPAIR_TAKE),
        ("assign_contractor", Capability.REPAIR_OPERATE),
        ("schedule_external_visit", Capability.REPAIR_OPERATE),
        ("escalate_to_supply", Capability.REPAIR_OPERATE),
        ("close", Capability.REPAIR_OPERATE),
        ("reopen", Capability.REPAIR_REOPEN),
        ("comment", Capability.REPAIR_OPERATE),
    ):
        try:
            context = repair_authorize(db, user, capability, repair=repair, write=True)
        except ActionContextError:
            if action == "comment":
                try:
                    context = repair_authorize(db, user, Capability.REPAIR_CREATE,
                        department_id=repair.department_id, write=True,
                        only_roles=frozenset({EmployeeRole.SELLER}))
                except ActionContextError:
                    continue
            else:
                continue
        if action == "take" and repair.status in {"new", "reopened", "escalated"} and repair.responsible_employee_id is None:
            result.append(action)
        elif action in {"assign_contractor", "schedule_external_visit", "escalate_to_supply", "close"}:
            active = repair.status in {"in_progress", "waiting_external", "reopened", "escalated"}
            assigned = repair.responsible_employee_id == context.employee_id or context.authorized_as.value == "ADMIN"
            if active and assigned and (action != "escalate_to_supply" or (repair.responsible_role == "HANDYMAN" and repair.visit_at is None)):
                result.append(action)
        elif action == "reopen" and repair.status == "completed":
            result.append(action)
        elif action == "comment" and repair.status not in {"completed", "cancelled"}:
            result.append(action)
            result.append("add_photo")
    if repair.status not in {"completed", "cancelled"}:
        try:
            _details_context(db, user, repair)
            result.append("edit_details")
        except ActionContextError:
            pass
    return result


def edit_details(db: Session, user: User, repair_id: int, *, description: str,
                 category: str, priority: str) -> WorkRequest:
    repair = visible_repair(db, user, repair_id)
    repair = db.scalar(select(WorkRequest).where(WorkRequest.id == repair_id,
        WorkRequest.tenant_id == user.tenant_id).with_for_update().execution_options(populate_existing=True))
    if "edit_details" not in allowed_actions(db, user, repair):
        raise RepairConflict("Редактирование сейчас недоступно")
    context = _details_context(db, user, repair)
    before = {"description": repair.description, "repair_category": repair.repair_category,
              "priority": repair.priority}
    repair.description = description.strip()
    repair.repair_category = category
    repair.priority = priority
    record_audit_event(db, tenant_id=user.tenant_id, event_type="REPAIR_DETAILS_UPDATED",
        entity_type="WorkRequest", entity_id=repair.id, operation="EDIT_DETAILS",
        context=context, actor_user=user, before=before,
        after={"description": repair.description, "repair_category": category, "priority": priority})
    db.commit()
    return visible_repair(db, user, repair_id)


def create_repair(db: Session, user: User, *, department_id: UUID, description: str,
                  category: str, priority: str, attachments: list[PendingAttachment] | None = None,
                  upload_dir: Path | None = None) -> WorkRequest:
    department = db.get(Department, department_id)
    if department is None or department.tenant_id != user.tenant_id or not department.is_active:
        raise RepairConflict("Подразделение недоступно")
    context = repair_authorize(db, user, Capability.REPAIR_CREATE, department_id=department_id, write=True)
    repair = WorkRequest(
        tenant_id=user.tenant_id, request_type="repair", department=department.name,
        department_id=department.id, description=description, repair_category=category,
        priority=priority, status="new", created_by_user_id=user.id,
        author_name=context.employee_name_snapshot,
        creator_employee_id=context.employee_id, creator_authorized_as=context.authorized_as.value,
        responsible_role="HANDYMAN", responsibility_started_at=context.determined_at,
    )
    db.add(repair)
    db.flush()
    written: list[Path] = []
    try:
        if attachments:
            if upload_dir is None:
                raise ValueError("Upload directory required")
            upload_dir.mkdir(parents=True, exist_ok=True)
            root = upload_dir.resolve()
            for attachment in attachments:
                suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[attachment.content_type]
                path = root / f"{uuid4().hex}{suffix}"
                path.write_bytes(attachment.content)
                written.append(path)
                db.add(WorkRequestAttachment(work_request_id=repair.id,
                    original_filename=attachment.original_filename[:255],
                    stored_filename=path.name, content_type=attachment.content_type,
                    size_bytes=len(attachment.content)))
        record_audit_event(db, tenant_id=user.tenant_id, event_type="REPAIR_CREATED",
            entity_type="WorkRequest", entity_id=repair.id, operation="CREATE", context=context,
            actor_user=user, after={"department_id": department.id, "status": "new",
                "responsible_role": "HANDYMAN", "description": description})
        db.commit()
    except Exception:
        db.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return visible_repair(db, user, repair.id)


def transition(db: Session, user: User, repair_id: int, action: str, *,
               reason: str | None = None, contractor_id: UUID | None = None,
               specialization_id: UUID | None = None, visit_at: datetime | None = None) -> WorkRequest:
    repair = visible_repair(db, user, repair_id)
    repair = db.scalar(select(WorkRequest).where(
        WorkRequest.id == repair_id, WorkRequest.tenant_id == user.tenant_id,
        WorkRequest.request_type == "repair",
    ).with_for_update().execution_options(populate_existing=True))
    if action not in allowed_actions(db, user, repair):
        raise RepairConflict("Действие недоступно в текущем состоянии")
    capability = Capability.REPAIR_REOPEN if action == "reopen" else Capability.REPAIR_TAKE if action == "take" else Capability.REPAIR_OPERATE
    context = repair_authorize(db, user, capability, repair=repair, write=True)
    before = {"status": repair.status, "responsible_role": repair.responsible_role,
              "responsible_employee_id": repair.responsible_employee_id,
              "responsibility_started_at": repair.responsibility_started_at,
              "contractor_id": repair.contractor_id, "specialization_id": repair.specialization_id,
              "visit_at": repair.visit_at, "closed_at": repair.closed_at}
    if repair.contractor_id:
        previous_contractor = db.get(ExternalContractor, repair.contractor_id)
        before["contractor_name_snapshot"] = previous_contractor.name if previous_contractor else None
    if repair.specialization_id:
        previous_specialization = db.get(ContractorSpecialization, repair.specialization_id)
        before["specialization_name_snapshot"] = previous_specialization.name if previous_specialization else None
    now = datetime.now(timezone.utc)
    if action == "take":
        repair.responsible_employee_id = context.employee_id
        repair.responsibility_started_at = now
        repair.status = "in_progress"
    elif action in {"assign_contractor", "schedule_external_visit"}:
        if contractor_id is None or specialization_id is None:
            raise RepairConflict("Укажите подрядчика и специализацию")
        contractor = db.get(ExternalContractor, contractor_id)
        specialization = db.get(ContractorSpecialization, specialization_id)
        linked = db.get(ContractorSpecializationLink, (user.tenant_id, contractor_id, specialization_id))
        if not contractor or contractor.tenant_id != user.tenant_id or not contractor.is_active or not specialization or not specialization.is_active or not linked:
            raise RepairConflict("Подрядчик или специализация недоступны")
        if action == "assign_contractor" and repair.visit_at is not None and (
            repair.contractor_id != contractor_id or repair.specialization_id != specialization_id
        ):
            repair.visit_at = None
            repair.status = "escalated" if repair.responsible_role == "SUPPLY_MANAGER" else "in_progress"
        repair.contractor_id = contractor_id
        repair.specialization_id = specialization_id
        if action == "schedule_external_visit":
            if visit_at is None or visit_at.tzinfo is None:
                raise RepairConflict("Укажите время визита с часовым поясом")
            if visit_at <= now:
                raise RepairConflict("Время визита должно быть в будущем")
            repair.visit_at = visit_at
            repair.status = "waiting_external"
    elif action == "escalate_to_supply":
        repair.responsible_role = "SUPPLY_MANAGER"
        repair.responsible_employee_id = None
        repair.responsibility_started_at = now
        repair.status = "escalated"
    elif action == "close":
        repair.status = "completed"
        repair.closed_at = now
        repair.closed_by_user_id = user.id
    elif action == "reopen":
        if not reason or not reason.strip():
            raise RepairConflict("Укажите причину переоткрытия")
        repair.status = "reopened"
        repair.responsibility_started_at = now
        employee = db.get(Employee, repair.responsible_employee_id) if repair.responsible_employee_id else None
        if employee is None or employee.status != EmployeeStatus.ACTIVE:
            repair.responsible_employee_id = None
        repair.closed_at = None
        repair.closed_by_user_id = None
    after = {"status": repair.status, "responsible_role": repair.responsible_role,
             "responsible_employee_id": repair.responsible_employee_id,
             "responsibility_started_at": repair.responsibility_started_at,
             "contractor_id": repair.contractor_id, "specialization_id": repair.specialization_id,
             "visit_at": repair.visit_at, "closed_at": repair.closed_at}
    if repair.contractor_id:
        current_contractor = db.get(ExternalContractor, repair.contractor_id)
        after["contractor_name_snapshot"] = current_contractor.name if current_contractor else None
    if repair.specialization_id:
        current_specialization = db.get(ContractorSpecialization, repair.specialization_id)
        after["specialization_name_snapshot"] = current_specialization.name if current_specialization else None
    record_audit_event(db, tenant_id=user.tenant_id, event_type=f"REPAIR_{action.upper()}",
        entity_type="WorkRequest", entity_id=repair.id, operation=action.upper(),
        context=context, actor_user=user, before=before, after=after, reason=reason)
    db.commit()
    return visible_repair(db, user, repair.id)


def add_comment(db: Session, user: User, repair_id: int, body: str) -> WorkRequestComment:
    repair = visible_repair(db, user, repair_id)
    if "comment" not in allowed_actions(db, user, repair):
        raise RepairConflict("Комментарий сейчас недоступен")
    try:
        context = repair_authorize(db, user, Capability.REPAIR_OPERATE, repair=repair, write=True)
    except ActionContextError:
        context = repair_authorize(db, user, Capability.REPAIR_CREATE,
            department_id=repair.department_id, write=True,
            only_roles=frozenset({EmployeeRole.SELLER}))
    comment = WorkRequestComment(work_request_id=repair_id, author_user_id=user.id, body=body)
    db.add(comment)
    db.flush()
    record_audit_event(db, tenant_id=user.tenant_id, event_type="REPAIR_COMMENTED",
        entity_type="WorkRequest", entity_id=repair_id, operation="COMMENT", context=context,
        actor_user=user, after={"comment_id": comment.id, "body": body})
    db.commit()
    db.refresh(comment)
    return comment


def add_photo(db: Session, user: User, repair_id: int, attachment: PendingAttachment,
              upload_dir: Path) -> WorkRequestAttachment:
    repair = visible_repair(db, user, repair_id)
    if "add_photo" not in allowed_actions(db, user, repair):
        raise RepairConflict("Фотография сейчас недоступна")
    try:
        context = repair_authorize(db, user, Capability.REPAIR_OPERATE, repair=repair, write=True)
    except ActionContextError:
        context = repair_authorize(db, user, Capability.REPAIR_CREATE,
            department_id=repair.department_id, write=True,
            only_roles=frozenset({EmployeeRole.SELLER}))
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[attachment.content_type]
    path = upload_dir.resolve() / f"{uuid4().hex}{suffix}"
    path.write_bytes(attachment.content)
    item = WorkRequestAttachment(work_request_id=repair_id,
        original_filename=attachment.original_filename[:255], stored_filename=path.name,
        content_type=attachment.content_type, size_bytes=len(attachment.content))
    try:
        db.add(item)
        db.flush()
        record_audit_event(db, tenant_id=user.tenant_id, event_type="REPAIR_PHOTO_ADDED",
            entity_type="WorkRequest", entity_id=repair_id, operation="ADD_PHOTO",
            context=context, actor_user=user, after={"attachment_id": item.id,
                "filename": item.original_filename})
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return item


def timeline(db: Session, user: User, repair_id: int) -> list[AuditEvent]:
    visible_repair(db, user, repair_id)
    return list(db.scalars(select(AuditEvent).where(
        AuditEvent.tenant_id == user.tenant_id, AuditEvent.entity_type == "WorkRequest",
        AuditEvent.entity_id == str(repair_id),
    ).order_by(AuditEvent.occurred_at, AuditEvent.id)).all())
