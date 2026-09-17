from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.supplier_settlement import (
    SupplySupplierDocumentSettlementRead,
    SupplySupplierObligationCreate,
    SupplySupplierObligationRead,
    SupplySupplierPaymentAllocationCreate,
    SupplySupplierPaymentAllocationRead,
    SupplySupplierPaymentAllocationReverse,
    SupplySupplierPaymentSettlementRead,
    SupplySupplierSettlementAdjustmentCreate,
    SupplySupplierSettlementAdjustmentRead,
    SupplySupplierSettlementStatement,
    SupplySupplierSettlementSummary,
)
from app.supply.supplier_settlements import (
    SupplierSettlementConflictError,
    SupplierSettlementNotFoundError,
    SupplierSettlementStateError,
    SupplierSettlementValidationError,
    create_adjustment,
    create_allocation,
    create_obligation,
    document_settlement,
    get_allocation,
    list_obligations,
    payment_settlement,
    reverse_allocation,
    settlement_statement,
    settlement_summary,
)


router = APIRouter(prefix="/supply", tags=["supply"])


def _error(error: Exception) -> HTTPException:
    if isinstance(error, SupplierSettlementNotFoundError):
        return HTTPException(status_code=404, detail="Объект взаиморасчётов не найден")
    if isinstance(error, SupplierSettlementConflictError):
        return HTTPException(status_code=409, detail="Такое активное распределение уже существует")
    if isinstance(error, SupplierSettlementStateError):
        return HTTPException(status_code=409, detail="Операция недоступна в текущем состоянии")
    return HTTPException(
        status_code=409,
        detail="Сумма или связь взаиморасчётов нарушает доступный остаток",
    )


@router.post("/supplier-orders/{order_id}/obligations", response_model=SupplySupplierObligationRead, status_code=status.HTTP_201_CREATED)
def create_supplier_obligation(
    order_id: UUID, payload: SupplySupplierObligationCreate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return create_obligation(db, order_id, tenant_id=admin.tenant_id, supplier_id=payload.supplier_id, user_id=admin.id)
    except SupplierSettlementNotFoundError as error:
        raise _error(error) from error


@router.get("/supplier-orders/{order_id}/obligations", response_model=list[SupplySupplierObligationRead])
def read_supplier_obligations(
    order_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    return list_obligations(db, order_id, tenant_id=admin.tenant_id)


@router.post("/supplier-payment-allocations", response_model=SupplySupplierPaymentAllocationRead, status_code=status.HTTP_201_CREATED)
def create_supplier_payment_allocation(
    payload: SupplySupplierPaymentAllocationCreate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return create_allocation(db, payload, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierSettlementNotFoundError, SupplierSettlementConflictError, SupplierSettlementStateError, SupplierSettlementValidationError) as error:
        raise _error(error) from error


@router.get("/supplier-payment-allocations/{allocation_id}", response_model=SupplySupplierPaymentAllocationRead)
def read_supplier_payment_allocation(
    allocation_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return get_allocation(db, allocation_id, tenant_id=admin.tenant_id)
    except SupplierSettlementNotFoundError as error:
        raise _error(error) from error


@router.post("/supplier-payment-allocations/{allocation_id}/reverse", response_model=SupplySupplierPaymentAllocationRead)
def reverse_supplier_payment_allocation(
    allocation_id: UUID, payload: SupplySupplierPaymentAllocationReverse,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return reverse_allocation(
            db, allocation_id, reason=payload.reason, amount=payload.amount,
            tenant_id=admin.tenant_id, user_id=admin.id,
        )
    except (SupplierSettlementNotFoundError, SupplierSettlementConflictError, SupplierSettlementStateError, SupplierSettlementValidationError) as error:
        raise _error(error) from error


@router.post("/supplier-settlement-adjustments", response_model=SupplySupplierSettlementAdjustmentRead, status_code=status.HTTP_201_CREATED)
def create_supplier_settlement_adjustment(
    payload: SupplySupplierSettlementAdjustmentCreate,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return create_adjustment(db, payload, tenant_id=admin.tenant_id, user_id=admin.id)
    except (SupplierSettlementNotFoundError, SupplierSettlementConflictError, SupplierSettlementStateError, SupplierSettlementValidationError) as error:
        raise _error(error) from error


@router.get("/suppliers/{supplier_id}/settlement", response_model=SupplySupplierSettlementSummary)
def read_supplier_settlement(
    supplier_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return settlement_summary(db, supplier_id, tenant_id=admin.tenant_id)
    except SupplierSettlementNotFoundError as error:
        raise _error(error) from error


@router.get("/suppliers/{supplier_id}/settlement/statement", response_model=SupplySupplierSettlementStatement)
def read_supplier_settlement_statement(
    supplier_id: UUID, date_from: date, date_to: date,
    db: Annotated[Session, Depends(get_db)], admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return settlement_statement(db, supplier_id, tenant_id=admin.tenant_id, date_from=date_from, date_to=date_to)
    except (SupplierSettlementNotFoundError, SupplierSettlementValidationError) as error:
        raise _error(error) from error


@router.get("/supplier-documents/{document_id}/settlement", response_model=SupplySupplierDocumentSettlementRead)
def read_supplier_document_settlement(
    document_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return document_settlement(db, document_id, tenant_id=admin.tenant_id)
    except SupplierSettlementNotFoundError as error:
        raise _error(error) from error


@router.get("/supplier-payments/{payment_id}/settlement", response_model=SupplySupplierPaymentSettlementRead)
def read_supplier_payment_settlement(
    payment_id: UUID, db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return payment_settlement(db, payment_id, tenant_id=admin.tenant_id)
    except SupplierSettlementNotFoundError as error:
        raise _error(error) from error
