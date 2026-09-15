from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_order import (
    SupplySupplierOrderCreationResult,
    SupplySupplierOrderPage,
    SupplySupplierOrderMessagePrepare,
    SupplySupplierOrderMessagePreview,
    SupplySupplierOrderRead,
    SupplySupplierOrderStatus,
    SupplySupplierOrderUpdate,
)
from app.supply.supplier_orders import (
    SupplierOrderConflictError,
    SupplierOrderEmptyError,
    SupplierOrderEmailError,
    SupplierOrderMessageStateError,
    SupplierOrderNotFoundError,
    SupplierOrderResponsiblePhoneError,
    SupplierOrderStateError,
    SupplierOrderSupplierInactiveError,
    cancel_supplier_order,
    list_supplier_orders,
    mark_supplier_order_ready,
    prepare_supplier_order_message,
    read_supplier_order,
    update_supplier_order,
)


router = APIRouter(prefix="/supply/supplier-orders", tags=["supply"])


def _error(error: Exception) -> HTTPException:
    if isinstance(error, SupplierOrderNotFoundError):
        return HTTPException(status_code=404, detail="Заказ поставщику не найден")
    if isinstance(error, SupplierOrderSupplierInactiveError):
        return HTTPException(status_code=409, detail="Нельзя зафиксировать заказ: поставщик находится в архиве")
    if isinstance(error, SupplierOrderEmptyError):
        return HTTPException(status_code=409, detail="Нельзя зафиксировать заказ без строк и положительной суммы")
    if isinstance(error, SupplierOrderConflictError):
        return HTTPException(status_code=409, detail="Исходные распределения заказа изменились или уже используются")
    if isinstance(error, SupplierOrderEmailError):
        return HTTPException(status_code=409, detail="У поставщика не указан корректный email для заказов")
    if isinstance(error, SupplierOrderResponsiblePhoneError):
        return HTTPException(status_code=409, detail="Укажите телефон ответственного")
    if isinstance(error, SupplierOrderMessageStateError):
        return HTTPException(status_code=409, detail="Подготовить сообщение можно только для готового заказа")
    return HTTPException(status_code=409, detail="Действие доступно только для черновика заказа")


@router.get("", response_model=SupplySupplierOrderPage)
def read_orders(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
    order_status: Annotated[SupplySupplierOrderStatus | None, Query(alias="status")] = None,
    supplier_id: UUID | None = None,
    search: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplySupplierOrderPage:
    items, total = list_supplier_orders(
        db, tenant_id=admin.tenant_id,
        status=order_status.value if order_status else None,
        supplier_id=supplier_id, search=search, limit=limit, offset=offset,
    )
    return SupplySupplierOrderPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{order_id}", response_model=SupplySupplierOrderRead)
def read_order(
    order_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierOrderRead:
    try:
        return read_supplier_order(db, order_id, tenant_id=admin.tenant_id)
    except SupplierOrderNotFoundError as error:
        raise _error(error) from error


@router.post("/{order_id}/prepare-message", response_model=SupplySupplierOrderMessagePreview)
def prepare_order_message(
    order_id: UUID, payload: SupplySupplierOrderMessagePrepare,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierOrderMessagePreview:
    try:
        return prepare_supplier_order_message(
            db, order_id, tenant_id=admin.tenant_id,
            responsible_name=admin.display_name,
            responsible_phone=payload.responsible_phone,
        )
    except (
        SupplierOrderNotFoundError, SupplierOrderMessageStateError,
        SupplierOrderEmptyError, SupplierOrderEmailError,
        SupplierOrderResponsiblePhoneError,
    ) as error:
        raise _error(error) from error


@router.patch("/{order_id}", response_model=SupplySupplierOrderRead)
def patch_order(
    order_id: UUID, payload: SupplySupplierOrderUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierOrderRead:
    try:
        return update_supplier_order(db, order_id, payload, tenant_id=admin.tenant_id)
    except (SupplierOrderNotFoundError, SupplierOrderStateError) as error:
        raise _error(error) from error


@router.post("/{order_id}/ready", response_model=SupplySupplierOrderRead)
def ready_order(
    order_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierOrderRead:
    try:
        return mark_supplier_order_ready(db, order_id, tenant_id=admin.tenant_id)
    except (SupplierOrderNotFoundError, SupplierOrderStateError, SupplierOrderEmptyError, SupplierOrderSupplierInactiveError, SupplierOrderConflictError) as error:
        raise _error(error) from error


@router.post("/{order_id}/cancel", response_model=SupplySupplierOrderRead)
def cancel_order(
    order_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierOrderRead:
    try:
        return cancel_supplier_order(db, order_id, tenant_id=admin.tenant_id)
    except (SupplierOrderNotFoundError, SupplierOrderStateError) as error:
        raise _error(error) from error
