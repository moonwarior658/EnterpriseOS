from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_confirmation import (
    SupplySupplierConfirmationLineUpdate,
    SupplySupplierConfirmationRead,
    SupplySupplierConfirmationUpdate,
)
from app.supply.supplier_confirmations import (
    SupplierConfirmationConflictError,
    SupplierConfirmationNotFoundError,
    SupplierConfirmationStateError,
    SupplierConfirmationValidationError,
    cancel_confirmation,
    create_confirmation,
    list_confirmations,
    read_confirmation,
    record_confirmation,
    update_confirmation,
    update_confirmation_line,
)


order_router = APIRouter(prefix="/supply/supplier-orders", tags=["supply"])
confirmation_router = APIRouter(prefix="/supply/supplier-confirmations", tags=["supply"])


def _error(error: Exception) -> HTTPException:
    if isinstance(error, SupplierConfirmationNotFoundError):
        return HTTPException(status_code=404, detail="Подтверждение поставщика не найдено")
    if isinstance(error, SupplierConfirmationValidationError):
        return HTTPException(status_code=409, detail="Заполните подтверждение по всем строкам заказа")
    if isinstance(error, SupplierConfirmationConflictError):
        return HTTPException(status_code=409, detail="Подтверждение уже изменено другим пользователем")
    return HTTPException(status_code=409, detail="Действие доступно только для черновика ответа по отправленному заказу")


@order_router.post("/{order_id}/confirmations", response_model=SupplySupplierConfirmationRead)
def create_order_confirmation(
    order_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierConfirmationRead:
    try:
        return create_confirmation(db, order_id, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierConfirmationNotFoundError, SupplierConfirmationStateError, SupplierConfirmationConflictError, SupplierConfirmationValidationError) as error:
        raise _error(error) from error


@order_router.get("/{order_id}/confirmations", response_model=list[SupplySupplierConfirmationRead])
def read_order_confirmations(
    order_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> list[SupplySupplierConfirmationRead]:
    try:
        return list_confirmations(db, order_id, tenant_id=admin.tenant_id)
    except SupplierConfirmationNotFoundError as error:
        raise _error(error) from error


@confirmation_router.get("/{confirmation_id}", response_model=SupplySupplierConfirmationRead)
def read_supplier_confirmation(
    confirmation_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierConfirmationRead:
    try:
        return read_confirmation(db, confirmation_id, tenant_id=admin.tenant_id)
    except SupplierConfirmationNotFoundError as error:
        raise _error(error) from error


@confirmation_router.patch("/{confirmation_id}", response_model=SupplySupplierConfirmationRead)
def patch_supplier_confirmation(
    confirmation_id: UUID, payload: SupplySupplierConfirmationUpdate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierConfirmationRead:
    try:
        return update_confirmation(db, confirmation_id, payload, tenant_id=admin.tenant_id)
    except (
        SupplierConfirmationNotFoundError, SupplierConfirmationStateError,
        SupplierConfirmationValidationError, SupplierConfirmationConflictError,
    ) as error:
        raise _error(error) from error


@confirmation_router.patch("/{confirmation_id}/lines/{line_id}", response_model=SupplySupplierConfirmationRead)
def patch_supplier_confirmation_line(
    confirmation_id: UUID, line_id: UUID, payload: SupplySupplierConfirmationLineUpdate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierConfirmationRead:
    try:
        return update_confirmation_line(db, confirmation_id, line_id, payload, tenant_id=admin.tenant_id)
    except (
        SupplierConfirmationNotFoundError, SupplierConfirmationStateError,
        SupplierConfirmationValidationError, SupplierConfirmationConflictError,
    ) as error:
        raise _error(error) from error


@confirmation_router.post("/{confirmation_id}/record", response_model=SupplySupplierConfirmationRead)
def record_supplier_confirmation(
    confirmation_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierConfirmationRead:
    try:
        return record_confirmation(db, confirmation_id, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierConfirmationNotFoundError, SupplierConfirmationStateError, SupplierConfirmationValidationError, SupplierConfirmationConflictError) as error:
        raise _error(error) from error


@confirmation_router.post("/{confirmation_id}/cancel", response_model=SupplySupplierConfirmationRead)
def cancel_supplier_confirmation(
    confirmation_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierConfirmationRead:
    try:
        return cancel_confirmation(db, confirmation_id, tenant_id=admin.tenant_id)
    except (SupplierConfirmationNotFoundError, SupplierConfirmationStateError) as error:
        raise _error(error) from error
