from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.supply import (
    SupplyDepartmentDebt,
    SupplyProduct,
    SupplyProcurementNeed,
    SupplyProcurementNeedStatus,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
    SupplyPurchaseRequestLineSource,
    SupplyRequest,
    SupplyRequestLine,
    SupplyUnit,
)
from app.schemas.purchase_request import (
    SupplyPurchaseRequestCreate,
    SupplyPurchaseRequestLineCreate,
    SupplyPurchaseRequestLineUpdate,
    SupplyPurchaseRequestUpdate,
)


class PurchaseRequestNotFoundError(LookupError):
    pass


class PurchaseRequestLineNotFoundError(LookupError):
    pass


class PurchaseRequestStateError(ValueError):
    pass


class PurchaseRequestEmptyError(ValueError):
    pass


class DuplicatePurchaseRequestLineError(ValueError):
    pass


class PurchaseRequestProductNotFoundError(LookupError):
    pass


class PurchaseRequestUnitNotFoundError(LookupError):
    pass


class PurchaseRequestSourceConflictError(ValueError):
    pass


def _options():
    return (
        selectinload(SupplyPurchaseRequest.lines).joinedload(
            SupplyPurchaseRequestLine.product
        ).joinedload(SupplyProduct.default_unit),
        selectinload(SupplyPurchaseRequest.lines).joinedload(
            SupplyPurchaseRequestLine.unit
        ),
        selectinload(SupplyPurchaseRequest.lines).selectinload(
            SupplyPurchaseRequestLine.sources
        ).joinedload(SupplyPurchaseRequestLineSource.unit),
        selectinload(SupplyPurchaseRequest.lines).selectinload(
            SupplyPurchaseRequestLine.sources
        ).joinedload(
            SupplyPurchaseRequestLineSource.procurement_need
        ).joinedload(SupplyProcurementNeed.request_line).joinedload(
            SupplyRequestLine.request
        ).joinedload(SupplyRequest.department),
        selectinload(SupplyPurchaseRequest.lines).selectinload(
            SupplyPurchaseRequestLine.sources
        ).joinedload(
            SupplyPurchaseRequestLineSource.procurement_need
        ).joinedload(SupplyProcurementNeed.department_debt).joinedload(
            SupplyDepartmentDebt.department
        ),
        selectinload(SupplyPurchaseRequest.lines).selectinload(
            SupplyPurchaseRequestLine.sources
        ).joinedload(
            SupplyPurchaseRequestLineSource.procurement_need
        ).joinedload(SupplyProcurementNeed.basis_stock_calculation_line),
    )


def get_purchase_request(
    session: Session, request_id: UUID, *, tenant_id: str
) -> SupplyPurchaseRequest:
    item = session.scalar(
        select(SupplyPurchaseRequest)
        .where(
            SupplyPurchaseRequest.id == request_id,
            SupplyPurchaseRequest.tenant_id == tenant_id,
        )
        .options(*_options())
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise PurchaseRequestNotFoundError
    return item


def list_purchase_requests(
    session: Session, *, tenant_id: str, limit: int, offset: int
) -> tuple[list[SupplyPurchaseRequest], int]:
    filters = (SupplyPurchaseRequest.tenant_id == tenant_id,)
    total = int(session.scalar(
        select(func.count()).select_from(SupplyPurchaseRequest).where(*filters)
    ) or 0)
    items = list(session.scalars(
        select(SupplyPurchaseRequest)
        .where(*filters)
        .options(selectinload(SupplyPurchaseRequest.lines))
        .order_by(
            SupplyPurchaseRequest.need_date.desc(),
            SupplyPurchaseRequest.created_at.desc(),
        )
        .limit(limit).offset(offset)
    ).all())
    return items, total


def _next_number(session: Session, tenant_id: str, need_date) -> str:
    prefix = f"ZR-{need_date:%Y%m%d}-"
    numbers = session.scalars(
        select(SupplyPurchaseRequest.number).where(
            SupplyPurchaseRequest.tenant_id == tenant_id,
            SupplyPurchaseRequest.number.like(f"{prefix}%"),
        )
    ).all()
    suffixes = [
        int(number[len(prefix):]) for number in numbers
        if number[len(prefix):].isdigit()
    ]
    return f"{prefix}{max(suffixes, default=0) + 1:03d}"


def create_purchase_request(
    session: Session, payload: SupplyPurchaseRequestCreate,
    *, tenant_id: str, user_id: int,
) -> SupplyPurchaseRequest:
    item = SupplyPurchaseRequest(
        tenant_id=tenant_id,
        number=_next_number(session, tenant_id, payload.need_date),
        need_date=payload.need_date,
        status="DRAFT",
        comment=payload.comment,
        created_by_user_id=user_id,
    )
    try:
        session.add(item)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_purchase_request(session, item.id, tenant_id=tenant_id)


def _require_draft(item: SupplyPurchaseRequest) -> None:
    if item.status != "DRAFT":
        raise PurchaseRequestStateError


def _lock_draft_request(
    session: Session, item: SupplyPurchaseRequest
) -> SupplyPurchaseRequest:
    locked = session.scalar(
        select(SupplyPurchaseRequest).where(
            SupplyPurchaseRequest.id == item.id,
            SupplyPurchaseRequest.tenant_id == item.tenant_id,
        ).options(*_options()).execution_options(
            populate_existing=True
        ).with_for_update()
    )
    if locked is None:
        raise PurchaseRequestNotFoundError
    _require_draft(locked)
    return locked


def update_purchase_request(
    session: Session, item: SupplyPurchaseRequest,
    payload: SupplyPurchaseRequestUpdate,
) -> SupplyPurchaseRequest:
    item = _lock_draft_request(session, item)
    for field in payload.model_fields_set:
        setattr(item, field, getattr(payload, field))
    session.commit()
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def mark_purchase_request_ready(
    session: Session, item: SupplyPurchaseRequest
) -> SupplyPurchaseRequest:
    item = _lock_draft_request(session, item)
    if not item.lines:
        raise PurchaseRequestEmptyError
    locked = list(session.scalars(
        select(SupplyProcurementNeed)
        .join(
            SupplyPurchaseRequestLineSource,
            SupplyPurchaseRequestLineSource.procurement_need_id
            == SupplyProcurementNeed.id,
        )
        .join(
            SupplyPurchaseRequestLine,
            SupplyPurchaseRequestLine.id
            == SupplyPurchaseRequestLineSource.purchase_request_line_id,
        )
        .where(
            SupplyPurchaseRequestLine.purchase_request_id == item.id,
            SupplyPurchaseRequestLine.tenant_id == item.tenant_id,
            SupplyPurchaseRequestLineSource.source_type == "PROCUREMENT_NEED",
        )
        .with_for_update(of=SupplyProcurementNeed)
    ).all())
    needs_by_id = {need.id: need for need in locked}
    for line in item.lines:
        for source in line.sources:
            if source.source_type != "PROCUREMENT_NEED":
                continue
            need = needs_by_id.get(source.procurement_need_id)
            if (
                need is None
                or need.tenant_id != item.tenant_id
                or need.status != SupplyProcurementNeedStatus.OPEN
                or need.reserved_purchase_request_id != item.id
                or need.need_date is None
                or need.need_date > item.need_date
                or need.product_id != line.product_id
                or need.unit_id != line.unit_id
                or need.unit_id != source.unit_id
                or need.quantity != source.quantity
            ):
                session.rollback()
                raise PurchaseRequestSourceConflictError
    for need in locked:
        need.status = SupplyProcurementNeedStatus.IN_PURCHASE_REQUEST
    item.status = "READY"
    session.commit()
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def cancel_purchase_request(
    session: Session, item: SupplyPurchaseRequest
) -> SupplyPurchaseRequest:
    item = _lock_draft_request(session, item)
    needs = list(session.scalars(
        select(SupplyProcurementNeed).where(
            SupplyProcurementNeed.tenant_id == item.tenant_id,
            SupplyProcurementNeed.reserved_purchase_request_id == item.id,
        ).with_for_update(of=SupplyProcurementNeed)
    ).all())
    for need in needs:
        need.reserved_purchase_request_id = None
    item.status = "CANCELLED"
    session.commit()
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def _get_product(session: Session, product_id: UUID, tenant_id: str) -> SupplyProduct:
    product = session.scalar(select(SupplyProduct).where(
        SupplyProduct.id == product_id,
        SupplyProduct.tenant_id == tenant_id,
        SupplyProduct.is_active.is_(True),
    ))
    if product is None:
        raise PurchaseRequestProductNotFoundError
    return product


def _get_unit(session: Session, unit_id: UUID, tenant_id: str) -> SupplyUnit:
    unit = session.scalar(select(SupplyUnit).where(
        SupplyUnit.id == unit_id,
        SupplyUnit.tenant_id == tenant_id,
        SupplyUnit.is_active.is_(True),
    ))
    if unit is None:
        raise PurchaseRequestUnitNotFoundError
    return unit


def _get_line(
    session: Session, item: SupplyPurchaseRequest, line_id: UUID
) -> SupplyPurchaseRequestLine:
    line = session.scalar(select(SupplyPurchaseRequestLine).where(
        SupplyPurchaseRequestLine.id == line_id,
        SupplyPurchaseRequestLine.purchase_request_id == item.id,
        SupplyPurchaseRequestLine.tenant_id == item.tenant_id,
    ))
    if line is None:
        raise PurchaseRequestLineNotFoundError
    return line


def add_purchase_request_line(
    session: Session, item: SupplyPurchaseRequest,
    payload: SupplyPurchaseRequestLineCreate,
) -> SupplyPurchaseRequest:
    item = _lock_draft_request(session, item)
    product = _get_product(session, payload.product_id, item.tenant_id)
    unit = _get_unit(session, payload.unit_id, item.tenant_id)
    quantity = Decimal(payload.quantity)
    manual_quantity = Decimal(payload.manual_future_quantity or quantity)
    existing_line = session.scalar(select(SupplyPurchaseRequestLine).where(
        SupplyPurchaseRequestLine.tenant_id == item.tenant_id,
        SupplyPurchaseRequestLine.purchase_request_id == item.id,
        SupplyPurchaseRequestLine.product_id == product.id,
        SupplyPurchaseRequestLine.unit_id == unit.id,
    ).options(selectinload(SupplyPurchaseRequestLine.sources)))
    if existing_line is not None:
        if any(
            source.source_type == "MANUAL_FUTURE"
            for source in existing_line.sources
        ):
            raise DuplicatePurchaseRequestLineError
        existing_line.sources.append(SupplyPurchaseRequestLineSource(
            tenant_id=item.tenant_id, source_type="MANUAL_FUTURE",
            procurement_need_id=None, quantity=manual_quantity, unit_id=unit.id,
        ))
        existing_line.manual_future_quantity = manual_quantity
        existing_line.quantity += manual_quantity
        existing_line.comment = payload.comment
        session.commit()
        return get_purchase_request(session, item.id, tenant_id=item.tenant_id)
    line = SupplyPurchaseRequestLine(
        tenant_id=item.tenant_id, purchase_request_id=item.id,
        product_id=product.id, quantity=quantity, unit_id=unit.id,
        manual_future_quantity=manual_quantity, comment=payload.comment,
    )
    line.sources.append(SupplyPurchaseRequestLineSource(
        tenant_id=item.tenant_id, source_type="MANUAL_FUTURE",
        procurement_need_id=None, quantity=manual_quantity, unit_id=unit.id,
    ))
    try:
        session.add(line)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicatePurchaseRequestLineError from error
    except Exception:
        session.rollback()
        raise
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def update_purchase_request_line(
    session: Session, item: SupplyPurchaseRequest, line_id: UUID,
    payload: SupplyPurchaseRequestLineUpdate,
) -> SupplyPurchaseRequest:
    item = _lock_draft_request(session, item)
    line = _get_line(session, item, line_id)
    fields = payload.model_fields_set
    manual_sources = [
        source for source in line.sources if source.source_type == "MANUAL_FUTURE"
    ]
    if not manual_sources:
        raise PurchaseRequestSourceConflictError
    manual_quantity = Decimal(
        payload.manual_future_quantity
        if "manual_future_quantity" in fields
        else payload.quantity if "quantity" in fields
        else manual_sources[0].quantity
    )
    if "quantity" in fields and "manual_future_quantity" in fields and (
        Decimal(payload.quantity) != manual_quantity
    ):
        raise PurchaseRequestSourceConflictError
    if "unit_id" in fields:
        unit_id = _get_unit(session, payload.unit_id, item.tenant_id).id
        if any(source.source_type == "PROCUREMENT_NEED" for source in line.sources):
            if unit_id != line.unit_id:
                raise PurchaseRequestSourceConflictError
        line.unit_id = unit_id
    line.manual_future_quantity = manual_quantity
    if "comment" in fields:
        line.comment = payload.comment
    source = manual_sources[0]
    source.quantity = manual_quantity
    source.unit_id = line.unit_id
    line.quantity = sum((source.quantity for source in line.sources), Decimal("0"))
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicatePurchaseRequestLineError from error
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def delete_purchase_request_line(
    session: Session, item: SupplyPurchaseRequest, line_id: UUID
) -> SupplyPurchaseRequest:
    item = _lock_draft_request(session, item)
    line = _get_line(session, item, line_id)
    auto_sources = [
        source for source in line.sources if source.source_type == "PROCUREMENT_NEED"
    ]
    if auto_sources:
        manual_sources = [
            source for source in line.sources if source.source_type == "MANUAL_FUTURE"
        ]
        if not manual_sources:
            raise PurchaseRequestSourceConflictError
        for source in manual_sources:
            session.delete(source)
        line.manual_future_quantity = Decimal("0")
        line.quantity = sum((source.quantity for source in auto_sources), Decimal("0"))
    else:
        session.delete(line)
    session.commit()
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def collect_purchase_request_needs(
    session: Session, item: SupplyPurchaseRequest
) -> SupplyPurchaseRequest:
    item = _lock_draft_request(session, item)

    eligible = list(session.scalars(
        select(SupplyProcurementNeed).where(
            SupplyProcurementNeed.tenant_id == item.tenant_id,
            SupplyProcurementNeed.status == SupplyProcurementNeedStatus.OPEN,
            SupplyProcurementNeed.need_date.is_not(None),
            SupplyProcurementNeed.need_date <= item.need_date,
            (
                SupplyProcurementNeed.reserved_purchase_request_id.is_(None)
                | (SupplyProcurementNeed.reserved_purchase_request_id == item.id)
            ),
        ).order_by(SupplyProcurementNeed.created_at, SupplyProcurementNeed.id)
        .with_for_update(of=SupplyProcurementNeed)
    ).all())
    eligible_by_id = {need.id: need for need in eligible}

    lines = list(session.scalars(
        select(SupplyPurchaseRequestLine).where(
            SupplyPurchaseRequestLine.tenant_id == item.tenant_id,
            SupplyPurchaseRequestLine.purchase_request_id == item.id,
        ).options(selectinload(SupplyPurchaseRequestLine.sources))
    ).all())
    by_group = {(line.product_id, line.unit_id): line for line in lines}
    existing = {
        source.procurement_need_id: (line, source)
        for line in lines for source in line.sources
        if source.source_type == "PROCUREMENT_NEED"
    }

    for need_id, (line, source) in list(existing.items()):
        need = eligible_by_id.get(need_id)
        if need is None:
            loaded_need = session.get(SupplyProcurementNeed, need_id)
            if loaded_need is not None and loaded_need.reserved_purchase_request_id == item.id:
                loaded_need.reserved_purchase_request_id = None
            session.delete(source)
            line.sources.remove(source)
            continue
        if need.product_id != line.product_id or need.unit_id != line.unit_id:
            session.rollback()
            raise PurchaseRequestSourceConflictError
        source.quantity = need.quantity
        source.unit_id = need.unit_id

    for need in eligible:
        need.reserved_purchase_request_id = item.id
        if need.id in existing:
            continue
        key = (need.product_id, need.unit_id)
        line = by_group.get(key)
        if line is None:
            line = SupplyPurchaseRequestLine(
                tenant_id=item.tenant_id, purchase_request_id=item.id,
                product_id=need.product_id, unit_id=need.unit_id,
                quantity=need.quantity, manual_future_quantity=Decimal("0"),
            )
            session.add(line)
            lines.append(line)
            by_group[key] = line
        line.sources.append(SupplyPurchaseRequestLineSource(
            tenant_id=item.tenant_id, source_type="PROCUREMENT_NEED",
            procurement_need_id=need.id, quantity=need.quantity,
            unit_id=need.unit_id,
        ))

    for line in list(lines):
        active_sources = [source for source in line.sources if source not in session.deleted]
        if not active_sources:
            session.delete(line)
            continue
        line.manual_future_quantity = sum(
            (source.quantity for source in active_sources
             if source.source_type == "MANUAL_FUTURE"), Decimal("0")
        )
        line.quantity = sum((source.quantity for source in active_sources), Decimal("0"))
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise PurchaseRequestSourceConflictError from error
    except Exception:
        session.rollback()
        raise
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)
