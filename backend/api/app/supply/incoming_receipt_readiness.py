from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from enum import StrEnum
from uuid import UUID

from app.integrations.iiko.schemas import (
    IikoIncomingInvoicePreviewDto,
    IikoIncomingInvoicePreviewItemDto,
)


MONEY_QUANTUM = Decimal("0.000001")


class ReceiptLineStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    EXCLUDED = "EXCLUDED"


class ReceiptLineClassification(StrEnum):
    BASE_UNIT_SAFE = "BASE_UNIT_SAFE"
    PACKAGE_CONVERSION_REQUIRED = "PACKAGE_CONVERSION_REQUIRED"
    UNMAPPED_UNIT = "UNMAPPED_UNIT"
    UNKNOWN_UNIT_CONTRACT = "UNKNOWN_UNIT_CONTRACT"
    FIXED_AMOUNT_SERVICE = "FIXED_AMOUNT_SERVICE"


class ReceiptReadinessReason(StrEnum):
    SUPPLIER_MAPPING_MISSING = "SUPPLIER_MAPPING_MISSING"
    SUPPLIER_MAPPING_STALE = "SUPPLIER_MAPPING_STALE"
    STORE_MAPPING_MISSING = "STORE_MAPPING_MISSING"
    PRODUCT_MAPPING_MISSING = "PRODUCT_MAPPING_MISSING"
    UNIT_MAPPING_MISSING = "UNIT_MAPPING_MISSING"
    PRODUCT_MAIN_UNIT_MISSING = "PRODUCT_MAIN_UNIT_MISSING"
    UNIT_NOT_MAIN = "UNIT_NOT_MAIN"
    PACKAGE_CONVERSION_REQUIRED = "PACKAGE_CONVERSION_REQUIRED"
    HISTORICAL_PRICE_MISSING = "HISTORICAL_PRICE_MISSING"
    FIXED_AMOUNT_NOT_PHYSICAL = "FIXED_AMOUNT_NOT_PHYSICAL"
    SUM_ALLOCATION_AMBIGUOUS = "SUM_ALLOCATION_AMBIGUOUS"
    PRIOR_ACCOUNTING_FACTS_REQUIRED = "PRIOR_ACCOUNTING_FACTS_REQUIRED"
    EXCESS_PRICE_SOURCE_MISSING = "EXCESS_PRICE_SOURCE_MISSING"
    VAT_MISSING = "VAT_MISSING"
    UNRESOLVED_EXCESS = "UNRESOLVED_EXCESS"
    NO_RECEIPT_ELIGIBLE_QUANTITY = "NO_RECEIPT_ELIGIBLE_QUANTITY"


class AcceptanceReceiptReadinessStatus(StrEnum):
    READY = "READY"
    PARTIALLY_READY = "PARTIALLY_READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ReceiptLineReadinessInput:
    line_id: UUID
    physical_line: bool
    receipt_eligible_quantity: Decimal | None
    unresolved_excess: bool
    pricing_basis: str | None
    supplier_document_line_id: UUID | None
    document_quantity: Decimal | None
    historical_unit_price: Decimal | None
    historical_line_sum: Decimal | None
    iiko_supplier_id: UUID | None
    supplier_mapping_confirmed: bool
    supplier_reference_current: bool
    iiko_store_id: UUID | None
    store_mapping_confirmed: bool
    iiko_product_id: UUID | None
    product_mapping_confirmed: bool
    iiko_unit_id: UUID | None
    unit_mapping_confirmed: bool
    product_main_unit_id: UUID | None
    vat_omission_safe: bool
    previously_accounted_quantity: Decimal | None = Decimal("0")
    previously_accounted_amount: Decimal | None = Decimal("0")


@dataclass(frozen=True)
class DocumentLineAmountAllocation:
    current_sum: Decimal
    cumulative_quantity: Decimal
    cumulative_sum: Decimal
    remaining_quantity: Decimal
    remaining_amount: Decimal


def allocate_document_line_amount(
    *,
    document_quantity: Decimal,
    document_line_amount: Decimal,
    current_receipt_quantity: Decimal,
    previously_accounted_quantity: Decimal,
    previously_accounted_amount: Decimal,
    monetary_quantum: Decimal = MONEY_QUANTUM,
    rounding: str = ROUND_HALF_EVEN,
) -> DocumentLineAmountAllocation:
    values = (
        document_quantity,
        document_line_amount,
        current_receipt_quantity,
        previously_accounted_quantity,
        previously_accounted_amount,
        monetary_quantum,
    )
    if any(not value.is_finite() for value in values):
        raise ValueError("ALLOCATION_VALUE_NOT_FINITE")
    if document_quantity <= 0:
        raise ValueError("DOCUMENT_QUANTITY_NOT_POSITIVE")
    if document_line_amount < 0:
        raise ValueError("DOCUMENT_LINE_AMOUNT_NEGATIVE")
    if current_receipt_quantity <= 0:
        raise ValueError("CURRENT_RECEIPT_QUANTITY_NOT_POSITIVE")
    if previously_accounted_quantity < 0:
        raise ValueError("PREVIOUS_QUANTITY_NEGATIVE")
    if previously_accounted_amount < 0:
        raise ValueError("PREVIOUS_AMOUNT_NEGATIVE")
    if monetary_quantum <= 0:
        raise ValueError("MONETARY_QUANTUM_NOT_POSITIVE")
    if previously_accounted_amount > document_line_amount:
        raise ValueError("PREVIOUS_AMOUNT_EXCEEDS_DOCUMENT_AMOUNT")

    cumulative_quantity = (
        previously_accounted_quantity + current_receipt_quantity
    )
    if cumulative_quantity > document_quantity:
        raise ValueError("EXCESS_PRICE_SOURCE_MISSING")

    line_amount = document_line_amount.quantize(
        monetary_quantum, rounding=rounding
    )
    previous_amount = previously_accounted_amount.quantize(
        monetary_quantum, rounding=rounding
    )
    if cumulative_quantity == document_quantity:
        cumulative_sum = line_amount
    else:
        cumulative_sum = (
            document_line_amount * cumulative_quantity / document_quantity
        ).quantize(monetary_quantum, rounding=rounding)
    current_sum = (cumulative_sum - previous_amount).quantize(
        monetary_quantum, rounding=rounding
    )
    if current_sum < 0:
        raise ValueError("CURRENT_SUM_NEGATIVE")
    return DocumentLineAmountAllocation(
        current_sum=current_sum,
        cumulative_quantity=cumulative_quantity,
        cumulative_sum=cumulative_sum,
        remaining_quantity=document_quantity - cumulative_quantity,
        remaining_amount=(line_amount - cumulative_sum).quantize(
            monetary_quantum, rounding=rounding
        ),
    )


@dataclass(frozen=True)
class ReceiptLineContract:
    product_id: UUID
    amount: Decimal
    amount_unit_id: UUID
    container_id: None
    price: Decimal
    sum_amount: Decimal
    vat_percent: None
    vat_sum: None
    store_id: UUID
    supplier_id: UUID


@dataclass(frozen=True)
class ReceiptLineReadiness:
    line_id: UUID
    status: ReceiptLineStatus
    classification: ReceiptLineClassification
    reason_codes: tuple[ReceiptReadinessReason, ...]
    contract: ReceiptLineContract | None = None

    @property
    def receipt_line_ready(self) -> bool:
        return self.status == ReceiptLineStatus.READY


@dataclass(frozen=True)
class AcceptanceReceiptReadiness:
    status: AcceptanceReceiptReadinessStatus
    total_physical_lines: int
    ready_lines: int
    blocked_lines: int
    excluded_lines: int
    reason_codes: tuple[ReceiptReadinessReason, ...]
    lines: tuple[ReceiptLineReadiness, ...]

    @property
    def receipt_preview_ready(self) -> bool:
        return self.status == AcceptanceReceiptReadinessStatus.READY


def _valid_positive(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def evaluate_receipt_line(
    value: ReceiptLineReadinessInput,
) -> ReceiptLineReadiness:
    if not value.physical_line:
        return ReceiptLineReadiness(
            line_id=value.line_id,
            status=ReceiptLineStatus.EXCLUDED,
            classification=ReceiptLineClassification.FIXED_AMOUNT_SERVICE,
            reason_codes=(
                ReceiptReadinessReason.FIXED_AMOUNT_NOT_PHYSICAL,
            ),
        )
    if value.pricing_basis == "FIXED_AMOUNT":
        return ReceiptLineReadiness(
            line_id=value.line_id,
            status=ReceiptLineStatus.BLOCKED,
            classification=ReceiptLineClassification.FIXED_AMOUNT_SERVICE,
            reason_codes=(
                ReceiptReadinessReason.FIXED_AMOUNT_NOT_PHYSICAL,
            ),
        )

    reasons: list[ReceiptReadinessReason] = []
    classification = ReceiptLineClassification.UNKNOWN_UNIT_CONTRACT

    if value.unresolved_excess or value.receipt_eligible_quantity is None:
        reasons.append(ReceiptReadinessReason.UNRESOLVED_EXCESS)
    elif not _valid_positive(value.receipt_eligible_quantity):
        reasons.append(
            ReceiptReadinessReason.NO_RECEIPT_ELIGIBLE_QUANTITY
        )

    if not value.supplier_mapping_confirmed or value.iiko_supplier_id is None:
        reasons.append(ReceiptReadinessReason.SUPPLIER_MAPPING_MISSING)
    elif not value.supplier_reference_current:
        reasons.append(ReceiptReadinessReason.SUPPLIER_MAPPING_STALE)

    if not value.store_mapping_confirmed or value.iiko_store_id is None:
        reasons.append(ReceiptReadinessReason.STORE_MAPPING_MISSING)

    if not value.product_mapping_confirmed or value.iiko_product_id is None:
        reasons.append(ReceiptReadinessReason.PRODUCT_MAPPING_MISSING)

    if not value.unit_mapping_confirmed or value.iiko_unit_id is None:
        reasons.append(ReceiptReadinessReason.UNIT_MAPPING_MISSING)
        classification = ReceiptLineClassification.UNMAPPED_UNIT
    elif value.product_main_unit_id is None:
        reasons.append(
            ReceiptReadinessReason.PRODUCT_MAIN_UNIT_MISSING
        )
    elif value.iiko_unit_id != value.product_main_unit_id:
        reasons.append(ReceiptReadinessReason.UNIT_NOT_MAIN)
    else:
        classification = ReceiptLineClassification.BASE_UNIT_SAFE

    if value.pricing_basis == "PACKAGE":
        reasons.append(ReceiptReadinessReason.PACKAGE_CONVERSION_REQUIRED)
        classification = ReceiptLineClassification.PACKAGE_CONVERSION_REQUIRED
    elif value.pricing_basis != "UNIT":
        reasons.append(ReceiptReadinessReason.HISTORICAL_PRICE_MISSING)
    elif (
        value.supplier_document_line_id is None
        or not _valid_positive(value.document_quantity)
        or not _valid_positive(value.historical_unit_price)
        or not _valid_positive(value.historical_line_sum)
    ):
        reasons.append(ReceiptReadinessReason.HISTORICAL_PRICE_MISSING)
    elif (
        value.previously_accounted_quantity is None
        or value.previously_accounted_amount is None
    ):
        reasons.append(
            ReceiptReadinessReason.PRIOR_ACCOUNTING_FACTS_REQUIRED
        )
    elif value.receipt_eligible_quantity is not None:
        try:
            allocation = allocate_document_line_amount(
                document_quantity=value.document_quantity,
                document_line_amount=value.historical_line_sum,
                current_receipt_quantity=value.receipt_eligible_quantity,
                previously_accounted_quantity=(
                    value.previously_accounted_quantity
                ),
                previously_accounted_amount=value.previously_accounted_amount,
            )
        except ValueError as error:
            reason = (
                ReceiptReadinessReason.EXCESS_PRICE_SOURCE_MISSING
                if str(error) == "EXCESS_PRICE_SOURCE_MISSING"
                else ReceiptReadinessReason.SUM_ALLOCATION_AMBIGUOUS
            )
            reasons.append(reason)

    if not value.vat_omission_safe:
        reasons.append(ReceiptReadinessReason.VAT_MISSING)

    unique_reasons = tuple(dict.fromkeys(reasons))
    required_ids = (
        value.iiko_product_id,
        value.iiko_unit_id,
        value.iiko_store_id,
        value.iiko_supplier_id,
    )
    if unique_reasons or any(item is None for item in required_ids):
        return ReceiptLineReadiness(
            line_id=value.line_id,
            status=ReceiptLineStatus.BLOCKED,
            classification=classification,
            reason_codes=unique_reasons,
        )

    assert value.receipt_eligible_quantity is not None
    assert value.historical_unit_price is not None
    assert value.historical_line_sum is not None
    assert value.previously_accounted_quantity is not None
    assert value.previously_accounted_amount is not None
    assert value.iiko_product_id is not None
    assert value.iiko_unit_id is not None
    assert value.iiko_store_id is not None
    assert value.iiko_supplier_id is not None
    return ReceiptLineReadiness(
        line_id=value.line_id,
        status=ReceiptLineStatus.READY,
        classification=ReceiptLineClassification.BASE_UNIT_SAFE,
        reason_codes=(),
        contract=ReceiptLineContract(
            product_id=value.iiko_product_id,
            amount=value.receipt_eligible_quantity,
            amount_unit_id=value.iiko_unit_id,
            container_id=None,
            price=value.historical_unit_price,
            sum_amount=allocation.current_sum,
            vat_percent=None,
            vat_sum=None,
            store_id=value.iiko_store_id,
            supplier_id=value.iiko_supplier_id,
        ),
    )


def evaluate_acceptance_receipt(
    values: tuple[ReceiptLineReadinessInput, ...],
) -> AcceptanceReceiptReadiness:
    lines = tuple(evaluate_receipt_line(value) for value in values)
    physical = tuple(
        line for line in lines if line.status != ReceiptLineStatus.EXCLUDED
    )
    ready = sum(line.status == ReceiptLineStatus.READY for line in physical)
    blocked = sum(
        line.status == ReceiptLineStatus.BLOCKED for line in physical
    )
    excluded = len(lines) - len(physical)
    if physical and blocked == 0:
        status = AcceptanceReceiptReadinessStatus.READY
    elif ready and blocked:
        status = AcceptanceReceiptReadinessStatus.PARTIALLY_READY
    else:
        status = AcceptanceReceiptReadinessStatus.BLOCKED
    reasons = tuple(dict.fromkeys(
        reason
        for line in lines
        for reason in line.reason_codes
        if line.status == ReceiptLineStatus.BLOCKED
    ))
    return AcceptanceReceiptReadiness(
        status=status,
        total_physical_lines=len(physical),
        ready_lines=ready,
        blocked_lines=blocked,
        excluded_lines=excluded,
        reason_codes=reasons,
        lines=lines,
    )


def build_incoming_invoice_preview(
    values: tuple[ReceiptLineReadinessInput, ...],
    *,
    document_number: str,
    date_incoming: datetime,
    incoming_date: date,
    supplier_id: UUID,
    default_store_id: UUID,
) -> IikoIncomingInvoicePreviewDto:
    readiness = evaluate_acceptance_receipt(values)
    if not readiness.receipt_preview_ready:
        raise ValueError("RECEIPT_PREVIEW_BLOCKED")

    contracts = tuple(
        line.contract for line in readiness.lines if line.contract is not None
    )
    if not contracts:
        raise ValueError("RECEIPT_PREVIEW_BLOCKED")
    if any(
        contract.supplier_id != supplier_id
        or contract.store_id != default_store_id
        for contract in contracts
    ):
        raise ValueError("RECEIPT_PREVIEW_REFERENCE_MISMATCH")

    return IikoIncomingInvoicePreviewDto(
        document_number=document_number,
        date_incoming=date_incoming,
        incoming_date=incoming_date,
        supplier_id=supplier_id,
        default_store_id=default_store_id,
        items=tuple(
            IikoIncomingInvoicePreviewItemDto(
                num=index,
                product_id=contract.product_id,
                store_id=contract.store_id,
                amount=contract.amount,
                amount_unit_id=contract.amount_unit_id,
                price=contract.price,
                sum_amount=contract.sum_amount,
            )
            for index, contract in enumerate(contracts, start=1)
        ),
    )
