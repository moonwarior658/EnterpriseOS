from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.supply import (
    SupplySupplier,
    SupplySupplierAcceptance,
    SupplySupplierAcceptanceLine,
    SupplySupplierDocument,
    SupplySupplierObligation,
    SupplySupplierOrder,
    SupplySupplierPayment,
    SupplySupplierPaymentAllocation,
    SupplySupplierSettlementAdjustment,
)
from app.schemas.supplier_settlement import (
    SupplySupplierDocumentSettlementRead,
    SupplySupplierObligationRead,
    SupplySupplierPaymentAllocationCreate,
    SupplySupplierPaymentAllocationRead,
    SupplySupplierPaymentSettlementRead,
    SupplySupplierSettlementAdjustmentCreate,
    SupplySupplierSettlementAdjustmentRead,
    SupplySupplierSettlementMovement,
    SupplySupplierSettlementStatement,
    SupplySupplierSettlementSummary,
)


MONEY_QUANTUM = Decimal("0.000001")
ZERO = Decimal("0.000000")


class SupplierSettlementNotFoundError(LookupError):
    pass


class SupplierSettlementValidationError(ValueError):
    pass


class SupplierSettlementStateError(ValueError):
    pass


class SupplierSettlementConflictError(ValueError):
    pass


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(MONEY_QUANTUM)


def allocation_read(row: SupplySupplierPaymentAllocation) -> SupplySupplierPaymentAllocationRead:
    return SupplySupplierPaymentAllocationRead(
        id=row.id, supplier_id=row.supplier_id, payment_id=row.payment_id,
        supplier_document_id=row.supplier_document_id, obligation_id=row.obligation_id,
        amount=row.amount, status=row.status, created_by_user_id=row.created_by_user_id,
        created_at=row.created_at, reversed_amount=row.reversed_amount,
        reversed_by_user_id=row.reversed_by_user_id,
        reversed_at=row.reversed_at, reverse_reason=row.reverse_reason,
    )


def create_obligation(
    session: Session, order_id: UUID, *, tenant_id: str, supplier_id: UUID, user_id: int,
) -> SupplySupplierObligationRead:
    # This endpoint remains tenant/supplier/order scoped.
    from app.models.supply import SupplySupplierOrder
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
        SupplySupplierOrder.supplier_id == supplier_id,
    ))
    if order is None:
        raise SupplierSettlementNotFoundError
    row = SupplySupplierObligation(
        tenant_id=tenant_id, supplier_id=supplier_id, supplier_order_id=order_id,
        status="ACTIVE", created_by_user_id=user_id,
    )
    session.add(row); session.commit(); session.refresh(row)
    return SupplySupplierObligationRead.model_validate(row, from_attributes=True)


def list_obligations(
    session: Session, order_id: UUID, *, tenant_id: str,
) -> list[SupplySupplierObligationRead]:
    rows = session.scalars(select(SupplySupplierObligation).where(
        SupplySupplierObligation.tenant_id == tenant_id,
        SupplySupplierObligation.supplier_order_id == order_id,
        SupplySupplierObligation.status == "ACTIVE",
    ).order_by(SupplySupplierObligation.created_at)).all()
    return [SupplySupplierObligationRead.model_validate(row, from_attributes=True) for row in rows]


def _payment_amounts(session: Session, payment: SupplySupplierPayment, *, lock: bool = False):
    allocation_query = select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.tenant_id == payment.tenant_id,
        SupplySupplierPaymentAllocation.payment_id == payment.id,
    )
    refund_query = select(SupplySupplierSettlementAdjustment).where(
        SupplySupplierSettlementAdjustment.tenant_id == payment.tenant_id,
        SupplySupplierSettlementAdjustment.supplier_payment_id == payment.id,
        SupplySupplierSettlementAdjustment.type == "SUPPLIER_REFUND",
        SupplySupplierSettlementAdjustment.status == "RECORDED",
    )
    if lock:
        allocation_query = allocation_query.with_for_update(of=SupplySupplierPaymentAllocation)
        refund_query = refund_query.with_for_update(of=SupplySupplierSettlementAdjustment)
    allocations = list(session.scalars(allocation_query).all())
    refunds = list(session.scalars(refund_query).all())
    allocated = _money(sum((Decimal(row.amount) for row in allocations if row.status == "ACTIVE"), ZERO))
    refunded = _money(sum((Decimal(row.amount) for row in refunds), ZERO))
    effective = _money(Decimal(payment.amount) - refunded)
    return allocations, refunded, effective, allocated, _money(effective - allocated)


def create_allocation(
    session: Session, payload: SupplySupplierPaymentAllocationCreate,
    *, tenant_id: str, user_id: int,
) -> SupplySupplierPaymentAllocationRead:
    payment = session.scalar(select(SupplySupplierPayment).where(
        SupplySupplierPayment.id == payload.payment_id,
        SupplySupplierPayment.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierPayment))
    document = session.scalar(select(SupplySupplierDocument).where(
        SupplySupplierDocument.id == payload.supplier_document_id,
        SupplySupplierDocument.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierDocument))
    if payment is None or document is None:
        raise SupplierSettlementNotFoundError
    if payment.status != "RECORDED" or document.status != "RECORDED":
        raise SupplierSettlementStateError
    if (
        document.financial_role != "PAYABLE" or document.obligation_id is None
        or payment.supplier_id != document.supplier_id
    ):
        raise SupplierSettlementValidationError
    obligation = session.scalar(select(SupplySupplierObligation).where(
        SupplySupplierObligation.id == document.obligation_id,
        SupplySupplierObligation.tenant_id == tenant_id,
        SupplySupplierObligation.status == "ACTIVE",
    ).with_for_update(of=SupplySupplierObligation))
    if obligation is None:
        raise SupplierSettlementStateError
    _, _, _, _, available = _payment_amounts(session, payment, lock=True)
    amount = _money(payload.amount)
    if amount <= 0 or amount > available:
        raise SupplierSettlementValidationError
    row = SupplySupplierPaymentAllocation(
        tenant_id=tenant_id, supplier_id=payment.supplier_id, payment_id=payment.id,
        supplier_document_id=document.id, obligation_id=document.obligation_id,
        amount=amount, status="ACTIVE", created_by_user_id=user_id,
    )
    try:
        session.add(row); session.commit(); session.refresh(row)
    except IntegrityError as error:
        session.rollback(); raise SupplierSettlementConflictError from error
    return allocation_read(row)


def get_allocation(session: Session, allocation_id: UUID, *, tenant_id: str):
    row = session.scalar(select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.id == allocation_id,
        SupplySupplierPaymentAllocation.tenant_id == tenant_id,
    ))
    if row is None:
        raise SupplierSettlementNotFoundError
    return allocation_read(row)


def reverse_allocation(
    session: Session, allocation_id: UUID, *, reason: str, amount: Decimal | None = None,
    tenant_id: str, user_id: int,
) -> SupplySupplierPaymentAllocationRead:
    candidate = session.scalar(select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.id == allocation_id,
        SupplySupplierPaymentAllocation.tenant_id == tenant_id,
    ))
    if candidate is None:
        raise SupplierSettlementNotFoundError
    payment = session.scalar(select(SupplySupplierPayment).where(
        SupplySupplierPayment.id == candidate.payment_id,
        SupplySupplierPayment.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierPayment))
    if payment is None:
        raise SupplierSettlementNotFoundError
    row = session.scalar(select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.id == allocation_id,
        SupplySupplierPaymentAllocation.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierPaymentAllocation).execution_options(populate_existing=True))
    if row.status != "ACTIVE":
        raise SupplierSettlementStateError
    reversed_amount = _money(amount if amount is not None else row.amount)
    if reversed_amount <= 0 or reversed_amount > _money(row.amount):
        raise SupplierSettlementValidationError
    reason = reason.strip()
    if not reason:
        raise SupplierSettlementValidationError
    row.status = "REVERSED"
    row.reversed_amount = reversed_amount
    row.reversed_by_user_id = user_id
    row.reversed_at = datetime.now(timezone.utc)
    row.reverse_reason = reason
    if reversed_amount < _money(row.amount):
        session.flush()
        session.add(SupplySupplierPaymentAllocation(
            tenant_id=row.tenant_id, supplier_id=row.supplier_id,
            payment_id=row.payment_id, supplier_document_id=row.supplier_document_id,
            obligation_id=row.obligation_id,
            amount=_money(Decimal(row.amount) - reversed_amount), status="ACTIVE",
            created_by_user_id=user_id,
        ))
    try:
        session.commit(); session.refresh(row)
    except IntegrityError as error:
        session.rollback(); raise SupplierSettlementConflictError from error
    return allocation_read(row)


def create_adjustment(
    session: Session, payload: SupplySupplierSettlementAdjustmentCreate,
    *, tenant_id: str, user_id: int,
) -> SupplySupplierSettlementAdjustmentRead:
    supplier = session.scalar(select(SupplySupplier).where(
        SupplySupplier.id == payload.supplier_id, SupplySupplier.tenant_id == tenant_id,
    ))
    if supplier is None:
        raise SupplierSettlementNotFoundError
    payment_id = payload.supplier_payment_id
    if payload.type.value == "SUPPLIER_REFUND":
        payment = session.scalar(select(SupplySupplierPayment).where(
            SupplySupplierPayment.id == payment_id,
            SupplySupplierPayment.tenant_id == tenant_id,
            SupplySupplierPayment.supplier_id == payload.supplier_id,
        ).with_for_update(of=SupplySupplierPayment))
        if payment is None:
            raise SupplierSettlementNotFoundError
        if payment.status != "RECORDED":
            raise SupplierSettlementStateError
        _, _, _, _, available = _payment_amounts(session, payment, lock=True)
        if _money(payload.amount) > available:
            raise SupplierSettlementValidationError
    row = SupplySupplierSettlementAdjustment(
        tenant_id=tenant_id, supplier_id=payload.supplier_id,
        supplier_payment_id=payment_id, type=payload.type.value,
        direction=payload.direction.value if payload.direction else None,
        amount=_money(payload.amount), effective_date=payload.effective_date,
        comment=payload.comment, status="RECORDED", created_by_user_id=user_id,
    )
    try:
        session.add(row); session.commit(); session.refresh(row)
    except IntegrityError as error:
        session.rollback(); raise SupplierSettlementConflictError from error
    return SupplySupplierSettlementAdjustmentRead.model_validate(row, from_attributes=True)


def payment_settlement(session: Session, payment_id: UUID, *, tenant_id: str):
    payment = session.scalar(select(SupplySupplierPayment).where(
        SupplySupplierPayment.id == payment_id, SupplySupplierPayment.tenant_id == tenant_id,
    ))
    if payment is None:
        raise SupplierSettlementNotFoundError
    allocations, refunded, effective, allocated, available = _payment_amounts(session, payment)
    state = "FULLY_ALLOCATED" if available == 0 else ("PARTIALLY_ALLOCATED" if allocated else "UNALLOCATED")
    return SupplySupplierPaymentSettlementRead(
        payment_id=payment.id, amount=payment.amount, refunded_amount=refunded,
        effective_payment_amount=effective, allocated_amount=allocated,
        available_amount=available, allocation_state=state,
        allocations=[allocation_read(row) for row in allocations],
    )


def document_settlement(session: Session, document_id: UUID, *, tenant_id: str):
    document = session.scalar(select(SupplySupplierDocument).where(
        SupplySupplierDocument.id == document_id,
        SupplySupplierDocument.tenant_id == tenant_id,
    ))
    if document is None:
        raise SupplierSettlementNotFoundError
    allocations = list(session.scalars(select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.tenant_id == tenant_id,
        SupplySupplierPaymentAllocation.supplier_document_id == document_id,
    ).order_by(SupplySupplierPaymentAllocation.created_at)).all())
    settled = _money(sum((Decimal(row.amount) for row in allocations if row.status == "ACTIVE"), ZERO))
    remaining = _money(Decimal(document.total_amount) - settled)
    state = "UNPAID" if settled == 0 else (
        "PARTIALLY_PAID" if remaining > 0 else "PAID" if remaining == 0 else "OVERPAID"
    )
    return SupplySupplierDocumentSettlementRead(
        supplier_document_id=document.id, document_amount=document.total_amount,
        settled_amount=settled, remaining_amount=remaining, payment_state=state,
        allocations=[allocation_read(row) for row in allocations],
    )


def settlement_summary(session: Session, supplier_id: UUID, *, tenant_id: str):
    supplier = session.scalar(select(SupplySupplier).where(
        SupplySupplier.id == supplier_id, SupplySupplier.tenant_id == tenant_id,
    ))
    if supplier is None:
        raise SupplierSettlementNotFoundError
    documents = list(session.scalars(select(SupplySupplierDocument).join(
        SupplySupplierObligation,
        (SupplySupplierObligation.id == SupplySupplierDocument.obligation_id)
        & (SupplySupplierObligation.tenant_id == SupplySupplierDocument.tenant_id),
    ).where(
        SupplySupplierDocument.tenant_id == tenant_id,
        SupplySupplierDocument.supplier_id == supplier_id,
        SupplySupplierDocument.status == "RECORDED",
        SupplySupplierDocument.financial_role == "PAYABLE",
        SupplySupplierObligation.status == "ACTIVE",
    )).all())
    payments = list(session.scalars(select(SupplySupplierPayment).where(
        SupplySupplierPayment.tenant_id == tenant_id,
        SupplySupplierPayment.supplier_id == supplier_id,
        SupplySupplierPayment.status == "RECORDED",
    )).all())
    allocations = list(session.scalars(select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.tenant_id == tenant_id,
        SupplySupplierPaymentAllocation.supplier_id == supplier_id,
        SupplySupplierPaymentAllocation.status == "ACTIVE",
    )).all())
    adjustments = list(session.scalars(select(SupplySupplierSettlementAdjustment).where(
        SupplySupplierSettlementAdjustment.tenant_id == tenant_id,
        SupplySupplierSettlementAdjustment.supplier_id == supplier_id,
        SupplySupplierSettlementAdjustment.status == "RECORDED",
    )).all())
    documented = _money(sum((Decimal(row.total_amount) for row in documents), ZERO))
    payment_total = _money(sum((Decimal(row.amount) for row in payments), ZERO))
    allocated = _money(sum((Decimal(row.amount) for row in allocations), ZERO))
    refunds = _money(sum((Decimal(row.amount) for row in adjustments if row.type == "SUPPLIER_REFUND"), ZERO))
    correction = _money(sum((
        Decimal(row.amount) if row.direction == "INCREASE_DEBT" else -Decimal(row.amount)
        for row in adjustments if row.type == "MANUAL_CORRECTION"
    ), ZERO))
    running = _money(documented - payment_total + refunds + correction)
    allocations_by_document: dict[UUID, Decimal] = {}
    for row in allocations:
        allocations_by_document[row.supplier_document_id] = allocations_by_document.get(row.supplier_document_id, ZERO) + Decimal(row.amount)
    overdue = _money(sum((
        max(Decimal(row.total_amount) - allocations_by_document.get(row.id, ZERO), ZERO)
        for row in documents if row.payment_due_date is not None and row.payment_due_date < date.today()
    ), ZERO))
    unallocated_prepayment = ZERO
    for payment in payments:
        if payment.payment_type != "PREPAYMENT":
            continue
        refund = sum((Decimal(row.amount) for row in adjustments if row.type == "SUPPLIER_REFUND" and row.supplier_payment_id == payment.id), ZERO)
        payment_allocated = sum((Decimal(row.amount) for row in allocations if row.payment_id == payment.id), ZERO)
        unallocated_prepayment += max(Decimal(payment.amount) - refund - payment_allocated, ZERO)
    has_accepted_supply = False
    if unallocated_prepayment > 0 and not documents:
        has_accepted_supply = bool(session.scalar(select(func.count()).select_from(
            SupplySupplierAcceptance
        ).join(
            SupplySupplierOrder,
            (SupplySupplierOrder.id == SupplySupplierAcceptance.supplier_order_id)
            & (SupplySupplierOrder.tenant_id == SupplySupplierAcceptance.tenant_id),
        ).join(
            SupplySupplierAcceptanceLine,
            (SupplySupplierAcceptanceLine.acceptance_id == SupplySupplierAcceptance.id)
            & (SupplySupplierAcceptanceLine.tenant_id == SupplySupplierAcceptance.tenant_id),
        ).where(
            SupplySupplierAcceptance.tenant_id == tenant_id,
            SupplySupplierAcceptance.status == "RECORDED",
            SupplySupplierOrder.supplier_id == supplier_id,
            SupplySupplierAcceptanceLine.accepted_quantity > 0,
        )))
    doc_unsettled = any(Decimal(row.total_amount) - allocations_by_document.get(row.id, ZERO) > 0 for row in documents)
    return SupplySupplierSettlementSummary(
        supplier_id=supplier_id, documented_amount=documented,
        recorded_payment_amount=payment_total, allocated_payment_amount=allocated,
        unallocated_prepayment_amount=_money(unallocated_prepayment), refund_amount=refunds,
        adjustment_amount=correction, running_balance=running,
        current_debt=max(running, ZERO), overdue_debt=overdue,
        overpayment=max(-running, ZERO),
        payment_without_supply=bool(
            unallocated_prepayment > 0 and not documents and not has_accepted_supply
        ),
        supply_without_payment=doc_unsettled,
    )


def settlement_statement(
    session: Session, supplier_id: UUID, *, tenant_id: str, date_from: date, date_to: date,
) -> SupplySupplierSettlementStatement:
    if date_from > date_to:
        raise SupplierSettlementValidationError
    settlement_summary(session, supplier_id, tenant_id=tenant_id)
    facts: list[tuple[date, datetime, str, str, Decimal, Decimal, Decimal]] = []
    documents = session.scalars(select(SupplySupplierDocument).join(
        SupplySupplierObligation,
        (SupplySupplierObligation.id == SupplySupplierDocument.obligation_id)
        & (SupplySupplierObligation.tenant_id == SupplySupplierDocument.tenant_id),
    ).where(
        SupplySupplierDocument.tenant_id == tenant_id,
        SupplySupplierDocument.supplier_id == supplier_id,
        SupplySupplierDocument.status == "RECORDED",
        SupplySupplierDocument.financial_role == "PAYABLE",
        SupplySupplierObligation.status == "ACTIVE",
    )).all()
    for row in documents:
        when = row.document_date or row.recorded_at.date()
        facts.append((when, row.recorded_at, "PAYABLE_DOCUMENT", row.document_number or str(row.id), _money(row.total_amount), ZERO, _money(row.total_amount)))
    payments = session.scalars(select(SupplySupplierPayment).where(
        SupplySupplierPayment.tenant_id == tenant_id,
        SupplySupplierPayment.supplier_id == supplier_id,
        SupplySupplierPayment.status == "RECORDED",
    )).all()
    for row in payments:
        facts.append((row.payment_date, row.recorded_at, "PAYMENT", row.payment_order_number or str(row.id), ZERO, _money(row.amount), -_money(row.amount)))
    adjustments = session.scalars(select(SupplySupplierSettlementAdjustment).where(
        SupplySupplierSettlementAdjustment.tenant_id == tenant_id,
        SupplySupplierSettlementAdjustment.supplier_id == supplier_id,
    )).all()
    for row in adjustments:
        delta = _money(row.amount) if row.type == "SUPPLIER_REFUND" or row.direction == "INCREASE_DEBT" else -_money(row.amount)
        movement_type = (
            row.type if row.type == "SUPPLIER_REFUND"
            else f"MANUAL_CORRECTION_{row.direction}"
        )
        facts.append((row.effective_date, row.created_at, movement_type, str(row.id), max(delta, ZERO), max(-delta, ZERO), delta))
    allocations = session.scalars(select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.tenant_id == tenant_id,
        SupplySupplierPaymentAllocation.supplier_id == supplier_id,
    )).all()
    for row in allocations:
        facts.append((row.created_at.date(), row.created_at, "PAYMENT_ALLOCATION", str(row.id), ZERO, ZERO, ZERO))
        if row.status == "REVERSED":
            facts.append((row.reversed_at.date(), row.reversed_at, "PAYMENT_ALLOCATION_REVERSAL", str(row.id), ZERO, ZERO, ZERO))
    facts.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    opening = _money(sum((item[6] for item in facts if item[0] < date_from), ZERO))
    balance = opening
    movements = []
    for movement_date, created_at, kind, reference, debit, credit, delta in facts:
        if not (date_from <= movement_date <= date_to):
            continue
        balance = _money(balance + delta)
        movements.append(SupplySupplierSettlementMovement(
            date=movement_date, created_at=created_at, type=kind, reference=reference,
            debit=debit, credit=credit, balance_delta=delta, running_balance=balance,
        ))
    return SupplySupplierSettlementStatement(
        supplier_id=supplier_id, date_from=date_from, date_to=date_to,
        opening_balance=opening, movements=movements, closing_balance=balance,
    )
