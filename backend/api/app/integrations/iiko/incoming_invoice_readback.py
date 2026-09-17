from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeAlias
from uuid import UUID

from app.integrations.iiko.schemas import (
    IikoIncomingInvoiceDto,
    IikoIncomingInvoiceItemDto,
)


NormalizedLine: TypeAlias = tuple[
    UUID,
    UUID | None,
    Decimal,
    Decimal | None,
    UUID | None,
    UUID | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    bool | None,
]


@dataclass(frozen=True)
class IncomingInvoiceReconciliationResult:
    matched: bool
    mismatches: tuple[str, ...]


def _decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value == 0:
        return Decimal(0)
    return value.normalize()


def normalized_line(item: IikoIncomingInvoiceItemDto) -> NormalizedLine:
    """Return an order-independent, scale-insensitive line identity."""
    return (
        item.product_id,
        item.store_id,
        _decimal(item.amount),
        _decimal(item.actual_amount),
        item.amount_unit,
        item.container_id,
        _decimal(item.price),
        _decimal(item.price_without_vat),
        _decimal(item.price_unit),
        _decimal(item.sum_amount),
        _decimal(item.discount_sum),
        _decimal(item.vat_percent),
        _decimal(item.vat_sum),
        item.is_additional_expense,
    )


def line_multiset(
    invoice: IikoIncomingInvoiceDto,
) -> Counter[NormalizedLine]:
    return Counter(normalized_line(item) for item in invoice.items)


def reconcile_incoming_invoice(
    expected: IikoIncomingInvoiceDto,
    actual: IikoIncomingInvoiceDto,
) -> IncomingInvoiceReconciliationResult:
    """Compare two read-side snapshots without relying on line order."""
    mismatches: list[str] = []
    for field, expected_value, actual_value in (
        ("document_id", expected.external_id, actual.external_id),
        ("document_number", expected.document_number, actual.document_number),
        ("status", expected.status, actual.status),
        ("supplier", expected.supplier_id, actual.supplier_id),
        ("store", expected.default_store_id, actual.default_store_id),
    ):
        if expected_value != actual_value:
            mismatches.append(field)
    if line_multiset(expected) != line_multiset(actual):
        mismatches.append("lines")
    return IncomingInvoiceReconciliationResult(
        matched=not mismatches,
        mismatches=tuple(mismatches),
    )
