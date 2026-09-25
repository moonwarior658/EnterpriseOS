from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_document import (
    SupplySupplierDocumentCreate,
    SupplySupplierDocumentLineCreate,
    SupplySupplierDocumentLineUpdate,
    SupplySupplierDocumentRead,
    SupplySupplierDocumentUpdate,
)
from app.supply.supplier_documents import (
    SupplierDocumentConflictError,
    SupplierDocumentLinkError,
    SupplierDocumentNotFoundError,
    SupplierDocumentReviewError,
    SupplierDocumentStateError,
    SupplierDocumentValidationError,
    cancel_document,
    create_attachment,
    create_document,
    create_document_line,
    delete_document_line,
    delete_attachment,
    get_attachment,
    list_documents,
    read_document,
    record_document,
    update_document,
    update_document_line,
)


order_router = APIRouter(prefix="/supply/supplier-orders", tags=["supply"])
document_router = APIRouter(prefix="/supply/supplier-documents", tags=["supply"])
ALLOWED_ATTACHMENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_ATTACHMENT_SIZE = 15 * 1024 * 1024


def _error(error: Exception) -> HTTPException:
    if isinstance(error, SupplierDocumentNotFoundError):
        return HTTPException(status_code=404, detail="Документ поставщика не найден")
    if isinstance(error, SupplierDocumentReviewError):
        return HTTPException(
            status_code=409,
            detail="Сначала примите решения по обязательным отклонениям ответа поставщика",
        )
    if isinstance(error, SupplierDocumentConflictError):
        return HTTPException(
            status_code=409,
            detail=(
                "Документ с таким номером уже существует или в обязательстве уже есть "
                "финансовое основание"
            ),
        )
    if isinstance(error, SupplierDocumentLinkError):
        return HTTPException(
            status_code=409,
            detail="Строка документа не соответствует заказу или подтверждению поставщика",
        )
    if isinstance(error, SupplierDocumentValidationError):
        return HTTPException(
            status_code=409,
            detail="Проверьте реквизиты, строки и вложения документа",
        )
    return HTTPException(
        status_code=409,
        detail="Изменение доступно только для черновика документа отправленного заказа",
    )


@order_router.post(
    "/{order_id}/documents", response_model=SupplySupplierDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_supplier_document(
    order_id: UUID, payload: SupplySupplierDocumentCreate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return create_document(
            db, order_id, payload, tenant_id=admin.tenant_id, user_id=admin.id,
        )
    except (
        SupplierDocumentNotFoundError, SupplierDocumentStateError,
        SupplierDocumentConflictError, SupplierDocumentValidationError, SupplierDocumentLinkError,
    ) as error:
        raise _error(error) from error


@order_router.get("/{order_id}/documents", response_model=list[SupplySupplierDocumentRead])
def read_supplier_documents(
    order_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> list[SupplySupplierDocumentRead]:
    try:
        return list_documents(db, order_id, tenant_id=admin.tenant_id)
    except SupplierDocumentNotFoundError as error:
        raise _error(error) from error


@document_router.get("/{document_id}", response_model=SupplySupplierDocumentRead)
def read_supplier_document(
    document_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return read_document(db, document_id, tenant_id=admin.tenant_id)
    except SupplierDocumentNotFoundError as error:
        raise _error(error) from error


@document_router.patch("/{document_id}", response_model=SupplySupplierDocumentRead)
def patch_supplier_document(
    document_id: UUID, payload: SupplySupplierDocumentUpdate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return update_document(db, document_id, payload, tenant_id=admin.tenant_id)
    except (
        SupplierDocumentNotFoundError, SupplierDocumentStateError,
        SupplierDocumentConflictError, SupplierDocumentValidationError, SupplierDocumentLinkError,
    ) as error:
        raise _error(error) from error


@document_router.post("/{document_id}/lines", response_model=SupplySupplierDocumentRead)
def create_supplier_document_line(
    document_id: UUID, payload: SupplySupplierDocumentLineCreate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return create_document_line(db, document_id, payload, tenant_id=admin.tenant_id)
    except (
        SupplierDocumentNotFoundError, SupplierDocumentStateError,
        SupplierDocumentValidationError, SupplierDocumentLinkError,
    ) as error:
        raise _error(error) from error


@document_router.patch("/{document_id}/lines/{line_id}", response_model=SupplySupplierDocumentRead)
def patch_supplier_document_line(
    document_id: UUID, line_id: UUID, payload: SupplySupplierDocumentLineUpdate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return update_document_line(
            db, document_id, line_id, payload, tenant_id=admin.tenant_id,
        )
    except (
        SupplierDocumentNotFoundError, SupplierDocumentStateError,
        SupplierDocumentValidationError, SupplierDocumentLinkError,
    ) as error:
        raise _error(error) from error


@document_router.delete("/{document_id}/lines/{line_id}", response_model=SupplySupplierDocumentRead)
def remove_supplier_document_line(
    document_id: UUID, line_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return delete_document_line(
            db, document_id, line_id, tenant_id=admin.tenant_id,
        )
    except (SupplierDocumentNotFoundError, SupplierDocumentStateError) as error:
        raise _error(error) from error


@document_router.post("/{document_id}/record", response_model=SupplySupplierDocumentRead)
def record_supplier_document(
    document_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return record_document(
            db, document_id, tenant_id=admin.tenant_id, user_id=admin.id,
        )
    except (
        SupplierDocumentNotFoundError, SupplierDocumentStateError,
        SupplierDocumentValidationError, SupplierDocumentReviewError,
        SupplierDocumentConflictError, SupplierDocumentLinkError,
    ) as error:
        raise _error(error) from error


@document_router.post("/{document_id}/cancel", response_model=SupplySupplierDocumentRead)
def cancel_supplier_document(
    document_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return cancel_document(db, document_id, tenant_id=admin.tenant_id)
    except (SupplierDocumentNotFoundError, SupplierDocumentStateError) as error:
        raise _error(error) from error


@document_router.post(
    "/{document_id}/attachments", response_model=SupplySupplierDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_supplier_document_attachment(
    document_id: UUID,
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    if file.content_type not in ALLOWED_ATTACHMENT_TYPES:
        await file.close()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Допустимы PDF, JPEG и PNG",
        )
    content = await file.read(MAX_ATTACHMENT_SIZE + 1)
    await file.close()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Пустой файл нельзя прикрепить")
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Размер файла не должен превышать 15 МБ",
        )
    try:
        return create_attachment(
            db,
            document_id,
            tenant_id=admin.tenant_id,
            user_id=admin.id,
            original_filename=file.filename or "document",
            content_type=file.content_type,
            content=content,
            upload_dir=Path(settings.supplier_document_upload_dir),
        )
    except (
        SupplierDocumentNotFoundError,
        SupplierDocumentStateError,
        SupplierDocumentValidationError,
    ) as error:
        raise _error(error) from error


@document_router.get("/{document_id}/attachments/{attachment_id}")
def read_supplier_document_attachment(
    document_id: UUID,
    attachment_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> FileResponse:
    try:
        attachment = get_attachment(
            db, document_id, attachment_id, tenant_id=admin.tenant_id,
        )
    except SupplierDocumentNotFoundError as error:
        raise _error(error) from error
    upload_root = Path(settings.supplier_document_upload_dir).resolve()
    file_path = (upload_root / attachment.stored_filename).resolve()
    if file_path.parent != upload_root or not file_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл документа не найден")
    return FileResponse(file_path, media_type=attachment.content_type)


@document_router.delete(
    "/{document_id}/attachments/{attachment_id}",
    response_model=SupplySupplierDocumentRead,
)
def remove_supplier_document_attachment(
    document_id: UUID,
    attachment_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierDocumentRead:
    try:
        return delete_attachment(
            db,
            document_id,
            attachment_id,
            tenant_id=admin.tenant_id,
            upload_dir=Path(settings.supplier_document_upload_dir),
        )
    except (SupplierDocumentNotFoundError, SupplierDocumentStateError) as error:
        raise _error(error) from error
