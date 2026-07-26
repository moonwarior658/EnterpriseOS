from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.db.session import get_db
from app.models.work_request import WorkRequest
from app.requests.service import PendingAttachment, create_work_request
from app.schemas.work_request import WorkRequestCreate, WorkRequestRead


router = APIRouter(prefix="/public/requests", tags=["public-requests"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_ATTACHMENT_COUNT = 5
MAX_ATTACHMENT_SIZE = 8 * 1024 * 1024


async def _read_public_payload(
    request: Request,
) -> tuple[WorkRequestCreate, list[PendingAttachment]]:
    content_type = request.headers.get("content-type", "")
    attachments: list[PendingAttachment] = []

    try:
        if content_type.startswith("application/json"):
            data = await request.json()
        elif content_type.startswith(
            ("multipart/form-data", "application/x-www-form-urlencoded")
        ):
            form = await request.form()
            data = {
                "request_type": form.get("request_type"),
                "department": form.get("department"),
                "description": form.get("description"),
                "warehouse_category": form.get("warehouse_category") or None,
                "repair_category": form.get("repair_category") or None,
                "priority": form.get("priority") or None,
            }
            uploads = [
                item
                for item in form.getlist("photos")
                if isinstance(item, UploadFile) and item.filename
            ]
            if len(uploads) > MAX_ATTACHMENT_COUNT:
                for upload in uploads:
                    await upload.close()
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Можно прикрепить не более 5 фотографий",
                )
            for upload in uploads:
                if upload.content_type not in ALLOWED_IMAGE_TYPES:
                    await upload.close()
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Допустимы только фотографии JPEG, PNG или WebP",
                    )
                content = await upload.read(MAX_ATTACHMENT_SIZE + 1)
                await upload.close()
                if len(content) > MAX_ATTACHMENT_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Размер одной фотографии не должен превышать 8 МБ",
                    )
                if not content:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Пустой файл нельзя прикрепить",
                    )
                attachments.append(
                    PendingAttachment(
                        original_filename=Path(upload.filename).name or "photo",
                        content_type=upload.content_type,
                        content=content,
                    )
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Неподдерживаемый формат запроса",
            )

        payload = WorkRequestCreate.model_validate(data)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Проверьте заполнение полей заявки",
        ) from error
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Проверьте заполнение полей заявки",
        ) from error

    if attachments and payload.request_type.value != "repair":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Фотографии можно прикрепить только к заявке на ремонт",
        )
    return payload, attachments


@router.post(
    "",
    response_model=WorkRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_public_request(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> WorkRequest:
    payload, attachments = await _read_public_payload(request)
    return create_work_request(
        db,
        payload,
        created_by_user_id=None,
        attachments=attachments,
        upload_dir=Path(settings.work_request_upload_dir),
    )
