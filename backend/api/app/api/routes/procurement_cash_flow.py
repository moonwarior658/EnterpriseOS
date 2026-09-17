from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.procurement_cash_flow import SupplyProcurementCashFlowSummary
from app.supply.procurement_cash_flow import (
    ProcurementCashFlowNotFoundError,
    ProcurementCashFlowValidationError,
    purchase_request_cash_flow,
    supplier_cash_flow,
)


router = APIRouter(prefix="/supply", tags=["supply"])


@router.get("/suppliers/{supplier_id}/cash-flow", response_model=SupplyProcurementCashFlowSummary)
def read_supplier_cash_flow(
    supplier_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
):
    try:
        return supplier_cash_flow(
            db, supplier_id, tenant_id=admin.tenant_id,
            date_from=date_from, date_to=date_to,
        )
    except ProcurementCashFlowNotFoundError as error:
        raise HTTPException(status_code=404, detail="Поставщик не найден") from error
    except ProcurementCashFlowValidationError as error:
        raise HTTPException(status_code=422, detail="Начальная дата должна быть не позже конечной") from error


@router.get("/purchase-requests/{request_id}/cash-flow", response_model=SupplyProcurementCashFlowSummary)
def read_purchase_request_cash_flow(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return purchase_request_cash_flow(db, request_id, tenant_id=admin.tenant_id)
    except ProcurementCashFlowNotFoundError as error:
        raise HTTPException(status_code=404, detail="Закупочный запрос не найден") from error
