from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.work_request import (
    WorkRequest,
    WorkRequestAttachment,
    WorkRequestComment,
)
from app.schemas.work_request import (
    WorkRequestCommentCreate,
    WorkRequestCreate,
    WorkRequestStatusUpdate,
    WorkRequestUpdate,
)


class WorkRequestNotFoundError(LookupError):
    pass


class WorkRequestTypeError(ValueError):
    pass


class WorkRequestAttachmentNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class PendingAttachment:
    original_filename: str
    content_type: str
    content: bytes


def _request_options():
    return (
        joinedload(WorkRequest.created_by),
        selectinload(WorkRequest.attachments),
    )


def list_work_requests(session: Session) -> list[WorkRequest]:
    statement = (
        select(WorkRequest)
        .where(WorkRequest.request_type == "repair")
        .options(*_request_options())
        .order_by(WorkRequest.created_at.desc(), WorkRequest.id.desc())
    )
    return list(session.scalars(statement).all())


def get_work_request(session: Session, request_id: int) -> WorkRequest:
    statement = (
        select(WorkRequest)
        .where(
            WorkRequest.id == request_id,
            WorkRequest.request_type == "repair",
        )
        .options(*_request_options())
    )
    work_request = session.scalar(statement)
    if work_request is None:
        raise WorkRequestNotFoundError
    return work_request


def create_work_request(
    session: Session,
    payload: WorkRequestCreate,
    *,
    created_by_user_id: int | None,
    attachments: list[PendingAttachment] | None = None,
    upload_dir: Path | None = None,
) -> WorkRequest:
    pending_attachments = attachments or []
    if pending_attachments and payload.request_type.value != "repair":
        raise WorkRequestTypeError
    if pending_attachments and upload_dir is None:
        raise ValueError("Upload directory is required")

    work_request = WorkRequest(
        request_type=payload.request_type.value,
        department=payload.department,
        description=payload.description,
        status="new",
        warehouse_category=None,
        repair_category=payload.repair_category,
        priority=payload.priority.value if payload.priority is not None else None,
        created_by_user_id=created_by_user_id,
        author_name=None,
    )
    written_paths: list[Path] = []

    try:
        session.add(work_request)
        session.flush()

        if upload_dir is not None:
            upload_dir.mkdir(parents=True, exist_ok=True)
            upload_root = upload_dir.resolve()
            for pending in pending_attachments:
                suffix = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/webp": ".webp",
                }[pending.content_type]
                stored_filename = f"{uuid4().hex}{suffix}"
                target = (upload_root / stored_filename).resolve()
                if target.parent != upload_root:
                    raise ValueError("Invalid upload path")
                target.write_bytes(pending.content)
                written_paths.append(target)
                session.add(
                    WorkRequestAttachment(
                        work_request_id=work_request.id,
                        original_filename=pending.original_filename[:255],
                        stored_filename=stored_filename,
                        content_type=pending.content_type,
                        size_bytes=len(pending.content),
                    )
                )

        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        raise

    return get_work_request(session, work_request.id)


def update_work_request(
    session: Session,
    request_id: int,
    payload: WorkRequestUpdate,
) -> WorkRequest:
    work_request = get_work_request(session, request_id)
    changes = payload.model_dump(exclude_unset=True)

    candidate = WorkRequestCreate(
        request_type=work_request.request_type,
        department="М15",
        description=changes.get("description", work_request.description),
        repair_category=changes.get(
            "repair_category", work_request.repair_category
        ),
        priority=changes.get("priority", work_request.priority),
    )

    try:
        work_request.department = changes.get(
            "department",
            work_request.department,
        )
        work_request.description = candidate.description
        work_request.warehouse_category = None
        work_request.repair_category = candidate.repair_category
        work_request.priority = (
            candidate.priority.value if candidate.priority is not None else None
        )
        if payload.status is not None:
            work_request.status = payload.status.value
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise

    return get_work_request(session, request_id)


def update_work_request_status(
    session: Session,
    request_id: int,
    payload: WorkRequestStatusUpdate,
) -> WorkRequest:
    return update_work_request(
        session,
        request_id,
        WorkRequestUpdate(status=payload.status),
    )


def list_work_request_comments(
    session: Session,
    request_id: int,
) -> list[WorkRequestComment]:
    work_request = session.get(WorkRequest, request_id)
    if work_request is None:
        raise WorkRequestNotFoundError
    if work_request.request_type != "repair":
        raise WorkRequestTypeError

    statement = (
        select(WorkRequestComment)
        .where(WorkRequestComment.work_request_id == request_id)
        .options(joinedload(WorkRequestComment.author))
        .order_by(
            WorkRequestComment.created_at.asc(),
            WorkRequestComment.id.asc(),
        )
    )
    return list(session.scalars(statement).all())


def create_work_request_comment(
    session: Session,
    request_id: int,
    payload: WorkRequestCommentCreate,
    *,
    author_user_id: int,
) -> WorkRequestComment:
    work_request = session.get(WorkRequest, request_id)
    if work_request is None:
        raise WorkRequestNotFoundError
    if work_request.request_type != "repair":
        raise WorkRequestTypeError

    comment = WorkRequestComment(
        work_request_id=request_id,
        author_user_id=author_user_id,
        body=payload.body,
    )
    try:
        session.add(comment)
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise

    statement = (
        select(WorkRequestComment)
        .where(WorkRequestComment.id == comment.id)
        .options(joinedload(WorkRequestComment.author))
    )
    stored_comment = session.scalar(statement)
    if stored_comment is None:
        raise RuntimeError("Created comment could not be loaded")
    return stored_comment


def get_work_request_attachment(
    session: Session,
    request_id: int,
    attachment_id: int,
) -> WorkRequestAttachment:
    if session.get(WorkRequest, request_id) is None:
        raise WorkRequestNotFoundError
    statement = select(WorkRequestAttachment).where(
        WorkRequestAttachment.id == attachment_id,
        WorkRequestAttachment.work_request_id == request_id,
    )
    attachment = session.scalar(statement)
    if attachment is None:
        raise WorkRequestAttachmentNotFoundError
    return attachment
