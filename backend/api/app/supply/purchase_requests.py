from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.supply import (
    SupplyProduct,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
    SupplyPurchaseRequestLineSource,
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


def update_purchase_request(
    session: Session, item: SupplyPurchaseRequest,
    payload: SupplyPurchaseRequestUpdate,
) -> SupplyPurchaseRequest:
    _require_draft(item)
    for field in payload.model_fields_set:
        setattr(item, field, getattr(payload, field))
    session.commit()
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def mark_purchase_request_ready(
    session: Session, item: SupplyPurchaseRequest
) -> SupplyPurchaseRequest:
    _require_draft(item)
    if not item.lines:
        raise PurchaseRequestEmptyError
    item.status = "READY"
    session.commit()
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def cancel_purchase_request(
    session: Session, item: SupplyPurchaseRequest
) -> SupplyPurchaseRequest:
    if item.status == "CANCELLED":
        raise PurchaseRequestStateError
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
    _require_draft(item)
    product = _get_product(session, payload.product_id, item.tenant_id)
    unit = _get_unit(session, payload.unit_id, item.tenant_id)
    quantity = Decimal(payload.quantity)
    manual_quantity = Decimal(payload.manual_future_quantity or quantity)
    line = SupplyPurchaseRequestLine(
        tenant_id=item.tenant_id, purchase_request_id=item.id,
        product_id=product.id, quantity=quantity, unit_id=unit.id,
        manual_future_quantity=manual_quantity, comment=payload.comment,
    )
    line.sources.append(SupplyPurchaseRequestLineSource(
        tenant_id=item.tenant_id, source_type="MANUAL_FUTURE",
        source_id=None, quantity=manual_quantity, unit_id=unit.id,
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
    _require_draft(item)
    line = _get_line(session, item, line_id)
    fields = payload.model_fields_set
    quantity = Decimal(payload.quantity) if "quantity" in fields else line.quantity
    manual_quantity = (
        Decimal(payload.manual_future_quantity)
        if "manual_future_quantity" in fields
        else quantity
    )
    if manual_quantity != quantity:
        raise ValueError("Manual source quantity must equal line quantity")
    if "unit_id" in fields:
        line.unit_id = _get_unit(session, payload.unit_id, item.tenant_id).id
    line.quantity = quantity
    line.manual_future_quantity = manual_quantity
    if "comment" in fields:
        line.comment = payload.comment
    source = line.sources[0]
    source.quantity = manual_quantity
    source.unit_id = line.unit_id
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicatePurchaseRequestLineError from error
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)


def delete_purchase_request_line(
    session: Session, item: SupplyPurchaseRequest, line_id: UUID
) -> SupplyPurchaseRequest:
    _require_draft(item)
    session.delete(_get_line(session, item, line_id))
    session.commit()
    return get_purchase_request(session, item.id, tenant_id=item.tenant_id)
