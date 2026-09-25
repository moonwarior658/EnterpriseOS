from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.supply import (
    SupplySupplierConfirmation,
    SupplySupplierConfirmationLine,
    SupplySupplierDocument,
    SupplySupplierDocumentAttachment,
    SupplySupplierDocumentLine,
    SupplySupplierObligation,
    SupplySupplierOrder,
    SupplySupplierOrderLine,
    SupplySupplierPayment,
    SupplyUnit,
)
from app.schemas.supplier_document import (
    SupplySupplierDocumentCreate,
    SupplySupplierDocumentAttachmentRead,
    SupplySupplierDocumentLineCreate,
    SupplySupplierDocumentLineRead,
    SupplySupplierDocumentLineUpdate,
    SupplySupplierDocumentRead,
    SupplySupplierDocumentSummary,
    SupplySupplierDocumentsSummary,
    SupplySupplierDocumentUpdate,
)


class SupplierDocumentNotFoundError(LookupError):
    pass


class SupplierDocumentStateError(ValueError):
    pass


class SupplierDocumentValidationError(ValueError):
    pass


class SupplierDocumentLinkError(ValueError):
    pass


class SupplierDocumentReviewError(ValueError):
    pass


class SupplierDocumentConflictError(ValueError):
    pass


MONEY_QUANTUM = Decimal("0.000001")
PACKAGE_QUANTUM = Decimal("0.001")
PRICE_QUANTUM = Decimal("0.01")
MAX_ATTACHMENT_COUNT = 10


def _document_options():
    return (
        selectinload(SupplySupplierDocument.lines),
        selectinload(SupplySupplierDocument.attachments),
        selectinload(SupplySupplierDocument.allocations),
        selectinload(SupplySupplierDocument.payments).joinedload(SupplySupplierPayment.supplier),
        selectinload(SupplySupplierDocument.payments).joinedload(SupplySupplierPayment.supplier_order),
    )


def _confirmation_options():
    return (
        selectinload(SupplySupplierConfirmation.deviations),
        selectinload(SupplySupplierConfirmation.lines).joinedload(
            SupplySupplierConfirmationLine.supplier_order_line
        ).joinedload(SupplySupplierOrderLine.package_unit_snapshot),
        selectinload(SupplySupplierConfirmation.lines).joinedload(
            SupplySupplierConfirmationLine.confirmed_package_unit
        ),
    )


def _get_document(
    session: Session, document_id: UUID, *, tenant_id: str, lock: bool = False,
) -> SupplySupplierDocument:
    query = select(SupplySupplierDocument).where(
        SupplySupplierDocument.id == document_id,
        SupplySupplierDocument.tenant_id == tenant_id,
    )
    if lock:
        query = query.with_for_update(of=SupplySupplierDocument)
    document = session.scalar(
        query.options(*_document_options()).execution_options(populate_existing=True)
    )
    if document is None:
        raise SupplierDocumentNotFoundError
    return document


def _latest_confirmation(
    session: Session, order_id: UUID, *, tenant_id: str,
) -> SupplySupplierConfirmation | None:
    return session.scalar(select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.tenant_id == tenant_id,
        SupplySupplierConfirmation.supplier_order_id == order_id,
        SupplySupplierConfirmation.status == "RECORDED",
    ).options(*_confirmation_options()).order_by(
        SupplySupplierConfirmation.revision_number.desc()
    ))


def _confirmation_review_state(confirmation: SupplySupplierConfirmation) -> str:
    required = [item for item in confirmation.deviations if item.requires_decision]
    if any(item.status == "OPEN" for item in required):
        return "REQUIRES_DECISION"
    return "RESOLVED" if required else "CLEAN"


def _line_read(line: SupplySupplierDocumentLine) -> SupplySupplierDocumentLineRead:
    return SupplySupplierDocumentLineRead(
        id=line.id,
        supplier_order_line_id=line.supplier_order_line_id,
        supplier_confirmation_line_id=line.supplier_confirmation_line_id,
        product_name_snapshot=line.product_name_snapshot,
        pricing_basis=line.pricing_basis,
        package_quantity_snapshot=line.package_quantity_snapshot,
        package_unit_id_snapshot=line.package_unit_id_snapshot,
        unit_name_snapshot=line.unit_name_snapshot,
        packages_count=line.packages_count,
        quantity_base=line.quantity_base,
        price_per_package=line.price_per_package,
        unit_price=line.unit_price,
        line_amount=line.line_amount,
        currency=line.currency,
        supplier_line_reference=line.supplier_line_reference,
        comment=line.comment,
        is_extra_line=line.supplier_order_line_id is None,
        created_at=line.created_at,
        updated_at=line.updated_at,
    )


def _attachment_read(
    attachment: SupplySupplierDocumentAttachment,
) -> SupplySupplierDocumentAttachmentRead:
    return SupplySupplierDocumentAttachmentRead(
        id=attachment.id,
        original_filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        created_by_user_id=attachment.created_by_user_id,
        created_at=attachment.created_at,
    )


def _summary(
    session: Session, document: SupplySupplierDocument,
) -> SupplySupplierDocumentSummary:
    revision = None
    if document.supplier_confirmation_id is not None:
        revision = session.scalar(select(SupplySupplierConfirmation.revision_number).where(
            SupplySupplierConfirmation.id == document.supplier_confirmation_id,
            SupplySupplierConfirmation.tenant_id == document.tenant_id,
        ))
    return SupplySupplierDocumentSummary(
        id=document.id,
        document_type=document.document_type,
        financial_role=document.financial_role,
        obligation_id=document.obligation_id,
        document_number=document.document_number,
        document_date=document.document_date,
        payment_due_date=document.payment_due_date,
        status=document.status,
        total_amount=document.total_amount,
        currency=document.currency,
        supplier_confirmation_revision=revision,
        created_at=document.created_at,
        recorded_at=document.recorded_at,
    )


def _read(session: Session, document: SupplySupplierDocument) -> SupplySupplierDocumentRead:
    from app.supply.supplier_payments import payment_read

    order_number = session.scalar(select(SupplySupplierOrder.number).where(
        SupplySupplierOrder.id == document.supplier_order_id,
        SupplySupplierOrder.tenant_id == document.tenant_id,
    ))
    if order_number is None:
        raise SupplierDocumentNotFoundError
    summary = _summary(session, document)
    active_allocations = [item for item in document.allocations if item.status == "ACTIVE"]
    recorded_amount = sum(
        (Decimal(item.amount) for item in active_allocations), Decimal("0")
    ).quantize(MONEY_QUANTUM)
    remaining = (Decimal(document.total_amount) - recorded_amount).quantize(MONEY_QUANTUM)
    if recorded_amount == 0:
        payment_state = "UNPAID"
    elif remaining > 0:
        payment_state = "PARTIALLY_PAID"
    elif remaining == 0:
        payment_state = "PAID"
    else:
        payment_state = "OVERPAID"
    if remaining <= 0:
        overdue_state = "SETTLED"
    elif document.payment_due_date is None:
        overdue_state = "UNKNOWN"
    elif date.today() > document.payment_due_date:
        overdue_state = "OVERDUE"
    else:
        overdue_state = "NOT_DUE"
    return SupplySupplierDocumentRead(
        **summary.model_dump(),
        supplier_order_id=document.supplier_order_id,
        supplier_order_number=order_number,
        supplier_confirmation_id=document.supplier_confirmation_id,
        supplier_id=document.supplier_id,
        supplier_display_name_snapshot=document.supplier_display_name_snapshot,
        supplier_inn_snapshot=document.supplier_inn_snapshot,
        supplier_kpp_snapshot=document.supplier_kpp_snapshot,
        comment=document.comment,
        created_by_user_id=document.created_by_user_id,
        recorded_by_user_id=document.recorded_by_user_id,
        updated_at=document.updated_at,
        document_total_amount=document.total_amount,
        recorded_payments_amount=recorded_amount,
        remaining_to_pay=remaining,
        payment_state=payment_state,
        overdue_state=overdue_state,
        payments=[payment_read(session, item) for item in document.payments],
        lines=[_line_read(line) for line in document.lines],
        attachments=[_attachment_read(item) for item in document.attachments],
    )


def read_document(
    session: Session, document_id: UUID, *, tenant_id: str,
) -> SupplySupplierDocumentRead:
    return _read(session, _get_document(session, document_id, tenant_id=tenant_id))


def list_documents(
    session: Session, order_id: UUID, *, tenant_id: str,
) -> list[SupplySupplierDocumentRead]:
    if session.scalar(select(SupplySupplierOrder.id).where(
        SupplySupplierOrder.id == order_id,
        SupplySupplierOrder.tenant_id == tenant_id,
    )) is None:
        raise SupplierDocumentNotFoundError
    documents = session.scalars(select(SupplySupplierDocument).where(
        SupplySupplierDocument.supplier_order_id == order_id,
        SupplySupplierDocument.tenant_id == tenant_id,
    ).options(*_document_options()).order_by(SupplySupplierDocument.created_at.desc())).all()
    return [_read(session, item) for item in documents]


def documents_summary(
    session: Session, documents: list[SupplySupplierDocument],
) -> SupplySupplierDocumentsSummary:
    latest = max(documents, key=lambda item: item.created_at) if documents else None
    return SupplySupplierDocumentsSummary(
        total_documents=len(documents),
        invoices_count=sum(item.document_type == "INVOICE" for item in documents),
        delivery_notes_count=sum(item.document_type == "DELIVERY_NOTE" for item in documents),
        upd_count=sum(item.document_type == "UPD" for item in documents),
        recorded_documents_count=sum(item.status == "RECORDED" for item in documents),
        latest_document=_summary(session, latest) if latest else None,
    )


def _default_line(
    document: SupplySupplierDocument,
    ordered: SupplySupplierOrderLine,
    confirmation_line: SupplySupplierConfirmationLine | None = None,
) -> SupplySupplierDocumentLine:
    if confirmation_line is None:
        packages_count = ordered.packages_count
        package_quantity = ordered.package_quantity_snapshot
        unit_id = ordered.package_unit_id_snapshot
        unit_name = ordered.package_unit_snapshot.short_name_ru
        quantity = ordered.quantity_base
        price = ordered.price_per_package_snapshot
        amount = ordered.planned_amount
    else:
        packages_count = confirmation_line.confirmed_packages_count
        package_quantity = confirmation_line.confirmed_package_quantity
        unit_id = confirmation_line.confirmed_package_unit_id
        unit_name = (
            confirmation_line.confirmed_package_unit.short_name_ru
            if confirmation_line.confirmed_package_unit else None
        )
        quantity = confirmation_line.confirmed_quantity_base
        price = confirmation_line.confirmed_price_per_package
        amount = confirmation_line.confirmed_planned_amount
    return SupplySupplierDocumentLine(
        tenant_id=document.tenant_id,
        supplier_document_id=document.id,
        supplier_order_id=document.supplier_order_id,
        supplier_confirmation_id=document.supplier_confirmation_id if confirmation_line else None,
        supplier_order_line_id=ordered.id,
        supplier_confirmation_line_id=confirmation_line.id if confirmation_line else None,
        product_name_snapshot=ordered.product_name_snapshot,
        pricing_basis="PACKAGE",
        package_quantity_snapshot=package_quantity,
        package_unit_id_snapshot=unit_id,
        unit_name_snapshot=unit_name,
        packages_count=packages_count,
        quantity_base=quantity,
        price_per_package=price,
        unit_price=None,
        line_amount=amount,
        currency="RUB",
    )


def _recalculate_total(document: SupplySupplierDocument) -> None:
    document.total_amount = sum(
        (Decimal(line.line_amount) for line in document.lines), Decimal("0")
    ).quantize(MONEY_QUANTUM)


def create_document(
    session: Session, order_id: UUID, payload: SupplySupplierDocumentCreate,
    *, tenant_id: str, user_id: int,
) -> SupplySupplierDocumentRead:
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id,
        SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierOrder))
    if order is None:
        raise SupplierDocumentNotFoundError
    if order.status != "SENT":
        raise SupplierDocumentStateError
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id,
        SupplySupplierOrder.tenant_id == tenant_id,
    ).options(
        joinedload(SupplySupplierOrder.supplier),
        selectinload(SupplySupplierOrder.lines).joinedload(
            SupplySupplierOrderLine.package_unit_snapshot
        ),
    ).execution_options(populate_existing=True))
    confirmation = _latest_confirmation(session, order_id, tenant_id=tenant_id)
    financial_role = (
        payload.financial_role.value if payload.financial_role
        else {"INVOICE": "PAYABLE", "DELIVERY_NOTE": "SUPPORTING", "UPD": "PAYABLE"}[payload.document_type.value]
    )
    obligation_id = payload.obligation_id
    if payload.create_obligation:
        if obligation_id is not None:
            raise SupplierDocumentValidationError
        obligation = SupplySupplierObligation(
            tenant_id=tenant_id, supplier_id=order.supplier_id,
            supplier_order_id=order.id, status="ACTIVE", created_by_user_id=user_id,
        )
        session.add(obligation)
        session.flush()
        obligation_id = obligation.id
    elif obligation_id is not None:
        obligation = session.scalar(select(SupplySupplierObligation).where(
            SupplySupplierObligation.id == obligation_id,
            SupplySupplierObligation.tenant_id == tenant_id,
            SupplySupplierObligation.supplier_id == order.supplier_id,
            SupplySupplierObligation.supplier_order_id == order.id,
            SupplySupplierObligation.status == "ACTIVE",
        ))
        if obligation is None:
            raise SupplierDocumentLinkError
    document = SupplySupplierDocument(
        tenant_id=tenant_id,
        supplier_order_id=order.id,
        supplier_confirmation_id=confirmation.id if confirmation else None,
        supplier_id=order.supplier_id,
        obligation_id=obligation_id,
        document_type=payload.document_type.value,
        financial_role=financial_role,
        document_number=payload.document_number,
        document_date=payload.document_date,
        payment_due_date=payload.payment_due_date,
        status="DRAFT",
        supplier_display_name_snapshot=order.supplier.display_name,
        supplier_inn_snapshot=order.supplier.inn,
        supplier_kpp_snapshot=order.supplier.kpp,
        currency="RUB",
        total_amount=Decimal("0"),
        comment=payload.comment,
        created_by_user_id=user_id,
    )
    try:
        session.add(document)
        session.flush()
        if confirmation is None:
            document.lines = [_default_line(document, line) for line in order.lines]
        elif _confirmation_review_state(confirmation) in {"CLEAN", "RESOLVED"}:
            document.lines = [
                _default_line(document, line.supplier_order_line, line)
                for line in confirmation.lines if line.response_status != "REJECTED"
            ]
        session.flush()
        _recalculate_total(document)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierDocumentConflictError from error
    except Exception:
        session.rollback()
        raise
    return read_document(session, document.id, tenant_id=tenant_id)


def update_document(
    session: Session, document_id: UUID, payload: SupplySupplierDocumentUpdate,
    *, tenant_id: str,
) -> SupplySupplierDocumentRead:
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if document.status != "DRAFT":
        raise SupplierDocumentStateError
    values = payload.model_dump(exclude_unset=True)
    create_obligation = values.pop("create_obligation", False)
    if create_obligation:
        if values.get("obligation_id") is not None:
            raise SupplierDocumentValidationError
        obligation = SupplySupplierObligation(
            tenant_id=tenant_id, supplier_id=document.supplier_id,
            supplier_order_id=document.supplier_order_id, status="ACTIVE",
            created_by_user_id=document.created_by_user_id,
        )
        session.add(obligation)
        session.flush()
        values["obligation_id"] = obligation.id
    if "obligation_id" in values and values["obligation_id"] is not None:
        obligation = session.scalar(select(SupplySupplierObligation).where(
            SupplySupplierObligation.id == values["obligation_id"],
            SupplySupplierObligation.tenant_id == tenant_id,
            SupplySupplierObligation.supplier_id == document.supplier_id,
            SupplySupplierObligation.supplier_order_id == document.supplier_order_id,
            SupplySupplierObligation.status == "ACTIVE",
        ))
        if obligation is None:
            raise SupplierDocumentLinkError
    for field, value in values.items():
        if field == "document_type" and value is None:
            raise SupplierDocumentValidationError
        setattr(document, field, value.value if hasattr(value, "value") else value)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierDocumentConflictError from error
    return read_document(session, document_id, tenant_id=tenant_id)


def _line_values(
    session: Session, document: SupplySupplierDocument, values: dict,
) -> dict:
    order_line_id = values.get("supplier_order_line_id")
    confirmation_line_id = values.get("supplier_confirmation_line_id")
    if order_line_id is not None:
        order_line = session.scalar(select(SupplySupplierOrderLine).where(
            SupplySupplierOrderLine.id == order_line_id,
            SupplySupplierOrderLine.tenant_id == document.tenant_id,
            SupplySupplierOrderLine.supplier_order_id == document.supplier_order_id,
        ))
        if order_line is None:
            raise SupplierDocumentLinkError
    if confirmation_line_id is not None:
        if document.supplier_confirmation_id is None or order_line_id is None:
            raise SupplierDocumentLinkError
        confirmation_line = session.scalar(select(SupplySupplierConfirmationLine).where(
            SupplySupplierConfirmationLine.id == confirmation_line_id,
            SupplySupplierConfirmationLine.tenant_id == document.tenant_id,
            SupplySupplierConfirmationLine.confirmation_id == document.supplier_confirmation_id,
            SupplySupplierConfirmationLine.supplier_order_line_id == order_line_id,
        ))
        if confirmation_line is None:
            raise SupplierDocumentLinkError

    unit_id = values.get("package_unit_id_snapshot")
    unit_name = None
    if unit_id is not None:
        unit = session.scalar(select(SupplyUnit).where(
            SupplyUnit.id == unit_id, SupplyUnit.tenant_id == document.tenant_id,
        ))
        if unit is None:
            raise SupplierDocumentLinkError
        unit_name = unit.short_name_ru

    basis = values["pricing_basis"]
    basis = basis.value if hasattr(basis, "value") else basis
    result = {
        **values,
        "pricing_basis": basis,
        "supplier_confirmation_id": document.supplier_confirmation_id if confirmation_line_id else None,
        "unit_name_snapshot": unit_name,
        "currency": "RUB",
    }
    if basis == "PACKAGE":
        packages = values.get("packages_count")
        price = values.get("price_per_package")
        package_quantity = values.get("package_quantity_snapshot")
        if packages is None or price is None:
            raise SupplierDocumentValidationError
        if (package_quantity is None) != (unit_id is None):
            raise SupplierDocumentValidationError
        result["packages_count"] = int(packages)
        result["price_per_package"] = Decimal(price).quantize(PRICE_QUANTUM)
        result["unit_price"] = None
        result["line_amount"] = (
            Decimal(packages) * result["price_per_package"]
        ).quantize(MONEY_QUANTUM)
        if package_quantity is None:
            result["package_quantity_snapshot"] = None
            result["quantity_base"] = None
        else:
            result["package_quantity_snapshot"] = Decimal(package_quantity).quantize(PACKAGE_QUANTUM)
            result["quantity_base"] = (
                Decimal(packages) * result["package_quantity_snapshot"]
            ).quantize(MONEY_QUANTUM)
    elif basis == "UNIT":
        quantity = values.get("quantity_base")
        unit_price = values.get("unit_price")
        if quantity is None or unit_price is None or unit_id is None:
            raise SupplierDocumentValidationError
        result.update({
            "packages_count": None,
            "package_quantity_snapshot": None,
            "price_per_package": None,
            "quantity_base": Decimal(quantity).quantize(MONEY_QUANTUM),
            "unit_price": Decimal(unit_price).quantize(MONEY_QUANTUM),
        })
        result["line_amount"] = (
            result["quantity_base"] * result["unit_price"]
        ).quantize(MONEY_QUANTUM)
    elif basis == "FIXED_AMOUNT":
        amount = values.get("line_amount")
        if amount is None:
            raise SupplierDocumentValidationError
        result.update({
            "packages_count": None,
            "package_quantity_snapshot": None,
            "package_unit_id_snapshot": None,
            "unit_name_snapshot": None,
            "quantity_base": None,
            "price_per_package": None,
            "unit_price": None,
            "line_amount": Decimal(amount).quantize(MONEY_QUANTUM),
        })
    else:
        raise SupplierDocumentValidationError
    name = (result.get("product_name_snapshot") or "").strip()
    if not name:
        raise SupplierDocumentValidationError
    result["product_name_snapshot"] = name
    return result


def create_document_line(
    session: Session, document_id: UUID, payload: SupplySupplierDocumentLineCreate,
    *, tenant_id: str,
) -> SupplySupplierDocumentRead:
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if document.status != "DRAFT":
        raise SupplierDocumentStateError
    values = _line_values(session, document, payload.model_dump())
    line = SupplySupplierDocumentLine(
        tenant_id=tenant_id,
        supplier_document_id=document.id,
        supplier_order_id=document.supplier_order_id,
        **values,
    )
    try:
        session.add(line)
        session.flush()
        session.expire(document, ["lines"])
        _recalculate_total(document)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierDocumentLinkError from error
    return read_document(session, document.id, tenant_id=tenant_id)


def update_document_line(
    session: Session, document_id: UUID, line_id: UUID,
    payload: SupplySupplierDocumentLineUpdate, *, tenant_id: str,
) -> SupplySupplierDocumentRead:
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if document.status != "DRAFT":
        raise SupplierDocumentStateError
    line = next((item for item in document.lines if item.id == line_id), None)
    if line is None:
        raise SupplierDocumentNotFoundError
    values = {
        "supplier_order_line_id": line.supplier_order_line_id,
        "supplier_confirmation_line_id": line.supplier_confirmation_line_id,
        "product_name_snapshot": line.product_name_snapshot,
        "pricing_basis": line.pricing_basis,
        "package_quantity_snapshot": line.package_quantity_snapshot,
        "package_unit_id_snapshot": line.package_unit_id_snapshot,
        "packages_count": line.packages_count,
        "quantity_base": line.quantity_base,
        "price_per_package": line.price_per_package,
        "unit_price": line.unit_price,
        "line_amount": line.line_amount,
        "supplier_line_reference": line.supplier_line_reference,
        "comment": line.comment,
    }
    values.update(payload.model_dump(exclude_unset=True))
    normalized = _line_values(session, document, values)
    for field, value in normalized.items():
        setattr(line, field, value)
    try:
        session.flush()
        _recalculate_total(document)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierDocumentLinkError from error
    return read_document(session, document.id, tenant_id=tenant_id)


def delete_document_line(
    session: Session, document_id: UUID, line_id: UUID, *, tenant_id: str,
) -> SupplySupplierDocumentRead:
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if document.status != "DRAFT":
        raise SupplierDocumentStateError
    line = next((item for item in document.lines if item.id == line_id), None)
    if line is None:
        raise SupplierDocumentNotFoundError
    session.delete(line)
    session.flush()
    session.expire(document, ["lines"])
    _recalculate_total(document)
    session.commit()
    return read_document(session, document.id, tenant_id=tenant_id)


def record_document(
    session: Session, document_id: UUID, *, tenant_id: str, user_id: int,
) -> SupplySupplierDocumentRead:
    document_ref = session.scalar(select(SupplySupplierDocument).where(
        SupplySupplierDocument.id == document_id,
        SupplySupplierDocument.tenant_id == tenant_id,
    ))
    if document_ref is None:
        raise SupplierDocumentNotFoundError
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == document_ref.supplier_order_id,
        SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierOrder))
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if order is None or order.status != "SENT" or document.status != "DRAFT":
        raise SupplierDocumentStateError
    latest = _latest_confirmation(session, order.id, tenant_id=tenant_id)
    if latest is not None and _confirmation_review_state(latest) == "REQUIRES_DECISION":
        raise SupplierDocumentReviewError
    _recalculate_total(document)
    if (
        document.document_number is None or document.document_date is None
        or not document.lines or document.total_amount <= 0
    ):
        raise SupplierDocumentValidationError
    if document.financial_role == "PAYABLE":
        if document.obligation_id is None:
            raise SupplierDocumentValidationError
        obligation = session.scalar(select(SupplySupplierObligation).where(
            SupplySupplierObligation.id == document.obligation_id,
            SupplySupplierObligation.tenant_id == tenant_id,
            SupplySupplierObligation.supplier_id == document.supplier_id,
            SupplySupplierObligation.supplier_order_id == document.supplier_order_id,
            SupplySupplierObligation.status == "ACTIVE",
        ).with_for_update(of=SupplySupplierObligation))
        if obligation is None:
            raise SupplierDocumentLinkError
    document.status = "RECORDED"
    document.recorded_by_user_id = user_id
    document.recorded_at = datetime.now(timezone.utc)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierDocumentConflictError from error
    return read_document(session, document.id, tenant_id=tenant_id)


def cancel_document(
    session: Session, document_id: UUID, *, tenant_id: str,
) -> SupplySupplierDocumentRead:
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if document.status != "DRAFT":
        raise SupplierDocumentStateError
    document.status = "CANCELLED"
    session.commit()
    return read_document(session, document.id, tenant_id=tenant_id)


def create_attachment(
    session: Session,
    document_id: UUID,
    *,
    tenant_id: str,
    user_id: int,
    original_filename: str,
    content_type: str,
    content: bytes,
    upload_dir: Path,
) -> SupplySupplierDocumentRead:
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if document.status == "CANCELLED":
        raise SupplierDocumentStateError
    if len(document.attachments) >= MAX_ATTACHMENT_COUNT:
        raise SupplierDocumentValidationError

    suffix = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }.get(content_type)
    if suffix is None or not content:
        raise SupplierDocumentValidationError

    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_root = upload_dir.resolve()
    stored_filename = f"{uuid4().hex}{suffix}"
    target = (upload_root / stored_filename).resolve()
    if target.parent != upload_root:
        raise SupplierDocumentValidationError

    try:
        target.write_bytes(content)
        session.add(SupplySupplierDocumentAttachment(
            tenant_id=tenant_id,
            supplier_document_id=document.id,
            original_filename=Path(original_filename).name[:255] or "document",
            stored_filename=stored_filename,
            content_type=content_type,
            size_bytes=len(content),
            created_by_user_id=user_id,
        ))
        session.commit()
    except Exception:
        session.rollback()
        target.unlink(missing_ok=True)
        raise
    return read_document(session, document.id, tenant_id=tenant_id)


def get_attachment(
    session: Session,
    document_id: UUID,
    attachment_id: UUID,
    *,
    tenant_id: str,
) -> SupplySupplierDocumentAttachment:
    attachment = session.scalar(select(SupplySupplierDocumentAttachment).where(
        SupplySupplierDocumentAttachment.id == attachment_id,
        SupplySupplierDocumentAttachment.supplier_document_id == document_id,
        SupplySupplierDocumentAttachment.tenant_id == tenant_id,
    ))
    if attachment is None:
        raise SupplierDocumentNotFoundError
    return attachment


def delete_attachment(
    session: Session,
    document_id: UUID,
    attachment_id: UUID,
    *,
    tenant_id: str,
    upload_dir: Path,
) -> SupplySupplierDocumentRead:
    document = _get_document(session, document_id, tenant_id=tenant_id, lock=True)
    if document.status == "CANCELLED":
        raise SupplierDocumentStateError
    attachment = next(
        (item for item in document.attachments if item.id == attachment_id), None,
    )
    if attachment is None:
        raise SupplierDocumentNotFoundError
    stored_filename = attachment.stored_filename
    session.delete(attachment)
    session.commit()

    upload_root = upload_dir.resolve()
    target = (upload_root / stored_filename).resolve()
    if target.parent == upload_root:
        target.unlink(missing_ok=True)
    return read_document(session, document.id, tenant_id=tenant_id)
