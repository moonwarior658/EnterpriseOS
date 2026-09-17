from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.api.routes.iiko import get_iiko_provider
from app.db.session import get_db
from app.integrations.iiko.provider import IikoProvider
from app.models.user import User
from app.schemas.iiko_incoming_receipt import SupplyIikoIncomingReceiptRead
from app.supply.iiko_incoming_receipts import (
    IncomingReceiptConflictError,
    IncomingReceiptNotFoundError,
    IncomingReceiptReadinessError,
    IncomingReceiptStateError,
    cancel_receipt,
    create_receipt,
    mark_receipt_ready,
    prepare_receipt,
    process_receipt,
    read_acceptance_receipt,
    read_receipt,
    retry_receipt,
)


acceptance_router = APIRouter(
    prefix="/supply/supplier-acceptances", tags=["supply"]
)
receipt_router = APIRouter(
    prefix="/supply/iiko-incoming-receipts", tags=["supply"]
)


def _error(error: Exception) -> HTTPException:
    if isinstance(error, IncomingReceiptNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Приход iiko не найден")
    if isinstance(error, IncomingReceiptReadinessError):
        return HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"code": "READINESS_BLOCKED", "reasons": error.reasons},
        )
    if isinstance(error, IncomingReceiptConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, str(error))
    return HTTPException(
        status.HTTP_409_CONFLICT,
        str(error) or "Операция недоступна для текущего состояния прихода",
    )


@acceptance_router.post(
    "/{acceptance_id}/iiko-receipt",
    response_model=SupplyIikoIncomingReceiptRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare(
    acceptance_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return prepare_receipt(
            db, acceptance_id, tenant_id=admin.tenant_id, user_id=admin.id
        )
    except (
        IncomingReceiptNotFoundError,
        IncomingReceiptReadinessError,
        IncomingReceiptStateError,
        IncomingReceiptConflictError,
    ) as error:
        raise _error(error) from error


@acceptance_router.get(
    "/{acceptance_id}/iiko-receipt",
    response_model=SupplyIikoIncomingReceiptRead,
)
def read_for_acceptance(
    acceptance_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return read_acceptance_receipt(
            db, acceptance_id, tenant_id=admin.tenant_id
        )
    except IncomingReceiptNotFoundError as error:
        raise _error(error) from error


@receipt_router.get("/{receipt_id}", response_model=SupplyIikoIncomingReceiptRead)
def read(
    receipt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return read_receipt(db, receipt_id, tenant_id=admin.tenant_id)
    except IncomingReceiptNotFoundError as error:
        raise _error(error) from error


@receipt_router.post("/{receipt_id}/ready", response_model=SupplyIikoIncomingReceiptRead)
def ready(
    receipt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return mark_receipt_ready(db, receipt_id, tenant_id=admin.tenant_id)
    except (
        IncomingReceiptNotFoundError,
        IncomingReceiptReadinessError,
        IncomingReceiptStateError,
        IncomingReceiptConflictError,
    ) as error:
        raise _error(error) from error


@receipt_router.post("/{receipt_id}/create", response_model=SupplyIikoIncomingReceiptRead)
async def create(
    receipt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
):
    try:
        return await create_receipt(
            db, provider, receipt_id, tenant_id=admin.tenant_id
        )
    except (
        IncomingReceiptNotFoundError,
        IncomingReceiptStateError,
        IncomingReceiptConflictError,
    ) as error:
        raise _error(error) from error


@receipt_router.post("/{receipt_id}/process", response_model=SupplyIikoIncomingReceiptRead)
async def process(
    receipt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
):
    try:
        return await process_receipt(
            db, provider, receipt_id, tenant_id=admin.tenant_id
        )
    except (
        IncomingReceiptNotFoundError,
        IncomingReceiptStateError,
        IncomingReceiptConflictError,
    ) as error:
        raise _error(error) from error


@receipt_router.post("/{receipt_id}/retry", response_model=SupplyIikoIncomingReceiptRead)
async def retry(
    receipt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
):
    try:
        return await retry_receipt(
            db, provider, receipt_id, tenant_id=admin.tenant_id
        )
    except (
        IncomingReceiptNotFoundError,
        IncomingReceiptStateError,
        IncomingReceiptConflictError,
    ) as error:
        raise _error(error) from error


@receipt_router.post("/{receipt_id}/cancel", response_model=SupplyIikoIncomingReceiptRead)
def cancel(
    receipt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return cancel_receipt(db, receipt_id, tenant_id=admin.tenant_id)
    except (
        IncomingReceiptNotFoundError,
        IncomingReceiptStateError,
        IncomingReceiptConflictError,
    ) as error:
        raise _error(error) from error
