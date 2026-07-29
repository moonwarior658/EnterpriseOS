from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.integrations.iiko.mapping_service import (
    MappingError,
    confirm_product_mapping,
    confirm_unit_mapping,
    confirm_warehouse_mapping,
    finish_generation,
    generate_mapping_candidates,
    get_generation_progress,
    list_mappings,
    set_mapping_ignored,
    start_generation,
    unmap_mapping,
)
from app.models.iiko import (
    IikoMappingAuditEvent,
    IikoMappingKind,
    IikoMappingStatus,
    IikoProductMapping,
    IikoUnitMapping,
    IikoWarehouseMapping,
)
from app.models.user import User
from app.schemas.iiko_mapping import (
    IikoMappingAuditPage,
    IikoMappingGenerateRead,
    IikoMappingGenerateStatusRead,
    IikoProductMappingAction,
    IikoProductMappingPage,
    IikoProductMappingRead,
    IikoUnitMappingAction,
    IikoUnitMappingPage,
    IikoUnitMappingRead,
    IikoWarehouseMappingAction,
    IikoWarehouseMappingPage,
    IikoWarehouseMappingRead,
)


router = APIRouter(
    prefix="/integrations/iiko/mappings",
    tags=["iiko-mappings"],
)


def mapping_error(error: MappingError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=str(error),
    )


def product_read(mapping: IikoProductMapping) -> IikoProductMappingRead:
    return IikoProductMappingRead(
        id=mapping.id,
        iiko_product_id=mapping.iiko_product_id,
        source_name=mapping.source_name,
        source_code=mapping.source_code,
        source_sku=mapping.source_sku,
        source_unit_id=mapping.source_unit_id,
        is_deleted=mapping.is_deleted,
        status=mapping.status,
        confidence=mapping.confidence,
        reasons=mapping.reasons,
        eos_product_id=mapping.eos_product_id,
        eos_product_name=(
            mapping.eos_product.name if mapping.eos_product else None
        ),
        decided_at=mapping.decided_at,
    )


def unit_read(mapping: IikoUnitMapping) -> IikoUnitMappingRead:
    return IikoUnitMappingRead(
        id=mapping.id,
        iiko_unit_id=mapping.iiko_unit_id,
        source_name=mapping.source_name,
        source_code=mapping.source_code,
        is_deleted=mapping.is_deleted,
        status=mapping.status,
        confidence=mapping.confidence,
        reasons=mapping.reasons,
        eos_unit_id=mapping.eos_unit_id,
        eos_unit_name=(
            mapping.eos_unit.name_ru if mapping.eos_unit else None
        ),
        decided_at=mapping.decided_at,
    )


def warehouse_read(
    mapping: IikoWarehouseMapping,
) -> IikoWarehouseMappingRead:
    return IikoWarehouseMappingRead(
        id=mapping.id,
        iiko_warehouse_id=mapping.iiko_warehouse_id,
        source_name=mapping.source_name,
        source_code=mapping.source_code,
        is_deleted=mapping.is_deleted,
        status=mapping.status,
        confidence=mapping.confidence,
        reasons=mapping.reasons,
        eos_department_id=mapping.eos_department_id,
        eos_department_name=(
            mapping.eos_department.name if mapping.eos_department else None
        ),
        destination_type=mapping.destination_type,
        role=mapping.role,
        legal_contour=(
            mapping.eos_department.legal_contour
            if mapping.eos_department
            else mapping.legal_contour
        ),
        decided_at=mapping.decided_at,
    )


@router.post("/generate", response_model=IikoMappingGenerateRead)
def generate_candidates(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    generation_id: Annotated[
        UUID | None,
        Header(alias="X-EOS-Generation-ID"),
    ] = None,
) -> IikoMappingGenerateRead:
    resolved_id = generation_id or uuid4()
    if not start_generation(settings.default_tenant_id, resolved_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Формирование предложений уже выполняется",
        )
    try:
        result = generate_mapping_candidates(
            db,
            tenant_id=settings.default_tenant_id,
        )
    except Exception:
        finish_generation(
            settings.default_tenant_id,
            resolved_id,
            result=None,
        )
        raise
    finish_generation(
        settings.default_tenant_id,
        resolved_id,
        result=result,
    )
    return IikoMappingGenerateRead.model_validate(
        result,
        from_attributes=True,
    )


@router.get(
    "/generate/status",
    response_model=IikoMappingGenerateStatusRead,
)
def read_generation_status(
    _: Annotated[User, Depends(get_current_admin)],
    generation_id: UUID,
) -> IikoMappingGenerateStatusRead:
    progress = get_generation_progress(
        settings.default_tenant_id,
        generation_id,
    )
    return IikoMappingGenerateStatusRead(
        generation_id=progress.generation_id,
        status=progress.status,
        result=(
            IikoMappingGenerateRead.model_validate(
                progress.result,
                from_attributes=True,
            )
            if progress.result is not None
            else None
        ),
    )


def _page_kwargs(
    status_filter: IikoMappingStatus | None,
    search: str | None,
    include_deleted: bool,
    conflicts_only: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "tenant_id": settings.default_tenant_id,
        "status": status_filter,
        "search": search,
        "include_deleted": include_deleted,
        "conflicts_only": conflicts_only,
        "limit": limit,
        "offset": offset,
    }


@router.get("/products", response_model=IikoProductMappingPage)
def list_product_mappings(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    status_filter: IikoMappingStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, max_length=240),
    include_deleted: bool = False,
    conflicts_only: bool = False,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> IikoProductMappingPage:
    page = list_mappings(
        db,
        IikoProductMapping,
        **_page_kwargs(
            status_filter,
            search,
            include_deleted,
            conflicts_only,
            limit,
            offset,
        ),
    )
    return IikoProductMappingPage(
        items=[product_read(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/units", response_model=IikoUnitMappingPage)
def list_unit_mappings(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    status_filter: IikoMappingStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, max_length=240),
    include_deleted: bool = False,
    conflicts_only: bool = False,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> IikoUnitMappingPage:
    page = list_mappings(
        db,
        IikoUnitMapping,
        **_page_kwargs(
            status_filter,
            search,
            include_deleted,
            conflicts_only,
            limit,
            offset,
        ),
    )
    return IikoUnitMappingPage(
        items=[unit_read(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/warehouses", response_model=IikoWarehouseMappingPage)
def list_warehouse_mappings(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    status_filter: IikoMappingStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, max_length=240),
    include_deleted: bool = False,
    conflicts_only: bool = False,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> IikoWarehouseMappingPage:
    page = list_mappings(
        db,
        IikoWarehouseMapping,
        **_page_kwargs(
            status_filter,
            search,
            include_deleted,
            conflicts_only,
            limit,
            offset,
        ),
    )
    return IikoWarehouseMappingPage(
        items=[warehouse_read(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


def _product_action(
    db: Session,
    user: User,
    mapping_id: UUID,
    payload: IikoProductMappingAction,
    *,
    replace: bool,
) -> IikoProductMappingRead:
    try:
        mapping = confirm_product_mapping(
            db,
            tenant_id=settings.default_tenant_id,
            mapping_id=mapping_id,
            eos_product_id=payload.eos_product_id,
            actor_user_id=user.id,
            replace=replace,
        )
    except MappingError as error:
        raise mapping_error(error) from error
    return product_read(mapping)


@router.post("/products/{mapping_id}/confirm", response_model=IikoProductMappingRead)
def confirm_product(
    mapping_id: UUID,
    payload: IikoProductMappingAction,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> IikoProductMappingRead:
    return _product_action(db, user, mapping_id, payload, replace=False)


@router.post("/products/{mapping_id}/replace", response_model=IikoProductMappingRead)
def replace_product(
    mapping_id: UUID,
    payload: IikoProductMappingAction,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> IikoProductMappingRead:
    return _product_action(db, user, mapping_id, payload, replace=True)


def _unit_action(
    db: Session,
    user: User,
    mapping_id: UUID,
    payload: IikoUnitMappingAction,
    *,
    replace: bool,
) -> IikoUnitMappingRead:
    try:
        mapping = confirm_unit_mapping(
            db,
            tenant_id=settings.default_tenant_id,
            mapping_id=mapping_id,
            eos_unit_id=payload.eos_unit_id,
            actor_user_id=user.id,
            replace=replace,
        )
    except MappingError as error:
        raise mapping_error(error) from error
    return unit_read(mapping)


@router.post("/units/{mapping_id}/confirm", response_model=IikoUnitMappingRead)
def confirm_unit(
    mapping_id: UUID,
    payload: IikoUnitMappingAction,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> IikoUnitMappingRead:
    return _unit_action(db, user, mapping_id, payload, replace=False)


@router.post("/units/{mapping_id}/replace", response_model=IikoUnitMappingRead)
def replace_unit(
    mapping_id: UUID,
    payload: IikoUnitMappingAction,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> IikoUnitMappingRead:
    return _unit_action(db, user, mapping_id, payload, replace=True)


def _warehouse_action(
    db: Session,
    user: User,
    mapping_id: UUID,
    payload: IikoWarehouseMappingAction,
    *,
    replace: bool,
) -> IikoWarehouseMappingRead:
    try:
        mapping = confirm_warehouse_mapping(
            db,
            tenant_id=settings.default_tenant_id,
            mapping_id=mapping_id,
            destination_type=payload.destination_type,
            eos_department_id=payload.eos_department_id,
            role=payload.role,
            legal_contour=payload.legal_contour,
            actor_user_id=user.id,
            replace=replace,
        )
    except MappingError as error:
        raise mapping_error(error) from error
    return warehouse_read(mapping)


@router.post(
    "/warehouses/{mapping_id}/confirm",
    response_model=IikoWarehouseMappingRead,
)
def confirm_warehouse(
    mapping_id: UUID,
    payload: IikoWarehouseMappingAction,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> IikoWarehouseMappingRead:
    return _warehouse_action(db, user, mapping_id, payload, replace=False)


@router.post(
    "/warehouses/{mapping_id}/replace",
    response_model=IikoWarehouseMappingRead,
)
def replace_warehouse(
    mapping_id: UUID,
    payload: IikoWarehouseMappingAction,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> IikoWarehouseMappingRead:
    return _warehouse_action(db, user, mapping_id, payload, replace=True)


MODEL_BY_KIND = {
    "products": (IikoProductMapping, product_read),
    "units": (IikoUnitMapping, unit_read),
    "warehouses": (IikoWarehouseMapping, warehouse_read),
}


@router.post("/{kind}/{mapping_id}/ignore")
def ignore_mapping(
    kind: str,
    mapping_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> Any:
    config = MODEL_BY_KIND.get(kind)
    if config is None:
        raise HTTPException(status_code=404, detail="Тип mapping не найден")
    model, serializer = config
    try:
        mapping = set_mapping_ignored(
            db,
            model,
            tenant_id=settings.default_tenant_id,
            mapping_id=mapping_id,
            actor_user_id=user.id,
        )
    except MappingError as error:
        raise mapping_error(error) from error
    return serializer(mapping)


@router.post("/{kind}/{mapping_id}/unmap")
def unmap(
    kind: str,
    mapping_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> Any:
    config = MODEL_BY_KIND.get(kind)
    if config is None:
        raise HTTPException(status_code=404, detail="Тип mapping не найден")
    model, serializer = config
    try:
        mapping = unmap_mapping(
            db,
            model,
            tenant_id=settings.default_tenant_id,
            mapping_id=mapping_id,
            actor_user_id=user.id,
        )
    except MappingError as error:
        raise mapping_error(error) from error
    return serializer(mapping)


@router.get("/audit", response_model=IikoMappingAuditPage)
def list_mapping_audit(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    mapping_kind: IikoMappingKind | None = None,
    mapping_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> IikoMappingAuditPage:
    query = select(IikoMappingAuditEvent).where(
        IikoMappingAuditEvent.tenant_id == settings.default_tenant_id
    )
    if mapping_kind:
        query = query.where(
            IikoMappingAuditEvent.mapping_kind == mapping_kind
        )
    if mapping_id:
        query = query.where(IikoMappingAuditEvent.mapping_id == mapping_id)
    rows = db.scalars(
        query.order_by(
            IikoMappingAuditEvent.created_at.desc(),
            IikoMappingAuditEvent.id.desc(),
        )
    ).all()
    return IikoMappingAuditPage(
        items=rows[offset : offset + limit],
        total=len(rows),
        limit=limit,
        offset=offset,
    )
