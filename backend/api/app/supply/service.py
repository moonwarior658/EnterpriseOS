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
    SupplyRequest,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyUnit,
)
from app.schemas.supply import (
    SupplyProductAliasCreate,
    SupplyProductCreate,
    SupplyProductUpdate,
    SupplyRequestCreate,
)
from app.supply.normalization import normalize_product_text


PUBLIC_NUMBER_RETRY_LIMIT = 5


class SupplyRequestNotFoundError(LookupError):
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
        selectinload(SupplyProduct.aliases),
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


def create_supply_product(
    session: Session,
    payload: SupplyProductCreate,
) -> SupplyProduct:
    normalized_name = normalize_product_text(payload.name)
    if _product_name_exists(session, normalized_name):
        raise DuplicateSupplyProductError
    unit = _get_supply_unit(session, payload.default_unit_id)
    direction = (
        _get_direction(session, payload.request_direction_id)
        if payload.request_direction_id is not None
        else None
    )
    product = SupplyProduct(
        tenant_id=settings.default_tenant_id,
        name=payload.name,
        normalized_name=normalized_name,
        default_unit_id=unit.id,
        request_direction_id=direction.id if direction is not None else None,
        is_active=payload.is_active,
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
    if "is_active" in fields:
        product.is_active = bool(payload.is_active)

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
        selectinload(SupplyRequest.lines),
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
