from collections.abc import AsyncGenerator
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.integrations.iiko.client import IikoServerClient
from app.integrations.iiko.config import IikoSettings, get_iiko_settings
from app.integrations.iiko.exceptions import (
    IikoAuthenticationError,
    IikoAuthorizationError,
    IikoConfigurationError,
    IikoConnectionError,
    IikoContractError,
    IikoError,
    IikoRateLimitError,
    IikoUnsupportedOperationError,
)
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import IikoPage
from app.integrations.iiko.service import (
    get_sync_run,
    latest_run,
    list_sync_runs,
    sync_reference_snapshot,
    sync_stock_balances,
    sync_warehouses,
    test_connection,
)
from app.models.iiko import IikoSyncRun, IikoSyncStatus, IikoSyncType
from app.models.user import User
from app.schemas.iiko import (
    IikoStatusRead,
    IikoStockBalanceSyncRequest,
    IikoSyncRunRead,
)


router = APIRouter(prefix="/integrations/iiko", tags=["iiko"])


async def get_iiko_provider() -> AsyncGenerator[IikoProvider, None]:
    provider = IikoServerClient(get_iiko_settings())
    try:
        yield provider
    finally:
        await provider.aclose()


def integration_error(error: IikoError) -> HTTPException:
    if isinstance(error, IikoConfigurationError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error.args[0] if error.args else error.code,
        )
    if isinstance(error, IikoUnsupportedOperationError):
        return HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=error.args[0] if error.args else error.code,
        )
    if isinstance(error, (IikoAuthenticationError, IikoAuthorizationError)):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=error.code,
        )
    if isinstance(error, IikoRateLimitError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error.code,
            headers={"Retry-After": "30"},
        )
    if isinstance(error, IikoConnectionError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error.code,
        )
    if isinstance(error, IikoContractError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=error.code,
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="IIKO_RESPONSE_ERROR",
    )


def paginate(records: list[Any], limit: int, offset: int) -> IikoPage[Any]:
    items = [record.dto for record in records[offset : offset + limit]]
    return IikoPage(
        items=items,
        total=len(records),
        limit=limit,
        offset=offset,
    )


async def read_page(
    reader: Any,
    *,
    limit: int,
    offset: int,
    external_id: str | None,
    search: str | None,
) -> IikoPage[Any]:
    try:
        records = await reader()
    except IikoError as error:
        raise integration_error(error) from error
    if external_id:
        records = [
            record for record in records
            if record.external_id == external_id
        ]
    if search:
        needle = search.casefold()
        records = [
            record
            for record in records
            if needle in getattr(record.dto, "name", "").casefold()
        ]
    return paginate(records, limit, offset)


@router.get("/status", response_model=IikoStatusRead)
def read_iiko_status(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> IikoStatusRead:
    config = get_iiko_settings()
    tenant_id = settings.default_tenant_id
    connection = latest_run(
        db,
        tenant_id=tenant_id,
        sync_type=IikoSyncType.CONNECTION_CHECK,
        statuses={IikoSyncStatus.SUCCEEDED},
    )
    reference = latest_run(
        db,
        tenant_id=tenant_id,
        sync_type=IikoSyncType.FULL_REFERENCE_SNAPSHOT,
        statuses={
            IikoSyncStatus.SUCCEEDED,
            IikoSyncStatus.PARTIALLY_SUCCEEDED,
        },
    )
    stock = latest_run(
        db,
        tenant_id=tenant_id,
        sync_type=IikoSyncType.STOCK_BALANCES,
        statuses={IikoSyncStatus.SUCCEEDED},
    )
    last_error = latest_run(
        db,
        tenant_id=tenant_id,
        statuses={IikoSyncStatus.FAILED, IikoSyncStatus.PARTIALLY_SUCCEEDED},
    )
    if not config.enabled:
        connection_state = "disabled"
    elif not config.configured:
        connection_state = "not_configured"
    elif last_error and (
        connection is None or last_error.started_at > connection.started_at
    ):
        connection_state = "error"
    elif connection:
        connection_state = "connected"
    else:
        connection_state = "unknown"
    return IikoStatusRead(
        enabled=config.enabled,
        configured=config.configured,
        api_type=config.api_type,
        connection_state=connection_state,
        last_successful_connection_at=(
            connection.finished_at if connection else None
        ),
        last_reference_sync_at=reference.finished_at if reference else None,
        last_stock_sync_at=stock.finished_at if stock else None,
        last_error_code=last_error.error_code if last_error else None,
        last_error_at=last_error.finished_at if last_error else None,
    )


@router.post("/test-connection", response_model=IikoSyncRunRead)
async def test_iiko_connection(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoSyncRunRead:
    config = get_iiko_settings()
    try:
        config.validate_enabled()
        run = await test_connection(
            db,
            provider,
            tenant_id=settings.default_tenant_id,
            requested_by=current_admin.id,
            source_api_type=config.api_type,
        )
    except IikoError as error:
        raise integration_error(error) from error
    return IikoSyncRunRead.model_validate(run)


def page_parameters(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    external_id: Annotated[str | None, Query(max_length=160)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
) -> tuple[int, int, str | None, str | None]:
    return limit, offset, external_id, search


PageParams = Annotated[
    tuple[int, int, str | None, str | None],
    Depends(page_parameters),
]


@router.get("/organizations")
async def read_organizations(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_organizations,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/enterprises")
async def read_enterprises(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_enterprises,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/warehouses")
async def read_warehouses(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_warehouses,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/departments")
async def read_departments(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_departments,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/product-groups")
async def read_product_groups(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_product_groups,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/product-categories")
async def read_product_categories(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_product_categories,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/products")
async def read_products(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_products,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/units")
async def read_units(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_units,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/packages")
async def read_packages(
    params: PageParams,
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoPage[Any]:
    limit, offset, external_id, search = params
    return await read_page(
        provider.get_packages,
        limit=limit,
        offset=offset,
        external_id=external_id,
        search=search,
    )


@router.get("/stock-balances")
async def read_stock_balances(
    warehouse_external_id: Annotated[str, Query(min_length=1, max_length=160)],
    balance_date: Annotated[date, Query()],
    _: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
    product_external_id: Annotated[
        str | None,
        Query(min_length=1, max_length=160),
    ] = None,
    include_zero: bool = True,
    include_deleted: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IikoPage[Any]:
    try:
        records = await provider.get_stock_balances(
            balance_date=balance_date,
            warehouse_external_ids=[warehouse_external_id],
            product_external_ids=(
                [product_external_id] if product_external_id else None
            ),
            include_zero=include_zero,
            include_deleted=include_deleted,
        )
    except IikoError as error:
        raise integration_error(error) from error
    return paginate(records, limit, offset)


@router.post("/sync/warehouses", response_model=IikoSyncRunRead)
async def sync_iiko_warehouses(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoSyncRunRead:
    config = get_iiko_settings()
    try:
        config.validate_enabled()
        run = await sync_warehouses(
            db,
            provider,
            tenant_id=settings.default_tenant_id,
            requested_by=current_admin.id,
            source_api_type=config.api_type,
        )
    except IikoError as error:
        raise integration_error(error) from error
    return IikoSyncRunRead.model_validate(run)


@router.post("/sync/stock-balances", response_model=IikoSyncRunRead)
async def sync_iiko_stock_balances(
    request: IikoStockBalanceSyncRequest,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoSyncRunRead:
    if not request.warehouse_external_ids or any(
        not value.strip() for value in request.warehouse_external_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WAREHOUSE_REQUIRED",
        )
    config = get_iiko_settings()
    try:
        config.validate_enabled()
        run = await sync_stock_balances(
            db,
            provider,
            tenant_id=settings.default_tenant_id,
            requested_by=current_admin.id,
            source_api_type=config.api_type,
            balance_date=request.balance_date,
            warehouse_external_ids=request.warehouse_external_ids,
            product_external_ids=request.product_external_ids,
            include_zero=request.include_zero,
            include_deleted=request.include_deleted,
        )
    except IikoError as error:
        raise integration_error(error) from error
    return IikoSyncRunRead.model_validate(run)


@router.post(
    "/sync/reference-snapshot",
    response_model=IikoSyncRunRead,
)
async def sync_iiko_reference_snapshot(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    provider: Annotated[IikoProvider, Depends(get_iiko_provider)],
) -> IikoSyncRunRead:
    config: IikoSettings = get_iiko_settings()
    try:
        config.validate_enabled()
        run = await sync_reference_snapshot(
            db,
            provider,
            tenant_id=settings.default_tenant_id,
            requested_by=current_admin.id,
            source_api_type=config.api_type,
        )
    except IikoError as error:
        raise integration_error(error) from error
    return IikoSyncRunRead.model_validate(run)


@router.get("/sync-runs", response_model=list[IikoSyncRunRead])
def read_sync_runs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[IikoSyncRun]:
    return list_sync_runs(
        db,
        tenant_id=settings.default_tenant_id,
        limit=limit,
        offset=offset,
    )


@router.get("/sync-runs/{run_id}", response_model=IikoSyncRunRead)
def read_sync_run(
    run_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> IikoSyncRun:
    run = get_sync_run(
        db,
        tenant_id=settings.default_tenant_id,
        run_id=run_id,
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IIKO_SYNC_RUN_NOT_FOUND",
        )
    return run
