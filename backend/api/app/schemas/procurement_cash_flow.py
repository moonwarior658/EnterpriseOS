from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class SupplyProcurementCashFlowBreakdown(BaseModel):
    entity_type: str
    entity_id: UUID
    reference: str
    amount: Decimal
    business_date: date


class SupplyProcurementCashFlowException(BaseModel):
    code: str
    requires_decision: bool
    amount: Decimal | None = None


class SupplyProcurementCashFlowSummary(BaseModel):
    scope: Literal["SUPPLIER", "PURCHASE_REQUEST"]
    supplier_id: UUID | None = None
    purchase_request_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    planned_amount: Decimal | None
    planned_amount_status: Literal["AVAILABLE", "UNAVAILABLE"]
    ordered_amount: Decimal
    draft_order_amount: Decimal
    ready_order_amount: Decimal
    committed_order_amount: Decimal
    confirmed_amount: Decimal
    payable_documented_amount: Decimal
    accepted_goods_amount: Decimal | None
    accepted_goods_amount_status: Literal["AVAILABLE", "UNAVAILABLE"]
    gross_paid_amount: Decimal
    supplier_refund_amount: Decimal
    net_paid_amount: Decimal
    current_debt_amount: Decimal
    overdue_debt_amount: Decimal
    unallocated_prepayment_amount: Decimal
    supplier_credit_amount: Decimal
    ordered_vs_confirmed_amount: Decimal
    confirmed_vs_documented_amount: Decimal
    documented_vs_accepted_goods_amount: Decimal | None
    price_deviation_open_count: int
    financial_exception_count: int
    financial_exceptions: list[SupplyProcurementCashFlowException]
    requires_decision: bool
    decision_reason_codes: list[str]
    breakdown: list[SupplyProcurementCashFlowBreakdown]
    date_semantics: dict[str, str]
