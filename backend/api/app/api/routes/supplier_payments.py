from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_payment import (
    SupplySupplierPaymentCreate,
    SupplySupplierPaymentPage,
    SupplySupplierPaymentRead,
    SupplySupplierPaymentStatus,
    SupplySupplierPaymentType,
    SupplySupplierPaymentUpdate,
)
from app.supply.supplier_payments import (
    SupplierPaymentConflictError,
    SupplierPaymentLinkError,
    SupplierPaymentNotFoundError,
    SupplierPaymentStateError,
    SupplierPaymentValidationError,
    cancel_payment,
    create_payment,
    list_payments,
    read_payment,
    record_payment,
    update_payment,
)


router = APIRouter(prefix="/supply/supplier-payments", tags=["supply"])


def _error(error: Exception) -> HTTPException:
    if isinstance(error, SupplierPaymentNotFoundError):
        return HTTPException(status_code=404, detail="Оплата поставщику не найдена")
    if isinstance(error, SupplierPaymentConflictError):
        return HTTPException(status_code=409, detail="Платёжное поручение уже зарегистрировано")
    if isinstance(error, SupplierPaymentLinkError):
        return HTTPException(
            status_code=409,
            detail="Документ или заказ не соответствует поставщику",
        )
    if isinstance(error, SupplierPaymentValidationError):
        return HTTPException(status_code=409, detail="Проверьте реквизиты и связи оплаты")
    return HTTPException(status_code=409, detail="Зафиксированную оплату изменить нельзя")


@router.get("", response_model=SupplySupplierPaymentPage)
def read_payments(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
    supplier_id: UUID | None = None,
    payment_status: Annotated[SupplySupplierPaymentStatus | None, Query(alias="status")] = None,
    payment_type: SupplySupplierPaymentType | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    payment_order_number: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplySupplierPaymentPage:
    items, total = list_payments(
        db,
        tenant_id=admin.tenant_id,
        supplier_id=supplier_id,
        status=payment_status.value if payment_status else None,
        payment_type=payment_type.value if payment_type else None,
        date_from=date_from,
        date_to=date_to,
        payment_order_number=payment_order_number,
        limit=limit,
        offset=offset,
    )
    return SupplySupplierPaymentPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{payment_id}", response_model=SupplySupplierPaymentRead)
def read_supplier_payment(
    payment_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierPaymentRead:
    try:
        return read_payment(db, payment_id, tenant_id=admin.tenant_id)
    except SupplierPaymentNotFoundError as error:
        raise _error(error) from error


@router.post("", response_model=SupplySupplierPaymentRead, status_code=status.HTTP_201_CREATED)
def create_supplier_payment(
    payload: SupplySupplierPaymentCreate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierPaymentRead:
    try:
        return create_payment(db, payload, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierPaymentConflictError, SupplierPaymentLinkError, SupplierPaymentValidationError) as error:
        raise _error(error) from error


@router.patch("/{payment_id}", response_model=SupplySupplierPaymentRead)
def patch_supplier_payment(
    payment_id: UUID, payload: SupplySupplierPaymentUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierPaymentRead:
    try:
        return update_payment(db, payment_id, payload, tenant_id=admin.tenant_id)
    except (
        SupplierPaymentNotFoundError, SupplierPaymentStateError,
        SupplierPaymentConflictError, SupplierPaymentLinkError,
        SupplierPaymentValidationError,
    ) as error:
        raise _error(error) from error


@router.post("/{payment_id}/record", response_model=SupplySupplierPaymentRead)
def record_supplier_payment(
    payment_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierPaymentRead:
    try:
        return record_payment(
            db, payment_id, tenant_id=admin.tenant_id, user_id=admin.id,
        )
    except (
        SupplierPaymentNotFoundError, SupplierPaymentStateError,
        SupplierPaymentConflictError, SupplierPaymentLinkError,
        SupplierPaymentValidationError,
    ) as error:
        raise _error(error) from error


@router.post("/{payment_id}/cancel", response_model=SupplySupplierPaymentRead)
def cancel_supplier_payment(
    payment_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierPaymentRead:
    try:
        return cancel_payment(db, payment_id, tenant_id=admin.tenant_id)
    except (SupplierPaymentNotFoundError, SupplierPaymentStateError) as error:
        raise _error(error) from error
