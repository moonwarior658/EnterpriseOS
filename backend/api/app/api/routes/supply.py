from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin, get_current_user
from app.db.session import get_db
from app.models.supply import (
    Department,
    SupplyRequest,
    SupplyRequestDirection,
)
from app.models.user import User
from app.schemas.supply import (
    DepartmentRead,
    SupplyRequestCreate,
    SupplyRequestDirectionRead,
    SupplyRequestListItem,
    SupplyRequestRead,
)
from app.supply.service import (
    DepartmentNotFoundError,
    DirectionNotFoundError,
    InactiveDepartmentError,
    InactiveDirectionError,
    PublicNumberGenerationError,
    SupplyRequestNotFoundError,
    SupplyRequestStateError,
    create_supply_request,
    get_supply_request,
    list_departments,
    list_request_directions,
    list_supply_requests,
    submit_supply_request,
)


router = APIRouter(prefix="/supply", tags=["supply"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Заявка снабжения не найдена",
    )


@router.get("/departments", response_model=list[DepartmentRead])
def read_departments(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[Department]:
    return list_departments(db)


@router.get(
    "/request-directions",
    response_model=list[SupplyRequestDirectionRead],
)
def read_request_directions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[SupplyRequestDirection]:
    return list_request_directions(db)


@router.post(
    "/requests",
    response_model=SupplyRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: SupplyRequestCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return create_supply_request(
            db,
            payload,
            created_by_user_id=current_admin.id,
        )
    except DepartmentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Подразделение не найдено",
        ) from error
    except DirectionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Направление заявки не найдено",
        ) from error
    except InactiveDepartmentError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Подразделение неактивно",
        ) from error
    except InactiveDirectionError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Направление заявки неактивно",
        ) from error
    except (IntegrityError, PublicNumberGenerationError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Не удалось сформировать уникальный номер заявки",
        ) from error


@router.get("/requests", response_model=list[SupplyRequestListItem])
def read_requests(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> list[SupplyRequest]:
    return list_supply_requests(db)


@router.get("/requests/{request_id}", response_model=SupplyRequestRead)
def read_request(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return get_supply_request(db, request_id)
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error


@router.post(
    "/requests/{request_id}/submit",
    response_model=SupplyRequestRead,
)
def submit_request(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return submit_supply_request(db, request_id)
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Заявку можно отправить только один раз из статуса DRAFT",
        ) from error
