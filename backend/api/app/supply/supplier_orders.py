from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.supply import (
    SupplyProductSupplier,
    SupplyPurchaseAllocation,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
    SupplySupplierOrder,
    SupplySupplierOrderLine,
)
from app.schemas.supplier_order import (
    SupplySupplierOrderLineRead,
    SupplySupplierOrderListItem,
    SupplySupplierOrderMinimumStatus,
    SupplySupplierOrderRead,
    SupplySupplierOrderUpdate,
)


class SupplierOrderNotFoundError(LookupError):
    pass


class SupplierOrderStateError(ValueError):
    pass


class SupplierOrderEmptyError(ValueError):
    pass


class SupplierOrderSupplierInactiveError(ValueError):
    pass


class SupplierOrderConflictError(ValueError):
    pass


def _options():
    return (
        joinedload(SupplySupplierOrder.supplier),
        joinedload(SupplySupplierOrder.purchase_request),
        selectinload(SupplySupplierOrder.lines).joinedload(
            SupplySupplierOrderLine.package_unit_snapshot
        ),
    )


def _minimum(order: SupplySupplierOrder):
    minimum = order.supplier.minimum_order_amount
    if minimum is None:
        return SupplySupplierOrderMinimumStatus.NOT_CONFIGURED, Decimal("0")
    shortfall = max(Decimal(minimum) - Decimal(order.total_amount), Decimal("0"))
    return (
        SupplySupplierOrderMinimumStatus.MET
        if shortfall == 0 else SupplySupplierOrderMinimumStatus.BELOW_MINIMUM,
        shortfall,
    )


def _read(order: SupplySupplierOrder) -> SupplySupplierOrderRead:
    minimum_status, shortfall = _minimum(order)
    return SupplySupplierOrderRead(
        id=order.id, number=order.number, supplier_id=order.supplier_id,
        supplier_display_name=order.supplier.display_name,
        purchase_request_id=order.purchase_request_id,
        purchase_request_number=order.purchase_request.number,
        status=order.status, planned_delivery_date=order.planned_delivery_date,
        comment=order.comment, line_count=len(order.lines),
        total_amount=order.total_amount, currency=order.currency,
        minimum_order_amount=order.supplier.minimum_order_amount,
        minimum_order_status=minimum_status, minimum_order_shortfall=shortfall,
        lines=[SupplySupplierOrderLineRead(
            id=line.id, product_name=line.product_name_snapshot,
            packages_count=line.packages_count,
            package_quantity_snapshot=line.package_quantity_snapshot,
            package_unit=line.package_unit_snapshot,
            quantity_base=line.quantity_base,
            price_per_package_snapshot=line.price_per_package_snapshot,
            base_unit_price_snapshot=line.base_unit_price_snapshot,
            planned_amount=line.planned_amount, currency=line.currency,
            created_at=line.created_at,
        ) for line in order.lines],
        created_at=order.created_at, updated_at=order.updated_at,
        confirmed_at=order.confirmed_at, cancelled_at=order.cancelled_at,
    )


def get_supplier_order(session: Session, order_id: UUID, *, tenant_id: str) -> SupplySupplierOrder:
    order = session.scalar(
        select(SupplySupplierOrder).where(
            SupplySupplierOrder.id == order_id,
            SupplySupplierOrder.tenant_id == tenant_id,
        ).options(*_options()).execution_options(populate_existing=True)
    )
    if order is None:
        raise SupplierOrderNotFoundError
    return order


def read_supplier_order(session: Session, order_id: UUID, *, tenant_id: str) -> SupplySupplierOrderRead:
    return _read(get_supplier_order(session, order_id, tenant_id=tenant_id))


def list_supplier_orders(
    session: Session, *, tenant_id: str, status: str | None,
    supplier_id: UUID | None, search: str | None, limit: int, offset: int,
) -> tuple[list[SupplySupplierOrderListItem], int]:
    filters = [SupplySupplierOrder.tenant_id == tenant_id]
    if status:
        filters.append(SupplySupplierOrder.status == status)
    if supplier_id:
        filters.append(SupplySupplierOrder.supplier_id == supplier_id)
    if search:
        filters.append(SupplySupplierOrder.number.ilike(f"%{search.strip()}%"))
    total = int(session.scalar(select(func.count()).select_from(SupplySupplierOrder).where(*filters)) or 0)
    orders = list(session.scalars(
        select(SupplySupplierOrder).where(*filters).options(*_options())
        .order_by(SupplySupplierOrder.updated_at.desc()).limit(limit).offset(offset)
    ).all())
    return [SupplySupplierOrderListItem(
        id=order.id, number=order.number, supplier_id=order.supplier_id,
        supplier_display_name=order.supplier.display_name,
        purchase_request_id=order.purchase_request_id,
        purchase_request_number=order.purchase_request.number,
        status=order.status, planned_delivery_date=order.planned_delivery_date,
        line_count=len(order.lines), total_amount=order.total_amount,
        currency=order.currency, updated_at=order.updated_at,
    ) for order in orders], total


def _next_numbers(session: Session, tenant_id: str, count: int) -> list[str]:
    prefix = f"PO-{date.today():%Y%m%d}-"
    numbers = session.scalars(select(SupplySupplierOrder.number).where(
        SupplySupplierOrder.tenant_id == tenant_id,
        SupplySupplierOrder.number.like(f"{prefix}%"),
    )).all()
    suffixes = [int(number[len(prefix):]) for number in numbers if number[len(prefix):].isdigit()]
    start = max(suffixes, default=0) + 1
    return [f"{prefix}{value:03d}" for value in range(start, start + count)]


def create_supplier_orders(
    session: Session, request_id: UUID, *, tenant_id: str, user_id: int,
) -> list[SupplySupplierOrderRead]:
    request = session.scalar(select(SupplyPurchaseRequest).where(
        SupplyPurchaseRequest.id == request_id,
        SupplyPurchaseRequest.tenant_id == tenant_id,
    ).with_for_update())
    if request is None:
        raise SupplierOrderNotFoundError
    if request.status != "READY":
        raise SupplierOrderStateError

    allocations = list(session.scalars(
        select(SupplyPurchaseAllocation)
        .join(SupplyPurchaseRequestLine)
        .where(
            SupplyPurchaseRequestLine.purchase_request_id == request.id,
            SupplyPurchaseRequestLine.tenant_id == tenant_id,
            SupplyPurchaseAllocation.status == "CONFIRMED",
            ~SupplyPurchaseAllocation.id.in_(
                select(SupplySupplierOrderLine.source_allocation_id).where(
                    SupplySupplierOrderLine.tenant_id == tenant_id,
                    SupplySupplierOrderLine.is_active_owner.is_(True),
                )
            ),
        )
        .options(
            joinedload(SupplyPurchaseAllocation.purchase_request_line).joinedload(SupplyPurchaseRequestLine.product),
            joinedload(SupplyPurchaseAllocation.product_supplier).joinedload(SupplyProductSupplier.supplier),
        ).with_for_update(of=SupplyPurchaseAllocation)
    ).all())
    grouped: dict[UUID, list[SupplyPurchaseAllocation]] = defaultdict(list)
    for allocation in allocations:
        grouped[allocation.product_supplier.supplier_id].append(allocation)

    numbers = _next_numbers(session, tenant_id, len(grouped))
    created: list[UUID] = []
    try:
        for number, (supplier_id, group) in zip(numbers, sorted(grouped.items(), key=lambda item: str(item[0]))):
            total = sum((Decimal(item.planned_amount) for item in group), Decimal("0"))
            order = SupplySupplierOrder(
                tenant_id=tenant_id, number=number, supplier_id=supplier_id,
                purchase_request_id=request.id, status="DRAFT", total_amount=total,
                currency="RUB", created_by_user_id=user_id,
            )
            session.add(order); session.flush(); created.append(order.id)
            for allocation in group:
                session.add(SupplySupplierOrderLine(
                    tenant_id=tenant_id, supplier_order_id=order.id,
                    source_allocation_id=allocation.id,
                    product_id=allocation.purchase_request_line.product_id,
                    product_name_snapshot=allocation.purchase_request_line.product.name,
                    packages_count=allocation.packages_count,
                    package_quantity_snapshot=allocation.package_quantity_snapshot,
                    package_unit_id_snapshot=allocation.package_unit_id_snapshot,
                    quantity_base=allocation.quantity_base,
                    price_per_package_snapshot=allocation.price_per_package_snapshot,
                    base_unit_price_snapshot=allocation.base_unit_price_snapshot,
                    planned_amount=allocation.planned_amount, currency=allocation.currency,
                    is_active_owner=True,
                ))
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierOrderConflictError from error
    except Exception:
        session.rollback()
        raise

    if not created:
        created = list(session.scalars(select(SupplySupplierOrder.id).where(
            SupplySupplierOrder.tenant_id == tenant_id,
            SupplySupplierOrder.purchase_request_id == request.id,
            SupplySupplierOrder.status != "CANCELLED",
        ).order_by(SupplySupplierOrder.created_at)).all())
    return [read_supplier_order(session, order_id, tenant_id=tenant_id) for order_id in created]


def update_supplier_order(
    session: Session, order_id: UUID, payload: SupplySupplierOrderUpdate, *, tenant_id: str,
) -> SupplySupplierOrderRead:
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update())
    if order is None:
        raise SupplierOrderNotFoundError
    if order.status != "DRAFT":
        raise SupplierOrderStateError
    for field in payload.model_fields_set:
        setattr(order, field, getattr(payload, field))
    session.commit()
    return read_supplier_order(session, order.id, tenant_id=tenant_id)


def mark_supplier_order_ready(session: Session, order_id: UUID, *, tenant_id: str) -> SupplySupplierOrderRead:
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).options(
        selectinload(SupplySupplierOrder.lines)
        .joinedload(SupplySupplierOrderLine.source_allocation)
        .joinedload(SupplyPurchaseAllocation.purchase_request_line),
        selectinload(SupplySupplierOrder.lines)
        .joinedload(SupplySupplierOrderLine.source_allocation)
        .joinedload(SupplyPurchaseAllocation.product_supplier),
        joinedload(SupplySupplierOrder.supplier),
    ).with_for_update())
    if order is None:
        raise SupplierOrderNotFoundError
    if order.status != "DRAFT":
        raise SupplierOrderStateError
    if not order.lines or order.total_amount <= 0:
        raise SupplierOrderEmptyError
    if not order.supplier.is_active:
        raise SupplierOrderSupplierInactiveError
    if any(
        not line.is_active_owner
        or line.source_allocation.status != "CONFIRMED"
        or line.source_allocation.purchase_request_line.purchase_request_id != order.purchase_request_id
        or line.source_allocation.product_supplier.supplier_id != order.supplier_id
        or line.product_id != line.source_allocation.purchase_request_line.product_id
        or line.packages_count != line.source_allocation.packages_count
        or line.package_quantity_snapshot != line.source_allocation.package_quantity_snapshot
        or line.package_unit_id_snapshot != line.source_allocation.package_unit_id_snapshot
        or line.quantity_base != line.source_allocation.quantity_base
        or line.price_per_package_snapshot != line.source_allocation.price_per_package_snapshot
        or line.base_unit_price_snapshot != line.source_allocation.base_unit_price_snapshot
        or line.planned_amount != line.source_allocation.planned_amount
        or line.currency != line.source_allocation.currency
        for line in order.lines
    ) or order.total_amount != sum((line.planned_amount for line in order.lines), Decimal("0")):
        raise SupplierOrderConflictError
    order.status = "READY"; order.confirmed_at = datetime.now(timezone.utc)
    session.commit()
    return read_supplier_order(session, order.id, tenant_id=tenant_id)


def cancel_supplier_order(session: Session, order_id: UUID, *, tenant_id: str) -> SupplySupplierOrderRead:
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).options(selectinload(SupplySupplierOrder.lines)).with_for_update())
    if order is None:
        raise SupplierOrderNotFoundError
    if order.status != "DRAFT":
        raise SupplierOrderStateError
    order.status = "CANCELLED"; order.cancelled_at = datetime.now(timezone.utc)
    for line in order.lines:
        line.is_active_owner = False
    session.commit()
    return read_supplier_order(session, order.id, tenant_id=tenant_id)
