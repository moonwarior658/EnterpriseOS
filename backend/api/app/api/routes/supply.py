from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_admin,
    require_request_view_access,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.supply import (
    Department,
    SupplyProduct,
    SupplyProductAlias,
    SupplyProductCategory,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyStorageZone,
    SupplyUnit,
    SupplyDepartmentDebt,
)
from app.models.user import User
from app.schemas.supply import (
    DepartmentRead,
    SupplyDuplicateGroupResolve,
    SupplyExpectedVersion,
    SupplyRequestFulfillmentUpdate,
    SupplyLineFulfillmentUpdate,
    SupplyDebtInclusionConfirm,
    SupplyDebtClose,
    SupplyDebtCancel,
    SupplyDebtPage,
    SupplyDebtRead,
    SupplyDebtStatus,
    SupplyDebtSeverity,
    SupplyDashboardSummary,
    SupplyProductAliasCreate,
    SupplyProductAliasRead,
    SupplyContextMappingConfirm,
    SupplyContextMappingBootstrapRead,
    SupplyContextMappingBootstrapRequest,
    SupplyContextMappingRead,
    SupplyContextMappingReplace,
    SupplyProductCreate,
    SupplyProductPage,
    SupplyProductRead,
    SupplyProductUpdate,
    SupplyReferenceCreate,
    SupplyReferencePage,
    SupplyReferenceRead,
    SupplyReferenceUpdate,
    SupplyLineManualMatch,
    SupplyLineWorkingValuesRead,
    SupplyLineWorkingValuesUpdate,
    SupplyLineAllocationsUpdate,
    SupplyAliasStatusUpdate,
    SupplyRecognitionSummary,
    SupplyRecognitionRequest,
    SupplyRequestCreate,
    SupplyRequestPlan,
    SupplyRequestCycleCreate,
    SupplyRequestCyclePage,
    SupplyRequestCycleRead,
    SupplyRequestCycleStatus,
    SupplyRequestCycleUpdate,
    SupplyRequestDirectionRead,
    SupplyRequestLineRead,
    SupplyRequestListItem,
    SupplyRequestRead,
    SupplyIikoSourceWarehouseSelect,
    SupplyIikoStockCheckRead,
    SupplyStockCalculationRead,
    SupplyStockCalculationConfirm,
    SupplyStockTransferQuantityUpdate,
    SupplyProductSourceAssign,
    SupplyProductSourceBootstrapRead,
    SupplyProductSourceMappingRead,
    SupplyProductSourcePreviewRead,
    SupplyRequestCancel,
    SupplyRequestStatus,
    SupplyUnitRead,
)
from app.supply.service import (
    DepartmentNotFoundError,
    DirectionNotFoundError,
    DuplicateSupplyRequestCycleError,
    DuplicateSupplyRequestError,
    DuplicateSupplyProductAliasError,
    DuplicateSupplyProductCategoryError,
    DuplicateSupplyProductError,
    DuplicateSupplyProductIikoIdError,
    DuplicateSupplyStorageZoneError,
    InactiveDepartmentError,
    InactiveDirectionError,
    InactiveSupplyProductError,
    InactiveSupplyProductCategoryError,
    InactiveSupplyStorageZoneError,
    InactiveSupplyUnitError,
    InvalidSupplyQuantityError,
    SupplyAllocationExceedsRequestedError,
    SupplyAllocationUnitMismatchError,
    SupplyRequestedQuantityImmutableError,
    SupplySendQuantityInvalidError,
    SupplyLineNotMatchedError,
    SupplyRequestPlanningIncompleteError,
    SupplyRequestNotFulfillableError,
    SupplyRequestAlreadyFulfilledError,
    SupplyFulfillmentExceedsPlannedError,
    SupplyFulfillmentInvalidActionError,
    SupplyFulfillmentDecreaseCommentRequiredError,
    SupplyDebtNotFoundError,
    SupplyDebtVersionConflictError,
    SupplyDebtNotActiveError,
    SupplyDebtCloseExceedsOutstandingError,
    SupplyDebtManualCloseDisabledError,
    SupplyDebtInclusionConfirmationRequiredError,
    SupplyDebtInclusionInvalidError,
    SupplyDebtProductRequiredError,
    SupplyRequestAlreadyPlannedError,
    SupplyRequestCancelledError,
    PublicNumberGenerationError,
    SupplyDuplicateGroupNotFoundError,
    SupplyProductAliasNotFoundError,
    SupplyProductCategoryNotFoundError,
    SupplyProductNotFoundError,
    SupplyProductRestoreConflictError,
    SupplyRequestNotFoundError,
    SupplyRequestLineNotFoundError,
    SupplyRequestCycleHasRequestsError,
    SupplyRequestCycleNotFoundError,
    SupplyRequestCycleStateError,
    SupplyRequestCycleUnavailableError,
    SupplyRequestDuplicatesPresentError,
    SupplyRequestStateError,
    SupplyRequestVersionConflictError,
    SupplyContextMappingVersionConflictError,
    SupplyUnitNotFoundError,
    SupplyStorageZoneNotFoundError,
    archive_supply_product,
    create_supply_product_category,
    create_supply_product,
    create_supply_product_alias,
    create_supply_request_cycle,
    create_supply_storage_zone,
    create_supply_request,
    delete_supply_product_alias,
    disable_supply_product_alias,
    get_supply_product_category,
    get_supply_product,
    get_supply_storage_zone,
    get_supply_request,
    get_supply_request_cycle,
    list_departments,
    list_request_directions,
    list_supply_product_categories,
    list_supply_products,
    list_supply_storage_zones,
    list_supply_requests,
    list_supply_request_cycles,
    list_supply_units,
    replace_supply_line_allocations,
    plan_supply_request,
    cancel_supply_request,
    manually_match_supply_request_line,
    confirm_context_mapping_for_line,
    bootstrap_permanent_milk_context_mappings,
    delete_context_mapping,
    replace_context_mapping,
    update_supply_line_working_values,
    detect_supply_request_duplicates,
    recognize_supply_request,
    reparse_supply_request_line,
    restore_supply_product,
    resolve_supply_duplicate_group,
    submit_supply_request,
    update_supply_product_category,
    update_supply_product,
    update_supply_storage_zone,
    update_supply_request_cycle,
    update_supply_line_fulfillment,
    fulfill_supply_request_as_planned,
    confirm_supply_debt_inclusion,
    count_supply_requests,
    list_supply_debts,
    get_supply_debt,
    close_supply_debt,
    cancel_supply_debt,
    get_supply_dashboard_summary,
)
from app.supply.iiko_stock import (
    SupplyIikoRequestNotFoundError,
    SupplyIikoSourceNotAllowedError,
    SupplyIikoTerminalRequestError,
    SupplyIikoVersionConflictError,
    get_stock_check,
    select_source_warehouse,
)
from app.supply.source_mapping import (
    SupplyProductSourceConcurrentAssignmentError,
    SupplyProductSourceNotAllowedError,
    SupplyProductSourceProductNotEligibleError,
    SupplyProductSourceReplacementCommentRequiredError,
    SupplyProductSourceRequestNotFoundError,
    SupplyProductSourceResolutionBlockedError,
    SupplyProductSourceVersionConflictError,
    assign_product_source,
    bootstrap_product_source_mappings,
    get_product_source_preview,
    resolve_supply_request_sources,
)
from app.supply.stock_calculation import (
    SupplyStockCalculationConfirmedError,
    SupplyStockCalculationBlockedError,
    SupplyStockCalculationNotFoundError,
    SupplyStockCalculationUnavailableError,
    SupplyStockCalculationVersionConflictError,
    SupplyStockTransferFractionInvalidError,
    SupplyStockTransferQuantityInvalidError,
    adjust_transferable_quantity,
    calculate_stock,
    confirm_stock_calculation,
    get_stock_calculation,
)


router = APIRouter(prefix="/supply", tags=["supply"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Заявка снабжения не найдена",
    )


def _product_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Товар не найден",
    )


def _invalid_product_reference(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def _reference_not_found(label: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{label} не найдена",
    )


def _reference_conflict(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    )


def _version_conflict(
    error: SupplyRequestVersionConflictError,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "SUPPLY_REQUEST_VERSION_CONFLICT",
            "current_version": error.current_version,
            "expected_version": error.expected_version,
        },
    )


def _fulfillment_error(error: Exception) -> HTTPException:
    code = "SUPPLY_REQUEST_NOT_FULFILLABLE"
    status_code = status.HTTP_409_CONFLICT
    if isinstance(error, SupplyRequestAlreadyFulfilledError):
        code = "SUPPLY_REQUEST_ALREADY_FULFILLED"
    elif isinstance(error, SupplyFulfillmentExceedsPlannedError):
        code = "SUPPLY_FULFILLMENT_EXCEEDS_PLANNED"
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, SupplyFulfillmentInvalidActionError):
        code = "SUPPLY_FULFILLMENT_INVALID_ACTION"
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, SupplyFulfillmentDecreaseCommentRequiredError):
        code = "SUPPLY_FULFILLMENT_DECREASE_COMMENT_REQUIRED"
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, SupplySendQuantityInvalidError):
        code = "SUPPLY_SEND_QUANTITY_INVALID"
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, SupplyDebtInclusionConfirmationRequiredError):
        code = "SUPPLY_DEBT_INCLUSION_CONFIRMATION_REQUIRED"
    elif isinstance(error, SupplyDebtInclusionInvalidError):
        code = "SUPPLY_DEBT_INCLUSION_INVALID"
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, SupplyDebtProductRequiredError):
        code = "SUPPLY_DEBT_PRODUCT_REQUIRED"
    return HTTPException(status_code=status_code, detail={"code": code})


def _debt_version_conflict(
    error: SupplyDebtVersionConflictError,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "SUPPLY_DEBT_VERSION_CONFLICT",
            "current_version": error.current_version,
            "expected_version": error.expected_version,
        },
    )


@router.get(
    "/request-cycles",
    response_model=SupplyRequestCyclePage,
)
def read_supply_request_cycles(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    direction_id: UUID | None = None,
    cycle_status: Annotated[
        SupplyRequestCycleStatus | None,
        Query(alias="status"),
    ] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplyRequestCyclePage:
    items, total = list_supply_request_cycles(
        db,
        direction_id=direction_id,
        cycle_status=cycle_status,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return SupplyRequestCyclePage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/request-cycles",
    response_model=SupplyRequestCycleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_request_cycle(
    payload: SupplyRequestCycleCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequestCycle:
    try:
        return create_supply_request_cycle(db, payload)
    except DirectionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Направление заявки не найдено",
        ) from error
    except InactiveDirectionError as error:
        raise _reference_conflict("Направление заявки неактивно") from error
    except DuplicateSupplyRequestCycleError as error:
        raise _reference_conflict(
            "Цикл для этого направления и даты уже существует"
        ) from error


@router.get(
    "/request-cycles/{cycle_id}",
    response_model=SupplyRequestCycleRead,
)
def read_supply_request_cycle(
    cycle_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequestCycle:
    try:
        return get_supply_request_cycle(db, cycle_id)
    except SupplyRequestCycleNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Цикл заявок не найден",
        ) from error


@router.patch(
    "/request-cycles/{cycle_id}",
    response_model=SupplyRequestCycleRead,
)
def update_request_cycle(
    cycle_id: UUID,
    payload: SupplyRequestCycleUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequestCycle:
    try:
        return update_supply_request_cycle(db, cycle_id, payload)
    except SupplyRequestCycleNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Цикл заявок не найден",
        ) from error
    except DirectionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Направление заявки не найдено",
        ) from error
    except InactiveDirectionError as error:
        raise _reference_conflict("Направление заявки неактивно") from error
    except DuplicateSupplyRequestCycleError as error:
        raise _reference_conflict(
            "Цикл для этого направления и даты уже существует"
        ) from error
    except SupplyRequestCycleHasRequestsError as error:
        raise _reference_conflict(
            "Нельзя изменить направление или дату цикла с заявками"
        ) from error
    except SupplyRequestCycleStateError as error:
        raise _reference_conflict(
            "Недопустимые границы времени или переход статуса цикла"
        ) from error


@router.get("/units", response_model=list[SupplyUnitRead])
def read_supply_units(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> list[SupplyUnit]:
    return list_supply_units(db, tenant_id=current_admin.tenant_id)


@router.get("/product-categories", response_model=SupplyReferencePage)
def read_supply_product_categories(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    active: bool | None = None,
    search: Annotated[str | None, Query(max_length=160)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplyReferencePage:
    items, total = list_supply_product_categories(
        db,
        active=active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return SupplyReferencePage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/product-categories",
    response_model=SupplyReferenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_product_category(
    payload: SupplyReferenceCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductCategory:
    try:
        return create_supply_product_category(db, payload)
    except DuplicateSupplyProductCategoryError as error:
        raise _reference_conflict(
            "Категория с таким кодом или названием уже существует"
        ) from error


@router.get(
    "/product-categories/{category_id}",
    response_model=SupplyReferenceRead,
)
def read_supply_product_category(
    category_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductCategory:
    try:
        return get_supply_product_category(db, category_id)
    except SupplyProductCategoryNotFoundError as error:
        raise _reference_not_found("Категория") from error


@router.patch(
    "/product-categories/{category_id}",
    response_model=SupplyReferenceRead,
)
def update_product_category(
    category_id: UUID,
    payload: SupplyReferenceUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductCategory:
    try:
        return update_supply_product_category(db, category_id, payload)
    except SupplyProductCategoryNotFoundError as error:
        raise _reference_not_found("Категория") from error
    except DuplicateSupplyProductCategoryError as error:
        raise _reference_conflict(
            "Категория с таким кодом или названием уже существует"
        ) from error


@router.get("/storage-zones", response_model=SupplyReferencePage)
def read_supply_storage_zones(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    active: bool | None = None,
    search: Annotated[str | None, Query(max_length=160)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplyReferencePage:
    items, total = list_supply_storage_zones(
        db,
        active=active,
        search=search,
        limit=limit,
        offset=offset,
    )
    return SupplyReferencePage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/storage-zones",
    response_model=SupplyReferenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_storage_zone(
    payload: SupplyReferenceCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyStorageZone:
    try:
        return create_supply_storage_zone(db, payload)
    except DuplicateSupplyStorageZoneError as error:
        raise _reference_conflict(
            "Зона хранения с таким кодом или названием уже существует"
        ) from error


@router.get(
    "/storage-zones/{zone_id}",
    response_model=SupplyReferenceRead,
)
def read_supply_storage_zone(
    zone_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyStorageZone:
    try:
        return get_supply_storage_zone(db, zone_id)
    except SupplyStorageZoneNotFoundError as error:
        raise _reference_not_found("Зона хранения") from error


@router.patch(
    "/storage-zones/{zone_id}",
    response_model=SupplyReferenceRead,
)
def update_storage_zone(
    zone_id: UUID,
    payload: SupplyReferenceUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyStorageZone:
    try:
        return update_supply_storage_zone(db, zone_id, payload)
    except SupplyStorageZoneNotFoundError as error:
        raise _reference_not_found("Зона хранения") from error
    except DuplicateSupplyStorageZoneError as error:
        raise _reference_conflict(
            "Зона хранения с таким кодом или названием уже существует"
        ) from error


@router.get("/products", response_model=SupplyProductPage)
def read_supply_products(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
    active: bool | None = None,
    search: Annotated[str | None, Query(max_length=240)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplyProductPage:
    items, total = list_supply_products(
        db,
        active=active,
        search=search,
        limit=limit,
        offset=offset,
        tenant_id=current_admin.tenant_id,
    )
    return SupplyProductPage(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/products",
    response_model=SupplyProductRead,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    payload: SupplyProductCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProduct:
    try:
        return create_supply_product(db, payload)
    except DuplicateSupplyProductError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Товар с таким нормализованным названием уже существует",
        ) from error
    except DuplicateSupplyProductIikoIdError as error:
        raise _reference_conflict(
            "Товар с таким iiko_id уже существует"
        ) from error
    except SupplyUnitNotFoundError as error:
        raise _invalid_product_reference("Единица измерения не найдена") from error
    except InactiveSupplyUnitError as error:
        raise _invalid_product_reference("Единица измерения неактивна") from error
    except DirectionNotFoundError as error:
        raise _invalid_product_reference("Направление заявки не найдено") from error
    except InactiveDirectionError as error:
        raise _invalid_product_reference("Направление заявки неактивно") from error
    except SupplyProductCategoryNotFoundError as error:
        raise _reference_not_found("Категория") from error
    except InactiveSupplyProductCategoryError as error:
        raise _reference_conflict("Категория неактивна") from error
    except SupplyStorageZoneNotFoundError as error:
        raise _reference_not_found("Зона хранения") from error
    except InactiveSupplyStorageZoneError as error:
        raise _reference_conflict("Зона хранения неактивна") from error


@router.get("/products/{product_id}", response_model=SupplyProductRead)
def read_supply_product(
    product_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProduct:
    try:
        return get_supply_product(db, product_id)
    except SupplyProductNotFoundError as error:
        raise _product_not_found() from error


@router.patch("/products/{product_id}", response_model=SupplyProductRead)
def update_product(
    product_id: UUID,
    payload: SupplyProductUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProduct:
    try:
        return update_supply_product(db, product_id, payload)
    except SupplyProductNotFoundError as error:
        raise _product_not_found() from error
    except DuplicateSupplyProductError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Товар с таким нормализованным названием уже существует",
        ) from error
    except DuplicateSupplyProductIikoIdError as error:
        raise _reference_conflict(
            "Товар с таким iiko_id уже существует"
        ) from error
    except SupplyUnitNotFoundError as error:
        raise _invalid_product_reference("Единица измерения не найдена") from error
    except InactiveSupplyUnitError as error:
        raise _invalid_product_reference("Единица измерения неактивна") from error
    except DirectionNotFoundError as error:
        raise _invalid_product_reference("Направление заявки не найдено") from error
    except InactiveDirectionError as error:
        raise _invalid_product_reference("Направление заявки неактивно") from error
    except SupplyProductCategoryNotFoundError as error:
        raise _reference_not_found("Категория") from error
    except InactiveSupplyProductCategoryError as error:
        raise _reference_conflict("Категория неактивна") from error
    except SupplyStorageZoneNotFoundError as error:
        raise _reference_not_found("Зона хранения") from error
    except InactiveSupplyStorageZoneError as error:
        raise _reference_conflict("Зона хранения неактивна") from error


@router.post(
    "/products/{product_id}/archive",
    response_model=SupplyProductRead,
)
def archive_product(
    product_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyProduct:
    try:
        return archive_supply_product(
            db,
            product_id,
            archived_by_user_id=current_admin.id,
        )
    except SupplyProductNotFoundError as error:
        raise _product_not_found() from error


@router.post(
    "/products/{product_id}/restore",
    response_model=SupplyProductRead,
)
def restore_product(
    product_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProduct:
    try:
        return restore_supply_product(db, product_id)
    except SupplyProductNotFoundError as error:
        raise _product_not_found() from error
    except SupplyProductRestoreConflictError as error:
        raise _reference_conflict(
            "Товар нельзя восстановить: связанный справочник неактивен"
        ) from error


@router.post(
    "/products/{product_id}/aliases",
    response_model=SupplyProductAliasRead,
    status_code=status.HTTP_201_CREATED,
)
def create_product_alias(
    product_id: UUID,
    payload: SupplyProductAliasCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductAlias:
    try:
        return create_supply_product_alias(db, product_id, payload)
    except SupplyProductNotFoundError as error:
        raise _product_not_found() from error
    except DuplicateSupplyProductAliasError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_ALIAS_CONFLICT"},
        ) from error


@router.patch(
    "/products/{product_id}/aliases/{alias_id}",
    response_model=SupplyProductAliasRead,
)
def update_product_alias_status(
    product_id: UUID,
    alias_id: UUID,
    _: SupplyAliasStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    __: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductAlias:
    try:
        return disable_supply_product_alias(db, product_id, alias_id)
    except (SupplyProductNotFoundError, SupplyProductAliasNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар или алиас не найден",
        ) from error


@router.delete(
    "/products/{product_id}/aliases/{alias_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_product_alias(
    product_id: UUID,
    alias_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> None:
    try:
        delete_supply_product_alias(db, product_id, alias_id)
    except (SupplyProductNotFoundError, SupplyProductAliasNotFoundError) as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Товар или алиас не найден",
        ) from error


@router.get("/departments", response_model=list[DepartmentRead])
def read_departments(
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> list[Department]:
    return list_departments(db, tenant_id=current_admin.tenant_id)


@router.get(
    "/request-directions",
    response_model=list[SupplyRequestDirectionRead],
)
def read_request_directions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
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
    except SupplyRequestCycleNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Цикл заявок не найден",
        ) from error
    except SupplyRequestCycleUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_CYCLE_UNAVAILABLE",
                "message": "Цикл закрыт, отменён или ещё не открыт",
            },
        ) from error
    except DuplicateSupplyRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_ALREADY_EXISTS",
                "request_id": str(error.request_id),
                "request_number": error.request_number,
            },
        ) from error
    except SupplyProductNotFoundError as error:
        raise _invalid_product_reference("Товар не найден") from error
    except InactiveSupplyProductError as error:
        raise _invalid_product_reference("Товар неактивен") from error
    except SupplyUnitNotFoundError as error:
        raise _invalid_product_reference("Единица измерения не найдена") from error
    except InactiveSupplyUnitError as error:
        raise _invalid_product_reference("Единица измерения неактивна") from error
    except InvalidSupplyQuantityError as error:
        raise _invalid_product_reference(
            "Для выбранной единицы допустимо только целое количество"
        ) from error
    except (IntegrityError, PublicNumberGenerationError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Не удалось сформировать уникальный номер заявки",
        ) from error


@router.get("/requests", response_model=list[SupplyRequestListItem])
def read_requests(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_request_view_access)],
    search: Annotated[str | None, Query(max_length=240)] = None,
    department_id: UUID | None = None,
    direction_id: UUID | None = None,
    cycle_id: UUID | None = None,
    request_status: Annotated[
        SupplyRequestStatus | None, Query(alias="status")
    ] = None,
    has_needs_review: bool | None = None,
    has_duplicates: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SupplyRequest]:
    filter_values = {
        "search": search,
        "department_id": department_id,
        "direction_id": direction_id,
        "cycle_id": cycle_id,
        "request_status": request_status,
        "has_needs_review": has_needs_review,
        "has_duplicates": has_duplicates,
        "date_from": date_from,
        "date_to": date_to,
    }
    response.headers["X-Total-Count"] = str(
        count_supply_requests(
            db, tenant_id=current_user.tenant_id, **filter_values
        )
    )
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    return list_supply_requests(
        db,
        tenant_id=current_user.tenant_id,
        **filter_values,
        limit=25,
        offset=offset,
    )


@router.get("/requests/{request_id}", response_model=SupplyRequestRead)
def read_request(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_request_view_access)],
) -> SupplyRequest:
    try:
        return get_supply_request(
            db,
            request_id,
            tenant_id=current_user.tenant_id,
            include_context_mapping_suggestions=current_user.is_admin,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error


@router.get(
    "/requests/{request_id}/iiko-stock-check",
    response_model=SupplyIikoStockCheckRead,
)
def read_iiko_stock_check(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyIikoStockCheckRead:
    try:
        return get_stock_check(
            db,
            tenant_id=settings.default_tenant_id,
            request_id=request_id,
        )
    except SupplyIikoRequestNotFoundError as error:
        raise _not_found() from error


@router.put(
    "/requests/{request_id}/iiko-source-warehouse",
    response_model=SupplyIikoStockCheckRead,
)
def update_iiko_source_warehouse(
    request_id: UUID,
    payload: SupplyIikoSourceWarehouseSelect,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyIikoStockCheckRead:
    try:
        return select_source_warehouse(
            db,
            tenant_id=settings.default_tenant_id,
            request_id=request_id,
            mapping_id=payload.mapping_id,
            expected_version=payload.expected_version,
        )
    except SupplyIikoRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyIikoSourceNotAllowedError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUPPLY_IIKO_SOURCE_NOT_ALLOWED"},
        ) from error
    except SupplyIikoTerminalRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_IIKO_SOURCE_TERMINAL_REQUEST"},
        ) from error
    except SupplyIikoVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_VERSION_CONFLICT",
                "current_version": error.current_version,
                "expected_version": error.expected_version,
            },
        ) from error


@router.get(
    "/requests/{request_id}/stock-calculation",
    response_model=SupplyStockCalculationRead | None,
)
def read_stock_calculation(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyStockCalculationRead | None:
    try:
        return get_stock_calculation(
            db,
            tenant_id=current_admin.tenant_id,
            request_id=request_id,
        )
    except SupplyStockCalculationNotFoundError as error:
        raise _not_found() from error


@router.post(
    "/requests/{request_id}/stock-calculation/calculate",
    response_model=SupplyStockCalculationRead,
)
def calculate_request_stock(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> SupplyStockCalculationRead:
    try:
        return calculate_stock(
            db,
            tenant_id=user.tenant_id,
            request_id=request_id,
            actor_user_id=user.id,
        )
    except SupplyStockCalculationNotFoundError as error:
        raise _not_found() from error
    except SupplyStockCalculationUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUPPLY_STOCK_CALCULATION_NO_MATCHED_LINES"},
        ) from error


@router.patch(
    "/requests/{request_id}/stock-calculation/lines/{line_id}",
    response_model=SupplyStockCalculationRead,
)
def update_request_stock_transferable(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyStockTransferQuantityUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> SupplyStockCalculationRead:
    try:
        return adjust_transferable_quantity(
            db,
            tenant_id=settings.default_tenant_id,
            request_id=request_id,
            calculation_id=payload.calculation_id,
            expected_revision=payload.expected_revision,
            expected_version=payload.expected_version,
            line_id=line_id,
            expected_line_version=payload.expected_line_version,
            quantity=payload.quantity,
            actor_user_id=user.id,
        )
    except SupplyStockCalculationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUPPLY_STOCK_CALCULATION_NOT_FOUND"},
        ) from error
    except SupplyStockCalculationConfirmedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_STOCK_CALCULATION_CONFIRMED"},
        ) from error
    except SupplyStockCalculationVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "current_calculation_id": (
                    str(error.current_calculation_id)
                    if error.current_calculation_id is not None else None
                ),
                "current_revision": error.current_revision,
                "current_version": error.current_version,
                "current_line_version": error.current_line_version,
            },
        ) from error
    except SupplyStockTransferQuantityInvalidError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUPPLY_STOCK_TRANSFER_EXCEEDS_AVAILABLE"},
        ) from error
    except SupplyStockTransferFractionInvalidError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUPPLY_STOCK_TRANSFER_FRACTION_NOT_ALLOWED"},
        ) from error


@router.post(
    "/requests/{request_id}/stock-calculation/confirm",
    response_model=SupplyStockCalculationRead,
)
def confirm_request_stock_calculation(
    request_id: UUID,
    payload: SupplyStockCalculationConfirm,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> SupplyStockCalculationRead:
    try:
        return confirm_stock_calculation(
            db,
            tenant_id=settings.default_tenant_id,
            request_id=request_id,
            calculation_id=payload.calculation_id,
            expected_revision=payload.expected_revision,
            expected_version=payload.expected_version,
            actor_user_id=user.id,
        )
    except SupplyStockCalculationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUPPLY_STOCK_CALCULATION_NOT_FOUND"},
        ) from error
    except SupplyStockCalculationConfirmedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_STOCK_CALCULATION_CONFIRMED"},
        ) from error
    except SupplyStockCalculationVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "current_calculation_id": (
                    str(error.current_calculation_id)
                    if error.current_calculation_id is not None else None
                ),
                "current_revision": error.current_revision,
                "current_version": error.current_version,
            },
        ) from error
    except SupplyStockCalculationBlockedError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "SUPPLY_STOCK_CALCULATION_BLOCKED",
                "reasons": error.reasons,
            },
        ) from error


@router.post(
    "/product-source-mappings/bootstrap",
    response_model=SupplyProductSourceBootstrapRead,
)
def bootstrap_source_mappings(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductSourceBootstrapRead:
    return bootstrap_product_source_mappings(
        db,
        tenant_id=settings.default_tenant_id,
        actor_user_id=user.id,
    )


@router.put(
    "/products/{product_id}/source-mapping",
    response_model=SupplyProductSourceMappingRead,
)
def update_product_source_mapping(
    product_id: UUID,
    payload: SupplyProductSourceAssign,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductSourceMappingRead:
    try:
        return assign_product_source(
            db,
            tenant_id=settings.default_tenant_id,
            product_id=product_id,
            legal_contour=payload.legal_contour,
            source_mapping_id=payload.source_mapping_id,
            actor_user_id=user.id,
            expected_version=payload.expected_version,
            comment=payload.comment,
        )
    except SupplyProductSourceProductNotEligibleError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUPPLY_PRODUCT_SOURCE_PRODUCT_NOT_ELIGIBLE"},
        ) from error
    except SupplyProductSourceNotAllowedError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUPPLY_PRODUCT_SOURCE_NOT_ALLOWED"},
        ) from error
    except SupplyProductSourceReplacementCommentRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUPPLY_PRODUCT_SOURCE_REPLACEMENT_COMMENT_REQUIRED"},
        ) from error
    except SupplyProductSourceVersionConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "current_version": error.current_version,
                "expected_version": error.expected_version,
            },
        ) from error
    except SupplyProductSourceConcurrentAssignmentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_PRODUCT_SOURCE_CONFLICT"},
        ) from error


@router.get(
    "/requests/{request_id}/source-groups-preview",
    response_model=SupplyProductSourcePreviewRead,
)
def read_source_groups_preview(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductSourcePreviewRead:
    try:
        return get_product_source_preview(
            db,
            tenant_id=current_admin.tenant_id,
            request_id=request_id,
        )
    except SupplyProductSourceRequestNotFoundError as error:
        raise _not_found() from error


@router.post(
    "/requests/{request_id}/source-resolution/resolve",
    response_model=SupplyProductSourcePreviewRead,
)
def resolve_request_sources(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyProductSourcePreviewRead:
    try:
        return resolve_supply_request_sources(
            db,
            tenant_id=current_admin.tenant_id,
            request_id=request_id,
        )
    except SupplyProductSourceRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyProductSourceResolutionBlockedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_PRODUCT_SOURCE_RESOLUTION_INCOMPLETE",
                "preview": error.preview.model_dump(mode="json"),
            },
        ) from error


@router.post(
    "/requests/{request_id}/submit",
    response_model=SupplyRequestRead,
)
def submit_request(
    request_id: UUID,
    payload: SupplyExpectedVersion,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return submit_supply_request(
            db,
            request_id,
            expected_version=payload.expected_version,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}) from error
    except SupplyRequestAlreadyPlannedError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_ALREADY_PLANNED"}) from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Заявку можно отправить только один раз из статуса DRAFT",
        ) from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyRequestDuplicatesPresentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_DUPLICATES_PRESENT",
                "duplicate_groups": [
                    str(group_id) for group_id in error.duplicate_groups
                ],
            },
        ) from error


@router.post(
    "/requests/{request_id}/recognize",
    response_model=SupplyRecognitionSummary,
)
def recognize_request(
    request_id: UUID,
    payload: SupplyRecognitionRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRecognitionSummary:
    try:
        return recognize_supply_request(
            db,
            request_id,
            expected_version=payload.expected_version,
            force=payload.force,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}) from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Отменённую заявку нельзя распознавать",
        ) from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error


@router.post(
    "/requests/{request_id}/lines/{line_id}/match",
    response_model=SupplyRequestLineRead,
)
def match_request_line(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineManualMatch,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequestLine:
    try:
        return manually_match_supply_request_line(
            db,
            request_id=request_id,
            line_id=line_id,
            payload=payload,
            matched_by_user_id=current_admin.id,
            tenant_id=current_admin.tenant_id,
        )
    except (SupplyRequestNotFoundError, SupplyRequestLineNotFoundError) as error:
        raise _not_found() from error
    except SupplyRequestAlreadyPlannedError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_ALREADY_PLANNED"}) from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}) from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_REQUEST_NOT_EDITABLE"},
        ) from error
    except DuplicateSupplyProductAliasError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_ALIAS_CONFLICT"},
        ) from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyProductNotFoundError as error:
        raise _product_not_found() from error
    except SupplyUnitNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Единица измерения не найдена",
        ) from error
    except InactiveSupplyProductError as error:
        raise _invalid_product_reference("Товар неактивен") from error
    except InactiveSupplyUnitError as error:
        raise _invalid_product_reference("Единица измерения неактивна") from error
    except InvalidSupplyQuantityError as error:
        raise _invalid_product_reference(
            "Для выбранной единицы допустимо только целое количество"
        ) from error


@router.post(
    "/requests/{request_id}/lines/{line_id}/reparse",
    response_model=SupplyLineWorkingValuesRead,
)
def reparse_request_line(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyExpectedVersion,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyLineWorkingValuesRead:
    try:
        request_version, line = reparse_supply_request_line(
            db,
            request_id=request_id,
            line_id=line_id,
            expected_version=payload.expected_version,
            actor_user_id=current_admin.id,
            tenant_id=current_admin.tenant_id,
        )
        return SupplyLineWorkingValuesRead(
            request_version=request_version,
            line=line,
        )
    except (SupplyRequestNotFoundError, SupplyRequestLineNotFoundError) as error:
        raise _not_found() from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_LINE_REPARSE_NOT_ALLOWED"},
        ) from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error


@router.post(
    "/requests/{request_id}/lines/{line_id}/context-mapping",
    response_model=SupplyContextMappingRead,
    status_code=status.HTTP_201_CREATED,
)
def confirm_line_context_mapping(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyContextMappingConfirm,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return confirm_context_mapping_for_line(
            db,
            request_id=request_id,
            line_id=line_id,
            product_id=payload.product_id,
            expected_version=payload.expected_version,
            actor_user_id=current_admin.id,
        )
    except (SupplyRequestLineNotFoundError, SupplyProductNotFoundError) as error:
        raise _not_found() from error
    except (SupplyRequestStateError, IntegrityError) as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_CONTEXT_MAPPING_NOT_AVAILABLE"},
        ) from error
    except SupplyContextMappingVersionConflictError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "current_version": error.current_version,
                "expected_version": error.expected_version,
            },
        ) from error


@router.post(
    "/context-mappings/bootstrap-permanent-milk",
    response_model=SupplyContextMappingBootstrapRead,
)
def bootstrap_permanent_milk_mappings(
    payload: SupplyContextMappingBootstrapRequest,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return bootstrap_permanent_milk_context_mappings(
        db,
        tenant_id=payload.tenant_id,
        actor_user_id=current_admin.id,
    )


@router.put(
    "/context-mappings/{mapping_id}",
    response_model=SupplyContextMappingRead,
)
def replace_department_context_mapping(
    mapping_id: UUID,
    payload: SupplyContextMappingReplace,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    try:
        return replace_context_mapping(
            db,
            mapping_id=mapping_id,
            product_id=payload.product_id,
            expected_version=payload.expected_version,
            actor_user_id=current_admin.id,
        )
    except SupplyContextMappingVersionConflictError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "current_version": error.current_version,
                "expected_version": error.expected_version,
            },
        ) from error
    except (SupplyRequestStateError, SupplyProductNotFoundError) as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_CONTEXT_MAPPING_NOT_EDITABLE"},
        ) from error


@router.delete(
    "/context-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_department_context_mapping(
    mapping_id: UUID,
    expected_version: Annotated[int, Query(ge=1)],
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> Response:
    try:
        delete_context_mapping(
            db,
            mapping_id=mapping_id,
            expected_version=expected_version,
            actor_user_id=current_admin.id,
        )
    except SupplyContextMappingVersionConflictError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VERSION_CONFLICT",
                "current_version": error.current_version,
                "expected_version": error.expected_version,
            },
        ) from error
    except SupplyRequestStateError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SUPPLY_CONTEXT_MAPPING_NOT_EDITABLE"},
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/requests/{request_id}/lines/{line_id}/working-values",
    response_model=SupplyLineWorkingValuesRead,
)
def update_line_working_values(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineWorkingValuesUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyLineWorkingValuesRead:
    try:
        request_version, line = update_supply_line_working_values(
            db,
            request_id=request_id,
            line_id=line_id,
            payload=payload,
            actor_user_id=current_admin.id,
        )
        return SupplyLineWorkingValuesRead(
            request_version=request_version,
            line=line,
        )
    except (SupplyRequestNotFoundError, SupplyRequestLineNotFoundError) as error:
        raise _not_found() from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "SUPPLY_REQUEST_CANCELLED"},
        ) from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "SUPPLY_REQUEST_NOT_EDITABLE"},
        ) from error
    except SupplyUnitNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail={"code": "SUPPLY_UNIT_NOT_FOUND"},
        ) from error
    except InactiveSupplyUnitError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "SUPPLY_UNIT_INACTIVE"},
        ) from error
    except InvalidSupplyQuantityError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "SUPPLY_QUANTITY_INVALID"},
        ) from error
    except SupplyRequestedQuantityImmutableError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "SUPPLY_REQUESTED_QUANTITY_IMMUTABLE"},
        ) from error
    except SupplySendQuantityInvalidError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "SUPPLY_SEND_QUANTITY_INVALID"},
        ) from error
    except SupplyRequestPlanningIncompleteError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "SUPPLY_REQUESTED_QUANTITY_REQUIRED"},
        ) from error


@router.put(
    "/requests/{request_id}/lines/{line_id}/allocations",
    response_model=SupplyRequestRead,
)
def update_line_allocations(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineAllocationsUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return replace_supply_line_allocations(
            db,
            request_id=request_id,
            line_id=line_id,
            payload=payload,
            user_id=current_admin.id,
        )
    except (SupplyRequestNotFoundError, SupplyRequestLineNotFoundError) as error:
        raise _not_found() from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}) from error
    except SupplyRequestAlreadyPlannedError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_ALREADY_PLANNED"}) from error
    except SupplyLineNotMatchedError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_LINE_NOT_MATCHED"}) from error
    except SupplyRequestDuplicatesPresentError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_DUPLICATES_PRESENT"}) from error
    except SupplyAllocationExceedsRequestedError as error:
        raise HTTPException(status_code=422, detail={"code": "SUPPLY_ALLOCATION_EXCEEDS_REQUESTED"}) from error
    except SupplyAllocationUnitMismatchError as error:
        raise HTTPException(status_code=422, detail={"code": "SUPPLY_ALLOCATION_UNIT_MISMATCH"}) from error
    except (SupplyRequestStateError, InactiveSupplyUnitError) as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_NOT_EDITABLE"}) from error


@router.post("/requests/{request_id}/plan", response_model=SupplyRequestRead)
def plan_request(
    request_id: UUID,
    payload: SupplyRequestPlan,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return plan_supply_request(
            db, request_id,
            expected_version=payload.expected_version,
            user_id=current_admin.id,
            simple_mode=payload.simple_mode,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyRequestAlreadyPlannedError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_ALREADY_PLANNED"}) from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}) from error
    except SupplyRequestDuplicatesPresentError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_DUPLICATES_PRESENT"}) from error
    except SupplyRequestPlanningIncompleteError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_PLANNING_INCOMPLETE"}) from error
    except SupplySendQuantityInvalidError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "SUPPLY_SEND_QUANTITY_INVALID"},
        ) from error
    except SupplyRequestStateError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_NOT_EDITABLE"}) from error


@router.put(
    "/requests/{request_id}/lines/{line_id}/fulfillment",
    response_model=SupplyRequestRead,
)
def update_line_fulfillment(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineFulfillmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return update_supply_line_fulfillment(
            db,
            request_id=request_id,
            line_id=line_id,
            payload=payload,
            user_id=current_admin.id,
        )
    except (SupplyRequestNotFoundError, SupplyRequestLineNotFoundError) as error:
        raise _not_found() from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(
            status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}
        ) from error
    except (
        SupplyRequestNotFulfillableError,
        SupplyRequestAlreadyFulfilledError,
        SupplyFulfillmentExceedsPlannedError,
        SupplyFulfillmentInvalidActionError,
        SupplyFulfillmentDecreaseCommentRequiredError,
        SupplyDebtInclusionConfirmationRequiredError,
        SupplyDebtInclusionInvalidError,
        SupplyDebtProductRequiredError,
    ) as error:
        raise _fulfillment_error(error) from error


@router.post(
    "/requests/{request_id}/fulfill-as-planned",
    response_model=SupplyRequestRead,
)
def fulfill_as_planned(
    request_id: UUID,
    payload: SupplyRequestFulfillmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return fulfill_supply_request_as_planned(
            db,
            request_id,
            expected_version=payload.expected_version,
            user_id=current_admin.id,
            items=payload.items,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(
            status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}
        ) from error
    except (
        SupplyRequestNotFulfillableError,
        SupplyRequestAlreadyFulfilledError,
        SupplyFulfillmentExceedsPlannedError,
        SupplyFulfillmentInvalidActionError,
        SupplySendQuantityInvalidError,
        SupplyDebtInclusionConfirmationRequiredError,
        SupplyDebtInclusionInvalidError,
        SupplyDebtProductRequiredError,
    ) as error:
        raise _fulfillment_error(error) from error


@router.post(
    "/requests/{request_id}/lines/{line_id}/confirm-debt-inclusion",
    response_model=SupplyRequestRead,
)
def confirm_debt_inclusion(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyDebtInclusionConfirm,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return confirm_supply_debt_inclusion(
            db,
            request_id=request_id,
            line_id=line_id,
            payload=payload,
            user_id=current_admin.id,
        )
    except (SupplyRequestNotFoundError, SupplyRequestLineNotFoundError) as error:
        raise _not_found() from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except (
        SupplyRequestNotFulfillableError,
        SupplyDebtInclusionInvalidError,
    ) as error:
        raise _fulfillment_error(error) from error


@router.post("/requests/{request_id}/cancel", response_model=SupplyRequestRead)
def cancel_request(
    request_id: UUID,
    payload: SupplyRequestCancel,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return cancel_supply_request(
            db, request_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
            user_id=current_admin.id,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error
    except SupplyRequestCancelledError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_CANCELLED"}) from error
    except SupplyRequestStateError as error:
        raise HTTPException(status_code=409, detail={"code": "SUPPLY_REQUEST_NOT_EDITABLE"}) from error


@router.post(
    "/requests/{request_id}/detect-duplicates",
    response_model=SupplyRequestRead,
)
def detect_request_duplicates(
    request_id: UUID,
    payload: SupplyExpectedVersion,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return detect_supply_request_duplicates(
            db,
            request_id,
            expected_version=payload.expected_version,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestStateError as error:
        raise _reference_conflict(
            "В отменённой заявке нельзя искать дубли"
        ) from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error


@router.post(
    "/requests/{request_id}/duplicate-groups/{group_id}/resolve",
    response_model=SupplyRequestRead,
)
def resolve_request_duplicate_group(
    request_id: UUID,
    group_id: UUID,
    payload: SupplyDuplicateGroupResolve,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyRequest:
    try:
        return resolve_supply_duplicate_group(
            db,
            request_id,
            group_id,
            expected_version=payload.expected_version,
            action=payload.action,
        )
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyDuplicateGroupNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Группа дублей не найдена",
        ) from error
    except SupplyRequestStateError as error:
        raise _reference_conflict(
            "В отменённой заявке нельзя разрешать дубли"
        ) from error
    except SupplyRequestVersionConflictError as error:
        raise _version_conflict(error) from error


@router.get("/debts", response_model=SupplyDebtPage)
def read_supply_debts(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    department_id: UUID | None = None,
    product_id: UUID | None = None,
    debt_status: Annotated[
        SupplyDebtStatus | None, Query(alias="status")
    ] = None,
    severity: SupplyDebtSeverity | None = None,
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplyDebtPage:
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    items, total = list_supply_debts(
        db,
        department_id=department_id,
        product_id=product_id,
        debt_status=debt_status,
        severity=severity,
        search=search,
        limit=limit,
        offset=offset,
    )
    return SupplyDebtPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/debts/{debt_id}", response_model=SupplyDebtRead)
def read_supply_debt(
    debt_id: UUID,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> SupplyDepartmentDebt:
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    try:
        return get_supply_debt(db, debt_id)
    except SupplyDebtNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Долг подразделения не найден"
        ) from error


@router.post("/debts/{debt_id}/close", response_model=SupplyDebtRead)
def close_debt(
    debt_id: UUID,
    payload: SupplyDebtClose,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyDepartmentDebt:
    try:
        return close_supply_debt(
            db,
            debt_id,
            expected_version=payload.expected_version,
            quantity=payload.quantity,
            comment=payload.comment,
            user_id=current_admin.id,
        )
    except SupplyDebtNotFoundError as error:
        raise HTTPException(status_code=404, detail="Долг не найден") from error
    except SupplyDebtVersionConflictError as error:
        raise _debt_version_conflict(error) from error
    except SupplyDebtNotActiveError as error:
        raise HTTPException(
            status_code=409, detail={"code": "SUPPLY_DEBT_NOT_ACTIVE"}
        ) from error
    except SupplyDebtManualCloseDisabledError as error:
        raise HTTPException(
            status_code=409,
            detail={"code": "SUPPLY_DEBT_MANUAL_CLOSE_DISABLED"},
        ) from error
    except SupplyDebtCloseExceedsOutstandingError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "SUPPLY_DEBT_CLOSE_EXCEEDS_OUTSTANDING"},
        ) from error


@router.post("/debts/{debt_id}/cancel", response_model=SupplyDebtRead)
def cancel_debt(
    debt_id: UUID,
    payload: SupplyDebtCancel,
    db: Annotated[Session, Depends(get_db)],
    current_admin: Annotated[User, Depends(get_current_admin)],
) -> SupplyDepartmentDebt:
    try:
        return cancel_supply_debt(
            db,
            debt_id,
            expected_version=payload.expected_version,
            comment=payload.comment,
            user_id=current_admin.id,
        )
    except SupplyDebtNotFoundError as error:
        raise HTTPException(status_code=404, detail="Долг не найден") from error
    except SupplyDebtVersionConflictError as error:
        raise _debt_version_conflict(error) from error
    except SupplyDebtNotActiveError as error:
        raise HTTPException(
            status_code=409, detail={"code": "SUPPLY_DEBT_NOT_ACTIVE"}
        ) from error


@router.get("/summary/dashboard", response_model=SupplyDashboardSummary)
def read_supply_dashboard_summary(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> dict[str, int]:
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, max-age=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return get_supply_dashboard_summary(db)
