from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.supply import (
    SupplyAcceptanceResolution,
    SupplyPurchaseAllocation,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
    SupplyProductSupplier,
    SupplySupplierAcceptance,
    SupplySupplierAcceptanceLine,
    SupplySupplierConfirmation,
    SupplySupplierConfirmationDeviation,
    SupplySupplierConfirmationLine,
    SupplySupplierDocument,
    SupplySupplierDocumentLine,
    SupplySupplierObligation,
    SupplySupplierOrder,
    SupplySupplierOrderLine,
    SupplySupplierPayment,
    SupplySupplierPaymentAllocation,
    SupplySupplierSettlementAdjustment,
    SupplySupplier,
)
from app.schemas.procurement_cash_flow import (
    SupplyProcurementCashFlowBreakdown,
    SupplyProcurementCashFlowException,
    SupplyProcurementCashFlowSummary,
)
from app.supply.supplier_settlements import settlement_summary


ZERO = Decimal("0")
MONEY = Decimal("0.000001")


class ProcurementCashFlowNotFoundError(LookupError):
    pass


class ProcurementCashFlowValidationError(ValueError):
    pass


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def _date(value: date | datetime | None, fallback: datetime) -> date:
    if value is None:
        return fallback.date()
    return value.date() if isinstance(value, datetime) else value


def _in_range(value: date, date_from: date | None, date_to: date | None) -> bool:
    return (date_from is None or value >= date_from) and (date_to is None or value <= date_to)


def _exception(code: str, requires_decision: bool, amount: Decimal | None = None):
    return SupplyProcurementCashFlowException(
        code=code, requires_decision=requires_decision,
        amount=_money(amount) if amount is not None else None,
    )


def _build(
    session: Session, *, tenant_id: str, scope: str,
    supplier_id: UUID | None = None, purchase_request_id: UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
) -> SupplyProcurementCashFlowSummary:
    if date_from and date_to and date_from > date_to:
        raise ProcurementCashFlowValidationError

    if supplier_id is not None:
        if session.scalar(select(SupplySupplier.id).where(
            SupplySupplier.id == supplier_id, SupplySupplier.tenant_id == tenant_id,
        )) is None:
            raise ProcurementCashFlowNotFoundError
        orders = list(session.scalars(select(SupplySupplierOrder).where(
            SupplySupplierOrder.tenant_id == tenant_id,
            SupplySupplierOrder.supplier_id == supplier_id,
        )).all())
    else:
        request = session.scalar(select(SupplyPurchaseRequest).where(
            SupplyPurchaseRequest.id == purchase_request_id,
            SupplyPurchaseRequest.tenant_id == tenant_id,
        ))
        if request is None:
            raise ProcurementCashFlowNotFoundError
        orders = list(session.scalars(select(SupplySupplierOrder).where(
            SupplySupplierOrder.tenant_id == tenant_id,
            SupplySupplierOrder.purchase_request_id == purchase_request_id,
        )).all())

    order_ids = {row.id for row in orders}
    supplier_ids = {row.supplier_id for row in orders if row.status != "CANCELLED"}
    order_lines = list(session.scalars(select(SupplySupplierOrderLine).where(
        SupplySupplierOrderLine.tenant_id == tenant_id,
        SupplySupplierOrderLine.supplier_order_id.in_(order_ids),
    )).all()) if order_ids else []

    if supplier_id is not None:
        allocations = list(session.scalars(select(SupplyPurchaseAllocation).join(
            SupplyProductSupplier,
            (SupplyProductSupplier.id == SupplyPurchaseAllocation.product_supplier_id)
            & (SupplyProductSupplier.tenant_id == SupplyPurchaseAllocation.tenant_id),
        ).where(
            SupplyPurchaseAllocation.tenant_id == tenant_id,
            SupplyProductSupplier.supplier_id == supplier_id,
        )).all())
    else:
        allocations = list(session.scalars(select(SupplyPurchaseAllocation).join(
            SupplyPurchaseRequestLine,
            (SupplyPurchaseRequestLine.id == SupplyPurchaseAllocation.purchase_request_line_id)
            & (SupplyPurchaseRequestLine.tenant_id == SupplyPurchaseAllocation.tenant_id),
        ).where(
            SupplyPurchaseAllocation.tenant_id == tenant_id,
            SupplyPurchaseRequestLine.purchase_request_id == purchase_request_id,
        )).all())
    allocations = [row for row in allocations if _in_range(row.created_at.date(), date_from, date_to)]
    planned = _money(sum((Decimal(row.planned_amount) for row in allocations), ZERO)) if allocations else None

    breakdown: list[SupplyProcurementCashFlowBreakdown] = []
    active_orders = []
    order_amounts: dict[UUID, Decimal] = {}
    for order in orders:
        business_date = _date(order.sent_at or order.confirmed_at, order.created_at)
        if order.status == "CANCELLED" or not _in_range(business_date, date_from, date_to):
            continue
        active_orders.append(order)
        amount = _money(sum((Decimal(line.planned_amount) for line in order_lines if line.supplier_order_id == order.id), ZERO))
        order_amounts[order.id] = amount
        breakdown.append(SupplyProcurementCashFlowBreakdown(
            entity_type="SUPPLIER_ORDER", entity_id=order.id, reference=order.number,
            amount=amount, business_date=business_date,
        ))
    ordered = _money(sum(order_amounts.values(), ZERO))
    draft = _money(sum((order_amounts[row.id] for row in active_orders if row.status == "DRAFT"), ZERO))
    ready = _money(sum((order_amounts[row.id] for row in active_orders if row.status == "READY"), ZERO))
    committed = _money(sum((order_amounts[row.id] for row in active_orders if row.status == "SENT"), ZERO))
    # Each metric uses its own business date. An order outside the selected
    # range must not hide a document, acceptance, or payment inside the range.
    chain_order_ids = {row.id for row in orders if row.status != "CANCELLED"}

    confirmations = list(session.scalars(select(SupplySupplierConfirmation).where(
        SupplySupplierConfirmation.tenant_id == tenant_id,
        SupplySupplierConfirmation.supplier_order_id.in_(chain_order_ids),
        SupplySupplierConfirmation.status == "RECORDED",
    )).all()) if chain_order_ids else []
    confirmation_ids = {row.id for row in confirmations}
    confirmation_lines = list(session.scalars(select(SupplySupplierConfirmationLine).where(
        SupplySupplierConfirmationLine.tenant_id == tenant_id,
        SupplySupplierConfirmationLine.confirmation_id.in_(confirmation_ids),
    )).all()) if confirmation_ids else []
    confirmed = ZERO
    for confirmation in confirmations:
        business_date = _date(confirmation.responded_at or confirmation.recorded_at, confirmation.created_at)
        if not _in_range(business_date, date_from, date_to):
            continue
        amount = _money(sum((
            Decimal(line.confirmed_planned_amount or ZERO) for line in confirmation_lines
            if line.confirmation_id == confirmation.id and line.response_status != "REJECTED"
        ), ZERO))
        confirmed += amount
        breakdown.append(SupplyProcurementCashFlowBreakdown(
            entity_type="SUPPLIER_CONFIRMATION", entity_id=confirmation.id,
            reference=f"revision-{confirmation.revision_number}", amount=amount,
            business_date=business_date,
        ))
    confirmed = _money(confirmed)

    documents = list(session.scalars(select(SupplySupplierDocument).where(
        SupplySupplierDocument.tenant_id == tenant_id,
        SupplySupplierDocument.supplier_order_id.in_(chain_order_ids),
        SupplySupplierDocument.status == "RECORDED",
        SupplySupplierDocument.financial_role == "PAYABLE",
    )).all()) if chain_order_ids else []
    ranged_documents = []
    for document in documents:
        business_date = _date(document.document_date, document.recorded_at or document.created_at)
        if not _in_range(business_date, date_from, date_to):
            continue
        ranged_documents.append(document)
        breakdown.append(SupplyProcurementCashFlowBreakdown(
            entity_type="SUPPLIER_DOCUMENT", entity_id=document.id,
            reference=document.document_number or str(document.id), amount=_money(document.total_amount),
            business_date=business_date,
        ))
    documented = _money(sum((Decimal(row.total_amount) for row in ranged_documents), ZERO))
    document_ids = {row.id for row in documents}
    active_obligation_ids = set(session.scalars(select(SupplySupplierObligation.id).where(
        SupplySupplierObligation.tenant_id == tenant_id,
        SupplySupplierObligation.supplier_order_id.in_(chain_order_ids),
        SupplySupplierObligation.status == "ACTIVE",
    )).all()) if chain_order_ids else set()
    current_documents = [row for row in documents if row.obligation_id in active_obligation_ids]

    acceptances = list(session.scalars(select(SupplySupplierAcceptance).where(
        SupplySupplierAcceptance.tenant_id == tenant_id,
        SupplySupplierAcceptance.supplier_order_id.in_(chain_order_ids),
        SupplySupplierAcceptance.status == "RECORDED",
    )).all()) if chain_order_ids else []
    ranged_acceptances = [row for row in acceptances if _in_range(
        _date(row.accepted_at or row.recorded_at, row.created_at), date_from, date_to
    )]
    acceptance_ids = {row.id for row in ranged_acceptances}
    acceptance_lines = list(session.scalars(select(SupplySupplierAcceptanceLine).where(
        SupplySupplierAcceptanceLine.tenant_id == tenant_id,
        SupplySupplierAcceptanceLine.acceptance_id.in_(acceptance_ids),
    )).all()) if acceptance_ids else []
    acceptance_line_ids = {row.id for row in acceptance_lines}
    resolutions = list(session.scalars(select(SupplyAcceptanceResolution).where(
        SupplyAcceptanceResolution.tenant_id == tenant_id,
        SupplyAcceptanceResolution.acceptance_line_id.in_(acceptance_line_ids),
        SupplyAcceptanceResolution.status == "RESOLVED",
        SupplyAcceptanceResolution.resolution_type == "REJECT_EXCESS",
    )).all()) if acceptance_line_ids else []
    rejected_excess = {row.acceptance_line_id: Decimal(row.quantity) for row in resolutions}
    linked_document_line_ids = {row.supplier_document_line_id for row in acceptance_lines if row.supplier_document_line_id}
    document_lines = list(session.scalars(select(SupplySupplierDocumentLine).where(
        SupplySupplierDocumentLine.tenant_id == tenant_id,
        SupplySupplierDocumentLine.id.in_(linked_document_line_ids),
    )).all()) if linked_document_line_ids else []
    document_line_map = {row.id: row for row in document_lines}
    accepted_total = ZERO
    accepted_unavailable = False
    acceptance_amounts: dict[UUID, Decimal] = {}
    for line in acceptance_lines:
        source_line = document_line_map.get(line.supplier_document_line_id)
        if source_line is not None and source_line.pricing_basis == "FIXED_AMOUNT":
            continue
        if line.product_id is None or line.unit_id is None:
            continue
        quantity = max(Decimal(line.accepted_quantity) - rejected_excess.get(line.id, ZERO), ZERO)
        if quantity == 0:
            continue
        if line.accepted_unit_price is None:
            accepted_unavailable = True
            continue
        amount = _money(quantity * Decimal(line.accepted_unit_price))
        accepted_total += amount
        acceptance_amounts[line.acceptance_id] = acceptance_amounts.get(line.acceptance_id, ZERO) + amount
    for acceptance in ranged_acceptances:
        amount = _money(acceptance_amounts.get(acceptance.id, ZERO))
        breakdown.append(SupplyProcurementCashFlowBreakdown(
            entity_type="SUPPLIER_ACCEPTANCE", entity_id=acceptance.id,
            reference=str(acceptance.id), amount=amount,
            business_date=_date(acceptance.accepted_at or acceptance.recorded_at, acceptance.created_at),
        ))
    accepted = None if accepted_unavailable else _money(accepted_total)

    all_payments = list(session.scalars(select(SupplySupplierPayment).where(
        SupplySupplierPayment.tenant_id == tenant_id,
        SupplySupplierPayment.status == "RECORDED",
        *([SupplySupplierPayment.supplier_id == supplier_id] if supplier_id else [SupplySupplierPayment.supplier_id.in_(supplier_ids)]),
    )).all()) if (supplier_id or supplier_ids) else []
    all_adjustments = list(session.scalars(select(SupplySupplierSettlementAdjustment).where(
        SupplySupplierSettlementAdjustment.tenant_id == tenant_id,
        SupplySupplierSettlementAdjustment.status == "RECORDED",
        *([SupplySupplierSettlementAdjustment.supplier_id == supplier_id] if supplier_id else [SupplySupplierSettlementAdjustment.supplier_id.in_(supplier_ids)]),
    )).all()) if (supplier_id or supplier_ids) else []
    allocations_for_payments = list(session.scalars(select(SupplySupplierPaymentAllocation).where(
        SupplySupplierPaymentAllocation.tenant_id == tenant_id,
        SupplySupplierPaymentAllocation.payment_id.in_({row.id for row in all_payments}),
        SupplySupplierPaymentAllocation.status == "ACTIVE",
    )).all()) if all_payments else []

    included_payments: dict[UUID, Decimal] = {}
    ambiguous_payment_ids: set[UUID] = set()
    for payment in all_payments:
        if not _in_range(payment.payment_date, date_from, date_to):
            continue
        if supplier_id is not None:
            included_payments[payment.id] = Decimal(payment.amount)
        elif payment.supplier_order_id in chain_order_ids or payment.supplier_document_id in document_ids:
            included_payments[payment.id] = Decimal(payment.amount)
        else:
            payment_allocations = [row for row in allocations_for_payments if row.payment_id == payment.id]
            pr_allocated = sum((Decimal(row.amount) for row in payment_allocations if row.supplier_document_id in document_ids), ZERO)
            other_allocated = sum((Decimal(row.amount) for row in payment_allocations if row.supplier_document_id not in document_ids), ZERO)
            if pr_allocated:
                included_payments[payment.id] = pr_allocated
                if other_allocated:
                    ambiguous_payment_ids.add(payment.id)
    gross_paid = _money(sum(included_payments.values(), ZERO))
    refunds = ZERO
    manual_correction = ZERO
    for adjustment in all_adjustments:
        if not _in_range(adjustment.effective_date, date_from, date_to):
            continue
        if adjustment.type == "SUPPLIER_REFUND":
            if adjustment.supplier_payment_id in included_payments and adjustment.supplier_payment_id not in ambiguous_payment_ids:
                refunds += Decimal(adjustment.amount)
        elif supplier_id is not None:
            manual_correction += Decimal(adjustment.amount) if adjustment.direction == "INCREASE_DEBT" else -Decimal(adjustment.amount)
    refunds = _money(refunds)
    net_paid = _money(gross_paid - refunds)
    for payment in all_payments:
        if payment.id in included_payments:
            breakdown.append(SupplyProcurementCashFlowBreakdown(
                entity_type="SUPPLIER_PAYMENT", entity_id=payment.id,
                reference=payment.payment_order_number or str(payment.id),
                amount=_money(included_payments[payment.id]), business_date=payment.payment_date,
            ))

    exceptions = []
    allocated_by_document: dict[UUID, Decimal] = {}
    for row in allocations_for_payments:
        if row.supplier_document_id in document_ids:
            allocated_by_document[row.supplier_document_id] = (
                allocated_by_document.get(row.supplier_document_id, ZERO) + Decimal(row.amount)
            )
    document_overpaid = _money(sum((
        max(allocated_by_document.get(row.id, ZERO) - Decimal(row.total_amount), ZERO)
        for row in documents
    ), ZERO))
    if supplier_id is not None:
        settlement = settlement_summary(session, supplier_id, tenant_id=tenant_id)
        current_debt = settlement.current_debt
        overdue = settlement.overdue_debt
        unallocated = settlement.unallocated_prepayment_amount
        credit = settlement.overpayment
        if settlement.payment_without_supply:
            exceptions.append(_exception("PAYMENT_WITHOUT_SUPPLY", True, unallocated))
        if settlement.supply_without_payment and not overdue:
            exceptions.append(_exception("SUPPLY_WITHOUT_PAYMENT", False, current_debt))
    else:
        overdue = _money(sum((
            max(Decimal(row.total_amount) - allocated_by_document.get(row.id, ZERO), ZERO)
            for row in current_documents if row.payment_due_date and row.payment_due_date < date.today()
        ), ZERO))
        balance = _money(sum((Decimal(row.total_amount) for row in current_documents), ZERO) - gross_paid + refunds)
        current_debt = max(balance, ZERO)
        credit = max(-balance, ZERO)
        unallocated = _money(sum((
            max(included_payments.get(row.id, ZERO) - sum((Decimal(a.amount) for a in allocations_for_payments if a.payment_id == row.id and a.supplier_document_id in document_ids), ZERO), ZERO)
            for row in all_payments if row.id in included_payments and row.payment_type == "PREPAYMENT"
        ), ZERO))
        if ambiguous_payment_ids:
            exceptions.append(_exception("AMBIGUOUS_FINANCIAL_LINK", True))

    if overdue > 0:
        exceptions.append(_exception("OVERDUE_PAYMENT", True, overdue))
    if credit > 0 or document_overpaid > 0:
        exceptions.append(_exception("OVERPAYMENT", True, max(credit, document_overpaid)))
    if unallocated > 0:
        exceptions.append(_exception("UNALLOCATED_PREPAYMENT", False, unallocated))
    if manual_correction:
        exceptions.append(_exception("MANUAL_CORRECTION_PRESENT", True, abs(manual_correction)))

    deviations = list(session.scalars(select(SupplySupplierConfirmationDeviation).where(
        SupplySupplierConfirmationDeviation.tenant_id == tenant_id,
        SupplySupplierConfirmationDeviation.confirmation_id.in_(confirmation_ids),
        SupplySupplierConfirmationDeviation.deviation_type == "PRICE_CHANGED",
        SupplySupplierConfirmationDeviation.status == "OPEN",
        SupplySupplierConfirmationDeviation.requires_decision.is_(True),
    )).all()) if confirmation_ids else []
    if deviations:
        exceptions.append(_exception("OPEN_PRICE_DEVIATION", True))

    return SupplyProcurementCashFlowSummary(
        scope=scope, supplier_id=supplier_id, purchase_request_id=purchase_request_id,
        date_from=date_from, date_to=date_to,
        planned_amount=planned, planned_amount_status="AVAILABLE" if planned is not None else "UNAVAILABLE",
        ordered_amount=ordered, draft_order_amount=draft, ready_order_amount=ready,
        committed_order_amount=committed, confirmed_amount=confirmed,
        payable_documented_amount=documented, accepted_goods_amount=accepted,
        accepted_goods_amount_status="UNAVAILABLE" if accepted_unavailable else "AVAILABLE",
        gross_paid_amount=gross_paid, supplier_refund_amount=refunds, net_paid_amount=net_paid,
        current_debt_amount=_money(current_debt), overdue_debt_amount=_money(overdue),
        unallocated_prepayment_amount=_money(unallocated), supplier_credit_amount=_money(credit),
        ordered_vs_confirmed_amount=_money(confirmed - ordered),
        confirmed_vs_documented_amount=_money(documented - confirmed),
        documented_vs_accepted_goods_amount=None if accepted is None else _money(accepted - documented),
        price_deviation_open_count=len(deviations), financial_exception_count=len(exceptions),
        financial_exceptions=exceptions,
        requires_decision=any(row.requires_decision for row in exceptions),
        decision_reason_codes=[row.code for row in exceptions if row.requires_decision],
        breakdown=breakdown,
        date_semantics={
            "planned_amount": "allocation.created_at",
            "ordered_amount": "sent_at; confirmed_at for READY; created_at for DRAFT",
            "confirmed_amount": "responded_at or recorded_at",
            "payable_documented_amount": "document_date",
            "accepted_goods_amount": "accepted_at or recorded_at",
            "paid_amount": "payment_date",
            "supplier_refund_amount": "adjustment.effective_date",
            "balance_and_overdue": "current canonical or traceable settlement snapshot; not limited by date range",
        },
    )


def supplier_cash_flow(session: Session, supplier_id: UUID, *, tenant_id: str, date_from: date | None, date_to: date | None):
    return _build(session, tenant_id=tenant_id, scope="SUPPLIER", supplier_id=supplier_id, date_from=date_from, date_to=date_to)


def purchase_request_cash_flow(session: Session, request_id: UUID, *, tenant_id: str):
    return _build(session, tenant_id=tenant_id, scope="PURCHASE_REQUEST", purchase_request_id=request_id)
