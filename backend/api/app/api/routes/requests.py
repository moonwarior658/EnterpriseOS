from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin, require_request_view_access
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.models.work_request import WorkRequest, WorkRequestComment
from app.requests.service import (
    WorkRequestAttachmentNotFoundError,
    WorkRequestNotFoundError,
    WorkRequestTypeError,
    create_work_request,
    create_work_request_comment,
    get_work_request,
    get_work_request_attachment,
    list_work_request_comments,
    list_work_requests,
    update_work_request,
    update_work_request_status,
)
from app.schemas.work_request import (
    WorkRequestCommentCreate,
    WorkRequestCommentRead,
    WorkRequestCreate,
    WorkRequestRead,
    WorkRequestStatusUpdate,
    WorkRequestUpdate,
)


router = APIRouter(prefix="/requests", tags=["requests"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Request not found",
    )


@router.post(
    "",
    response_model=WorkRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: WorkRequestCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> WorkRequest:
    return create_work_request(
        db,
        payload,
        created_by_user_id=current_admin.id,
        tenant_id=current_admin.tenant_id,
    )


@router.get("", response_model=list[WorkRequestRead])
def read_requests(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_request_view_access)],
) -> list[WorkRequest]:
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return list_work_requests(db, tenant_id=current_user.tenant_id)


@router.get("/{request_id}", response_model=WorkRequestRead)
def read_request(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_request_view_access)],
) -> WorkRequest:
    try:
        return get_work_request(
            db, request_id, tenant_id=current_user.tenant_id
        )
    except WorkRequestNotFoundError as error:
        raise _not_found() from error


@router.patch("/{request_id}", response_model=WorkRequestRead)
def change_request(
    request_id: int,
    payload: WorkRequestUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> WorkRequest:
    try:
        return update_work_request(
            db, request_id, payload, tenant_id=current_admin.tenant_id
        )
    except WorkRequestNotFoundError as error:
        raise _not_found() from error
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Check the request fields",
        ) from error


@router.patch("/{request_id}/status", response_model=WorkRequestRead)
def change_request_status(
    request_id: int,
    payload: WorkRequestStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> WorkRequest:
    try:
        return update_work_request_status(
            db, request_id, payload, tenant_id=current_admin.tenant_id
        )
    except WorkRequestNotFoundError as error:
        raise _not_found() from error


@router.get(
    "/{request_id}/comments",
    response_model=list[WorkRequestCommentRead],
)
def read_request_comments(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_request_view_access)],
) -> list[WorkRequestComment]:
    try:
        return list_work_request_comments(
            db, request_id, tenant_id=current_user.tenant_id
        )
    except WorkRequestNotFoundError as error:
        raise _not_found() from error
    except WorkRequestTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Comments are available only for repair requests",
        ) from error


@router.post(
    "/{request_id}/comments",
    response_model=WorkRequestCommentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_request_comment(
    request_id: int,
    payload: WorkRequestCommentCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> WorkRequestComment:
    try:
        return create_work_request_comment(
            db,
            request_id,
            payload,
            author_user_id=current_admin.id,
            tenant_id=current_admin.tenant_id,
        )
    except WorkRequestNotFoundError as error:
        raise _not_found() from error
    except WorkRequestTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Comments are available only for repair requests",
        ) from error


@router.get("/{request_id}/attachments/{attachment_id}")
def read_request_attachment(
    request_id: int,
    attachment_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_request_view_access)],
) -> FileResponse:
    try:
        attachment = get_work_request_attachment(
            db,
            request_id,
            attachment_id,
            tenant_id=current_user.tenant_id,
        )
    except WorkRequestNotFoundError as error:
        raise _not_found() from error
    except WorkRequestAttachmentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        ) from error

    upload_root = Path(settings.work_request_upload_dir).resolve()
    file_path = (upload_root / attachment.stored_filename).resolve()
    if file_path.parent != upload_root or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )
    return FileResponse(file_path, media_type=attachment.content_type)
