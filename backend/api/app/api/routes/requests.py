from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.action_context import ActionContextError
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.requests.repair import visible_repair, visible_repairs, repair_read, add_comment
from app.models.work_request import WorkRequest, WorkRequestComment
from app.requests.service import (
    WorkRequestAttachmentNotFoundError,
    WorkRequestNotFoundError,
    WorkRequestTypeError,
    get_work_request_attachment,
    list_work_request_comments,
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
    current_admin: Annotated[User, Depends(get_current_user)],
) -> WorkRequest:
    raise HTTPException(status_code=405, detail="Используйте создание ремонта с выбором подразделения")


@router.get("", response_model=list[WorkRequestRead])
def read_requests(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[WorkRequest]:
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    try:
        return [repair_read(db, current_user, item) for item in visible_repairs(db, current_user)]
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра ремонтов") from error


@router.get("/{request_id}", response_model=WorkRequestRead)
def read_request(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkRequest:
    try:
        item = visible_repair(db, current_user, request_id)
        return repair_read(db, current_user, item)
    except (WorkRequestNotFoundError, ActionContextError) as error:
        raise _not_found() from error


@router.patch("/{request_id}", response_model=WorkRequestRead)
def change_request(
    request_id: int,
    payload: WorkRequestUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_user)],
) -> WorkRequest:
    raise HTTPException(status_code=405, detail="Используйте действия ремонта")


@router.patch("/{request_id}/status", response_model=WorkRequestRead)
def change_request_status(
    request_id: int,
    payload: WorkRequestStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_user)],
) -> WorkRequest:
    raise HTTPException(status_code=405, detail="Используйте действия ремонта")


@router.get(
    "/{request_id}/comments",
    response_model=list[WorkRequestCommentRead],
)
def read_request_comments(
    request_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[WorkRequestComment]:
    try:
        visible_repair(db, current_user, request_id)
        return list_work_request_comments(
            db, request_id, tenant_id=current_user.tenant_id
        )
    except (WorkRequestNotFoundError, ActionContextError) as error:
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
    current_admin: Annotated[User, Depends(get_current_user)],
) -> WorkRequestComment:
    try:
        return add_comment(db, current_admin, request_id, payload.body)
    except (WorkRequestNotFoundError, ActionContextError) as error:
        raise _not_found() from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
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
    current_user: Annotated[User, Depends(get_current_user)],
) -> FileResponse:
    try:
        visible_repair(db, current_user, request_id)
        attachment = get_work_request_attachment(
            db,
            request_id,
            attachment_id,
            tenant_id=current_user.tenant_id,
        )
    except (WorkRequestNotFoundError, ActionContextError) as error:
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
