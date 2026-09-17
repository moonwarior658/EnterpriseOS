from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.supply import (
    SupplyProduct,
    SupplySupplierAcceptance,
    SupplySupplierAcceptanceLine,
    SupplySupplierConfirmation,
    SupplySupplierConfirmationLine,
    SupplySupplierDocument,
    SupplySupplierDocumentLine,
    SupplySupplierOrder,
    SupplySupplierOrderLine,
    SupplyUnit,
)
from app.schemas.supplier_acceptance import (
    SupplySupplierAcceptanceCreate,
    SupplySupplierAcceptanceLineCreate,
    SupplySupplierAcceptanceLineRead,
    SupplySupplierAcceptanceLineUpdate,
    SupplySupplierAcceptanceRead,
    SupplySupplierAcceptanceUpdate,
    SupplySupplierAcceptanceSummary,
)

Q = Decimal("0.000001")


class SupplierAcceptanceNotFoundError(LookupError): pass
class SupplierAcceptanceStateError(ValueError): pass
class SupplierAcceptanceValidationError(ValueError): pass
class SupplierAcceptanceLinkError(ValueError): pass
class SupplierAcceptanceConflictError(ValueError): pass
class SupplierAcceptanceUnitError(ValueError): pass


def _options():
    return (selectinload(SupplySupplierAcceptance.lines),)


def _get(session: Session, acceptance_id: UUID, *, tenant_id: str, lock: bool = False):
    query = select(SupplySupplierAcceptance).where(
        SupplySupplierAcceptance.id == acceptance_id,
        SupplySupplierAcceptance.tenant_id == tenant_id,
    ).options(*_options())
    if lock:
        query = query.with_for_update(of=SupplySupplierAcceptance)
    value = session.scalar(query)
    if value is None:
        raise SupplierAcceptanceNotFoundError
    return value


def _source_quantities(session: Session, line: SupplySupplierAcceptanceLine):
    ordered = confirmed = None
    if line.supplier_order_line_id:
        ordered = session.scalar(select(SupplySupplierOrderLine.quantity_base).where(
            SupplySupplierOrderLine.id == line.supplier_order_line_id,
            SupplySupplierOrderLine.tenant_id == line.tenant_id,
        ))
    if line.supplier_confirmation_line_id:
        confirmed = session.scalar(select(SupplySupplierConfirmationLine.confirmed_quantity_base).where(
            SupplySupplierConfirmationLine.id == line.supplier_confirmation_line_id,
            SupplySupplierConfirmationLine.tenant_id == line.tenant_id,
        ))
    return ordered, confirmed


def _line_read(session: Session, line: SupplySupplierAcceptanceLine):
    documented = Decimal(line.documented_quantity) if line.documented_quantity is not None else None
    received = Decimal(line.received_quantity)
    shortage = max((documented or received) - received, Decimal("0")) if documented is not None else Decimal("0")
    excess = max(received - (documented or received), Decimal("0")) if documented is not None else Decimal("0")
    ordered, confirmed = _source_quantities(session, line)
    return SupplySupplierAcceptanceLineRead(
        id=line.id, supplier_document_line_id=line.supplier_document_line_id,
        supplier_order_line_id=line.supplier_order_line_id,
        supplier_confirmation_line_id=line.supplier_confirmation_line_id,
        product_name_snapshot=line.product_name_snapshot, product_id=line.product_id,
        unit_id=line.unit_id, unit_name_snapshot=line.unit_name_snapshot,
        ordered_quantity=ordered, confirmed_quantity=confirmed,
        documented_quantity=documented, received_quantity=received,
        accepted_quantity=line.accepted_quantity, rejected_quantity=line.rejected_quantity,
        shortage_quantity=shortage, excess_quantity=excess,
        documented_unit_price=line.documented_unit_price,
        accepted_unit_price=line.accepted_unit_price, accepted_amount=line.accepted_amount,
        currency=line.currency, rejection_reason=line.rejection_reason,
        comment=line.comment,
        is_unmatched=line.supplier_document_line_id is None and line.supplier_order_line_id is None,
    )


def _result(lines: list[SupplySupplierAcceptanceLineRead]) -> str:
    if lines and all(line.accepted_quantity == 0 and line.rejected_quantity > 0 for line in lines):
        return "REJECTED"
    if any(line.excess_quantity > 0 for line in lines):
        return "OVER_DELIVERED"
    if any(line.shortage_quantity > 0 or line.rejected_quantity > 0 for line in lines):
        return "PARTIALLY_ACCEPTED"
    return "FULLY_ACCEPTED" if lines else "MIXED"


def _read(session: Session, acceptance: SupplySupplierAcceptance):
    lines = [_line_read(session, line) for line in acceptance.lines]
    source = "DOCUMENT" if acceptance.supplier_document_id else (
        "CONFIRMATION" if acceptance.supplier_confirmation_id else "ORDER"
    )
    return SupplySupplierAcceptanceRead(
        id=acceptance.id, supplier_order_id=acceptance.supplier_order_id,
        supplier_document_id=acceptance.supplier_document_id,
        supplier_confirmation_id=acceptance.supplier_confirmation_id,
        source=source, status=acceptance.status, result=_result(lines),
        accepted_at=acceptance.accepted_at, received_at=acceptance.received_at,
        comment=acceptance.comment, recorded_by_user_id=acceptance.recorded_by_user_id,
        recorded_at=acceptance.recorded_at, created_by_user_id=acceptance.created_by_user_id,
        created_at=acceptance.created_at, updated_at=acceptance.updated_at, lines=lines,
    )


def read_acceptance(session: Session, acceptance_id: UUID, *, tenant_id: str):
    return _read(session, _get(session, acceptance_id, tenant_id=tenant_id))


def list_acceptances(session: Session, order_id: UUID, *, tenant_id: str):
    if session.scalar(select(SupplySupplierOrder.id).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    )) is None:
        raise SupplierAcceptanceNotFoundError
    values = session.scalars(select(SupplySupplierAcceptance).where(
        SupplySupplierAcceptance.supplier_order_id == order_id,
        SupplySupplierAcceptance.tenant_id == tenant_id,
    ).options(*_options()).order_by(SupplySupplierAcceptance.created_at.desc())).all()
    return [_read(session, value) for value in values]


def acceptance_summary(session: Session, values: list[SupplySupplierAcceptance]):
    reads = [_read(session, value) for value in values]
    recorded = [item for item in reads if item.status == "RECORDED"]
    totals: dict[str, dict[str, Decimal]] = {}
    for item in recorded:
        for line in item.lines:
            unit = line.unit_name_snapshot or "—"
            bucket = totals.setdefault(unit, {"documented": Decimal("0"), "received": Decimal("0"), "accepted": Decimal("0"), "rejected": Decimal("0")})
            bucket["documented"] += line.documented_quantity or Decimal("0")
            bucket["received"] += line.received_quantity
            bucket["accepted"] += line.accepted_quantity
            bucket["rejected"] += line.rejected_quantity
    latest = max(reads, key=lambda item: item.created_at) if reads else None
    return SupplySupplierAcceptanceSummary(
        draft_count=sum(item.status == "DRAFT" for item in reads),
        recorded_count=len(recorded), latest_acceptance=latest,
        quantities_by_unit=totals,
        has_shortage=any(line.shortage_quantity > 0 for item in recorded for line in item.lines),
        has_excess=any(line.excess_quantity > 0 for item in recorded for line in item.lines),
    )


def _unit_price(document_line: SupplySupplierDocumentLine) -> Decimal | None:
    if document_line.pricing_basis == "UNIT":
        return Decimal(document_line.unit_price)
    if document_line.pricing_basis == "PACKAGE" and document_line.quantity_base:
        return (Decimal(document_line.line_amount) / Decimal(document_line.quantity_base)).quantize(Q)
    return None


def _remaining(session: Session, line: SupplySupplierDocumentLine) -> Decimal:
    used = session.scalar(select(func.coalesce(func.sum(SupplySupplierAcceptanceLine.received_quantity), 0)).join(
        SupplySupplierAcceptance,
        SupplySupplierAcceptance.id == SupplySupplierAcceptanceLine.acceptance_id,
    ).where(
        SupplySupplierAcceptanceLine.tenant_id == line.tenant_id,
        SupplySupplierAcceptanceLine.supplier_document_line_id == line.id,
        SupplySupplierAcceptance.status == "RECORDED",
    ))
    return max(Decimal(line.quantity_base) - Decimal(used), Decimal("0"))


def _document_defaults(session: Session, acceptance: SupplySupplierAcceptance, document: SupplySupplierDocument):
    order_lines = {line.id: line for line in session.scalars(select(SupplySupplierOrderLine).where(
        SupplySupplierOrderLine.tenant_id == acceptance.tenant_id,
        SupplySupplierOrderLine.supplier_order_id == acceptance.supplier_order_id,
    )).all()}
    for line in document.lines:
        if line.quantity_base is None or line.package_unit_id_snapshot is None:
            continue
        remaining = _remaining(session, line)
        if remaining <= 0:
            continue
        ordered = order_lines.get(line.supplier_order_line_id)
        price = _unit_price(line)
        acceptance.lines.append(SupplySupplierAcceptanceLine(
            tenant_id=acceptance.tenant_id, supplier_order_id=acceptance.supplier_order_id,
            supplier_confirmation_id=line.supplier_confirmation_id,
            supplier_document_line_id=line.id, supplier_order_line_id=line.supplier_order_line_id,
            supplier_confirmation_line_id=line.supplier_confirmation_line_id,
            product_name_snapshot=line.product_name_snapshot,
            product_id=ordered.product_id if ordered else None,
            unit_id=line.package_unit_id_snapshot, unit_name_snapshot=line.unit_name_snapshot,
            documented_quantity=remaining, received_quantity=remaining,
            accepted_quantity=remaining, rejected_quantity=Decimal("0"),
            documented_unit_price=price, accepted_unit_price=price,
            accepted_amount=(remaining * price).quantize(Q) if price else None,
            currency="RUB",
        ))


def _confirmation_defaults(acceptance: SupplySupplierAcceptance, confirmation: SupplySupplierConfirmation):
    for line in confirmation.lines:
        if line.response_status == "REJECTED" or not line.confirmed_quantity_base or not line.confirmed_package_unit_id:
            continue
        quantity = Decimal(line.confirmed_quantity_base)
        price = (Decimal(line.confirmed_planned_amount) / quantity).quantize(Q) if line.confirmed_planned_amount else None
        acceptance.lines.append(SupplySupplierAcceptanceLine(
            tenant_id=acceptance.tenant_id, supplier_order_id=acceptance.supplier_order_id,
            supplier_confirmation_id=confirmation.id,
            supplier_order_line_id=line.supplier_order_line_id,
            supplier_confirmation_line_id=line.id,
            product_name_snapshot=line.product_name_snapshot,
            product_id=line.supplier_order_line.product_id,
            unit_id=line.confirmed_package_unit_id,
            unit_name_snapshot=line.confirmed_package_unit.short_name_ru,
            documented_quantity=quantity, received_quantity=quantity,
            accepted_quantity=quantity, rejected_quantity=Decimal("0"),
            documented_unit_price=price, accepted_unit_price=price,
            accepted_amount=(quantity * price).quantize(Q) if price else None, currency="RUB",
        ))


def _order_defaults(acceptance: SupplySupplierAcceptance, order: SupplySupplierOrder):
    for line in order.lines:
        quantity = Decimal(line.quantity_base)
        acceptance.lines.append(SupplySupplierAcceptanceLine(
            tenant_id=acceptance.tenant_id, supplier_order_id=order.id,
            supplier_order_line_id=line.id, product_name_snapshot=line.product_name_snapshot,
            product_id=line.product_id, unit_id=line.package_unit_id_snapshot,
            unit_name_snapshot=line.package_unit_snapshot.short_name_ru,
            documented_quantity=quantity, received_quantity=quantity,
            accepted_quantity=quantity, rejected_quantity=Decimal("0"),
            documented_unit_price=line.base_unit_price_snapshot,
            accepted_unit_price=line.base_unit_price_snapshot,
            accepted_amount=line.planned_amount, currency="RUB",
        ))


def create_acceptance(session: Session, order_id: UUID, payload: SupplySupplierAcceptanceCreate, *, tenant_id: str, user_id: int):
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierOrder))
    if order is None:
        raise SupplierAcceptanceNotFoundError
    if order.status != "SENT":
        raise SupplierAcceptanceStateError
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).options(selectinload(SupplySupplierOrder.lines).selectinload(SupplySupplierOrderLine.package_unit_snapshot)).execution_options(populate_existing=True))
    document = None
    confirmation = None
    if payload.supplier_document_id:
        document = session.scalar(select(SupplySupplierDocument).where(
            SupplySupplierDocument.id == payload.supplier_document_id,
            SupplySupplierDocument.tenant_id == tenant_id,
            SupplySupplierDocument.supplier_order_id == order_id,
            SupplySupplierDocument.status == "RECORDED",
        ).options(selectinload(SupplySupplierDocument.lines)))
        if document is None:
            raise SupplierAcceptanceLinkError
    else:
        confirmation = session.scalar(select(SupplySupplierConfirmation).where(
            SupplySupplierConfirmation.tenant_id == tenant_id,
            SupplySupplierConfirmation.supplier_order_id == order_id,
            SupplySupplierConfirmation.status == "RECORDED",
        ).options(
            selectinload(SupplySupplierConfirmation.lines).selectinload(SupplySupplierConfirmationLine.supplier_order_line),
            selectinload(SupplySupplierConfirmation.lines).selectinload(SupplySupplierConfirmationLine.confirmed_package_unit),
        ).order_by(SupplySupplierConfirmation.revision_number.desc()).limit(1))
    acceptance = SupplySupplierAcceptance(
        tenant_id=tenant_id, supplier_order_id=order_id,
        supplier_document_id=document.id if document else None,
        supplier_confirmation_id=document.supplier_confirmation_id if document else (confirmation.id if confirmation else None),
        received_at=payload.received_at, comment=payload.comment, created_by_user_id=user_id,
    )
    session.add(acceptance); session.flush()
    if document:
        _document_defaults(session, acceptance, document)
    elif confirmation:
        _confirmation_defaults(acceptance, confirmation)
    else:
        _order_defaults(acceptance, order)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback(); raise SupplierAcceptanceConflictError from error
    return read_acceptance(session, acceptance.id, tenant_id=tenant_id)


def update_acceptance(session: Session, acceptance_id: UUID, payload: SupplySupplierAcceptanceUpdate, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    for field in payload.model_fields_set: setattr(acceptance, field, getattr(payload, field))
    session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def _validate_values(values: dict):
    received = Decimal(values["received_quantity"]); accepted = Decimal(values["accepted_quantity"]); rejected = Decimal(values["rejected_quantity"])
    reason = values.get("rejection_reason")
    if hasattr(reason, "value"): reason = reason.value
    comment = (values.get("comment") or "").strip() or None
    if accepted + rejected != received or (rejected > 0 and not reason) or (rejected == 0 and reason) or (reason == "OTHER" and not comment):
        raise SupplierAcceptanceValidationError
    price = values.get("accepted_unit_price")
    return received, accepted, rejected, reason, comment, ((accepted * Decimal(price)).quantize(Q) if price else None)


def create_line(session: Session, acceptance_id: UUID, payload: SupplySupplierAcceptanceLineCreate, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    unit = session.scalar(select(SupplyUnit).where(SupplyUnit.id == payload.unit_id, SupplyUnit.tenant_id == tenant_id))
    if unit is None: raise SupplierAcceptanceUnitError
    if payload.product_id and session.scalar(select(SupplyProduct.id).where(SupplyProduct.id == payload.product_id, SupplyProduct.tenant_id == tenant_id)) is None:
        raise SupplierAcceptanceLinkError
    values = payload.model_dump(); received, accepted, rejected, reason, comment, amount = _validate_values(values)
    acceptance.lines.append(SupplySupplierAcceptanceLine(
        tenant_id=tenant_id, supplier_order_id=acceptance.supplier_order_id,
        product_name_snapshot=payload.product_name_snapshot.strip(), product_id=payload.product_id,
        unit_id=unit.id, unit_name_snapshot=unit.short_name_ru,
        received_quantity=received, accepted_quantity=accepted, rejected_quantity=rejected,
        accepted_unit_price=payload.accepted_unit_price, accepted_amount=amount, currency="RUB",
        rejection_reason=reason, comment=comment,
    ))
    session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def update_line(session: Session, acceptance_id: UUID, line_id: UUID, payload: SupplySupplierAcceptanceLineUpdate, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    line = next((item for item in acceptance.lines if item.id == line_id), None)
    if line is None: raise SupplierAcceptanceNotFoundError
    values = {"received_quantity": line.received_quantity, "accepted_quantity": line.accepted_quantity, "rejected_quantity": line.rejected_quantity, "accepted_unit_price": line.accepted_unit_price, "rejection_reason": line.rejection_reason, "comment": line.comment}
    values.update(payload.model_dump(exclude_unset=True))
    received, accepted, rejected, reason, comment, amount = _validate_values(values)
    line.received_quantity=received; line.accepted_quantity=accepted; line.rejected_quantity=rejected
    line.accepted_unit_price=values.get("accepted_unit_price"); line.accepted_amount=amount
    line.rejection_reason=reason; line.comment=comment
    session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def delete_line(session: Session, acceptance_id: UUID, line_id: UUID, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    line = next((item for item in acceptance.lines if item.id == line_id), None)
    if line is None: raise SupplierAcceptanceNotFoundError
    session.delete(line); session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def record_acceptance(session: Session, acceptance_id: UUID, *, tenant_id: str, user_id: int):
    ref = session.scalar(select(SupplySupplierAcceptance).where(SupplySupplierAcceptance.id == acceptance_id, SupplySupplierAcceptance.tenant_id == tenant_id))
    if ref is None: raise SupplierAcceptanceNotFoundError
    order = session.scalar(select(SupplySupplierOrder).where(SupplySupplierOrder.id == ref.supplier_order_id, SupplySupplierOrder.tenant_id == tenant_id).with_for_update(of=SupplySupplierOrder))
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if order is None or order.status != "SENT" or acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    if not acceptance.lines: raise SupplierAcceptanceValidationError
    document_line_ids = sorted(
        (line.supplier_document_line_id for line in acceptance.lines if line.supplier_document_line_id),
        key=str,
    )
    if document_line_ids:
        locked_lines = session.scalars(select(SupplySupplierDocumentLine).where(
            SupplySupplierDocumentLine.tenant_id == tenant_id,
            SupplySupplierDocumentLine.id.in_(document_line_ids),
        ).order_by(SupplySupplierDocumentLine.id).with_for_update()).all()
        locked_by_id = {line.id: line for line in locked_lines}
        for line in acceptance.lines:
            if line.supplier_document_line_id is None:
                continue
            source = locked_by_id.get(line.supplier_document_line_id)
            if source is None or line.documented_quantity != _remaining(session, source):
                raise SupplierAcceptanceConflictError
    for line in acceptance.lines:
        if line.unit_id is None: raise SupplierAcceptanceUnitError
        _validate_values({"received_quantity": line.received_quantity, "accepted_quantity": line.accepted_quantity, "rejected_quantity": line.rejected_quantity, "accepted_unit_price": line.accepted_unit_price, "rejection_reason": line.rejection_reason, "comment": line.comment})
    acceptance.status="RECORDED"; acceptance.recorded_by_user_id=user_id
    acceptance.recorded_at=datetime.now(timezone.utc); acceptance.accepted_at=acceptance.recorded_at
    try: session.commit()
    except IntegrityError as error: session.rollback(); raise SupplierAcceptanceConflictError from error
    return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def cancel_acceptance(session: Session, acceptance_id: UUID, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    acceptance.status="CANCELLED"; session.commit()
    return read_acceptance(session, acceptance_id, tenant_id=tenant_id)
