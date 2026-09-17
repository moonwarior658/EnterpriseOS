from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
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
    create_document,
    create_document_line,
    delete_document_line,
    list_documents,
    read_document,
    record_document,
    update_document,
    update_document_line,
)


order_router = APIRouter(prefix="/supply/supplier-orders", tags=["supply"])
document_router = APIRouter(prefix="/supply/supplier-documents", tags=["supply"])


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
            detail="Документ с таким номером и датой уже зарегистрирован",
        )
    if isinstance(error, SupplierDocumentLinkError):
        return HTTPException(
            status_code=409,
            detail="Строка документа не соответствует заказу или подтверждению поставщика",
        )
    if isinstance(error, SupplierDocumentValidationError):
        return HTTPException(
            status_code=409,
            detail="Заполните номер, дату и корректные позиции документа",
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
        SupplierDocumentConflictError, SupplierDocumentValidationError,
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
        SupplierDocumentConflictError, SupplierDocumentValidationError,
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
        SupplierDocumentConflictError,
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
