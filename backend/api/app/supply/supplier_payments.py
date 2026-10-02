from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.audit.service import record_audit_event
from app.core.action_context import ActionContext
from app.models.supply import (
    SupplySupplier,
    SupplySupplierDocument,
    SupplySupplierOrder,
    SupplySupplierPayment,
    SupplySupplierPaymentAllocation,
    SupplySupplierSettlementAdjustment,
)
from app.models.user import User
from app.schemas.supplier_payment import (
    SupplySupplierOrderPrepaymentSummary,
    SupplySupplierPaymentCreate,
    SupplySupplierPaymentRead,
    SupplySupplierPaymentUpdate,
)


MONEY_QUANTUM = Decimal("0.000001")


class SupplierPaymentNotFoundError(LookupError):
    pass


class SupplierPaymentStateError(ValueError):
    pass


class SupplierPaymentValidationError(ValueError):
    pass


class SupplierPaymentLinkError(ValueError):
    pass


class SupplierPaymentConflictError(ValueError):
    pass


def _options():
    return (
        joinedload(SupplySupplierPayment.supplier),
        joinedload(SupplySupplierPayment.supplier_document),
        joinedload(SupplySupplierPayment.supplier_order),
        selectinload(SupplySupplierPayment.allocations),
        selectinload(SupplySupplierPayment.adjustments),
    )


def _get_payment(
    session: Session, payment_id: UUID, *, tenant_id: str, lock: bool = False,
) -> SupplySupplierPayment:
    statement = select(SupplySupplierPayment).where(
        SupplySupplierPayment.id == payment_id,
        SupplySupplierPayment.tenant_id == tenant_id,
    )
    if lock:
        statement = statement.with_for_update(of=SupplySupplierPayment)
    payment = session.scalar(statement.options(*_options()).execution_options(populate_existing=True))
    if payment is None:
        raise SupplierPaymentNotFoundError
    return payment


def payment_read(session: Session, payment: SupplySupplierPayment) -> SupplySupplierPaymentRead:
    recorder_name = None
    if payment.recorded_by_user_id is not None:
        recorder_name = session.scalar(select(User.display_name).where(
            User.id == payment.recorded_by_user_id,
            User.tenant_id == payment.tenant_id,
        ))
    refunded = Decimal(session.scalar(select(func.coalesce(func.sum(
        SupplySupplierSettlementAdjustment.amount
    ), 0)).where(
        SupplySupplierSettlementAdjustment.tenant_id == payment.tenant_id,
        SupplySupplierSettlementAdjustment.supplier_payment_id == payment.id,
        SupplySupplierSettlementAdjustment.type == "SUPPLIER_REFUND",
        SupplySupplierSettlementAdjustment.status == "RECORDED",
    )) or 0).quantize(MONEY_QUANTUM)
    allocated = sum(
        (Decimal(item.amount) for item in payment.allocations if item.status == "ACTIVE"), Decimal("0")
    ).quantize(MONEY_QUANTUM)
    effective = (Decimal(payment.amount) - refunded).quantize(MONEY_QUANTUM)
    available = (effective - allocated).quantize(MONEY_QUANTUM)
    allocation_state = "FULLY_ALLOCATED" if available == 0 else (
        "PARTIALLY_ALLOCATED" if allocated > 0 else "UNALLOCATED"
    )
    return SupplySupplierPaymentRead(
        id=payment.id,
        supplier_id=payment.supplier_id,
        supplier_display_name=payment.supplier.display_name,
        supplier_document_id=payment.supplier_document_id,
        supplier_document_number=(
            payment.supplier_document.document_number if payment.supplier_document else None
        ),
        supplier_order_id=payment.supplier_order_id,
        supplier_order_number=payment.supplier_order.number if payment.supplier_order else None,
        payment_type=payment.payment_type,
        status=payment.status,
        payment_date=payment.payment_date,
        amount=payment.amount,
        refunded_amount=refunded,
        effective_payment_amount=effective,
        allocated_amount=allocated,
        available_amount=available,
        allocation_state=allocation_state,
        currency=payment.currency,
        payment_order_number=payment.payment_order_number,
        payment_order_date=payment.payment_order_date,
        comment=payment.comment,
        recorded_by_user_id=payment.recorded_by_user_id,
        recorded_by_display_name=recorder_name,
        recorded_at=payment.recorded_at,
        created_by_user_id=payment.created_by_user_id,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
    )


def _validate_links(
    session: Session, *, tenant_id: str, supplier_id: UUID,
    payment_type: str, supplier_document_id: UUID | None,
    supplier_order_id: UUID | None, lock_order: bool = False,
) -> tuple[SupplySupplierDocument | None, SupplySupplierOrder | None]:
    supplier = session.scalar(select(SupplySupplier).where(
        SupplySupplier.id == supplier_id,
        SupplySupplier.tenant_id == tenant_id,
    ))
    if supplier is None:
        raise SupplierPaymentLinkError

    document = None
    if supplier_document_id is not None:
        document = session.scalar(select(SupplySupplierDocument).where(
            SupplySupplierDocument.id == supplier_document_id,
            SupplySupplierDocument.tenant_id == tenant_id,
        ))
        if (
            document is None or document.status != "RECORDED"
            or document.financial_role != "PAYABLE" or document.obligation_id is None
            or document.supplier_id != supplier_id or document.currency != "RUB"
        ):
            raise SupplierPaymentLinkError
        if supplier_order_id is not None and supplier_order_id != document.supplier_order_id:
            raise SupplierPaymentLinkError
        supplier_order_id = document.supplier_order_id
    elif payment_type == "POSTPAYMENT":
        raise SupplierPaymentValidationError

    order = None
    if supplier_order_id is not None:
        statement = select(SupplySupplierOrder).where(
            SupplySupplierOrder.id == supplier_order_id,
            SupplySupplierOrder.tenant_id == tenant_id,
        )
        if lock_order:
            statement = statement.with_for_update(of=SupplySupplierOrder)
        order = session.scalar(statement)
        if order is None or order.supplier_id != supplier_id or order.currency != "RUB":
            raise SupplierPaymentLinkError
        if order.status not in {"READY", "SENT"}:
            raise SupplierPaymentStateError("Заказ недоступен для оплаты")
        recorded = Decimal(session.scalar(select(func.coalesce(func.sum(SupplySupplierPayment.amount), 0)).where(
            SupplySupplierPayment.tenant_id == tenant_id,
            SupplySupplierPayment.supplier_order_id == order.id,
            SupplySupplierPayment.status == "RECORDED",
        )) or 0)
        if recorded >= Decimal(order.total_amount):
            raise SupplierPaymentStateError("Заказ уже оплачен")
    return document, order


def available_orders(session: Session, *, tenant_id: str, supplier_id: UUID) -> list[dict]:
    orders = session.scalars(select(SupplySupplierOrder).where(
        SupplySupplierOrder.tenant_id == tenant_id,
        SupplySupplierOrder.supplier_id == supplier_id,
        SupplySupplierOrder.status.in_(("READY", "SENT")),
    ).order_by(SupplySupplierOrder.number)).all()
    result = []
    for order in orders:
        recorded = Decimal(session.scalar(select(func.coalesce(func.sum(SupplySupplierPayment.amount), 0)).where(
            SupplySupplierPayment.tenant_id == tenant_id,
            SupplySupplierPayment.supplier_order_id == order.id,
            SupplySupplierPayment.status == "RECORDED",
        )) or 0)
        remaining = Decimal(order.total_amount) - recorded
        if remaining > 0:
            result.append({"id": order.id, "number": order.number, "remaining_amount": remaining})
    return result


def _validate_order_fields(number: str | None, order_date) -> None:
    if (number is None) != (order_date is None):
        raise SupplierPaymentValidationError


def create_payment(
    session: Session, payload: SupplySupplierPaymentCreate, *, tenant_id: str, user_id: int,
    audit_context: ActionContext | None = None, actor_user: User | None = None,
) -> SupplySupplierPaymentRead:
    document, order = _validate_links(
        session,
        tenant_id=tenant_id,
        supplier_id=payload.supplier_id,
        payment_type=payload.payment_type.value,
        supplier_document_id=payload.supplier_document_id,
        supplier_order_id=payload.supplier_order_id,
    )
    payment = SupplySupplierPayment(
        tenant_id=tenant_id,
        supplier_id=payload.supplier_id,
        supplier_document_id=document.id if document else None,
        supplier_order_id=(order.id if order else None),
        payment_type=payload.payment_type.value,
        status="DRAFT",
        payment_date=payload.payment_date,
        amount=Decimal(payload.amount).quantize(MONEY_QUANTUM),
        currency="RUB",
        payment_order_number=payload.payment_order_number,
        payment_order_date=payload.payment_order_date,
        comment=payload.comment,
        created_by_user_id=user_id,
    )
    try:
        session.add(payment)
        session.flush()
        if audit_context is not None and actor_user is not None:
            record_audit_event(
                session, tenant_id=tenant_id, event_type="SUPPLIER_PAYMENT_CREATED",
                entity_type="SupplySupplierPayment", entity_id=payment.id, operation="CREATE",
                context=audit_context, actor_user=actor_user, before={},
                after={"supplier_id": payment.supplier_id, "amount": payment.amount, "status": payment.status},
            )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierPaymentConflictError from error
    return read_payment(session, payment.id, tenant_id=tenant_id)


def read_payment(
    session: Session, payment_id: UUID, *, tenant_id: str,
) -> SupplySupplierPaymentRead:
    return payment_read(session, _get_payment(session, payment_id, tenant_id=tenant_id))


def list_payments(
    session: Session, *, tenant_id: str, supplier_id: UUID | None = None,
    status: str | None = None, payment_type: str | None = None,
    date_from=None, date_to=None, payment_order_number: str | None = None,
    limit: int = 50, offset: int = 0,
) -> tuple[list[SupplySupplierPaymentRead], int]:
    filters = [SupplySupplierPayment.tenant_id == tenant_id]
    if supplier_id is not None:
        filters.append(SupplySupplierPayment.supplier_id == supplier_id)
    if status is not None:
        filters.append(SupplySupplierPayment.status == status)
    if payment_type is not None:
        filters.append(SupplySupplierPayment.payment_type == payment_type)
    if date_from is not None:
        filters.append(SupplySupplierPayment.payment_date >= date_from)
    if date_to is not None:
        filters.append(SupplySupplierPayment.payment_date <= date_to)
    if payment_order_number:
        filters.append(SupplySupplierPayment.payment_order_number.ilike(
            f"%{payment_order_number.strip()}%"
        ))
    total = int(session.scalar(
        select(func.count()).select_from(SupplySupplierPayment).where(*filters)
    ) or 0)
    rows = session.scalars(
        select(SupplySupplierPayment).where(*filters).options(*_options())
        .order_by(SupplySupplierPayment.payment_date.desc(), SupplySupplierPayment.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return [payment_read(session, row) for row in rows], total


def update_payment(
    session: Session, payment_id: UUID, payload: SupplySupplierPaymentUpdate, *, tenant_id: str,
    audit_context: ActionContext | None = None, actor_user: User | None = None,
) -> SupplySupplierPaymentRead:
    payment = _get_payment(session, payment_id, tenant_id=tenant_id, lock=True)
    if payment.status != "DRAFT":
        raise SupplierPaymentStateError
    values = {
        "supplier_document_id": payment.supplier_document_id,
        "supplier_order_id": payment.supplier_order_id,
        "payment_date": payment.payment_date,
        "amount": payment.amount,
        "payment_order_number": payment.payment_order_number,
        "payment_order_date": payment.payment_order_date,
        "comment": payment.comment,
    }
    values.update(payload.model_dump(exclude_unset=True, exclude={"reason"}))
    if values["payment_date"] is None or values["amount"] is None:
        raise SupplierPaymentValidationError
    _validate_order_fields(values["payment_order_number"], values["payment_order_date"])
    document, order = _validate_links(
        session,
        tenant_id=tenant_id,
        supplier_id=payment.supplier_id,
        payment_type=payment.payment_type,
        supplier_document_id=values["supplier_document_id"],
        supplier_order_id=values["supplier_order_id"],
    )
    values["supplier_document_id"] = document.id if document else None
    values["supplier_order_id"] = order.id if order else None
    values["amount"] = Decimal(values["amount"]).quantize(MONEY_QUANTUM)
    before = {field: getattr(payment, field) for field in values}
    for field, value in values.items():
        setattr(payment, field, value)
    try:
        if audit_context is not None and actor_user is not None:
            session.flush()
            record_audit_event(
                session, tenant_id=tenant_id, event_type="SUPPLIER_PAYMENT_UPDATED",
                entity_type="SupplySupplierPayment", entity_id=payment.id, operation="UPDATE",
                context=audit_context, actor_user=actor_user, before=before,
                after={field: getattr(payment, field) for field in values}, reason=payload.reason,
            )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierPaymentConflictError from error
    return read_payment(session, payment_id, tenant_id=tenant_id)


def record_payment(
    session: Session, payment_id: UUID, *, tenant_id: str, user_id: int,
    audit_context: ActionContext | None = None, actor_user: User | None = None,
    reason: str | None = None,
) -> SupplySupplierPaymentRead:
    payment = _get_payment(session, payment_id, tenant_id=tenant_id, lock=True)
    if payment.status != "DRAFT":
        raise SupplierPaymentStateError
    _validate_order_fields(payment.payment_order_number, payment.payment_order_date)
    document, order = _validate_links(
        session,
        tenant_id=tenant_id,
        supplier_id=payment.supplier_id,
        payment_type=payment.payment_type,
        supplier_document_id=payment.supplier_document_id,
        supplier_order_id=payment.supplier_order_id, lock_order=True,
    )
    if order is not None:
        recorded = Decimal(session.scalar(select(func.coalesce(func.sum(SupplySupplierPayment.amount), 0)).where(
            SupplySupplierPayment.tenant_id == tenant_id,
            SupplySupplierPayment.supplier_order_id == order.id,
            SupplySupplierPayment.status == "RECORDED",
        )) or 0)
        if recorded + Decimal(payment.amount) > Decimal(order.total_amount):
            raise SupplierPaymentValidationError("Сумма превышает остаток по заказу")
    payment.supplier_document_id = document.id if document else None
    payment.supplier_order_id = order.id if order else None
    if payment.amount <= 0 or payment.currency != "RUB":
        raise SupplierPaymentValidationError
    payment.status = "RECORDED"
    payment.recorded_by_user_id = user_id
    payment.recorded_at = datetime.now(timezone.utc)
    if document is not None:
        session.add(SupplySupplierPaymentAllocation(
            tenant_id=tenant_id, supplier_id=payment.supplier_id,
            payment_id=payment.id, supplier_document_id=document.id,
            obligation_id=document.obligation_id, amount=payment.amount,
            status="ACTIVE", created_by_user_id=user_id,
        ))
    try:
        if audit_context is not None and actor_user is not None:
            session.flush()
            record_audit_event(
                session, tenant_id=tenant_id, event_type="SUPPLIER_PAYMENT_RECORDED",
                entity_type="SupplySupplierPayment", entity_id=payment.id, operation="RECORD",
                context=audit_context, actor_user=actor_user,
                before={"status": "DRAFT"}, after={"status": payment.status}, reason=reason,
            )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierPaymentConflictError from error
    return read_payment(session, payment_id, tenant_id=tenant_id)


def cancel_payment(
    session: Session, payment_id: UUID, *, tenant_id: str,
    audit_context: ActionContext | None = None, actor_user: User | None = None,
    reason: str | None = None,
) -> SupplySupplierPaymentRead:
    payment = _get_payment(session, payment_id, tenant_id=tenant_id, lock=True)
    if payment.status != "DRAFT":
        raise SupplierPaymentStateError
    payment.status = "CANCELLED"
    if audit_context is not None and actor_user is not None:
        session.flush()
        record_audit_event(
            session, tenant_id=tenant_id, event_type="SUPPLIER_PAYMENT_CANCELLED",
            entity_type="SupplySupplierPayment", entity_id=payment.id, operation="CANCEL",
            context=audit_context, actor_user=actor_user,
            before={"status": "DRAFT"}, after={"status": payment.status}, reason=reason,
        )
    session.commit()
    return read_payment(session, payment_id, tenant_id=tenant_id)


def order_prepayment_summary(
    payments: list[SupplySupplierPayment],
) -> SupplySupplierOrderPrepaymentSummary:
    recorded = [
        item for item in payments
        if item.status == "RECORDED" and item.payment_type == "PREPAYMENT"
    ]
    unallocated = []
    unallocated_amount = Decimal("0")
    for item in recorded:
        allocated = sum(
            (Decimal(row.amount) for row in item.allocations if row.status == "ACTIVE"), Decimal("0")
        )
        refunded = sum(
            (
                Decimal(row.amount) for row in item.adjustments
                if row.status == "RECORDED" and row.type == "SUPPLIER_REFUND"
            ),
            Decimal("0"),
        )
        available = Decimal(item.amount) - refunded - allocated
        if available > 0:
            unallocated.append(item)
            unallocated_amount += available
    return SupplySupplierOrderPrepaymentSummary(
        prepayment_total=sum(
            (
                Decimal(item.amount) - sum(
                    (
                        Decimal(row.amount) for row in item.adjustments
                        if row.status == "RECORDED" and row.type == "SUPPLIER_REFUND"
                    ),
                    Decimal("0"),
                )
                for item in recorded
            ),
            Decimal("0"),
        ),
        unallocated_prepayment_count=len(unallocated),
        unallocated_prepayment_amount=unallocated_amount,
    )
