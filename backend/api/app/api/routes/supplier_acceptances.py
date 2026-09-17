from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_acceptance import (
    SupplyAcceptanceResolutionRead, SupplyAcceptanceResolutionResolve,
    SupplySupplierAcceptanceCreate, SupplySupplierAcceptanceLineCreate,
    SupplySupplierAcceptanceLineSourcesUpdate, SupplySupplierAcceptanceLineUpdate,
    SupplySupplierAcceptanceRead,
    SupplySupplierAcceptanceUpdate,
)
from app.supply.supplier_acceptances import (
    SupplierAcceptanceResolutionNeedDateError,
    SupplierAcceptanceResolutionNotFoundError,
    SupplierAcceptanceResolutionQuantityError,
    SupplierAcceptanceResolutionSourceError,
    SupplierAcceptanceResolutionStateError,
    SupplierAcceptanceResolutionTypeError,
    SupplierAcceptanceConflictError, SupplierAcceptanceLinkError,
    SupplierAcceptanceDestinationError,
    SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError,
    SupplierAcceptanceUnitError, SupplierAcceptanceValidationError,
    cancel_acceptance, create_acceptance, create_line, delete_line,
    list_acceptance_resolutions, list_acceptances, read_acceptance,
    read_acceptance_resolution, record_acceptance, resolve_acceptance_resolution,
    update_acceptance, update_acceptance_line_sources, update_line,
)

order_router = APIRouter(prefix="/supply/supplier-orders", tags=["supply"])
acceptance_router = APIRouter(prefix="/supply/supplier-acceptances", tags=["supply"])
resolution_router = APIRouter(prefix="/supply/acceptance-resolutions", tags=["supply"])


def _error(error: Exception):
    if isinstance(error, SupplierAcceptanceResolutionNotFoundError):
        return HTTPException(404, "Расхождение приёмки не найдено")
    if isinstance(error, SupplierAcceptanceResolutionNeedDateError):
        return HTTPException(422, "Не удалось однозначно определить дату потребности")
    if isinstance(error, SupplierAcceptanceResolutionSourceError):
        return HTTPException(422, "Для возврата в закупку нужны сопоставленные товар и единица")
    if isinstance(error, SupplierAcceptanceResolutionQuantityError):
        return HTTPException(422, "Количество для закупки должно иметь не более трёх знаков после запятой")
    if isinstance(error, SupplierAcceptanceResolutionTypeError):
        return HTTPException(422, "Решение не соответствует типу расхождения")
    if isinstance(error, SupplierAcceptanceResolutionStateError):
        return HTTPException(409, "Решение по расхождению уже зафиксировано")
    if isinstance(error, SupplierAcceptanceNotFoundError):
        return HTTPException(404, "Приёмка не найдена")
    if isinstance(error, SupplierAcceptanceUnitError):
        return HTTPException(422, "Изменение единицы при приёмке пока не поддерживается")
    if isinstance(error, SupplierAcceptanceDestinationError):
        return HTTPException(422, "Выберите действующий склад приёмки")
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
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceLinkError, SupplierAcceptanceConflictError, SupplierAcceptanceDestinationError) as error: raise _error(error) from error


@order_router.get("/{order_id}/acceptances", response_model=list[SupplySupplierAcceptanceRead])
def listing(order_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return list_acceptances(db, order_id, tenant_id=admin.tenant_id)
    except SupplierAcceptanceNotFoundError as error: raise _error(error) from error


@acceptance_router.get("/{acceptance_id}", response_model=SupplySupplierAcceptanceRead)
def read(acceptance_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return read_acceptance(db, acceptance_id, tenant_id=admin.tenant_id)
    except SupplierAcceptanceNotFoundError as error: raise _error(error) from error


@acceptance_router.get("/{acceptance_id}/resolutions", response_model=list[SupplyAcceptanceResolutionRead])
def resolutions(acceptance_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return list_acceptance_resolutions(db, acceptance_id, tenant_id=admin.tenant_id)
    except SupplierAcceptanceNotFoundError as error: raise _error(error) from error


@resolution_router.get("/{resolution_id}", response_model=SupplyAcceptanceResolutionRead)
def read_resolution(resolution_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return read_acceptance_resolution(db, resolution_id, tenant_id=admin.tenant_id)
    except SupplierAcceptanceResolutionNotFoundError as error: raise _error(error) from error


@resolution_router.post("/{resolution_id}/resolve", response_model=SupplyAcceptanceResolutionRead)
def resolve_resolution(resolution_id: UUID, payload: SupplyAcceptanceResolutionResolve, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try:
        return resolve_acceptance_resolution(
            db, resolution_id, payload, tenant_id=admin.tenant_id, user_id=admin.id
        )
    except (
        SupplierAcceptanceResolutionNotFoundError,
        SupplierAcceptanceResolutionNeedDateError,
        SupplierAcceptanceResolutionSourceError,
        SupplierAcceptanceResolutionQuantityError,
        SupplierAcceptanceResolutionStateError,
        SupplierAcceptanceResolutionTypeError,
        SupplierAcceptanceConflictError,
    ) as error:
        raise _error(error) from error


@acceptance_router.patch("/{acceptance_id}", response_model=SupplySupplierAcceptanceRead)
def patch(acceptance_id: UUID, payload: SupplySupplierAcceptanceUpdate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return update_acceptance(db, acceptance_id, payload, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceDestinationError) as error: raise _error(error) from error


@acceptance_router.post("/{acceptance_id}/lines", response_model=SupplySupplierAcceptanceRead)
def add_line(acceptance_id: UUID, payload: SupplySupplierAcceptanceLineCreate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return create_line(db, acceptance_id, payload, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceValidationError, SupplierAcceptanceLinkError, SupplierAcceptanceUnitError) as error: raise _error(error) from error


@acceptance_router.patch("/{acceptance_id}/lines/{line_id}", response_model=SupplySupplierAcceptanceRead)
def patch_line(acceptance_id: UUID, line_id: UUID, payload: SupplySupplierAcceptanceLineUpdate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return update_line(db, acceptance_id, line_id, payload, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceValidationError) as error: raise _error(error) from error


@acceptance_router.put("/{acceptance_id}/lines/{line_id}/sources", response_model=SupplySupplierAcceptanceRead)
def patch_line_sources(acceptance_id: UUID, line_id: UUID, payload: SupplySupplierAcceptanceLineSourcesUpdate, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return update_acceptance_line_sources(db, acceptance_id, line_id, payload.sources, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceValidationError, SupplierAcceptanceConflictError) as error: raise _error(error) from error


@acceptance_router.delete("/{acceptance_id}/lines/{line_id}", response_model=SupplySupplierAcceptanceRead)
def remove_line(acceptance_id: UUID, line_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return delete_line(db, acceptance_id, line_id, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError) as error: raise _error(error) from error


@acceptance_router.post("/{acceptance_id}/record", response_model=SupplySupplierAcceptanceRead)
def record(acceptance_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return record_acceptance(db, acceptance_id, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError, SupplierAcceptanceValidationError, SupplierAcceptanceConflictError, SupplierAcceptanceUnitError, SupplierAcceptanceDestinationError) as error: raise _error(error) from error


@acceptance_router.post("/{acceptance_id}/cancel", response_model=SupplySupplierAcceptanceRead)
def cancel(acceptance_id: UUID, db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)]):
    try: return cancel_acceptance(db, acceptance_id, tenant_id=admin.tenant_id)
    except (SupplierAcceptanceNotFoundError, SupplierAcceptanceStateError) as error: raise _error(error) from error
