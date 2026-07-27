from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin, get_current_user
from app.db.session import get_db
from app.models.supply import (
    Department,
    SupplyProduct,
    SupplyProductAlias,
    SupplyProductCategory,
    SupplyRequest,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyStorageZone,
    SupplyUnit,
)
from app.models.user import User
from app.schemas.supply import (
    DepartmentRead,
    SupplyProductAliasCreate,
    SupplyProductAliasRead,
    SupplyProductCreate,
    SupplyProductPage,
    SupplyProductRead,
    SupplyProductUpdate,
    SupplyReferenceCreate,
    SupplyReferencePage,
    SupplyReferenceRead,
    SupplyReferenceUpdate,
    SupplyLineManualMatch,
    SupplyRecognitionSummary,
    SupplyRequestCreate,
    SupplyRequestDirectionRead,
    SupplyRequestLineRead,
    SupplyRequestListItem,
    SupplyRequestRead,
    SupplyUnitRead,
)
from app.supply.service import (
    DepartmentNotFoundError,
    DirectionNotFoundError,
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
    PublicNumberGenerationError,
    SupplyProductAliasNotFoundError,
    SupplyProductCategoryNotFoundError,
    SupplyProductNotFoundError,
    SupplyProductRestoreConflictError,
    SupplyRequestNotFoundError,
    SupplyRequestLineNotFoundError,
    SupplyRequestStateError,
    SupplyUnitNotFoundError,
    SupplyStorageZoneNotFoundError,
    archive_supply_product,
    create_supply_product_category,
    create_supply_product,
    create_supply_product_alias,
    create_supply_storage_zone,
    create_supply_request,
    delete_supply_product_alias,
    get_supply_product_category,
    get_supply_product,
    get_supply_storage_zone,
    get_supply_request,
    list_departments,
    list_request_directions,
    list_supply_product_categories,
    list_supply_products,
    list_supply_storage_zones,
    list_supply_requests,
    list_supply_units,
    manually_match_supply_request_line,
    recognize_supply_request,
    restore_supply_product,
    submit_supply_request,
    update_supply_product_category,
    update_supply_product,
    update_supply_storage_zone,
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


@router.get("/units", response_model=list[SupplyUnitRead])
def read_supply_units(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> list[SupplyUnit]:
    return list_supply_units(db)


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
    _: Annotated[User, Depends(get_current_admin)],
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
            detail="Такой нормализованный алиас уже существует",
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


@router.post(
    "/requests/{request_id}/recognize",
    response_model=SupplyRecognitionSummary,
)
def recognize_request(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
    force: bool = False,
) -> SupplyRecognitionSummary:
    try:
        return recognize_supply_request(db, request_id, force=force)
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Отменённую заявку нельзя распознавать",
        ) from error


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
        )
    except (SupplyRequestNotFoundError, SupplyRequestLineNotFoundError) as error:
        raise _not_found() from error
    except SupplyRequestStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Строки отменённой заявки нельзя изменять",
        ) from error
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
