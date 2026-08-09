from datetime import date, datetime, timezone
from decimal import Decimal
import logging
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
from app.models.supply import (
    Department,
    SupplyContextMappingAuditAction,
    SupplyDepartmentProductCorrection,
    SupplyDepartmentProductMapping,
    SupplyDepartmentProductMappingAuditEvent,
    SupplyDepartmentDebt,
    SupplyDepartmentDebtEvent,
    SupplyProduct,
    SupplyProductAlias,
    SupplyProductCategory,
    SupplyLineAllocation,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyRequestLineDebtLink,
    SupplyStorageZone,
    SupplyUnit,
)
from app.schemas.supply import (
    SupplyContextMappingBootstrapRead,
    SupplyLineManualMatch,
    SupplyLineWorkingValuesUpdate,
    SupplyLineAllocationsUpdate,
    SupplyLineFulfillmentUpdate,
    SupplyRequestFulfillmentItem,
    SupplyDebtInclusionConfirm,
    SupplyLineMatchAction,
    SupplyDuplicateResolutionAction,
    SupplyProductAliasCreate,
    SupplyProductCreate,
    SupplyProductUpdate,
    SupplyReferenceCreate,
    SupplyReferenceUpdate,
    SupplyRecognitionResult,
    SupplyRecognitionSummary,
    SupplyRequestCreate,
    SupplyRequestCycleCreate,
    SupplyRequestCycleUpdate,
)
from app.supply.normalization import normalize_product_text
from app.supply.parser import parse_supply_line, supply_line_product_name


PUBLIC_NUMBER_RETRY_LIMIT = 5
SIMPLE_MODE_ALLOCATION_COMMENT = (
    "Техническое решение простого режима"
)
logger = logging.getLogger(__name__)


class SupplyRequestNotFoundError(LookupError):
    pass


class SupplyRequestLineNotFoundError(LookupError):
    pass


class SupplyContextMappingVersionConflictError(ValueError):
    def __init__(
        self,
        current_version: int | None,
        expected_version: int | None,
    ):
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__("Supply contextual mapping version conflict")


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


class SupplyRequestCancelledError(SupplyRequestStateError):
    pass


class SupplyRequestAlreadyPlannedError(SupplyRequestStateError):
    pass


class SupplyRequestCycleNotFoundError(LookupError):
    pass


class DuplicateSupplyRequestCycleError(ValueError):
    pass


class SupplyRequestCycleStateError(ValueError):
    pass


class SupplyRequestCycleHasRequestsError(ValueError):
    pass


class SupplyRequestCycleUnavailableError(ValueError):
    pass


class DuplicateSupplyRequestError(ValueError):
    def __init__(self, request_id: UUID, request_number: str):
        self.request_id = request_id
        self.request_number = request_number
        super().__init__("Supply request already exists")


class SupplyRequestVersionConflictError(ValueError):
    def __init__(self, current_version: int, expected_version: int):
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__("Supply request version conflict")


class SupplyRequestDuplicatesPresentError(ValueError):
    def __init__(self, duplicate_groups: list[UUID]):
        self.duplicate_groups = duplicate_groups
        super().__init__("Supply request contains duplicates")


class SupplyDuplicateGroupNotFoundError(LookupError):
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


class SupplyLineNotMatchedError(ValueError):
    pass


class SupplyAllocationExceedsRequestedError(ValueError):
    pass


class SupplyAllocationUnitMismatchError(ValueError):
    pass


class SupplyRequestedQuantityImmutableError(ValueError):
    pass


class SupplySendQuantityInvalidError(ValueError):
    pass


class SupplyRequestPlanningIncompleteError(ValueError):
    pass


class SupplyRequestNotFulfillableError(ValueError):
    pass


class SupplyFulfillmentExceedsPlannedError(ValueError):
    pass


class SupplyFulfillmentInvalidActionError(ValueError):
    pass


class SupplyFulfillmentDecreaseCommentRequiredError(ValueError):
    pass


class SupplyRequestAlreadyFulfilledError(ValueError):
    pass


class SupplyDebtNotFoundError(LookupError):
    pass


class SupplyDebtVersionConflictError(ValueError):
    def __init__(self, current_version: int, expected_version: int):
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__("Supply debt version conflict")


class SupplyDebtNotActiveError(ValueError):
    pass


class SupplyDebtCloseExceedsOutstandingError(ValueError):
    pass


class SupplyDebtManualCloseDisabledError(ValueError):
    pass


class SupplyDebtInclusionConfirmationRequiredError(ValueError):
    pass


class SupplyDebtInclusionInvalidError(ValueError):
    pass


class SupplyDebtProductRequiredError(ValueError):
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


def _cycle_options():
    return (joinedload(SupplyRequestCycle.direction),)


def list_supply_request_cycles(
    session: Session,
    *,
    direction_id: UUID | None,
    cycle_status: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> tuple[list[SupplyRequestCycle], int]:
    filters = [SupplyRequestCycle.tenant_id == settings.default_tenant_id]
    if direction_id is not None:
        filters.append(SupplyRequestCycle.direction_id == direction_id)
    if cycle_status is not None:
        filters.append(SupplyRequestCycle.status == cycle_status)
    if date_from is not None:
        filters.append(SupplyRequestCycle.cycle_date >= date_from)
    if date_to is not None:
        filters.append(SupplyRequestCycle.cycle_date <= date_to)
    total = session.scalar(
        select(func.count()).select_from(SupplyRequestCycle).where(*filters)
    )
    statement = (
        select(SupplyRequestCycle)
        .where(*filters)
        .options(*_cycle_options())
        .order_by(
            SupplyRequestCycle.cycle_date.desc(),
            SupplyRequestCycle.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement).all()), int(total or 0)


def get_supply_request_cycle(
    session: Session,
    cycle_id: UUID,
) -> SupplyRequestCycle:
    cycle = session.scalar(
        select(SupplyRequestCycle)
        .where(
            SupplyRequestCycle.id == cycle_id,
            SupplyRequestCycle.tenant_id == settings.default_tenant_id,
        )
        .options(*_cycle_options())
    )
    if cycle is None:
        raise SupplyRequestCycleNotFoundError
    return cycle


def _validate_cycle_window(
    opens_at: datetime,
    closes_at: datetime,
    hard_closes_at: datetime | None,
) -> None:
    normalized_opens_at = _as_aware_utc(opens_at)
    normalized_closes_at = _as_aware_utc(closes_at)
    if normalized_closes_at <= normalized_opens_at:
        raise SupplyRequestCycleStateError
    if (
        hard_closes_at is not None
        and _as_aware_utc(hard_closes_at) < normalized_closes_at
    ):
        raise SupplyRequestCycleStateError


def _advance_debts_for_closed_cycle(
    session: Session,
    cycle: SupplyRequestCycle,
) -> None:
    return None


def create_supply_request_cycle(
    session: Session,
    payload: SupplyRequestCycleCreate,
) -> SupplyRequestCycle:
    direction = _get_direction(session, payload.direction_id)
    cycle = SupplyRequestCycle(
        tenant_id=settings.default_tenant_id,
        direction_id=direction.id,
        cycle_date=payload.cycle_date,
        opens_at=payload.opens_at,
        closes_at=payload.closes_at,
        hard_closes_at=payload.hard_closes_at,
        status=payload.status,
    )
    try:
        session.add(cycle)
        session.flush()
        if cycle.status == "CLOSED":
            _advance_debts_for_closed_cycle(session, cycle)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicateSupplyRequestCycleError from error
    except Exception:
        session.rollback()
        raise
    return get_supply_request_cycle(session, cycle.id)


def update_supply_request_cycle(
    session: Session,
    cycle_id: UUID,
    payload: SupplyRequestCycleUpdate,
) -> SupplyRequestCycle:
    cycle = get_supply_request_cycle(session, cycle_id)
    fields = payload.model_fields_set
    has_requests = session.scalar(
        select(
            exists().where(
                SupplyRequest.tenant_id == settings.default_tenant_id,
                SupplyRequest.cycle_id == cycle.id,
            )
        )
    )
    identity_changes = (
        "direction_id" in fields
        and payload.direction_id != cycle.direction_id
    ) or (
        "cycle_date" in fields
        and payload.cycle_date != cycle.cycle_date
    )
    if has_requests and identity_changes:
        raise SupplyRequestCycleHasRequestsError

    if "direction_id" in fields:
        direction = _get_direction(session, payload.direction_id)
        cycle.direction_id = direction.id
    if "cycle_date" in fields:
        cycle.cycle_date = payload.cycle_date

    opens_at = payload.opens_at if "opens_at" in fields else cycle.opens_at
    closes_at = (
        payload.closes_at if "closes_at" in fields else cycle.closes_at
    )
    hard_closes_at = (
        payload.hard_closes_at
        if "hard_closes_at" in fields
        else cycle.hard_closes_at
    )
    _validate_cycle_window(opens_at, closes_at, hard_closes_at)

    previous_status = cycle.status
    if "status" in fields:
        allowed_transitions = {
            "SCHEDULED": {"SCHEDULED", "OPEN", "CLOSED", "CANCELLED"},
            "OPEN": {"OPEN", "CLOSED", "CANCELLED"},
            "CLOSED": {"CLOSED"},
            "CANCELLED": {"CANCELLED"},
        }
        if payload.status not in allowed_transitions[cycle.status]:
            raise SupplyRequestCycleStateError
        cycle.status = payload.status
    cycle.opens_at = opens_at
    cycle.closes_at = closes_at
    cycle.hard_closes_at = hard_closes_at
    try:
        session.flush()
        if previous_status != "CLOSED" and cycle.status == "CLOSED":
            _advance_debts_for_closed_cycle(session, cycle)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicateSupplyRequestCycleError from error
    except Exception:
        session.rollback()
        raise
    return get_supply_request_cycle(session, cycle.id)


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
    ranking = None
    if active is not None:
        filters.append(SupplyProduct.is_active == active)
    if search is not None:
        normalized_search = normalize_product_text(search)
        if normalized_search:
            exact_alias = exists().where(
                SupplyProductAlias.product_id == SupplyProduct.id,
                SupplyProductAlias.tenant_id == settings.default_tenant_id,
                SupplyProductAlias.normalized_alias == normalized_search,
                SupplyProductAlias.status == "APPROVED",
            )
            prefix_alias = exists().where(
                SupplyProductAlias.product_id == SupplyProduct.id,
                SupplyProductAlias.tenant_id == settings.default_tenant_id,
                SupplyProductAlias.status == "APPROVED",
                SupplyProductAlias.normalized_alias.startswith(
                    normalized_search
                ),
            )
            partial_alias = exists().where(
                SupplyProductAlias.product_id == SupplyProduct.id,
                SupplyProductAlias.tenant_id == settings.default_tenant_id,
                SupplyProductAlias.status == "APPROVED",
                SupplyProductAlias.normalized_alias.contains(
                    normalized_search
                ),
            )
            filters.append(
                or_(
                    SupplyProduct.normalized_name.contains(normalized_search),
                    SupplyProduct.iiko_id.contains(search.strip()),
                    partial_alias,
                )
            )
            ranking = case(
                (SupplyProduct.normalized_name == normalized_search, 1),
                (exact_alias, 2),
                (SupplyProduct.normalized_name.startswith(normalized_search), 3),
                (prefix_alias, 4),
                else_=5,
            )

    total = session.scalar(
        select(func.count()).select_from(SupplyProduct).where(*filters)
    )
    statement = select(SupplyProduct).where(*filters).options(
        *_product_options()
    )
    if ranking is not None:
        statement = statement.order_by(
            ranking.asc(),
            SupplyProduct.normalized_name.asc(),
            SupplyProduct.id.asc(),
        )
    else:
        statement = statement.order_by(
            SupplyProduct.normalized_name.asc(),
            SupplyProduct.id.asc(),
        )
    statement = statement.limit(limit).offset(offset)
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
        joinedload(SupplyRequest.cycle).joinedload(
            SupplyRequestCycle.direction
        ),
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
        selectinload(SupplyRequest.lines)
        .selectinload(SupplyRequestLine.allocations)
        .joinedload(SupplyLineAllocation.unit),
        selectinload(SupplyRequest.lines)
        .joinedload(SupplyRequestLine.debt_link)
        .joinedload(SupplyRequestLineDebtLink.debt),
        selectinload(SupplyRequest.lines)
        .joinedload(SupplyRequestLine.debt_link)
        .joinedload(SupplyRequestLineDebtLink.included_debt),
    )


def _populate_active_debt_context(
    session: Session,
    requests: list[SupplyRequest],
    *,
    tenant_id: str = settings.default_tenant_id,
) -> None:
    keys = {
        (request.department_id, line.product_id, line.requested_unit_id)
        for request in requests
        for line in request.lines
        if line.product_id is not None and line.requested_unit_id is not None
    }
    if not keys:
        return
    debts = session.scalars(
        select(SupplyDepartmentDebt)
        .where(
            SupplyDepartmentDebt.tenant_id == tenant_id,
            SupplyDepartmentDebt.status == "ACTIVE",
            or_(*[
                (
                    (SupplyDepartmentDebt.department_id == department_id)
                    & (SupplyDepartmentDebt.product_id == product_id)
                    & (SupplyDepartmentDebt.unit_id == unit_id)
                )
                for department_id, product_id, unit_id in keys
            ]),
        )
    ).all()
    by_key = {
        (debt.department_id, debt.product_id, debt.unit_id): debt
        for debt in debts
    }
    for request in requests:
        for line in request.lines:
            line._active_debt = by_key.get(
                (
                    request.department_id,
                    line.product_id,
                    line.requested_unit_id,
                )
            )


def get_supply_request(
    session: Session,
    request_id: UUID,
    *,
    tenant_id: str = settings.default_tenant_id,
    include_context_mapping_suggestions: bool = True,
) -> SupplyRequest:
    statement = (
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == tenant_id,
        )
        .options(*_request_options())
    )
    supply_request = session.scalar(statement)
    if supply_request is None:
        raise SupplyRequestNotFoundError
    _populate_active_debt_context(
        session, [supply_request], tenant_id=tenant_id
    )
    if include_context_mapping_suggestions:
        _populate_context_mapping_suggestions(session, supply_request)
    return supply_request


def _supply_request_filters(
    *,
    tenant_id: str = settings.default_tenant_id,
    search: str | None = None,
    department_id: UUID | None = None,
    direction_id: UUID | None = None,
    cycle_id: UUID | None = None,
    request_status: str | None = None,
    has_needs_review: bool | None = None,
    has_duplicates: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list:
    filters = [SupplyRequest.tenant_id == tenant_id]
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(
            SupplyRequest.public_number.ilike(term),
            SupplyRequest.raw_input.ilike(term),
            SupplyRequest.public_author_name.ilike(term),
        ))
    if department_id:
        filters.append(SupplyRequest.department_id == department_id)
    if direction_id:
        filters.append(SupplyRequest.direction_id == direction_id)
    if cycle_id:
        filters.append(SupplyRequest.cycle_id == cycle_id)
    if request_status:
        filters.append(SupplyRequest.status == request_status)
    if date_from:
        filters.append(func.date(func.coalesce(
            SupplyRequest.submitted_at, SupplyRequest.created_at
        )) >= date_from)
    if date_to:
        filters.append(func.date(func.coalesce(
            SupplyRequest.submitted_at, SupplyRequest.created_at
        )) <= date_to)
    if has_needs_review is not None:
        predicate = exists().where(
            SupplyRequestLine.request_id == SupplyRequest.id,
            SupplyRequestLine.match_status.in_(
                {"UNPROCESSED", "PARSED", "NEEDS_REVIEW"}
            ),
        )
        filters.append(predicate if has_needs_review else ~predicate)
    if has_duplicates is not None:
        predicate = exists().where(
            SupplyRequestLine.request_id == SupplyRequest.id,
            SupplyRequestLine.duplicate_status.in_({"SUSPECTED", "CONFIRMED"}),
        )
        filters.append(predicate if has_duplicates else ~predicate)
    return filters


def count_supply_requests(
    session: Session,
    **filter_values,
) -> int:
    filters = _supply_request_filters(**filter_values)
    return int(session.scalar(
        select(func.count()).select_from(SupplyRequest).where(*filters)
    ) or 0)


def list_supply_requests(
    session: Session,
    *,
    tenant_id: str = settings.default_tenant_id,
    search: str | None = None,
    department_id: UUID | None = None,
    direction_id: UUID | None = None,
    cycle_id: UUID | None = None,
    request_status: str | None = None,
    has_needs_review: bool | None = None,
    has_duplicates: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 25,
    offset: int = 0,
) -> list[SupplyRequest]:
    filters = _supply_request_filters(
        tenant_id=tenant_id,
        search=search,
        department_id=department_id,
        direction_id=direction_id,
        cycle_id=cycle_id,
        request_status=request_status,
        has_needs_review=has_needs_review,
        has_duplicates=has_duplicates,
        date_from=date_from,
        date_to=date_to,
    )
    statement = (
        select(SupplyRequest)
        .where(*filters)
        .options(*_request_options())
        .order_by(
            case(
                (SupplyRequest.status.in_(
                    {"SUBMITTED", "IN_REVIEW"}
                ), 0),
                else_=1,
            ),
            func.coalesce(
                SupplyRequest.submitted_at, SupplyRequest.created_at
            ).desc(),
            SupplyRequest.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    requests = list(session.scalars(statement).all())
    _populate_active_debt_context(session, requests, tenant_id=tenant_id)
    return requests


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


def _get_cycle(
    session: Session,
    cycle_id: UUID,
) -> SupplyRequestCycle:
    cycle = session.scalar(
        select(SupplyRequestCycle).where(
            SupplyRequestCycle.id == cycle_id,
            SupplyRequestCycle.tenant_id == settings.default_tenant_id,
        )
    )
    if cycle is None:
        raise SupplyRequestCycleNotFoundError
    return cycle


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_cycle_for_new_request(
    cycle: SupplyRequestCycle,
    *,
    direction_id: UUID,
    now: datetime,
) -> None:
    if cycle.direction_id != direction_id or cycle.status != "OPEN":
        raise SupplyRequestCycleUnavailableError
    business_timezone = ZoneInfo(settings.business_timezone)
    business_now = now.astimezone(business_timezone)
    open_time = _as_aware_utc(cycle.opens_at).astimezone(business_timezone)
    deadline = _as_aware_utc(
        cycle.hard_closes_at or cycle.closes_at
    ).astimezone(business_timezone)
    if business_now < open_time or business_now > deadline:
        raise SupplyRequestCycleUnavailableError


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


def _is_request_uniqueness_conflict(error: IntegrityError) -> bool:
    constraint_name = getattr(
        getattr(error.orig, "diag", None),
        "constraint_name",
        None,
    )
    if (
        constraint_name
        == "uq_supply_requests_tenant_department_direction_cycle"
    ):
        return True
    message = str(error.orig).lower()
    return all(
        column in message
        for column in (
            "supply_requests.tenant_id",
            "supply_requests.department_id",
            "supply_requests.direction_id",
            "supply_requests.cycle_id",
        )
    )


def _existing_request_for_cycle(
    session: Session,
    *,
    department_id: UUID,
    direction_id: UUID,
    cycle_id: UUID,
) -> SupplyRequest | None:
    return session.scalar(
        select(SupplyRequest).where(
            SupplyRequest.tenant_id == settings.default_tenant_id,
            SupplyRequest.department_id == department_id,
            SupplyRequest.direction_id == direction_id,
            SupplyRequest.cycle_id == cycle_id,
        )
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
            cycle = _get_cycle(session, payload.cycle_id)
            _validate_cycle_for_new_request(
                cycle,
                direction_id=direction.id,
                now=number_time,
            )
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
                cycle_id=cycle.id,
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
                        tenant_id=settings.default_tenant_id,
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
            if _is_request_uniqueness_conflict(error):
                existing = _existing_request_for_cycle(
                    session,
                    department_id=payload.department_id,
                    direction_id=payload.direction_id,
                    cycle_id=payload.cycle_id,
                )
                if existing is not None:
                    raise DuplicateSupplyRequestError(
                        existing.id,
                        existing.public_number,
                    ) from error
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


def _get_supply_request_for_update(
    session: Session,
    request_id: UUID,
    *,
    expected_version: int | None = None,
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
        raise SupplyRequestCancelledError
    if (
        expected_version is not None
        and supply_request.version != expected_version
    ):
        raise SupplyRequestVersionConflictError(
            supply_request.version,
            expected_version,
        )
    return supply_request


def _get_request_line_for_update(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
    expected_version: int,
) -> tuple[SupplyRequest, SupplyRequestLine]:
    supply_request = _get_supply_request_for_update(
        session,
        request_id,
        expected_version=expected_version,
    )
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


def _duplicate_key(line: SupplyRequestLine) -> str | None:
    if line.match_status == "MATCHED" and line.product_id is not None:
        return f"product:{line.product_id}"
    if line.parsed_name:
        normalized_name = normalize_product_text(line.parsed_name)
        if normalized_name:
            return f"name:{normalized_name}"
    return None


def _apply_duplicate_detection(
    supply_request: SupplyRequest,
    lines: list[SupplyRequestLine],
) -> tuple[list[UUID], bool]:
    grouped: dict[str, list[SupplyRequestLine]] = {}
    for line in lines:
        key = _duplicate_key(line)
        if key is not None:
            grouped.setdefault(key, []).append(line)

    duplicate_groups: list[UUID] = []
    changed = False
    duplicate_line_ids: set[UUID] = set()
    for key, group_lines in grouped.items():
        if len(group_lines) < 2:
            continue
        duplicate_line_ids.update(line.id for line in group_lines)
        group_id = uuid5(
            NAMESPACE_URL,
            f"enterpriseos:supply:{supply_request.id}:{key}",
        )
        duplicate_groups.append(group_id)
        preserved_statuses = {
            line.duplicate_status
            for line in group_lines
            if line.duplicate_group_id == group_id
        }
        if (
            len(preserved_statuses) == 1
            and preserved_statuses <= {"CONFIRMED", "RESOLVED"}
            and all(line.duplicate_group_id == group_id for line in group_lines)
        ):
            target_status = preserved_statuses.pop()
        else:
            target_status = "SUSPECTED"
        for line in group_lines:
            if (
                line.duplicate_group_id != group_id
                or line.duplicate_status != target_status
            ):
                line.duplicate_group_id = group_id
                line.duplicate_status = target_status
                changed = True

    for line in lines:
        if line.id not in duplicate_line_ids and (
            line.duplicate_group_id is not None
            or line.duplicate_status != "NONE"
        ):
            line.duplicate_group_id = None
            line.duplicate_status = "NONE"
            changed = True
    return sorted(duplicate_groups, key=str), changed


def detect_supply_request_duplicates(
    session: Session,
    request_id: UUID,
    *,
    expected_version: int,
) -> SupplyRequest:
    supply_request = _get_supply_request_for_update(
        session,
        request_id,
        expected_version=expected_version,
    )
    lines = list(
        session.scalars(
            select(SupplyRequestLine)
            .where(SupplyRequestLine.request_id == supply_request.id)
            .order_by(SupplyRequestLine.position.asc())
            .with_for_update()
        ).all()
    )
    _, changed = _apply_duplicate_detection(supply_request, lines)
    if changed:
        supply_request.version += 1
    try:
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def resolve_supply_duplicate_group(
    session: Session,
    request_id: UUID,
    group_id: UUID,
    *,
    expected_version: int,
    action: SupplyDuplicateResolutionAction,
) -> SupplyRequest:
    supply_request = _get_supply_request_for_update(
        session,
        request_id,
        expected_version=expected_version,
    )
    lines = list(
        session.scalars(
            select(SupplyRequestLine)
            .where(
                SupplyRequestLine.request_id == supply_request.id,
                SupplyRequestLine.duplicate_group_id == group_id,
            )
            .with_for_update()
        ).all()
    )
    if len(lines) < 2:
        raise SupplyDuplicateGroupNotFoundError
    target_status = (
        "RESOLVED"
        if action == SupplyDuplicateResolutionAction.KEEP_SEPARATE
        else "CONFIRMED"
    )
    changed = any(line.duplicate_status != target_status for line in lines)
    for line in lines:
        line.duplicate_status = target_status
    if changed:
        supply_request.version += 1
    try:
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def submit_supply_request(
    session: Session,
    request_id: UUID,
    *,
    expected_version: int,
) -> SupplyRequest:
    supply_request = _get_supply_request_for_update(
        session,
        request_id,
        expected_version=expected_version,
    )
    if supply_request.status != "DRAFT":
        raise SupplyRequestStateError
    lines = list(
        session.scalars(
            select(SupplyRequestLine)
            .where(SupplyRequestLine.request_id == supply_request.id)
            .order_by(SupplyRequestLine.position.asc())
            .with_for_update()
        ).all()
    )
    if not lines:
        raise SupplyRequestStateError
    _apply_duplicate_detection(supply_request, lines)
    blocking_groups = sorted(
        {
            line.duplicate_group_id
            for line in lines
            if line.duplicate_group_id is not None
            and line.duplicate_status in {"SUSPECTED", "CONFIRMED"}
        },
        key=str,
    )
    if blocking_groups:
        session.rollback()
        raise SupplyRequestDuplicatesPresentError(blocking_groups)

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

    aliases = list(
        session.execute(
            select(SupplyProduct, SupplyProductAlias)
            .join(
                SupplyProductAlias,
                SupplyProductAlias.product_id == SupplyProduct.id,
            )
            .where(
                SupplyProduct.tenant_id == settings.default_tenant_id,
                SupplyProduct.is_active.is_(True),
                SupplyProductAlias.tenant_id == settings.default_tenant_id,
                SupplyProductAlias.normalized_alias == normalized_name,
                SupplyProductAlias.status == "APPROVED",
            )
            .limit(2)
        ).all()
    )
    if len(aliases) == 1:
        product, alias = aliases[0]
        alias.successful_application_count += 1
        alias.last_applied_at = datetime.now(timezone.utc)
        return product, "EXACT_ALIAS"
    return None, None


def _find_context_product(
    session: Session,
    *,
    department_id: UUID,
    normalized_phrase: str,
    request_created_at: datetime,
) -> SupplyProduct | None:
    return session.scalar(
        select(SupplyProduct)
        .join(
            SupplyDepartmentProductMapping,
            SupplyDepartmentProductMapping.product_id == SupplyProduct.id,
        )
        .where(
            SupplyDepartmentProductMapping.tenant_id
            == settings.default_tenant_id,
            SupplyDepartmentProductMapping.department_id == department_id,
            SupplyDepartmentProductMapping.normalized_phrase
            == normalized_phrase,
            SupplyDepartmentProductMapping.created_at < request_created_at,
            SupplyDepartmentProductMapping.updated_at < request_created_at,
            SupplyProduct.tenant_id == settings.default_tenant_id,
            SupplyProduct.is_active.is_(True),
        )
    )


def _recognize_line(
    session: Session,
    line: SupplyRequestLine,
    *,
    department_id: UUID,
    request_created_at: datetime,
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
    line.requested_unit_id = unit.id
    line.quantity = parsed.quantity
    normalized_phrase = normalize_product_text(parsed.name)
    product = _find_context_product(
        session,
        department_id=department_id,
        normalized_phrase=normalized_phrase,
        request_created_at=request_created_at,
    )
    method = "CONTEXT_MAPPING" if product is not None else None
    if product is None:
        product, method = _find_exact_product(session, normalized_phrase)
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
    expected_version: int,
    force: bool = False,
) -> SupplyRecognitionSummary:
    supply_request = _get_supply_request_for_update(
        session,
        request_id,
        expected_version=expected_version,
    )
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
        skipped = line.match_method == "MANUAL"
        if not skipped:
            _recognize_line(
                session,
                line,
                department_id=supply_request.department_id,
                request_created_at=supply_request.created_at,
                now=now,
            )
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
        expected_version=payload.expected_version,
    )
    editable_statuses = {"DRAFT", "SUBMITTED", "IN_REVIEW"}
    late_match_statuses = {"PLANNED", "PARTIALLY_FULFILLED", "FULFILLED"}
    if supply_request.status not in editable_statuses | late_match_statuses:
        raise SupplyRequestStateError
    if line.debt_link and line.debt_link.inclusion_confirmed:
        raise SupplyRequestStateError
    late_match = supply_request.status in late_match_statuses
    if late_match and payload.action != SupplyLineMatchAction.MATCH:
        raise SupplyRequestStateError
    now = datetime.now(timezone.utc)

    if payload.action == SupplyLineMatchAction.MATCH:
        product = get_supply_product(
            session,
            payload.product_id,
            require_active=True,
        )
        unit = _get_supply_unit(session, payload.unit_id)
        validate_quantity_for_unit(payload.quantity, unit)
        debt_link = line.debt_link
        legacy_debts: list[SupplyDepartmentDebt] = []
        legacy_debt_ids: set[UUID] = set()
        for debt in (
            debt_link.debt if debt_link else None,
            debt_link.included_debt if debt_link else None,
        ):
            if (
                debt is not None
                and debt.product_id is None
                and debt.id not in legacy_debt_ids
            ):
                legacy_debts.append(debt)
                legacy_debt_ids.add(debt.id)
        if late_match and (
            (line.product_id is not None and not legacy_debts)
            or line.requested_unit_id != unit.id
            or line.quantity != payload.quantity
        ):
            raise SupplyRequestStateError
        line.product_id = product.id
        line.requested_unit_id = unit.id
        line.quantity = payload.quantity
        line.match_status = "MATCHED"
        line.match_method = "MANUAL"
        line.match_confidence = Decimal("1.0000")
        line.matched_at = now
        line.matched_by_user_id = matched_by_user_id
        line.match_notes = payload.notes
        for debt in legacy_debts:
            conflicting_debt = session.scalar(
                select(SupplyDepartmentDebt).where(
                    SupplyDepartmentDebt.tenant_id
                    == settings.default_tenant_id,
                    SupplyDepartmentDebt.department_id
                    == supply_request.department_id,
                    SupplyDepartmentDebt.product_id == product.id,
                    SupplyDepartmentDebt.unit_id == unit.id,
                    SupplyDepartmentDebt.status == "ACTIVE",
                    SupplyDepartmentDebt.id != debt.id,
                ).with_for_update()
            )
            if conflicting_debt is not None:
                raise SupplyRequestStateError
            debt.product_id = product.id
            debt.unit_id = unit.id
            debt.working_name = product.name
            debt.version += 1
            _add_debt_event(
                session,
                debt,
                event_type="ADJUSTED",
                before=debt.outstanding_quantity,
                after=debt.outstanding_quantity,
                supply_request=supply_request,
                line=line,
                user_id=matched_by_user_id,
                comment="Выполнено ручное сопоставление долга",
            )
        phrase = line.parsed_name or supply_line_product_name(line.raw_text)
        normalized_phrase = normalize_product_text(phrase)
        correction_exists = session.scalar(
            select(SupplyDepartmentProductCorrection.id).where(
                SupplyDepartmentProductCorrection.request_line_id == line.id,
                SupplyDepartmentProductCorrection.product_id == product.id,
            )
        )
        if correction_exists is None:
            session.add(SupplyDepartmentProductCorrection(
                tenant_id=settings.default_tenant_id,
                department_id=supply_request.department_id,
                normalized_phrase=normalized_phrase,
                product_id=product.id,
                request_line_id=line.id,
                corrected_by_user_id=matched_by_user_id,
            ))
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

    if supply_request.status == "SUBMITTED":
        supply_request.status = "IN_REVIEW"
    supply_request.version += 1
    try:
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    refreshed_request = get_supply_request(session, request_id)
    refreshed_line = next(
        request_line
        for request_line in refreshed_request.lines
        if request_line.id == line_id
    )
    if payload.action == SupplyLineMatchAction.MATCH:
        suggestion = get_context_mapping_suggestion(
            session,
            request_id=request_id,
            line_id=line_id,
        )
        if suggestion is not None:
            refreshed_line.context_mapping_suggestion = suggestion
    return refreshed_line


def get_context_mapping_suggestion(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
) -> dict | None:
    row = session.execute(
        select(SupplyRequestLine, SupplyRequest)
        .join(SupplyRequest, SupplyRequest.id == SupplyRequestLine.request_id)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequestLine.id == line_id,
            SupplyRequest.tenant_id == settings.default_tenant_id,
        )
    ).one_or_none()
    if row is None:
        raise SupplyRequestLineNotFoundError
    line, supply_request = row
    if line.product_id is None or line.match_method != "MANUAL":
        return None
    phrase = line.parsed_name or supply_line_product_name(line.raw_text)
    normalized_phrase = normalize_product_text(phrase)
    existing_mapping = session.scalar(
        select(SupplyDepartmentProductMapping).where(
            SupplyDepartmentProductMapping.tenant_id
            == settings.default_tenant_id,
            SupplyDepartmentProductMapping.department_id
            == supply_request.department_id,
            SupplyDepartmentProductMapping.normalized_phrase
            == normalized_phrase,
        )
    )
    if existing_mapping is not None and (
        existing_mapping.product_id == line.product_id
        or existing_mapping.is_permanent
    ):
        return None
    correction_count = int(session.scalar(
        select(func.count(SupplyDepartmentProductCorrection.id)).where(
            SupplyDepartmentProductCorrection.tenant_id
            == settings.default_tenant_id,
            SupplyDepartmentProductCorrection.department_id
            == supply_request.department_id,
            SupplyDepartmentProductCorrection.normalized_phrase
            == normalized_phrase,
            SupplyDepartmentProductCorrection.product_id == line.product_id,
        )
    ) or 0)
    if correction_count < 3:
        return None
    product = get_supply_product(session, line.product_id)
    return {
        "mapping_id": existing_mapping.id if existing_mapping else None,
        "mapping_version": (
            existing_mapping.version if existing_mapping else None
        ),
        "department_id": supply_request.department_id,
        "phrase": phrase,
        "product_id": product.id,
        "product_name": product.name,
        "correction_count": correction_count,
    }


def confirm_context_mapping_for_line(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
    product_id: UUID,
    expected_version: int | None,
    actor_user_id: int,
) -> SupplyDepartmentProductMapping:
    suggestion = get_context_mapping_suggestion(
        session, request_id=request_id, line_id=line_id
    )
    if suggestion is None or suggestion["product_id"] != product_id:
        raise SupplyRequestStateError
    if suggestion["mapping_id"] is not None:
        return replace_context_mapping(
            session,
            mapping_id=suggestion["mapping_id"],
            product_id=product_id,
            expected_version=expected_version,
            actor_user_id=actor_user_id,
        )
    if expected_version is not None:
        raise SupplyContextMappingVersionConflictError(None, expected_version)
    mapping = SupplyDepartmentProductMapping(
        tenant_id=settings.default_tenant_id,
        department_id=suggestion["department_id"],
        phrase=suggestion["phrase"],
        normalized_phrase=normalize_product_text(suggestion["phrase"]),
        product_id=product_id,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    try:
        with session.begin_nested():
            session.add(mapping)
            session.flush()
            session.add(SupplyDepartmentProductMappingAuditEvent(
                tenant_id=settings.default_tenant_id,
                mapping_id=mapping.id,
                action=SupplyContextMappingAuditAction.CREATED,
                department_id=mapping.department_id,
                normalized_phrase=mapping.normalized_phrase,
                previous_product_id=None,
                product_id=mapping.product_id,
                actor_user_id=actor_user_id,
            ))
            session.flush()
        session.commit()
    except IntegrityError as error:
        session.rollback()
        current_version = session.scalar(
            select(SupplyDepartmentProductMapping.version).where(
                SupplyDepartmentProductMapping.tenant_id
                == settings.default_tenant_id,
                SupplyDepartmentProductMapping.department_id
                == suggestion["department_id"],
                SupplyDepartmentProductMapping.normalized_phrase
                == normalize_product_text(suggestion["phrase"]),
            )
        )
        raise SupplyContextMappingVersionConflictError(
            current_version, expected_version
        ) from error
    except Exception:
        session.rollback()
        raise
    return mapping


def replace_context_mapping(
    session: Session,
    *,
    mapping_id: UUID,
    product_id: UUID,
    expected_version: int,
    actor_user_id: int,
) -> SupplyDepartmentProductMapping:
    mapping = session.scalar(
        select(SupplyDepartmentProductMapping).where(
            SupplyDepartmentProductMapping.id == mapping_id,
            SupplyDepartmentProductMapping.tenant_id
            == settings.default_tenant_id,
        ).with_for_update()
    )
    if mapping is None or mapping.is_permanent:
        raise SupplyRequestStateError
    if mapping.version != expected_version:
        raise SupplyContextMappingVersionConflictError(
            mapping.version, expected_version
        )
    department_exists = session.scalar(select(Department.id).where(
        Department.id == mapping.department_id,
        Department.tenant_id == mapping.tenant_id,
    ))
    current_product_exists = session.scalar(select(SupplyProduct.id).where(
        SupplyProduct.id == mapping.product_id,
        SupplyProduct.tenant_id == mapping.tenant_id,
    ))
    if department_exists is None or current_product_exists is None:
        raise SupplyRequestStateError
    product = get_supply_product(session, product_id, require_active=True)
    previous_product_id = mapping.product_id
    mapping.product_id = product.id
    mapping.updated_by_user_id = actor_user_id
    mapping.version += 1
    session.add(SupplyDepartmentProductMappingAuditEvent(
        tenant_id=settings.default_tenant_id,
        mapping_id=mapping.id,
        action=SupplyContextMappingAuditAction.REPLACED,
        department_id=mapping.department_id,
        normalized_phrase=mapping.normalized_phrase,
        previous_product_id=previous_product_id,
        product_id=product.id,
        actor_user_id=actor_user_id,
    ))
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return mapping


def delete_context_mapping(
    session: Session,
    *,
    mapping_id: UUID,
    expected_version: int,
    actor_user_id: int,
) -> None:
    mapping = session.scalar(
        select(SupplyDepartmentProductMapping).where(
            SupplyDepartmentProductMapping.id == mapping_id,
            SupplyDepartmentProductMapping.tenant_id
            == settings.default_tenant_id,
        ).with_for_update()
    )
    if mapping is None or mapping.is_permanent:
        raise SupplyRequestStateError
    if mapping.version != expected_version:
        raise SupplyContextMappingVersionConflictError(
            mapping.version, expected_version
        )
    if session.scalar(select(Department.id).where(
        Department.id == mapping.department_id,
        Department.tenant_id == mapping.tenant_id,
    )) is None or session.scalar(select(SupplyProduct.id).where(
        SupplyProduct.id == mapping.product_id,
        SupplyProduct.tenant_id == mapping.tenant_id,
    )) is None:
        raise SupplyRequestStateError
    session.add(SupplyDepartmentProductMappingAuditEvent(
        tenant_id=settings.default_tenant_id,
        mapping_id=mapping.id,
        action=SupplyContextMappingAuditAction.DELETED,
        department_id=mapping.department_id,
        normalized_phrase=mapping.normalized_phrase,
        previous_product_id=mapping.product_id,
        product_id=None,
        actor_user_id=actor_user_id,
    ))
    session.delete(mapping)
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _populate_context_mapping_suggestions(
    session: Session,
    supply_request: SupplyRequest,
) -> None:
    for line in supply_request.lines:
        if line.match_method != "MANUAL" or line.product_id is None:
            continue
        suggestion = get_context_mapping_suggestion(
            session,
            request_id=supply_request.id,
            line_id=line.id,
        )
        if suggestion is not None:
            line.context_mapping_suggestion = suggestion


PERMANENT_MILK_DEPARTMENT_CODES = ("М15", "М35", "М6А")
PERMANENT_MILK_PHRASE = "молоко"
PERMANENT_MILK_PRODUCT_NAME = "молоко для кофе"


def bootstrap_permanent_milk_context_mappings(
    session: Session,
    *,
    tenant_id: str,
    actor_user_id: int,
) -> SupplyContextMappingBootstrapRead:
    errors: list[str] = []
    departments = list(session.scalars(
        select(Department)
        .where(
            Department.tenant_id == tenant_id,
            Department.code.in_(PERMANENT_MILK_DEPARTMENT_CODES),
        )
        .order_by(Department.code)
        .with_for_update()
    ).all())
    departments_by_code = {item.code: item for item in departments}
    missing_codes = [
        code for code in PERMANENT_MILK_DEPARTMENT_CODES
        if code not in departments_by_code
    ]
    if missing_codes:
        errors.append(
            "Не найдены подразделения: " + ", ".join(missing_codes)
        )
    inactive_codes = [item.code for item in departments if not item.is_active]
    if inactive_codes:
        errors.append(
            "Неактивные подразделения: " + ", ".join(inactive_codes)
        )
    products = list(session.scalars(
        select(SupplyProduct)
        .where(
            SupplyProduct.tenant_id == tenant_id,
            SupplyProduct.normalized_name == PERMANENT_MILK_PRODUCT_NAME,
            SupplyProduct.is_active.is_(True),
        )
        .with_for_update()
    ).all())
    if len(products) != 1:
        errors.append(
            "Нужен ровно один активный товар «Молоко для кофе»; "
            f"найдено: {len(products)}"
        )
    product = products[0] if len(products) == 1 else None
    department_ids = [item.id for item in departments]
    existing = list(session.scalars(
        select(SupplyDepartmentProductMapping)
        .where(
            SupplyDepartmentProductMapping.tenant_id == tenant_id,
            SupplyDepartmentProductMapping.department_id.in_(department_ids),
            SupplyDepartmentProductMapping.normalized_phrase
            == PERMANENT_MILK_PHRASE,
        )
        .with_for_update()
    ).all()) if department_ids else []
    if product is not None:
        conflicts = [
            item for item in existing
            if item.product_id != product.id or not item.is_permanent
        ]
        if conflicts:
            conflict_codes = sorted(
                next(
                    department.code
                    for department in departments
                    if department.id == item.department_id
                )
                for item in conflicts
            )
            errors.append(
                "Конфликтующие contextual mapping: "
                + ", ".join(conflict_codes)
            )
    if errors:
        session.rollback()
        return SupplyContextMappingBootstrapRead(
            tenant_id=tenant_id,
            status="BLOCKED",
            created=0,
            already_configured=0,
            errors=errors,
        )
    existing_department_ids = {item.department_id for item in existing}
    missing_departments = [
        item for item in departments if item.id not in existing_department_ids
    ]
    try:
        for department in missing_departments:
            mapping = SupplyDepartmentProductMapping(
                tenant_id=tenant_id,
                department_id=department.id,
                phrase=PERMANENT_MILK_PHRASE,
                normalized_phrase=PERMANENT_MILK_PHRASE,
                product_id=product.id,
                is_permanent=True,
                created_by_user_id=actor_user_id,
                updated_by_user_id=actor_user_id,
            )
            session.add(mapping)
            session.flush()
            session.add(SupplyDepartmentProductMappingAuditEvent(
                tenant_id=tenant_id,
                mapping_id=mapping.id,
                action=SupplyContextMappingAuditAction.CREATED,
                department_id=department.id,
                normalized_phrase=PERMANENT_MILK_PHRASE,
                previous_product_id=None,
                product_id=product.id,
                actor_user_id=actor_user_id,
            ))
        session.commit()
    except IntegrityError:
        session.rollback()
        return SupplyContextMappingBootstrapRead(
            tenant_id=tenant_id,
            status="BLOCKED",
            created=0,
            already_configured=0,
            errors=[
                "Правила изменились параллельно; обновите данные и повторите"
            ],
        )
    except Exception:
        session.rollback()
        raise
    return SupplyContextMappingBootstrapRead(
        tenant_id=tenant_id,
        status=("CREATED" if missing_departments else "ALREADY_CONFIGURED"),
        created=len(missing_departments),
        already_configured=len(existing),
        errors=[],
    )


def update_supply_line_working_values(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineWorkingValuesUpdate,
    actor_user_id: int,
) -> tuple[int, SupplyRequestLine]:
    supply_request, line = _get_request_line_for_update(
        session,
        request_id=request_id,
        line_id=line_id,
        expected_version=payload.request_version,
    )
    if supply_request.status not in {"SUBMITTED", "IN_REVIEW"}:
        raise SupplyRequestStateError
    if line.debt_link and line.debt_link.inclusion_confirmed:
        raise SupplyRequestStateError

    unit = _get_supply_unit(session, payload.requested_unit_id)
    original_requested_quantity = line.quantity
    requested_quantity = original_requested_quantity
    if requested_quantity is None:
        if payload.requested_quantity is None:
            raise SupplyRequestPlanningIncompleteError
        requested_quantity = payload.requested_quantity
        validate_quantity_for_unit(requested_quantity, unit)
        line.quantity = requested_quantity
    elif (
        payload.requested_quantity is not None
        and payload.requested_quantity != requested_quantity
    ):
        if payload.requested_quantity < requested_quantity:
            raise SupplyRequestedQuantityImmutableError
        requested_quantity = payload.requested_quantity
        line.quantity = requested_quantity
    validate_quantity_for_unit(requested_quantity, unit)
    if (
        not unit.allows_fraction
        and payload.send_quantity
        != payload.send_quantity.to_integral_value()
    ):
        raise SupplySendQuantityInvalidError
    changed_at = datetime.now(timezone.utc)
    old_values = {
        "working_name": line.working_name,
        "requested_quantity": (
            str(original_requested_quantity)
            if original_requested_quantity is not None else None
        ),
        "send_quantity": (
            str(line.send_quantity)
            if line.send_quantity is not None else None
        ),
        "unit_id": (
            str(line.requested_unit_id)
            if line.requested_unit_id is not None
            else None
        ),
    }

    line.working_name_override = payload.working_name
    line.send_quantity = payload.send_quantity
    line.requested_unit_id = unit.id
    if line.product_id is None:
        line.match_status = "NEEDS_REVIEW"
        line.match_method = None
        line.match_confidence = None
        line.matched_at = None
        line.matched_by_user_id = None
        line.match_notes = None
    supply_request.version += 1

    try:
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    logger.info(
        "Supply line working values changed actor_user_id=%s "
        "changed_at=%s request_id=%s line_id=%s old=%s new=%s",
        actor_user_id,
        changed_at.isoformat(),
        request_id,
        line_id,
        old_values,
        {
            "working_name": payload.working_name,
            "requested_quantity": str(requested_quantity),
            "send_quantity": str(payload.send_quantity),
            "unit_id": str(unit.id),
        },
    )

    refreshed_request = get_supply_request(session, request_id)
    refreshed_line = next(
        request_line
        for request_line in refreshed_request.lines
        if request_line.id == line_id
    )
    return refreshed_request.version, refreshed_line


def replace_supply_line_allocations(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineAllocationsUpdate,
    user_id: int,
) -> SupplyRequest:
    supply_request, line = _get_request_line_for_update(
        session,
        request_id=request_id,
        line_id=line_id,
        expected_version=payload.expected_version,
    )
    if supply_request.status == "PLANNED":
        raise SupplyRequestAlreadyPlannedError
    if supply_request.status not in {"SUBMITTED", "IN_REVIEW"}:
        raise SupplyRequestStateError
    operational_unmatched = (
        line.match_status == "NEEDS_REVIEW"
        and line.product_id is None
        and line.quantity is not None
        and line.requested_unit_id is not None
    )
    if (
        line.match_status != "MATCHED" and not operational_unmatched
    ) or line.quantity is None:
        raise SupplyLineNotMatchedError
    if line.duplicate_status in {"SUSPECTED", "CONFIRMED"}:
        raise SupplyRequestDuplicatesPresentError(
            [line.duplicate_group_id] if line.duplicate_group_id else []
        )
    total = sum(
        (item.planned_quantity for item in payload.allocations), Decimal("0")
    )
    if total > line.quantity:
        raise SupplyAllocationExceedsRequestedError
    for item in payload.allocations:
        if item.unit_id != line.requested_unit_id:
            raise SupplyAllocationUnitMismatchError
        _get_supply_unit(session, item.unit_id)
    try:
        session.query(SupplyLineAllocation).filter(
            SupplyLineAllocation.request_line_id == line.id,
            SupplyLineAllocation.tenant_id == settings.default_tenant_id,
        ).delete(synchronize_session=False)
        for item in payload.allocations:
            session.add(SupplyLineAllocation(
                tenant_id=settings.default_tenant_id,
                request_id=supply_request.id,
                request_line_id=line.id,
                action=item.action,
                planned_quantity=item.planned_quantity,
                unit_id=item.unit_id,
                comment=item.comment,
                created_by_user_id=user_id,
            ))
        if supply_request.status == "SUBMITTED":
            supply_request.status = "IN_REVIEW"
        supply_request.version += 1
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def plan_supply_request(
    session: Session,
    request_id: UUID,
    *,
    expected_version: int,
    user_id: int,
    simple_mode: bool = False,
) -> SupplyRequest:
    supply_request = _get_supply_request_for_update(
        session, request_id, expected_version=expected_version
    )
    if supply_request.status == "PLANNED":
        raise SupplyRequestAlreadyPlannedError
    editable_statuses = (
        {"SUBMITTED", "IN_REVIEW"} if simple_mode else {"IN_REVIEW"}
    )
    if supply_request.status not in editable_statuses:
        raise SupplyRequestStateError
    refreshed = get_supply_request(session, request_id)
    if any(
        line.match_status not in {"MATCHED", "NEEDS_REVIEW"}
        or line.quantity is None
        or line.requested_unit_id is None
        for line in refreshed.lines
    ):
        raise SupplyRequestPlanningIncompleteError
    blocking = [
        line.duplicate_group_id for line in refreshed.lines
        if line.duplicate_status in {"SUSPECTED", "CONFIRMED"}
        and line.duplicate_group_id is not None
    ]
    if blocking:
        raise SupplyRequestDuplicatesPresentError(blocking)
    if not refreshed.lines:
        raise SupplyRequestPlanningIncompleteError
    try:
        if simple_mode:
            session.query(SupplyLineAllocation).filter(
                SupplyLineAllocation.request_id == supply_request.id,
                SupplyLineAllocation.tenant_id == settings.default_tenant_id,
            ).delete(synchronize_session=False)
            for line in refreshed.lines:
                sent_quantity = (
                    line.send_quantity
                    if line.send_quantity is not None
                    else line.quantity
                )
                if (
                    sent_quantity is None
                    or (
                        not line.requested_unit.allows_fraction
                        and sent_quantity
                        != sent_quantity.to_integral_value()
                    )
                ):
                    raise SupplySendQuantityInvalidError
                line.send_quantity = sent_quantity
                session.add(SupplyLineAllocation(
                    tenant_id=settings.default_tenant_id,
                    request_id=supply_request.id,
                    request_line_id=line.id,
                    action="PURCHASE",
                    planned_quantity=max(line.quantity, sent_quantity),
                    unit_id=line.requested_unit_id,
                    comment=SIMPLE_MODE_ALLOCATION_COMMENT,
                    created_by_user_id=user_id,
                ))
        elif any(
            line.planning_status != "COMPLETE" for line in refreshed.lines
        ):
            raise SupplyRequestPlanningIncompleteError
        for line in refreshed.lines:
            _ensure_debt_inclusion(
                session,
                supply_request,
                line,
                user_id=user_id,
                require_confirmation=True,
            )
        supply_request.status = "PLANNED"
        supply_request.planned_at = datetime.now(timezone.utc)
        supply_request.planned_by_user_id = user_id
        supply_request.version += 1
        session.commit()
        if simple_mode:
            session.expire_all()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def _add_debt_event(
    session: Session,
    debt: SupplyDepartmentDebt,
    *,
    event_type: str,
    before: Decimal,
    after: Decimal,
    supply_request: SupplyRequest | None,
    line: SupplyRequestLine | None,
    user_id: int | None,
    comment: str | None = None,
) -> None:
    session.add(SupplyDepartmentDebtEvent(
        tenant_id=settings.default_tenant_id,
        debt=debt,
        event_type=event_type,
        quantity_delta=after - before,
        quantity_before=before,
        quantity_after=after,
        request_id=supply_request.id if supply_request else None,
        request_line_id=line.id if line else None,
        cycle_id=supply_request.cycle_id if supply_request else None,
        actor_user_id=user_id,
        comment=comment,
    ))


def _active_debt_for_line(
    session: Session,
    supply_request: SupplyRequest,
    line: SupplyRequestLine,
) -> SupplyDepartmentDebt | None:
    if line.product_id is None or line.requested_unit_id is None:
        return None
    return session.scalar(
        select(SupplyDepartmentDebt)
        .where(
            SupplyDepartmentDebt.tenant_id == settings.default_tenant_id,
            SupplyDepartmentDebt.department_id == supply_request.department_id,
            SupplyDepartmentDebt.product_id == line.product_id,
            SupplyDepartmentDebt.unit_id == line.requested_unit_id,
            SupplyDepartmentDebt.status == "ACTIVE",
        )
        .with_for_update()
    )


def _line_debt_link_for_update(
    session: Session,
    line_id: UUID,
) -> SupplyRequestLineDebtLink | None:
    return session.scalar(
        select(SupplyRequestLineDebtLink)
        .where(
            SupplyRequestLineDebtLink.request_line_id == line_id,
            SupplyRequestLineDebtLink.tenant_id == settings.default_tenant_id,
        )
        .with_for_update()
    )


def _ensure_debt_inclusion(
    session: Session,
    supply_request: SupplyRequest,
    line: SupplyRequestLine,
    *,
    user_id: int,
    require_confirmation: bool,
) -> SupplyRequestLineDebtLink:
    link = _line_debt_link_for_update(session, line.id)
    if link is None:
        link = SupplyRequestLineDebtLink(
            request_line_id=line.id,
            tenant_id=settings.default_tenant_id,
        )
        session.add(link)
        session.flush()
    if link.inclusion_confirmed or link.included_debt_id is not None:
        return link

    debt = _active_debt_for_line(session, supply_request, line)
    requested = line.quantity or Decimal("0")
    if debt is None or debt.first_request_line_id == line.id:
        link.included_quantity = requested
        return link
    if requested < debt.outstanding_quantity and require_confirmation:
        raise SupplyDebtInclusionConfirmationRequiredError
    link.included_debt_id = debt.id
    link.included_quantity = requested
    link.inclusion_confirmed = False
    _add_debt_event(
        session, debt,
        event_type="INCLUDED_IN_REQUEST",
        before=debt.outstanding_quantity,
        after=debt.outstanding_quantity,
        supply_request=supply_request,
        line=line,
        user_id=user_id,
    )
    return link


def confirm_supply_debt_inclusion(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
    payload: SupplyDebtInclusionConfirm,
    user_id: int,
) -> SupplyRequest:
    supply_request, line = _get_request_line_for_update(
        session,
        request_id=request_id,
        line_id=line_id,
        expected_version=payload.expected_version,
    )
    if supply_request.status not in {"SUBMITTED", "IN_REVIEW", "PLANNED"}:
        raise SupplyRequestNotFulfillableError
    link = _line_debt_link_for_update(session, line.id)
    debt = (
        session.get(SupplyDepartmentDebt, link.included_debt_id)
        if link and link.included_debt_id else
        _active_debt_for_line(session, supply_request, line)
    )
    if debt is None or debt.status != "ACTIVE":
        raise SupplyDebtInclusionInvalidError
    if debt.unit_id != line.requested_unit_id:
        raise SupplyDebtInclusionInvalidError
    requested = line.quantity or Decimal("0")
    if (
        requested >= debt.outstanding_quantity
        or payload.included_quantity != requested
    ):
        raise SupplyDebtInclusionInvalidError
    if (
        link is not None
        and link.included_debt_id == debt.id
        and link.included_quantity == payload.included_quantity
        and link.inclusion_confirmed
    ):
        return get_supply_request(session, request_id)
    if link is None:
        link = SupplyRequestLineDebtLink(
            request_line_id=line.id,
            tenant_id=settings.default_tenant_id,
        )
        session.add(link)
    link.included_debt_id = debt.id
    link.included_quantity = payload.included_quantity
    link.inclusion_confirmed = True
    before = debt.outstanding_quantity
    if before != payload.included_quantity:
        debt.outstanding_quantity = payload.included_quantity
        debt.latest_request_id = supply_request.id
        debt.latest_request_line_id = line.id
        debt.version += 1
        _add_debt_event(
            session,
            debt,
            event_type="ADJUSTED",
            before=before,
            after=payload.included_quantity,
            supply_request=supply_request,
            line=line,
            user_id=user_id,
            comment="Подтверждено меньшее актуальное обязательство",
        )
    _add_debt_event(
        session, debt,
        event_type="INCLUDED_IN_REQUEST",
        before=debt.outstanding_quantity,
        after=debt.outstanding_quantity,
        supply_request=supply_request,
        line=line,
        user_id=user_id,
        comment="Подтверждено частичное включение долга",
    )
    supply_request.version += 1
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def _apply_debt_for_line(
    session: Session,
    supply_request: SupplyRequest,
    line: SupplyRequestLine,
    link: SupplyRequestLineDebtLink,
    *,
    user_id: int,
    comment: str | None,
) -> None:
    target = link.included_quantity
    fulfilled = line.fulfilled_total
    remaining = max(target - fulfilled, Decimal("0"))
    debt = (
        session.get(SupplyDepartmentDebt, link.included_debt_id)
        if link.included_debt_id else None
    )
    if debt is None and link.debt_id is not None:
        debt = session.get(SupplyDepartmentDebt, link.debt_id)
    if debt is not None and debt.unit_id != line.requested_unit_id:
        raise SupplyDebtInclusionInvalidError
    if remaining > 0:
        if line.product_id is None or line.product is None:
            raise SupplyDebtProductRequiredError
        if debt is None:
            debt = _active_debt_for_line(session, supply_request, line)
        now = datetime.now(timezone.utc)
        if debt is None:
            debt = SupplyDepartmentDebt(
                tenant_id=settings.default_tenant_id,
                department_id=supply_request.department_id,
                product_id=line.product_id,
                working_name=line.product.name,
                unit_id=line.requested_unit_id,
                outstanding_quantity=remaining,
                original_quantity=remaining,
                first_request_id=supply_request.id,
                latest_request_id=supply_request.id,
                first_request_line_id=line.id,
                latest_request_line_id=line.id,
                opened_at=now,
                cycle_count=1,
                last_cycle_id=supply_request.cycle_id,
            )
            session.add(debt)
            session.flush()
            _add_debt_event(
                session, debt,
                event_type="CREATED",
                before=Decimal("0"),
                after=remaining,
                supply_request=supply_request,
                line=line,
                user_id=user_id,
                comment=comment,
            )
        else:
            before = debt.outstanding_quantity
            debt.outstanding_quantity = remaining
            debt.latest_request_id = supply_request.id
            debt.latest_request_line_id = line.id
            debt.cycle_count += 1
            debt.last_cycle_id = supply_request.cycle_id
            debt.version += 1
            _add_debt_event(
                session,
                debt,
                event_type=(
                    "INCREASED" if remaining > before
                    else "PARTIALLY_CLOSED" if remaining < before
                    else "ADJUSTED"
                ),
                before=before,
                after=remaining,
                supply_request=supply_request,
                line=line,
                user_id=user_id,
                comment=comment,
            )
        link.debt_id = debt.id
        link.contributed_quantity = remaining
    elif debt is not None and debt.status == "ACTIVE":
        before = debt.outstanding_quantity
        debt.outstanding_quantity = Decimal("0")
        debt.status = "CLOSED"
        debt.closed_at = datetime.now(timezone.utc)
        debt.closed_by_user_id = user_id
        debt.close_comment = comment
        debt.cycle_count = 0
        debt.latest_request_id = supply_request.id
        debt.latest_request_line_id = line.id
        debt.version += 1
        if before != 0:
            _add_debt_event(
                session,
                debt,
                event_type="PARTIALLY_CLOSED",
                before=before,
                after=Decimal("0"),
                supply_request=supply_request,
                line=line,
                user_id=user_id,
                comment=comment,
            )
        _add_debt_event(
            session,
            debt,
            event_type="CLOSED",
            before=Decimal("0"),
            after=Decimal("0"),
            supply_request=supply_request,
            line=line,
            user_id=user_id,
            comment=comment,
        )
    link.applied_included_quantity = min(fulfilled, target)


def _finish_request_status(
    session: Session,
    supply_request: SupplyRequest,
    *,
    user_id: int,
    explicit_action: bool,
) -> None:
    session.flush()
    refreshed = get_supply_request(session, supply_request.id)
    any_fact = any(line.fulfilled_total > 0 for line in refreshed.lines)
    all_resolved = bool(refreshed.lines) and all(
        line.unresolved_quantity == 0 for line in refreshed.lines
    )
    all_included_applied = all(
        line.debt_link is None
        or line.debt_link.applied_included_quantity
        == line.debt_link.included_quantity
        for line in refreshed.lines
    )
    if all_resolved and all_included_applied and (any_fact or explicit_action):
        supply_request.status = "FULFILLED"
        supply_request.fulfilled_at = datetime.now(timezone.utc)
        supply_request.fulfilled_by_user_id = user_id
    else:
        supply_request.status = "PARTIALLY_FULFILLED"


def update_supply_line_fulfillment(
    session: Session,
    *,
    request_id: UUID,
    line_id: UUID,
    payload: SupplyLineFulfillmentUpdate,
    user_id: int,
) -> SupplyRequest:
    supply_request, line = _get_request_line_for_update(
        session,
        request_id=request_id,
        line_id=line_id,
        expected_version=payload.expected_version,
    )
    if supply_request.status in {"PARTIALLY_FULFILLED", "FULFILLED"}:
        raise SupplyRequestAlreadyFulfilledError
    if supply_request.status != "PLANNED":
        raise SupplyRequestNotFulfillableError
    allocations = list(session.scalars(
        select(SupplyLineAllocation)
        .where(
            SupplyLineAllocation.request_line_id == line.id,
            SupplyLineAllocation.request_id == supply_request.id,
            SupplyLineAllocation.tenant_id == settings.default_tenant_id,
        )
        .with_for_update()
    ).all())
    by_id = {allocation.id: allocation for allocation in allocations}
    changed = False
    now = datetime.now(timezone.utc)
    for item in payload.items:
        allocation = by_id.get(item.allocation_id)
        if allocation is None or allocation.action == "CANCEL":
            raise SupplyFulfillmentInvalidActionError
        if (
            item.fulfilled_quantity < allocation.fulfilled_quantity
            and not item.comment
        ):
            raise SupplyFulfillmentDecreaseCommentRequiredError
        if (
            item.fulfilled_quantity != allocation.fulfilled_quantity
            or item.comment != allocation.fulfillment_comment
        ):
            allocation.fulfilled_quantity = item.fulfilled_quantity
            allocation.fulfilled_at = now if item.fulfilled_quantity > 0 else None
            allocation.fulfilled_by_user_id = (
                user_id if item.fulfilled_quantity > 0 else None
            )
            allocation.fulfillment_comment = item.comment
            changed = True
    if not changed:
        return get_supply_request(session, request_id)

    try:
        session.flush()
        link = _ensure_debt_inclusion(
            session, supply_request, line,
            user_id=user_id,
            require_confirmation=True,
        )
        comment = next(
            (item.comment for item in payload.items if item.comment), None
        )
        _apply_debt_for_line(
            session, supply_request, line, link,
            user_id=user_id, comment=comment,
        )
        _finish_request_status(
            session, supply_request, user_id=user_id, explicit_action=True
        )
        supply_request.version += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def fulfill_supply_request_as_planned(
    session: Session,
    request_id: UUID,
    *,
    expected_version: int,
    user_id: int,
    items: list[SupplyRequestFulfillmentItem] | None = None,
) -> SupplyRequest:
    supply_request = _get_supply_request_for_update(
        session, request_id, expected_version=expected_version
    )
    if supply_request.status == "FULFILLED":
        raise SupplyRequestAlreadyFulfilledError
    if supply_request.status != "PLANNED":
        raise SupplyRequestNotFulfillableError
    refreshed = get_supply_request(session, request_id)
    fulfilled_by_line = (
        {item.line_id: item.fulfilled_quantity for item in items}
        if items is not None else None
    )
    if fulfilled_by_line is not None and (
        len(fulfilled_by_line) != len(refreshed.lines)
        or set(fulfilled_by_line) != {line.id for line in refreshed.lines}
    ):
        raise SupplyFulfillmentInvalidActionError
    try:
        now = datetime.now(timezone.utc)
        simple_mode_request = False
        for line in refreshed.lines:
            link = _ensure_debt_inclusion(
                session, supply_request, line,
                user_id=user_id,
                require_confirmation=True,
            )
            simple_mode_allocation = next(
                (
                    allocation
                    for allocation in line.allocations
                    if allocation.action == "PURCHASE"
                    and allocation.comment == SIMPLE_MODE_ALLOCATION_COMMENT
                ),
                None,
            )
            simple_mode_request = (
                simple_mode_request or simple_mode_allocation is not None
            )
            physical_allocations = [
                allocation for allocation in line.allocations
                if allocation.action in {"TRANSFER", "PURCHASE"}
            ]
            if fulfilled_by_line is not None:
                fulfilled_quantity = fulfilled_by_line[line.id]
                if line.quantity is None or (
                    fulfilled_quantity > 0 and not physical_allocations
                ):
                    raise SupplyFulfillmentInvalidActionError
                if (
                    line.requested_unit is None
                    or (
                        not line.requested_unit.allows_fraction
                        and fulfilled_quantity
                        != fulfilled_quantity.to_integral_value()
                    )
                ):
                    raise SupplySendQuantityInvalidError
                line.send_quantity = fulfilled_quantity
                remaining = fulfilled_quantity
                for index, allocation in enumerate(physical_allocations):
                    allocation_quantity = (
                        remaining
                        if index == len(physical_allocations) - 1
                        else min(remaining, allocation.planned_quantity)
                    )
                    remaining -= allocation_quantity
                    allocation.fulfilled_quantity = allocation_quantity
                    allocation.fulfilled_at = (
                        now if allocation_quantity > 0 else None
                    )
                    allocation.fulfilled_by_user_id = (
                        user_id if allocation_quantity > 0 else None
                    )
            else:
                for allocation in physical_allocations:
                    fulfilled_quantity = (
                        line.send_quantity
                        if allocation is simple_mode_allocation
                        and line.send_quantity is not None
                        else allocation.planned_quantity
                    )
                    allocation.fulfilled_quantity = fulfilled_quantity
                    allocation.fulfilled_at = (
                        now if fulfilled_quantity > 0 else None
                    )
                    allocation.fulfilled_by_user_id = (
                        user_id if fulfilled_quantity > 0 else None
                    )
            session.flush()
            _apply_debt_for_line(
                session, supply_request, line, link,
                user_id=user_id, comment="Отправлено как запланировано",
            )
        _finish_request_status(
            session, supply_request, user_id=user_id, explicit_action=True
        )
        supply_request.version += 1
        session.commit()
        if simple_mode_request:
            session.expire_all()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def cancel_supply_request(
    session: Session,
    request_id: UUID,
    *,
    expected_version: int,
    reason: str,
    user_id: int,
) -> SupplyRequest:
    supply_request = _get_supply_request_for_update(
        session, request_id, expected_version=expected_version
    )
    if supply_request.status not in {"SUBMITTED", "IN_REVIEW"}:
        raise SupplyRequestStateError
    try:
        supply_request.status = "CANCELLED"
        supply_request.cancelled_at = datetime.now(timezone.utc)
        supply_request.cancelled_by_user_id = user_id
        supply_request.cancellation_reason = reason
        supply_request.version += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_supply_request(session, request_id)


def disable_supply_product_alias(
    session: Session,
    product_id: UUID,
    alias_id: UUID,
) -> SupplyProductAlias:
    get_supply_product(session, product_id)
    alias = session.scalar(select(SupplyProductAlias).where(
        SupplyProductAlias.id == alias_id,
        SupplyProductAlias.product_id == product_id,
        SupplyProductAlias.tenant_id == settings.default_tenant_id,
    ))
    if alias is None:
        raise SupplyProductAliasNotFoundError
    alias.status = "DISABLED"
    session.commit()
    session.refresh(alias)
    return alias


def _debt_options():
    return (
        joinedload(SupplyDepartmentDebt.department),
        joinedload(SupplyDepartmentDebt.product).joinedload(
            SupplyProduct.default_unit
        ),
        joinedload(SupplyDepartmentDebt.product).joinedload(
            SupplyProduct.request_direction
        ),
        joinedload(SupplyDepartmentDebt.product).joinedload(
            SupplyProduct.category
        ),
        joinedload(SupplyDepartmentDebt.product).joinedload(
            SupplyProduct.storage_zone
        ),
        joinedload(SupplyDepartmentDebt.unit),
        selectinload(SupplyDepartmentDebt.events),
    )


def get_supply_debt(
    session: Session,
    debt_id: UUID,
    *,
    for_update: bool = False,
) -> SupplyDepartmentDebt:
    statement = (
        select(SupplyDepartmentDebt)
        .where(
            SupplyDepartmentDebt.id == debt_id,
            SupplyDepartmentDebt.tenant_id == settings.default_tenant_id,
        )
        .options(*_debt_options())
    )
    if for_update:
        statement = statement.with_for_update(of=SupplyDepartmentDebt)
    debt = session.scalar(statement)
    if debt is None:
        raise SupplyDebtNotFoundError
    return debt


def list_supply_debts(
    session: Session,
    *,
    department_id: UUID | None = None,
    product_id: UUID | None = None,
    debt_status: str | None = None,
    severity: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SupplyDepartmentDebt], int]:
    filters = [SupplyDepartmentDebt.tenant_id == settings.default_tenant_id]
    if department_id:
        filters.append(SupplyDepartmentDebt.department_id == department_id)
    if product_id:
        filters.append(SupplyDepartmentDebt.product_id == product_id)
    if debt_status:
        filters.append(SupplyDepartmentDebt.status == debt_status)
    if severity == "NONE":
        filters.append(SupplyDepartmentDebt.cycle_count <= 1)
    elif severity == "YELLOW":
        filters.append(SupplyDepartmentDebt.cycle_count == 2)
    elif severity == "RED":
        filters.append(SupplyDepartmentDebt.cycle_count >= 3)
    if search:
        term = f"%{search.strip()}%"
        filters.append(or_(
            SupplyProduct.name.ilike(term),
            SupplyDepartmentDebt.working_name.ilike(term),
            Department.name.ilike(term),
            Department.code.ilike(term),
        ))
    total = session.scalar(
        select(func.count())
        .select_from(SupplyDepartmentDebt)
        .join(Department)
        .outerjoin(SupplyProduct)
        .where(*filters)
    )
    severity_order = case(
        (SupplyDepartmentDebt.cycle_count >= 3, 0),
        (SupplyDepartmentDebt.cycle_count == 2, 1),
        else_=2,
    )
    items = list(session.scalars(
        select(SupplyDepartmentDebt)
        .join(Department)
        .outerjoin(SupplyProduct)
        .where(*filters)
        .options(*_debt_options())
        .order_by(
            severity_order.asc(),
            SupplyDepartmentDebt.opened_at.asc(),
            SupplyDepartmentDebt.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).unique().all())
    return items, int(total or 0)


def close_supply_debt(
    session: Session,
    debt_id: UUID,
    *,
    expected_version: int,
    quantity: Decimal,
    comment: str,
    user_id: int,
) -> SupplyDepartmentDebt:
    raise SupplyDebtManualCloseDisabledError


def cancel_supply_debt(
    session: Session,
    debt_id: UUID,
    *,
    expected_version: int,
    comment: str,
    user_id: int,
) -> SupplyDepartmentDebt:
    debt = get_supply_debt(session, debt_id, for_update=True)
    if debt.version != expected_version:
        raise SupplyDebtVersionConflictError(debt.version, expected_version)
    if debt.status != "ACTIVE":
        raise SupplyDebtNotActiveError
    before = debt.outstanding_quantity
    debt.outstanding_quantity = Decimal("0")
    debt.status = "CANCELLED"
    debt.cancelled_at = datetime.now(timezone.utc)
    debt.cancelled_by_user_id = user_id
    debt.cancel_comment = comment
    debt.version += 1
    _add_debt_event(
        session, debt,
        event_type="CANCELLED",
        before=before,
        after=Decimal("0"),
        supply_request=None,
        line=None,
        user_id=user_id,
        comment=comment,
    )
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_supply_debt(session, debt_id)


def get_supply_dashboard_summary(session: Session) -> dict[str, int]:
    tenant = settings.default_tenant_id
    request_counts = dict(session.execute(
        select(SupplyRequest.status, func.count())
        .where(SupplyRequest.tenant_id == tenant)
        .group_by(SupplyRequest.status)
    ).all())
    mapping_required = int(session.scalar(
        select(func.count(func.distinct(SupplyRequest.id)))
        .join(SupplyRequestLine)
        .where(
            SupplyRequest.tenant_id == tenant,
            SupplyRequestLine.match_status == "NEEDS_REVIEW",
            SupplyRequest.status.in_({"SUBMITTED", "IN_REVIEW"}),
        )
    ) or 0)
    active_debts = int(session.scalar(
        select(func.count()).select_from(SupplyDepartmentDebt).where(
            SupplyDepartmentDebt.tenant_id == tenant,
            SupplyDepartmentDebt.status == "ACTIVE",
        )
    ) or 0)
    critical_debts = int(session.scalar(
        select(func.count()).select_from(SupplyDepartmentDebt).where(
            SupplyDepartmentDebt.tenant_id == tenant,
            SupplyDepartmentDebt.status == "ACTIVE",
            SupplyDepartmentDebt.cycle_count >= 3,
        )
    ) or 0)
    return {
        "new_requests": int(request_counts.get("SUBMITTED", 0)),
        "mapping_required": mapping_required,
        "requests_in_progress": sum(
            int(request_counts.get(status, 0))
            for status in ("SUBMITTED", "IN_REVIEW", "PLANNED")
        ),
        "active_debts": active_debts,
        "critical_debts": critical_debts,
    }
