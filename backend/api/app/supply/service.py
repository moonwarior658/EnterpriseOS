from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
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
from app.schemas.supply import (
    SupplyLineManualMatch,
    SupplyLineMatchAction,
    SupplyProductAliasCreate,
    SupplyProductCreate,
    SupplyProductUpdate,
    SupplyReferenceCreate,
    SupplyReferenceUpdate,
    SupplyRecognitionResult,
    SupplyRecognitionSummary,
    SupplyRequestCreate,
)
from app.supply.normalization import normalize_product_text
from app.supply.parser import parse_supply_line


PUBLIC_NUMBER_RETRY_LIMIT = 5


class SupplyRequestNotFoundError(LookupError):
    pass


class SupplyRequestLineNotFoundError(LookupError):
    pass


class DepartmentNotFoundError(LookupError):
    pass


class DirectionNotFoundError(LookupError):
    pass


class InactiveDepartmentError(ValueError):
    pass


class InactiveDirectionError(ValueError):
    pass


class SupplyRequestStateError(ValueError):
    pass


class PublicNumberGenerationError(RuntimeError):
    pass


class SupplyUnitNotFoundError(LookupError):
    pass


class InactiveSupplyUnitError(ValueError):
    pass


class SupplyProductNotFoundError(LookupError):
    pass


class InactiveSupplyProductError(ValueError):
    pass


class DuplicateSupplyProductError(ValueError):
    pass


class DuplicateSupplyProductAliasError(ValueError):
    pass


class SupplyProductAliasNotFoundError(LookupError):
    pass


class SupplyProductCategoryNotFoundError(LookupError):
    pass


class SupplyStorageZoneNotFoundError(LookupError):
    pass


class InactiveSupplyProductCategoryError(ValueError):
    pass


class InactiveSupplyStorageZoneError(ValueError):
    pass


class DuplicateSupplyProductCategoryError(ValueError):
    pass


class DuplicateSupplyStorageZoneError(ValueError):
    pass


class DuplicateSupplyProductIikoIdError(ValueError):
    pass


class SupplyProductRestoreConflictError(ValueError):
    pass


class InvalidSupplyQuantityError(ValueError):
    pass


def list_departments(session: Session) -> list[Department]:
    statement = (
        select(Department)
        .where(Department.tenant_id == settings.default_tenant_id)
        .order_by(Department.display_order.asc(), Department.code.asc())
    )
    return list(session.scalars(statement).all())


def list_request_directions(
    session: Session,
) -> list[SupplyRequestDirection]:
    statement = (
        select(SupplyRequestDirection)
        .where(
            SupplyRequestDirection.tenant_id == settings.default_tenant_id
        )
        .order_by(
            SupplyRequestDirection.display_order.asc(),
            SupplyRequestDirection.code.asc(),
        )
    )
    return list(session.scalars(statement).all())


def list_supply_units(session: Session) -> list[SupplyUnit]:
    statement = (
        select(SupplyUnit)
        .where(SupplyUnit.tenant_id == settings.default_tenant_id)
        .order_by(SupplyUnit.code.asc())
    )
    return list(session.scalars(statement).all())


def _get_supply_unit(
    session: Session,
    unit_id: UUID,
    *,
    require_active: bool = True,
) -> SupplyUnit:
    unit = session.scalar(
        select(SupplyUnit).where(
            SupplyUnit.id == unit_id,
            SupplyUnit.tenant_id == settings.default_tenant_id,
        )
    )
    if unit is None:
        raise SupplyUnitNotFoundError
    if require_active and not unit.is_active:
        raise InactiveSupplyUnitError
    return unit


def _product_options():
    return (
        joinedload(SupplyProduct.default_unit),
        joinedload(SupplyProduct.request_direction),
        joinedload(SupplyProduct.category),
        joinedload(SupplyProduct.storage_zone),
        selectinload(SupplyProduct.aliases),
    )


def _list_reference_items(
    session: Session,
    model,
    *,
    active: bool | None,
    search: str | None,
    limit: int,
    offset: int,
):
    filters = [model.tenant_id == settings.default_tenant_id]
    if active is not None:
        filters.append(model.is_active == active)
    if search is not None:
        normalized_search = normalize_product_text(search)
        if normalized_search:
            filters.append(
                or_(
                    model.normalized_name.contains(normalized_search),
                    model.code.contains(search.strip()),
                )
            )
    total = session.scalar(
        select(func.count()).select_from(model).where(*filters)
    )
    statement = (
        select(model)
        .where(*filters)
        .order_by(
            model.sort_order.asc(),
            model.normalized_name.asc(),
            model.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement).all()), int(total or 0)


def list_supply_product_categories(
    session: Session,
    *,
    active: bool | None,
    search: str | None,
    limit: int,
    offset: int,
) -> tuple[list[SupplyProductCategory], int]:
    return _list_reference_items(
        session,
        SupplyProductCategory,
        active=active,
        search=search,
        limit=limit,
        offset=offset,
    )


def list_supply_storage_zones(
    session: Session,
    *,
    active: bool | None,
    search: str | None,
    limit: int,
    offset: int,
) -> tuple[list[SupplyStorageZone], int]:
    return _list_reference_items(
        session,
        SupplyStorageZone,
        active=active,
        search=search,
        limit=limit,
        offset=offset,
    )


def _get_reference_item(
    session: Session,
    model,
    item_id: UUID,
    *,
    not_found_error,
    inactive_error=None,
    require_active: bool = False,
):
    item = session.scalar(
        select(model).where(
            model.id == item_id,
            model.tenant_id == settings.default_tenant_id,
        )
    )
    if item is None:
        raise not_found_error
    if require_active and not item.is_active:
        raise inactive_error
    return item


def get_supply_product_category(
    session: Session,
    category_id: UUID,
    *,
    require_active: bool = False,
) -> SupplyProductCategory:
    return _get_reference_item(
        session,
        SupplyProductCategory,
        category_id,
        not_found_error=SupplyProductCategoryNotFoundError,
        inactive_error=InactiveSupplyProductCategoryError,
        require_active=require_active,
    )


def get_supply_storage_zone(
    session: Session,
    zone_id: UUID,
    *,
    require_active: bool = False,
) -> SupplyStorageZone:
    return _get_reference_item(
        session,
        SupplyStorageZone,
        zone_id,
        not_found_error=SupplyStorageZoneNotFoundError,
        inactive_error=InactiveSupplyStorageZoneError,
        require_active=require_active,
    )


def _reference_conflict_exists(
    session: Session,
    model,
    *,
    code: str,
    normalized_name: str,
    exclude_id: UUID | None = None,
) -> bool:
    statement = select(model.id).where(
        model.tenant_id == settings.default_tenant_id,
        or_(
            model.code == code,
            model.normalized_name == normalized_name,
        ),
    )
    if exclude_id is not None:
        statement = statement.where(model.id != exclude_id)
    return session.scalar(statement.limit(1)) is not None


def _create_reference_item(
    session: Session,
    model,
    payload: SupplyReferenceCreate,
    *,
    duplicate_error,
):
    normalized_name = normalize_product_text(payload.name)
    if _reference_conflict_exists(
        session,
        model,
        code=payload.code,
        normalized_name=normalized_name,
    ):
        raise duplicate_error
    item = model(
        tenant_id=settings.default_tenant_id,
        code=payload.code,
        name=payload.name,
        normalized_name=normalized_name,
        description=payload.description,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
    )
    try:
        session.add(item)
        session.flush()
        session.commit()
        session.refresh(item)
    except IntegrityError as error:
        session.rollback()
        raise duplicate_error from error
    except Exception:
        session.rollback()
        raise
    return item


def create_supply_product_category(
    session: Session,
    payload: SupplyReferenceCreate,
) -> SupplyProductCategory:
    return _create_reference_item(
        session,
        SupplyProductCategory,
        payload,
        duplicate_error=DuplicateSupplyProductCategoryError,
    )


def create_supply_storage_zone(
    session: Session,
    payload: SupplyReferenceCreate,
) -> SupplyStorageZone:
    return _create_reference_item(
        session,
        SupplyStorageZone,
        payload,
        duplicate_error=DuplicateSupplyStorageZoneError,
    )


def _update_reference_item(
    session: Session,
    item,
    payload: SupplyReferenceUpdate,
    *,
    duplicate_error,
):
    fields = payload.model_fields_set
    code = payload.code if "code" in fields else item.code
    normalized_name = (
        normalize_product_text(payload.name or "")
        if "name" in fields
        else item.normalized_name
    )
    if _reference_conflict_exists(
        session,
        type(item),
        code=code,
        normalized_name=normalized_name,
        exclude_id=item.id,
    ):
        raise duplicate_error
    for field in ("code", "name", "description", "is_active", "sort_order"):
        if field in fields:
            setattr(item, field, getattr(payload, field))
    if "name" in fields:
        item.normalized_name = normalized_name
    try:
        session.flush()
        session.commit()
        session.refresh(item)
    except IntegrityError as error:
        session.rollback()
        raise duplicate_error from error
    except Exception:
        session.rollback()
        raise
    return item


def update_supply_product_category(
    session: Session,
    category_id: UUID,
    payload: SupplyReferenceUpdate,
) -> SupplyProductCategory:
    return _update_reference_item(
        session,
        get_supply_product_category(session, category_id),
        payload,
        duplicate_error=DuplicateSupplyProductCategoryError,
    )


def update_supply_storage_zone(
    session: Session,
    zone_id: UUID,
    payload: SupplyReferenceUpdate,
) -> SupplyStorageZone:
    return _update_reference_item(
        session,
        get_supply_storage_zone(session, zone_id),
        payload,
        duplicate_error=DuplicateSupplyStorageZoneError,
    )


def get_supply_product(
    session: Session,
    product_id: UUID,
    *,
    require_active: bool = False,
) -> SupplyProduct:
    product = session.scalar(
        select(SupplyProduct)
        .where(
            SupplyProduct.id == product_id,
            SupplyProduct.tenant_id == settings.default_tenant_id,
        )
        .options(*_product_options())
    )
    if product is None:
        raise SupplyProductNotFoundError
    if require_active and not product.is_active:
        raise InactiveSupplyProductError
    return product


def list_supply_products(
    session: Session,
    *,
    active: bool | None,
    search: str | None,
    limit: int,
    offset: int,
) -> tuple[list[SupplyProduct], int]:
    filters = [SupplyProduct.tenant_id == settings.default_tenant_id]
    if active is not None:
        filters.append(SupplyProduct.is_active == active)
    if search is not None:
        normalized_search = normalize_product_text(search)
        if normalized_search:
            filters.append(
                or_(
                    SupplyProduct.normalized_name.contains(normalized_search),
                    SupplyProduct.iiko_id.contains(search.strip()),
                    exists().where(
                        SupplyProductAlias.product_id == SupplyProduct.id,
                        SupplyProductAlias.tenant_id
                        == settings.default_tenant_id,
                        SupplyProductAlias.normalized_alias.contains(
                            normalized_search
                        ),
                    ),
                )
            )

    total = session.scalar(
        select(func.count()).select_from(SupplyProduct).where(*filters)
    )
    statement = (
        select(SupplyProduct)
        .where(*filters)
        .options(*_product_options())
        .order_by(
            SupplyProduct.normalized_name.asc(),
            SupplyProduct.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement).all()), int(total or 0)


def _product_name_exists(
    session: Session,
    normalized_name: str,
    *,
    exclude_product_id: UUID | None = None,
) -> bool:
    statement = select(SupplyProduct.id).where(
        SupplyProduct.tenant_id == settings.default_tenant_id,
        SupplyProduct.normalized_name == normalized_name,
    )
    if exclude_product_id is not None:
        statement = statement.where(SupplyProduct.id != exclude_product_id)
    return session.scalar(statement.limit(1)) is not None


def _product_iiko_id_exists(
    session: Session,
    iiko_id: str | None,
    *,
    exclude_product_id: UUID | None = None,
) -> bool:
    if iiko_id is None:
        return False
    statement = select(SupplyProduct.id).where(
        SupplyProduct.tenant_id == settings.default_tenant_id,
        SupplyProduct.iiko_id == iiko_id,
    )
    if exclude_product_id is not None:
        statement = statement.where(SupplyProduct.id != exclude_product_id)
    return session.scalar(statement.limit(1)) is not None


def create_supply_product(
    session: Session,
    payload: SupplyProductCreate,
) -> SupplyProduct:
    normalized_name = normalize_product_text(payload.name)
    if _product_name_exists(session, normalized_name):
        raise DuplicateSupplyProductError
    if _product_iiko_id_exists(session, payload.iiko_id):
        raise DuplicateSupplyProductIikoIdError
    unit = _get_supply_unit(session, payload.default_unit_id)
    direction = (
        _get_direction(session, payload.request_direction_id)
        if payload.request_direction_id is not None
        else None
    )
    category = (
        get_supply_product_category(
            session,
            payload.category_id,
            require_active=True,
        )
        if payload.category_id is not None
        else None
    )
    storage_zone = (
        get_supply_storage_zone(
            session,
            payload.storage_zone_id,
            require_active=True,
        )
        if payload.storage_zone_id is not None
        else None
    )
    product = SupplyProduct(
        tenant_id=settings.default_tenant_id,
        name=payload.name,
        normalized_name=normalized_name,
        iiko_id=payload.iiko_id,
        default_unit_id=unit.id,
        request_direction_id=direction.id if direction is not None else None,
        category_id=category.id if category is not None else None,
        storage_zone_id=storage_zone.id if storage_zone is not None else None,
        is_active=True,
    )
    try:
        session.add(product)
        session.flush()
        session.commit()
        session.expire(product)
    except IntegrityError as error:
        session.rollback()
        raise DuplicateSupplyProductError from error
    except Exception:
        session.rollback()
        raise
    return get_supply_product(session, product.id)


def update_supply_product(
    session: Session,
    product_id: UUID,
    payload: SupplyProductUpdate,
) -> SupplyProduct:
    product = get_supply_product(session, product_id)
    fields = payload.model_fields_set
    if "name" in fields:
        normalized_name = normalize_product_text(payload.name or "")
        if _product_name_exists(
            session,
            normalized_name,
            exclude_product_id=product.id,
        ):
            raise DuplicateSupplyProductError
        product.name = payload.name or ""
        product.normalized_name = normalized_name
    if "iiko_id" in fields:
        if _product_iiko_id_exists(
            session,
            payload.iiko_id,
            exclude_product_id=product.id,
        ):
            raise DuplicateSupplyProductIikoIdError
        product.iiko_id = payload.iiko_id
    if "default_unit_id" in fields:
        unit = _get_supply_unit(session, payload.default_unit_id)
        product.default_unit_id = unit.id
    if "request_direction_id" in fields:
        direction = (
            _get_direction(session, payload.request_direction_id)
            if payload.request_direction_id is not None
            else None
        )
        product.request_direction_id = (
            direction.id if direction is not None else None
        )
    if "category_id" in fields:
        category = (
            get_supply_product_category(
                session,
                payload.category_id,
                require_active=True,
            )
            if payload.category_id is not None
            else None
        )
        product.category_id = category.id if category is not None else None
    if "storage_zone_id" in fields:
        storage_zone = (
            get_supply_storage_zone(
                session,
                payload.storage_zone_id,
                require_active=True,
            )
            if payload.storage_zone_id is not None
            else None
        )
        product.storage_zone_id = (
            storage_zone.id if storage_zone is not None else None
        )

    try:
        session.flush()
        session.commit()
        session.expire(product)
    except IntegrityError as error:
        session.rollback()
        raise DuplicateSupplyProductError from error
    except Exception:
        session.rollback()
        raise
    return get_supply_product(session, product.id)


def archive_supply_product(
    session: Session,
    product_id: UUID,
    *,
    archived_by_user_id: int,
) -> SupplyProduct:
    product = get_supply_product(session, product_id)
    if not product.is_active:
        return product
    try:
        product.is_active = False
        product.archived_at = datetime.now(timezone.utc)
        product.archived_by_user_id = archived_by_user_id
        session.flush()
        session.commit()
        session.expire(product)
    except Exception:
        session.rollback()
        raise
    return get_supply_product(session, product.id)


def restore_supply_product(
    session: Session,
    product_id: UUID,
) -> SupplyProduct:
    product = get_supply_product(session, product_id)
    if product.is_active:
        return product
    try:
        _get_supply_unit(session, product.default_unit_id)
        if product.category_id is not None:
            get_supply_product_category(
                session,
                product.category_id,
                require_active=True,
            )
        if product.storage_zone_id is not None:
            get_supply_storage_zone(
                session,
                product.storage_zone_id,
                require_active=True,
            )
    except (
        InactiveSupplyUnitError,
        InactiveSupplyProductCategoryError,
        InactiveSupplyStorageZoneError,
        SupplyUnitNotFoundError,
        SupplyProductCategoryNotFoundError,
        SupplyStorageZoneNotFoundError,
    ) as error:
        raise SupplyProductRestoreConflictError from error

    try:
        product.is_active = True
        product.archived_at = None
        product.archived_by_user_id = None
        session.flush()
        session.commit()
        session.expire(product)
    except Exception:
        session.rollback()
        raise
    return get_supply_product(session, product.id)


def create_supply_product_alias(
    session: Session,
    product_id: UUID,
    payload: SupplyProductAliasCreate,
) -> SupplyProductAlias:
    product = get_supply_product(session, product_id)
    normalized_alias = normalize_product_text(payload.alias)
    duplicate = session.scalar(
        select(SupplyProductAlias.id)
        .where(
            SupplyProductAlias.tenant_id == settings.default_tenant_id,
            SupplyProductAlias.normalized_alias == normalized_alias,
        )
        .limit(1)
    )
    if duplicate is not None:
        raise DuplicateSupplyProductAliasError
    alias = SupplyProductAlias(
        tenant_id=settings.default_tenant_id,
        product_id=product.id,
        alias=payload.alias,
        normalized_alias=normalized_alias,
    )
    try:
        session.add(alias)
        session.flush()
        session.commit()
        session.refresh(alias)
    except IntegrityError as error:
        session.rollback()
        raise DuplicateSupplyProductAliasError from error
    except Exception:
        session.rollback()
        raise
    return alias


def delete_supply_product_alias(
    session: Session,
    product_id: UUID,
    alias_id: UUID,
) -> None:
    get_supply_product(session, product_id)
    alias = session.scalar(
        select(SupplyProductAlias).where(
            SupplyProductAlias.id == alias_id,
            SupplyProductAlias.product_id == product_id,
            SupplyProductAlias.tenant_id == settings.default_tenant_id,
        )
    )
    if alias is None:
        raise SupplyProductAliasNotFoundError
    try:
        session.delete(alias)
        session.commit()
    except Exception:
        session.rollback()
        raise


def validate_quantity_for_unit(
    quantity: Decimal,
    unit: SupplyUnit,
) -> None:
    if quantity <= 0:
        raise InvalidSupplyQuantityError
    if not unit.allows_fraction and quantity != quantity.to_integral_value():
        raise InvalidSupplyQuantityError


def _request_options():
    return (
        joinedload(SupplyRequest.department),
        joinedload(SupplyRequest.direction),
        selectinload(SupplyRequest.lines).joinedload(
            SupplyRequestLine.parsed_unit
        ),
        selectinload(SupplyRequest.lines).joinedload(
            SupplyRequestLine.requested_unit
        ),
        selectinload(SupplyRequest.lines)
        .joinedload(SupplyRequestLine.product)
        .joinedload(SupplyProduct.default_unit),
        selectinload(SupplyRequest.lines)
        .joinedload(SupplyRequestLine.product)
        .joinedload(SupplyProduct.request_direction),
        selectinload(SupplyRequest.lines)
        .joinedload(SupplyRequestLine.product)
        .joinedload(SupplyProduct.category),
        selectinload(SupplyRequest.lines)
        .joinedload(SupplyRequestLine.product)
        .joinedload(SupplyProduct.storage_zone),
        selectinload(SupplyRequest.lines)
        .joinedload(SupplyRequestLine.product)
        .selectinload(SupplyProduct.aliases),
    )


def get_supply_request(
    session: Session,
    request_id: UUID,
) -> SupplyRequest:
    statement = (
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == settings.default_tenant_id,
        )
        .options(*_request_options())
    )
    supply_request = session.scalar(statement)
    if supply_request is None:
        raise SupplyRequestNotFoundError
    return supply_request


def list_supply_requests(session: Session) -> list[SupplyRequest]:
    statement = (
        select(SupplyRequest)
        .where(SupplyRequest.tenant_id == settings.default_tenant_id)
        .options(*_request_options())
        .order_by(SupplyRequest.created_at.desc(), SupplyRequest.id.desc())
    )
    return list(session.scalars(statement).all())


def _get_department(session: Session, department_id: UUID) -> Department:
    department = session.scalar(
        select(Department).where(
            Department.id == department_id,
            Department.tenant_id == settings.default_tenant_id,
        )
    )
    if department is None:
        raise DepartmentNotFoundError
    if not department.is_active:
        raise InactiveDepartmentError
    return department


def _get_direction(
    session: Session,
    direction_id: UUID,
) -> SupplyRequestDirection:
    direction = session.scalar(
        select(SupplyRequestDirection).where(
            SupplyRequestDirection.id == direction_id,
            SupplyRequestDirection.tenant_id == settings.default_tenant_id,
        )
    )
    if direction is None:
        raise DirectionNotFoundError
    if not direction.is_active:
        raise InactiveDirectionError
    return direction


def _next_public_number(
    session: Session,
    *,
    department_code: str,
    direction_code: str,
    now: datetime,
) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    business_date = now.astimezone(ZoneInfo(settings.business_timezone))
    prefix = (
        f"ЗАЯВКА-{business_date:%Y%m%d}-"
        f"{department_code}-{direction_code}-"
    )
    existing_numbers = session.scalars(
        select(SupplyRequest.public_number)
        .where(
            SupplyRequest.tenant_id == settings.default_tenant_id,
            SupplyRequest.public_number.like(f"{prefix}%"),
        )
    ).all()
    sequences = [
        int(number.removeprefix(prefix))
        for number in existing_numbers
        if number.removeprefix(prefix).isdigit()
    ]
    sequence = max(sequences, default=0) + 1
    return f"{prefix}{sequence:03d}"


def _is_public_number_conflict(error: IntegrityError) -> bool:
    constraint_name = getattr(
        getattr(error.orig, "diag", None),
        "constraint_name",
        None,
    )
    if constraint_name == "uq_supply_requests_tenant_public_number":
        return True
    message = str(error.orig).lower()
    return (
        "supply_requests.tenant_id" in message
        and "supply_requests.public_number" in message
    )


def create_supply_request(
    session: Session,
    payload: SupplyRequestCreate,
    *,
    created_by_user_id: int | None,
    source_work_request_id: int | None = None,
    now: datetime | None = None,
) -> SupplyRequest:
    number_time = now or datetime.now(timezone.utc)
    for attempt in range(PUBLIC_NUMBER_RETRY_LIMIT):
        try:
            department = _get_department(session, payload.department_id)
            direction = _get_direction(session, payload.direction_id)
            public_number = _next_public_number(
                session,
                department_code=department.code,
                direction_code=direction.code,
                now=number_time,
            )
            supply_request = SupplyRequest(
                tenant_id=settings.default_tenant_id,
                public_number=public_number,
                department_id=department.id,
                direction_id=direction.id,
                status="DRAFT",
                source_type="INTERNAL",
                source_work_request_id=source_work_request_id,
                raw_input=payload.raw_input,
                version=1,
                created_by_user_id=created_by_user_id,
            )
            request_lines = []
            for position, line in enumerate(payload.lines, start=1):
                product = (
                    get_supply_product(
                        session,
                        line.product_id,
                        require_active=True,
                    )
                    if line.product_id is not None
                    else None
                )
                unit = (
                    _get_supply_unit(session, line.requested_unit_id)
                    if line.requested_unit_id is not None
                    else None
                )
                if line.quantity is not None and unit is not None:
                    validate_quantity_for_unit(line.quantity, unit)
                request_lines.append(
                    SupplyRequestLine(
                        position=position,
                        raw_text=line.raw_text,
                        product_id=product.id if product is not None else None,
                        requested_unit_id=unit.id if unit is not None else None,
                        quantity=line.quantity,
                    )
                )
            supply_request.lines = request_lines
            session.add(supply_request)
            session.flush()
            session.commit()
            return get_supply_request(session, supply_request.id)
        except IntegrityError as error:
            session.rollback()
            if (
                _is_public_number_conflict(error)
                and attempt + 1 < PUBLIC_NUMBER_RETRY_LIMIT
            ):
                continue
            raise
        except Exception:
            session.rollback()
            raise

    raise PublicNumberGenerationError


def submit_supply_request(
    session: Session,
    request_id: UUID,
) -> SupplyRequest:
    supply_request = get_supply_request(session, request_id)
    if supply_request.status != "DRAFT":
        raise SupplyRequestStateError
    if not supply_request.lines:
        raise SupplyRequestStateError

    try:
        supply_request.status = "SUBMITTED"
        supply_request.submitted_at = datetime.now(timezone.utc)
        supply_request.version += 1
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise

    return get_supply_request(session, request_id)


def _get_supply_request_for_update(
    session: Session,
    request_id: UUID,
) -> SupplyRequest:
    supply_request = session.scalar(
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == settings.default_tenant_id,
        )
        .with_for_update()
    )
    if supply_request is None:
        raise SupplyRequestNotFoundError
    if supply_request.status == "CANCELLED":
        raise SupplyRequestStateError
    return supply_request


def _get_request_line_for_update(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
) -> tuple[SupplyRequest, SupplyRequestLine]:
    supply_request = _get_supply_request_for_update(session, request_id)
    line = session.scalar(
        select(SupplyRequestLine)
        .where(
            SupplyRequestLine.id == line_id,
            SupplyRequestLine.request_id == supply_request.id,
        )
        .with_for_update()
    )
    if line is None:
        raise SupplyRequestLineNotFoundError
    return supply_request, line


def _clear_confirmed_match(line: SupplyRequestLine) -> None:
    line.product_id = None
    line.requested_unit_id = None
    line.quantity = None
    line.match_method = None
    line.match_confidence = None
    line.matched_at = None
    line.matched_by_user_id = None
    line.match_notes = None


def _find_exact_product(
    session: Session,
    normalized_name: str,
) -> tuple[SupplyProduct | None, str | None]:
    product = session.scalar(
        select(SupplyProduct).where(
            SupplyProduct.tenant_id == settings.default_tenant_id,
            SupplyProduct.is_active.is_(True),
            SupplyProduct.normalized_name == normalized_name,
        )
    )
    if product is not None:
        return product, "EXACT_PRODUCT"

    products = list(
        session.scalars(
            select(SupplyProduct)
            .join(
                SupplyProductAlias,
                SupplyProductAlias.product_id == SupplyProduct.id,
            )
            .where(
                SupplyProduct.tenant_id == settings.default_tenant_id,
                SupplyProduct.is_active.is_(True),
                SupplyProductAlias.tenant_id == settings.default_tenant_id,
                SupplyProductAlias.normalized_alias == normalized_name,
            )
            .limit(2)
        ).all()
    )
    if len(products) == 1:
        return products[0], "EXACT_ALIAS"
    return None, None


def _recognize_line(
    session: Session,
    line: SupplyRequestLine,
    *,
    now: datetime,
) -> None:
    parsed = parse_supply_line(line.raw_text)
    _clear_confirmed_match(line)
    if parsed is None:
        line.parsed_name = None
        line.parsed_quantity = None
        line.parsed_unit_id = None
        line.match_status = "NEEDS_REVIEW"
        return

    line.parsed_name = parsed.name
    line.parsed_quantity = parsed.quantity
    unit = session.scalar(
        select(SupplyUnit).where(
            SupplyUnit.tenant_id == settings.default_tenant_id,
            SupplyUnit.code == parsed.unit_code,
            SupplyUnit.is_active.is_(True),
        )
    )
    if unit is None:
        line.parsed_unit_id = None
        line.match_status = "NEEDS_REVIEW"
        return

    line.parsed_unit_id = unit.id
    product, method = _find_exact_product(
        session,
        normalize_product_text(parsed.name),
    )
    if product is None or method is None:
        line.match_status = "NEEDS_REVIEW"
        return

    line.product_id = product.id
    line.requested_unit_id = unit.id
    line.quantity = parsed.quantity
    line.match_status = "MATCHED"
    line.match_method = method
    line.match_confidence = Decimal("1.0000")
    line.matched_at = now


def recognize_supply_request(
    session: Session,
    request_id: UUID,
    *,
    force: bool = False,
) -> SupplyRecognitionSummary:
    supply_request = _get_supply_request_for_update(session, request_id)
    lines = list(
        session.scalars(
            select(SupplyRequestLine)
            .where(SupplyRequestLine.request_id == supply_request.id)
            .order_by(SupplyRequestLine.position.asc())
            .with_for_update()
        ).all()
    )
    now = datetime.now(timezone.utc)
    results: list[SupplyRecognitionResult] = []
    changed = False
    for line in lines:
        skipped = not force and line.match_method == "MANUAL"
        if not skipped:
            _recognize_line(session, line, now=now)
            changed = True
        results.append(
            SupplyRecognitionResult(
                line_id=line.id,
                position=line.position,
                match_status=line.match_status,
                match_method=line.match_method,
                skipped=skipped,
            )
        )

    if changed:
        supply_request.version += 1
    try:
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise

    return SupplyRecognitionSummary(
        total=len(results),
        matched=sum(
            not result.skipped and result.match_status == "MATCHED"
            for result in results
        ),
        needs_review=sum(
            not result.skipped and result.match_status == "NEEDS_REVIEW"
            for result in results
        ),
        rejected=sum(
            not result.skipped and result.match_status == "REJECTED"
            for result in results
        ),
        skipped=sum(result.skipped for result in results),
        results=results,
    )


def manually_match_supply_request_line(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineManualMatch,
    matched_by_user_id: int,
) -> SupplyRequestLine:
    supply_request, line = _get_request_line_for_update(
        session,
        request_id=request_id,
        line_id=line_id,
    )
    now = datetime.now(timezone.utc)

    if payload.action == SupplyLineMatchAction.MATCH:
        product = get_supply_product(
            session,
            payload.product_id,
            require_active=True,
        )
        unit = _get_supply_unit(session, payload.unit_id)
        validate_quantity_for_unit(payload.quantity, unit)
        line.product_id = product.id
        line.requested_unit_id = unit.id
        line.quantity = payload.quantity
        line.match_status = "MATCHED"
        line.match_method = "MANUAL"
        line.match_confidence = Decimal("1.0000")
        line.matched_at = now
        line.matched_by_user_id = matched_by_user_id
        line.match_notes = payload.notes
    elif payload.action == SupplyLineMatchAction.REJECT:
        _clear_confirmed_match(line)
        line.match_status = "REJECTED"
        line.match_method = "MANUAL"
        line.matched_at = now
        line.matched_by_user_id = matched_by_user_id
        line.match_notes = payload.notes
    else:
        _clear_confirmed_match(line)
        line.match_status = "UNPROCESSED"

    supply_request.version += 1
    try:
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    refreshed_request = get_supply_request(session, request_id)
    return next(
        request_line
        for request_line in refreshed_request.lines
        if request_line.id == line_id
    )
