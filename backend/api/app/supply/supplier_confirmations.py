from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.supply import (
    SupplySupplierConfirmation,
    SupplySupplierConfirmationLine,
    SupplySupplierOrder,
    SupplySupplierOrderLine,
    SupplyUnit,
)
from app.schemas.supplier_confirmation import (
    SupplySupplierConfirmationLineRead,
    SupplySupplierConfirmationLineUpdate,
    SupplySupplierConfirmationRead,
    SupplySupplierConfirmationSummary,
    SupplySupplierConfirmationUpdate,
)


class SupplierConfirmationNotFoundError(LookupError):
    pass


class SupplierConfirmationStateError(ValueError):
    pass


class SupplierConfirmationConflictError(ValueError):
    pass


class SupplierConfirmationValidationError(ValueError):
    pass


def _options():
    return (
        joinedload(SupplySupplierConfirmation.supplier_order).joinedload(SupplySupplierOrder.supplier),
        selectinload(SupplySupplierConfirmation.lines).joinedload(
            SupplySupplierConfirmationLine.supplier_order_line
        ).joinedload(SupplySupplierOrderLine.package_unit_snapshot),
        selectinload(SupplySupplierConfirmation.lines).joinedload(
            SupplySupplierConfirmationLine.confirmed_package_unit
        ),
    )


def get_confirmation(
    session: Session, confirmation_id: UUID, *, tenant_id: str, lock: bool = False,
) -> SupplySupplierConfirmation:
    query = select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.id == confirmation_id,
        SupplySupplierConfirmation.tenant_id == tenant_id,
    )
    if lock:
        query = query.with_for_update(of=SupplySupplierConfirmation)
    confirmation = session.scalar(query.options(*_options()).execution_options(populate_existing=True))
    if confirmation is None:
        raise SupplierConfirmationNotFoundError
    return confirmation


def _summary(confirmation: SupplySupplierConfirmation) -> SupplySupplierConfirmationSummary:
    return SupplySupplierConfirmationSummary(
        id=confirmation.id, revision_number=confirmation.revision_number,
        status=confirmation.status, response_type=confirmation.response_type,
        confirmed_delivery_date=confirmation.confirmed_delivery_date,
        responded_at=confirmation.responded_at, recorded_at=confirmation.recorded_at,
        confirmed_total_amount=sum(
            (Decimal(line.confirmed_planned_amount) for line in confirmation.lines
             if line.response_status != "REJECTED" and line.confirmed_planned_amount is not None),
            Decimal("0"),
        ),
    )


def confirmation_summary(confirmation: SupplySupplierConfirmation) -> SupplySupplierConfirmationSummary:
    return _summary(confirmation)


def read_confirmation_model(confirmation: SupplySupplierConfirmation) -> SupplySupplierConfirmationRead:
    order = confirmation.supplier_order
    confirmed_total = Decimal("0")
    lines = []
    for line in confirmation.lines:
        ordered = line.supplier_order_line
        if line.response_status != "REJECTED" and line.confirmed_planned_amount is not None:
            confirmed_total += Decimal(line.confirmed_planned_amount)
        lines.append(SupplySupplierConfirmationLineRead(
            id=line.id, supplier_order_line_id=line.supplier_order_line_id,
            response_status=line.response_status, product_name_snapshot=line.product_name_snapshot,
            ordered_packages_count=ordered.packages_count,
            ordered_package_quantity=ordered.package_quantity_snapshot,
            ordered_package_unit_id=ordered.package_unit_id_snapshot,
            ordered_package_unit=ordered.package_unit_snapshot.short_name_ru,
            ordered_quantity_base=ordered.quantity_base,
            ordered_price_per_package=ordered.price_per_package_snapshot,
            ordered_planned_amount=ordered.planned_amount,
            confirmed_packages_count=line.confirmed_packages_count,
            confirmed_package_quantity=line.confirmed_package_quantity,
            confirmed_package_unit_id=line.confirmed_package_unit_id,
            confirmed_package_unit=line.confirmed_package_unit.short_name_ru if line.confirmed_package_unit else None,
            confirmed_quantity_base=line.confirmed_quantity_base,
            confirmed_price_per_package=line.confirmed_price_per_package,
            confirmed_planned_amount=line.confirmed_planned_amount,
            currency=line.currency, supplier_line_comment=line.supplier_line_comment,
            created_at=line.created_at, updated_at=line.updated_at,
        ))
    return SupplySupplierConfirmationRead(
        id=confirmation.id, supplier_order_id=confirmation.supplier_order_id,
        revision_number=confirmation.revision_number, status=confirmation.status,
        response_type=confirmation.response_type, supplier_id=order.supplier_id,
        supplier_display_name=order.supplier.display_name, order_number=order.number,
        supplier_reference=confirmation.supplier_reference,
        supplier_comment=confirmation.supplier_comment,
        planned_delivery_date=order.planned_delivery_date,
        confirmed_delivery_date=confirmation.confirmed_delivery_date,
        responded_at=confirmation.responded_at, recorded_at=confirmation.recorded_at,
        created_at=confirmation.created_at, updated_at=confirmation.updated_at,
        ordered_total_amount=order.total_amount, confirmed_total_amount=confirmed_total,
        currency=order.currency, lines=lines,
    )


def read_confirmation(session: Session, confirmation_id: UUID, *, tenant_id: str) -> SupplySupplierConfirmationRead:
    return read_confirmation_model(get_confirmation(session, confirmation_id, tenant_id=tenant_id))


def list_confirmations(session: Session, order_id: UUID, *, tenant_id: str) -> list[SupplySupplierConfirmationRead]:
    order_exists = session.scalar(select(SupplySupplierOrder.id).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ))
    if order_exists is None:
        raise SupplierConfirmationNotFoundError
    confirmations = session.scalars(select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.supplier_order_id == order_id,
        SupplySupplierConfirmation.tenant_id == tenant_id,
    ).options(*_options()).order_by(SupplySupplierConfirmation.revision_number.desc())).all()
    return [read_confirmation_model(item) for item in confirmations]


def _copy_line(confirmation: SupplySupplierConfirmation, source) -> SupplySupplierConfirmationLine:
    if isinstance(source, SupplySupplierOrderLine):
        return SupplySupplierConfirmationLine(
            tenant_id=confirmation.tenant_id, confirmation_id=confirmation.id,
            supplier_order_line_id=source.id, response_status="CONFIRMED",
            product_name_snapshot=source.product_name_snapshot,
            confirmed_packages_count=source.packages_count,
            confirmed_package_quantity=source.package_quantity_snapshot,
            confirmed_package_unit_id=source.package_unit_id_snapshot,
            confirmed_quantity_base=source.quantity_base,
            confirmed_price_per_package=source.price_per_package_snapshot,
            confirmed_planned_amount=source.planned_amount, currency=source.currency,
        )
    return SupplySupplierConfirmationLine(
        tenant_id=confirmation.tenant_id, confirmation_id=confirmation.id,
        supplier_order_line_id=source.supplier_order_line_id,
        response_status=source.response_status, product_name_snapshot=source.product_name_snapshot,
        confirmed_packages_count=source.confirmed_packages_count,
        confirmed_package_quantity=source.confirmed_package_quantity,
        confirmed_package_unit_id=source.confirmed_package_unit_id,
        confirmed_quantity_base=source.confirmed_quantity_base,
        confirmed_price_per_package=source.confirmed_price_per_package,
        confirmed_planned_amount=source.confirmed_planned_amount,
        currency=source.currency, supplier_line_comment=source.supplier_line_comment,
    )


def create_confirmation(
    session: Session, order_id: UUID, *, tenant_id: str, user_id: int,
) -> SupplySupplierConfirmationRead:
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierOrder))
    if order is None:
        raise SupplierConfirmationNotFoundError
    if order.status != "SENT":
        raise SupplierConfirmationStateError
    existing = session.scalar(select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.tenant_id == tenant_id,
        SupplySupplierConfirmation.supplier_order_id == order_id,
        SupplySupplierConfirmation.status == "DRAFT",
    ).with_for_update(of=SupplySupplierConfirmation))
    if existing is not None:
        session.commit()
        return read_confirmation(session, existing.id, tenant_id=tenant_id)

    previous = session.scalar(select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.tenant_id == tenant_id,
        SupplySupplierConfirmation.supplier_order_id == order_id,
        SupplySupplierConfirmation.status == "RECORDED",
    ).options(selectinload(SupplySupplierConfirmation.lines)))
    revision = int(session.scalar(select(func.max(SupplySupplierConfirmation.revision_number)).where(
        SupplySupplierConfirmation.tenant_id == tenant_id,
        SupplySupplierConfirmation.supplier_order_id == order_id,
    )) or 0) + 1
    confirmation = SupplySupplierConfirmation(
        tenant_id=tenant_id, supplier_order_id=order_id, revision_number=revision,
        status="DRAFT", created_by_user_id=user_id,
        supplier_reference=previous.supplier_reference if previous else None,
        supplier_comment=previous.supplier_comment if previous else None,
        confirmed_delivery_date=previous.confirmed_delivery_date if previous else order.planned_delivery_date,
        responded_at=datetime.now(timezone.utc),
    )
    try:
        session.add(confirmation); session.flush()
        sources = previous.lines if previous else list(session.scalars(select(SupplySupplierOrderLine).where(
            SupplySupplierOrderLine.tenant_id == tenant_id,
            SupplySupplierOrderLine.supplier_order_id == order_id,
        ).order_by(SupplySupplierOrderLine.created_at)).all())
        if not sources:
            raise SupplierConfirmationValidationError
        session.add_all([_copy_line(confirmation, source) for source in sources])
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierConfirmationConflictError from error
    except Exception:
        session.rollback()
        raise
    return read_confirmation(session, confirmation.id, tenant_id=tenant_id)


def update_confirmation(
    session: Session, confirmation_id: UUID, payload: SupplySupplierConfirmationUpdate, *, tenant_id: str,
) -> SupplySupplierConfirmationRead:
    confirmation = get_confirmation(session, confirmation_id, tenant_id=tenant_id, lock=True)
    if confirmation.status != "DRAFT":
        raise SupplierConfirmationStateError
    for field in payload.model_fields_set:
        setattr(confirmation, field, getattr(payload, field))
    session.commit()
    return read_confirmation(session, confirmation_id, tenant_id=tenant_id)


def update_confirmation_line(
    session: Session, confirmation_id: UUID, line_id: UUID,
    payload: SupplySupplierConfirmationLineUpdate, *, tenant_id: str,
) -> SupplySupplierConfirmationRead:
    confirmation = get_confirmation(session, confirmation_id, tenant_id=tenant_id, lock=True)
    if confirmation.status != "DRAFT":
        raise SupplierConfirmationStateError
    line = next((item for item in confirmation.lines if item.id == line_id), None)
    if line is None:
        raise SupplierConfirmationNotFoundError
    if (
        "confirmed_package_unit_id" in payload.model_fields_set
        and payload.confirmed_package_unit_id is not None
        and session.scalar(select(SupplyUnit.id).where(
            SupplyUnit.id == payload.confirmed_package_unit_id,
            SupplyUnit.tenant_id == tenant_id,
        )) is None
    ):
        raise SupplierConfirmationValidationError
    for field in payload.model_fields_set:
        setattr(line, field, getattr(payload, field))
    if line.response_status == "REJECTED":
        line.confirmed_packages_count = None
        line.confirmed_package_quantity = None
        line.confirmed_package_unit_id = None
        line.confirmed_quantity_base = None
        line.confirmed_price_per_package = None
        line.confirmed_planned_amount = None
    else:
        if line.confirmed_packages_count is not None and line.confirmed_package_quantity is not None:
            line.confirmed_quantity_base = (
                Decimal(line.confirmed_packages_count) * Decimal(line.confirmed_package_quantity)
            )
        if line.confirmed_packages_count is not None and line.confirmed_price_per_package is not None:
            line.confirmed_planned_amount = (
                Decimal(line.confirmed_packages_count) * Decimal(line.confirmed_price_per_package)
            )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierConfirmationConflictError from error
    return read_confirmation(session, confirmation_id, tenant_id=tenant_id)


def _validate_record(confirmation: SupplySupplierConfirmation) -> str:
    order = confirmation.supplier_order
    order_lines = {line.id: line for line in order.lines}
    if not confirmation.lines or {line.supplier_order_line_id for line in confirmation.lines} != set(order_lines):
        raise SupplierConfirmationValidationError
    for line in confirmation.lines:
        ordered = order_lines[line.supplier_order_line_id]
        if line.product_name_snapshot != ordered.product_name_snapshot or line.currency != ordered.currency:
            raise SupplierConfirmationValidationError
        if line.response_status != "REJECTED" and any(value is None for value in (
            line.confirmed_packages_count, line.confirmed_package_quantity,
            line.confirmed_package_unit_id, line.confirmed_quantity_base,
            line.confirmed_price_per_package, line.confirmed_planned_amount,
        )):
            raise SupplierConfirmationValidationError
    statuses = {line.response_status for line in confirmation.lines}
    if statuses == {"REJECTED"}:
        return "REJECTED"
    if statuses == {"CONFIRMED"}:
        return "CONFIRMED"
    return "PARTIALLY_CONFIRMED"


def record_confirmation(
    session: Session, confirmation_id: UUID, *, tenant_id: str, user_id: int,
) -> SupplySupplierConfirmationRead:
    confirmation_ref = session.scalar(select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.id == confirmation_id,
        SupplySupplierConfirmation.tenant_id == tenant_id,
    ))
    if confirmation_ref is None:
        raise SupplierConfirmationNotFoundError
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == confirmation_ref.supplier_order_id,
        SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierOrder))
    confirmation = get_confirmation(session, confirmation_id, tenant_id=tenant_id, lock=True)
    if confirmation.status != "DRAFT" or order is None or order.status != "SENT":
        raise SupplierConfirmationStateError
    # Load order lines independently so locking the order never locks nullable joined rows.
    order.lines = list(session.scalars(select(SupplySupplierOrderLine).where(
        SupplySupplierOrderLine.tenant_id == tenant_id,
        SupplySupplierOrderLine.supplier_order_id == order.id,
    ).options(joinedload(SupplySupplierOrderLine.package_unit_snapshot))).all())
    confirmation.supplier_order = order
    response_type = _validate_record(confirmation)
    previous = session.scalar(select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.tenant_id == tenant_id,
        SupplySupplierConfirmation.supplier_order_id == order.id,
        SupplySupplierConfirmation.status == "RECORDED",
    ).with_for_update(of=SupplySupplierConfirmation))
    if previous is not None:
        previous.status = "SUPERSEDED"
        session.flush()
    confirmation.status = "RECORDED"
    confirmation.response_type = response_type
    confirmation.recorded_at = datetime.now(timezone.utc)
    confirmation.recorded_by_user_id = user_id
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierConfirmationConflictError from error
    return read_confirmation(session, confirmation_id, tenant_id=tenant_id)


def cancel_confirmation(session: Session, confirmation_id: UUID, *, tenant_id: str) -> SupplySupplierConfirmationRead:
    confirmation = get_confirmation(session, confirmation_id, tenant_id=tenant_id, lock=True)
    if confirmation.status != "DRAFT":
        raise SupplierConfirmationStateError
    confirmation.status = "CANCELLED"
    session.commit()
    return read_confirmation(session, confirmation_id, tenant_id=tenant_id)
