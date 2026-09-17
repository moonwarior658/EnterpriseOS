from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.integrations.iiko.supplier_mapping_service import (
    SupplierMappingError,
    confirm_supplier_mapping,
    current_reference_warning,
    get_mapping_state,
    list_iiko_suppliers,
)
from app.models.user import User
from app.schemas.iiko_supplier_mapping import (
    IikoSupplierMappingCreate,
    IikoSupplierMappingRead,
    IikoSupplierReferencePage,
    IikoSupplierReferenceRead,
    SupplySupplierIikoMappingState,
)


router = APIRouter(prefix="/supply", tags=["supply-iiko-suppliers"])


def mapping_conflict(error: SupplierMappingError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def mapping_state_response(
    db: Session,
    *,
    tenant_id: str,
    supplier_id: UUID,
) -> SupplySupplierIikoMappingState:
    try:
        _, current, history = get_mapping_state(
            db, tenant_id=tenant_id, supplier_id=supplier_id,
        )
    except SupplierMappingError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    warning = current_reference_warning(db, tenant_id=tenant_id, mapping=current)
    return SupplySupplierIikoMappingState(
        mapping=(IikoSupplierMappingRead.model_validate(current) if current else None),
        history=[IikoSupplierMappingRead.model_validate(item) for item in history],
        iiko_receipt_ready_supplier_mapping=current is not None and warning is None,
        warning=warning,
    )


@router.get("/iiko/suppliers", response_model=IikoSupplierReferencePage)
def read_iiko_suppliers(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    search: Annotated[str | None, Query(max_length=240)] = None,
    include_deleted: bool = False,
    supplier_id: UUID | None = None,
) -> IikoSupplierReferencePage:
    eos_inn = None
    if supplier_id is not None:
        try:
            supplier, _, _ = get_mapping_state(
                db, tenant_id=current_admin.tenant_id, supplier_id=supplier_id,
            )
            eos_inn = supplier.inn
        except SupplierMappingError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
    rows = list_iiko_suppliers(
        db,
        tenant_id=current_admin.tenant_id,
        search=search,
        include_deleted=include_deleted,
    )
    items = []
    for row in rows:
        payload = row.payload
        source_inn = str(payload["inn"]).strip() if payload.get("inn") else None
        try:
            external_id = UUID(row.external_id)
        except ValueError as error:
            raise HTTPException(
                status_code=502, detail="IIKO_SUPPLIER_GUID_INVALID",
            ) from error
        items.append(IikoSupplierReferenceRead(
            external_id=external_id,
            name=str(payload.get("name") or ""),
            code=(str(payload["code"]) if payload.get("code") else None),
            inn=source_inn,
            is_supplier=bool(payload.get("supplier", False)),
            is_employee=bool(payload.get("employee", False)),
            represents_store=bool(payload.get("representsStore", False)),
            is_deleted=bool(payload.get("deleted", False)),
            is_active=row.is_active,
            exact_inn_match=bool(eos_inn and source_inn and eos_inn == source_inn),
        ))
    return IikoSupplierReferencePage(items=items, total=len(items))


@router.get(
    "/suppliers/{supplier_id}/iiko-mapping",
    response_model=SupplySupplierIikoMappingState,
)
def read_supplier_iiko_mapping(
    supplier_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierIikoMappingState:
    return mapping_state_response(
        db, tenant_id=current_admin.tenant_id, supplier_id=supplier_id,
    )


@router.post(
    "/suppliers/{supplier_id}/iiko-mapping",
    response_model=SupplySupplierIikoMappingState,
)
def create_or_replace_supplier_iiko_mapping(
    supplier_id: UUID,
    payload: IikoSupplierMappingCreate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplySupplierIikoMappingState:
    try:
        confirm_supplier_mapping(
            db,
            tenant_id=current_admin.tenant_id,
            supplier_id=supplier_id,
            iiko_supplier_id=payload.iiko_supplier_id,
            actor_user_id=current_admin.id,
        )
    except SupplierMappingError as error:
        raise mapping_conflict(error) from error
    return mapping_state_response(
        db, tenant_id=current_admin.tenant_id, supplier_id=supplier_id,
    )
