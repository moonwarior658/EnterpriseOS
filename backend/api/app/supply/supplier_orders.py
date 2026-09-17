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
    SupplySupplierConfirmation,
)
from app.schemas.supplier_order import (
    SupplySupplierOrderMessageLine,
    SupplySupplierOrderMessageOrder,
    SupplySupplierOrderMessagePreview,
    SupplySupplierOrderMessageRecipient,
    SupplySupplierOrderMessageResponsible,
    SupplySupplierOrderLineRead,
    SupplySupplierOrderListItem,
    SupplySupplierOrderMinimumStatus,
    SupplySupplierOrderRead,
    SupplySupplierOrderUpdate,
)
from app.schemas.supply import SUPPLIER_EMAIL_PATTERN


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


class SupplierOrderEmailError(ValueError):
    pass


class SupplierOrderResponsiblePhoneError(ValueError):
    pass


class SupplierOrderMessageStateError(ValueError):
    pass


def _options():
    return (
        joinedload(SupplySupplierOrder.supplier),
        joinedload(SupplySupplierOrder.purchase_request),
        selectinload(SupplySupplierOrder.lines).joinedload(
            SupplySupplierOrderLine.package_unit_snapshot
        ),
        selectinload(SupplySupplierOrder.delivery_attempts),
        selectinload(SupplySupplierOrder.confirmations).selectinload(
            SupplySupplierConfirmation.lines
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
    from app.supply.supplier_order_delivery import delivery_attempt_read
    from app.supply.supplier_confirmations import confirmation_summary

    minimum_status, shortfall = _minimum(order)
    history = [delivery_attempt_read(item) for item in order.delivery_attempts]
    recorded = [item for item in order.confirmations if item.status == "RECORDED"]
    draft = next((item for item in order.confirmations if item.status == "DRAFT"), None)
    latest = max(recorded, key=lambda item: item.revision_number) if recorded else None
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
        sent_at=order.sent_at,
        recipient_email_snapshot=order.recipient_email_snapshot,
        recipient_name_snapshot=order.recipient_name_snapshot,
        responsible_name_snapshot=order.responsible_name_snapshot,
        responsible_phone_snapshot=order.responsible_phone_snapshot,
        latest_delivery_attempt=history[-1] if history else None,
        delivery_history=history,
        supplier_confirmation_state=latest.response_type if latest else "NONE",
        latest_confirmation=confirmation_summary(latest) if latest else None,
        draft_confirmation=confirmation_summary(draft) if draft else None,
        confirmation_history_count=len(order.confirmations),
    )


def _format_quantity(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


def _format_money(value: Decimal) -> str:
    return f"{Decimal(value):,.2f}".replace(",", " ").replace(".", ",")


def _message_subject(order: SupplySupplierOrder) -> str:
    if order.planned_delivery_date is None:
        return f"Заказ {order.number}"
    return f"Заказ {order.number} на {order.planned_delivery_date:%d.%m.%Y}"


def _message_body(order: SupplySupplierOrder) -> str:
    lines = [
        "Здравствуйте.",
        "",
        f"Просим подтвердить заказ №{order.number}:",
        "",
    ]
    for position, line in enumerate(order.lines, start=1):
        unit = line.package_unit_snapshot.short_name_ru
        lines.append(
            f"{position}. {line.product_name_snapshot} — упаковка "
            f"{_format_quantity(line.package_quantity_snapshot)} {unit}; "
            f"{line.packages_count} уп.; всего {_format_quantity(line.quantity_base)} {unit}; "
            f"{_format_money(line.price_per_package_snapshot)} ₽/уп.; "
            f"сумма {_format_money(line.planned_amount)} ₽."
        )
    lines.extend(["", f"Итого: {_format_money(order.total_amount)} ₽."])
    if order.planned_delivery_date is not None:
        lines.append(f"Плановая дата поставки: {order.planned_delivery_date:%d.%m.%Y}.")
    lines.extend([
        "",
        "Ответственный:",
        order.responsible_name_snapshot or "",
        f"Телефон: {order.responsible_phone_snapshot or ''}",
        "",
        "Просим подтвердить наличие, количество, цену и дату поставки.",
        "",
        "Заказ сформирован автоматически в EnterpriseOS.",
    ])
    return "\n".join(lines)


def prepare_supplier_order_message(
    session: Session, order_id: UUID, *, tenant_id: str,
    responsible_name: str, responsible_phone: str | None,
) -> SupplySupplierOrderMessagePreview:
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id,
        SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierOrder))
    if order is None:
        raise SupplierOrderNotFoundError
    if order.status != "READY":
        raise SupplierOrderMessageStateError
    if not order.lines or order.total_amount <= 0:
        raise SupplierOrderEmptyError

    if order.recipient_email_snapshot is None:
        email = (order.supplier.order_email or "").strip()
        if not email or not SUPPLIER_EMAIL_PATTERN.fullmatch(email):
            raise SupplierOrderEmailError
        if responsible_phone is None:
            raise SupplierOrderResponsiblePhoneError
        order.recipient_email_snapshot = email
        order.recipient_name_snapshot = order.supplier.display_name
        order.responsible_name_snapshot = responsible_name.strip()
        order.responsible_phone_snapshot = responsible_phone
        session.commit()

    message_lines = [SupplySupplierOrderMessageLine(
        product_name=line.product_name_snapshot,
        packages_count=line.packages_count,
        package_quantity=line.package_quantity_snapshot,
        package_unit=line.package_unit_snapshot.short_name_ru,
        total_quantity=line.quantity_base,
        price_per_package=line.price_per_package_snapshot,
        planned_amount=line.planned_amount,
        currency=line.currency,
    ) for line in order.lines]
    warnings = [] if order.planned_delivery_date is not None else ["Дата поставки не указана"]
    return SupplySupplierOrderMessagePreview(
        recipient=SupplySupplierOrderMessageRecipient(
            email=order.recipient_email_snapshot,
            supplier_display_name=order.recipient_name_snapshot,
        ),
        subject=_message_subject(order),
        body_text=_message_body(order),
        order=SupplySupplierOrderMessageOrder(
            id=order.id, number=order.number,
            planned_delivery_date=order.planned_delivery_date,
            total_amount=order.total_amount, currency=order.currency,
        ),
        lines=message_lines,
        responsible=SupplySupplierOrderMessageResponsible(
            name=order.responsible_name_snapshot,
            phone=order.responsible_phone_snapshot,
        ),
        warnings=warnings,
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
    ).with_for_update(of=SupplySupplierOrder))
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
    ).with_for_update(of=SupplySupplierOrder))
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
    ).options(selectinload(SupplySupplierOrder.lines)).with_for_update(of=SupplySupplierOrder))
    if order is None:
        raise SupplierOrderNotFoundError
    if order.status != "DRAFT":
        raise SupplierOrderStateError
    order.status = "CANCELLED"; order.cancelled_at = datetime.now(timezone.utc)
    for line in order.lines:
        line.is_active_owner = False
    session.commit()
    return read_supplier_order(session, order.id, tenant_id=tenant_id)
