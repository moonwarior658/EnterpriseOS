from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_acceptance import (
    SupplySupplierAcceptanceCreate, SupplySupplierAcceptanceLineCreate,
    SupplySupplierAcceptanceLineUpdate, SupplySupplierAcceptanceRead,
    SupplySupplierAcceptanceUpdate,
)
from app.supply.supplier_acceptances import (
    SupplierAcceptanceConflictError, SupplierAcceptanceLinkError,
    SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError,
    SupplierAcceptanceUnitError, SupplierAcceptanceValidationError,
    cancel_acceptance, create_acceptance, create_line, delete_line,
    list_acceptances, read_acceptance, record_acceptance, update_acceptance, update_line,
)

order_router = APIRouter(prefix="/supply/supplier-orders", tags=["supply"])
acceptance_router = APIRouter(prefix="/supply/supplier-acceptances", tags=["supply"])


def _error(error: Exception):
    if isinstance(error, SupplierAcceptanceNotFoundError):
        return HTTPException(404, "Приёмка не найдена")
    if isinstance(error, SupplierAcceptanceUnitError):
        return HTTPException(422, "Изменение единицы при приёмке пока не поддерживается")
    if isinstance(error, SupplierAcceptanceLinkError):
        return HTTPException(409, "Источник строки приёмки не соответствует заказу")
    if isinstance(error, SupplierAcceptanceValidationError):
        return HTTPException(422, "Проверьте количества и причину отклонения")
    if isinstance(error, SupplierAcceptanceConflictError):
        return HTTPException(409, "Приёмка конфликтует с уже зафиксированными данными")
    return HTTPException(409, "Изменение доступно только для черновика приёмки отправленного заказа")


@order_router.post("/{order_id}/acceptances", response_model=SupplySupplierAcceptanceRead, status_code=status.HTTP_201_CREATED)
def create(order_id: UUID, payload: SupplySupplierAcceptanceCreate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return create_acceptance(db, order_id, payload, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceLinkError, SupplierAcceptanceConflictError) as error: raise _error(error) from error


@order_router.get("/{order_id}/acceptances", response_model=list[SupplySupplierAcceptanceRead])
def listing(order_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return list_acceptances(db, order_id, tenant_id=admin.tenant_id)
    except SupplierAcceptanceNotFoundError as error: raise _error(error) from error


@acceptance_router.get("/{acceptance_id}", response_model=SupplySupplierAcceptanceRead)
def read(acceptance_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return read_acceptance(db, acceptance_id, tenant_id=admin.tenant_id)
    except SupplierAcceptanceNotFoundError as error: raise _error(error) from error


@acceptance_router.patch("/{acceptance_id}", response_model=SupplySupplierAcceptanceRead)
def patch(acceptance_id: UUID, payload: SupplySupplierAcceptanceUpdate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return update_acceptance(db, acceptance_id, payload, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError) as error: raise _error(error) from error


@acceptance_router.post("/{acceptance_id}/lines", response_model=SupplySupplierAcceptanceRead)
def add_line(acceptance_id: UUID, payload: SupplySupplierAcceptanceLineCreate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return create_line(db, acceptance_id, payload, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceValidationError, SupplierAcceptanceLinkError, SupplierAcceptanceUnitError) as error: raise _error(error) from error


@acceptance_router.patch("/{acceptance_id}/lines/{line_id}", response_model=SupplySupplierAcceptanceRead)
def patch_line(acceptance_id: UUID, line_id: UUID, payload: SupplySupplierAcceptanceLineUpdate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return update_line(db, acceptance_id, line_id, payload, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceValidationError) as error: raise _error(error) from error


@acceptance_router.delete("/{acceptance_id}/lines/{line_id}", response_model=SupplySupplierAcceptanceRead)
def remove_line(acceptance_id: UUID, line_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return delete_line(db, acceptance_id, line_id, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError) as error: raise _error(error) from error


@acceptance_router.post("/{acceptance_id}/record", response_model=SupplySupplierAcceptanceRead)
def record(acceptance_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return record_acceptance(db, acceptance_id, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceValidationError, SupplierAcceptanceConflictError, SupplierAcceptanceUnitError) as error: raise _error(error) from error


@acceptance_router.post("/{acceptance_id}/cancel", response_model=SupplySupplierAcceptanceRead)
def cancel(acceptance_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return cancel_acceptance(db, acceptance_id, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError) as error: raise _error(error) from error
