from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.supply import (
    SupplyDepartmentDebt,
    SupplyProcurementNeed,
    SupplyProcurementNeedReason,
    SupplyProcurementNeedSourceType,
    SupplyProcurementNeedStatus,
    SupplyRequest,
    SupplyRequestLine,
    SupplyRequestLineDebtLink,
    SupplyStockCalculation,
    SupplyStockCalculationLine,
    SupplyStockCalculationStatus,
)


def _close(need: SupplyProcurementNeed, now: datetime) -> None:
    if need.status != SupplyProcurementNeedStatus.OPEN:
        return
    need.status = SupplyProcurementNeedStatus.CLOSED
    need.closed_at = now
    need.version += 1


def invalidate_open_request_need(
    session: Session,
    *,
    tenant_id: str,
    request_line_id: UUID,
    now: datetime | None = None,
) -> None:
    need = session.scalar(
        select(SupplyProcurementNeed)
        .where(
            SupplyProcurementNeed.tenant_id == tenant_id,
            SupplyProcurementNeed.source_type
            == SupplyProcurementNeedSourceType.REQUEST_LINE,
            SupplyProcurementNeed.supply_request_line_id == request_line_id,
            SupplyProcurementNeed.status == SupplyProcurementNeedStatus.OPEN,
        )
        .with_for_update(of=SupplyProcurementNeed)
    )
    if need is not None:
        _close(need, now or datetime.now(timezone.utc))


def invalidate_open_request_needs(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    now: datetime | None = None,
) -> None:
    needs = session.scalars(
        select(SupplyProcurementNeed)
        .join(
            SupplyRequestLine,
            SupplyRequestLine.id == SupplyProcurementNeed.supply_request_line_id,
        )
        .where(
            SupplyProcurementNeed.tenant_id == tenant_id,
            SupplyRequestLine.tenant_id == tenant_id,
            SupplyRequestLine.request_id == request_id,
            SupplyProcurementNeed.source_type
            == SupplyProcurementNeedSourceType.REQUEST_LINE,
            SupplyProcurementNeed.status == SupplyProcurementNeedStatus.OPEN,
        )
        .with_for_update(of=SupplyProcurementNeed)
    ).all()
    closed_at = now or datetime.now(timezone.utc)
    for need in needs:
        _close(need, closed_at)


def reconcile_confirmed_stock_calculation_needs(
    session: Session,
    *,
    request: SupplyRequest,
    calculation: SupplyStockCalculation,
    now: datetime | None = None,
) -> None:
    """Reconcile request-origin needs without committing the caller transaction."""
    if calculation.status != SupplyStockCalculationStatus.CONFIRMED:
        return
    if calculation.request_id != request.id or calculation.tenant_id != request.tenant_id:
        raise ValueError("Stock calculation does not belong to request")

    current_lines = {line.id: line for line in request.lines}
    existing = {
        need.supply_request_line_id: need
        for need in session.scalars(
            select(SupplyProcurementNeed)
            .join(
                SupplyRequestLine,
                SupplyRequestLine.id == SupplyProcurementNeed.supply_request_line_id,
            )
            .where(
                SupplyProcurementNeed.tenant_id == request.tenant_id,
                SupplyRequestLine.request_id == request.id,
                SupplyProcurementNeed.source_type
                == SupplyProcurementNeedSourceType.REQUEST_LINE,
                SupplyProcurementNeed.status == SupplyProcurementNeedStatus.OPEN,
            )
            .with_for_update(of=SupplyProcurementNeed)
        ).all()
    }
    basis_line_ids: set[UUID] = set()
    changed_at = now or datetime.now(timezone.utc)

    for basis in calculation.lines:
        basis_line_ids.add(basis.request_line_id)
        line = current_lines.get(basis.request_line_id)
        need = existing.get(basis.request_line_id)
        matches = bool(
            line is not None
            and line.match_status == "MATCHED"
            and line.product_id == basis.product_id
            and line.requested_unit_id == basis.requested_unit_id
            and line.quantity == basis.requested_quantity
        )
        deficit = basis.deficit_quantity
        if (
            not matches
            or request.need_date is None
            or deficit is None
            or deficit <= Decimal("0")
        ):
            if need is not None:
                _close(need, changed_at)
            continue

        if need is None:
            session.add(SupplyProcurementNeed(
                tenant_id=request.tenant_id,
                source_type=SupplyProcurementNeedSourceType.REQUEST_LINE,
                supply_request_line_id=line.id,
                department_debt_id=None,
                basis_stock_calculation_line_id=basis.id,
                product_id=basis.product_id,
                unit_id=basis.requested_unit_id,
                quantity=deficit,
                need_date=request.need_date,
                status=SupplyProcurementNeedStatus.OPEN,
                reason=SupplyProcurementNeedReason.INTERNAL_STOCK_DEFICIT,
                version=1,
                reserved_purchase_request_id=None,
            ))
            continue

        changed = (
            need.basis_stock_calculation_line_id != basis.id
            or need.product_id != basis.product_id
            or need.unit_id != basis.requested_unit_id
            or need.quantity != deficit
            or need.need_date != request.need_date
        )
        if changed:
            need.basis_stock_calculation_line_id = basis.id
            need.product_id = basis.product_id
            need.unit_id = basis.requested_unit_id
            need.quantity = deficit
            need.need_date = request.need_date
            need.version += 1

    for line_id, need in existing.items():
        if line_id not in basis_line_ids:
            _close(need, changed_at)


def reconcile_department_debt_need(
    session: Session,
    *,
    debt: SupplyDepartmentDebt,
    need_date: date | None,
    now: datetime | None = None,
) -> SupplyProcurementNeed | None:
    """Support debt-origin needs when a trusted need date is supplied by a caller.

    This foundation slice intentionally has no automatic caller because the current
    debt model has no authoritative procurement date.
    """
    existing = session.scalar(
        select(SupplyProcurementNeed)
        .where(
            SupplyProcurementNeed.tenant_id == debt.tenant_id,
            SupplyProcurementNeed.source_type
            == SupplyProcurementNeedSourceType.DEPARTMENT_DEBT,
            SupplyProcurementNeed.department_debt_id == debt.id,
            SupplyProcurementNeed.status == SupplyProcurementNeedStatus.OPEN,
        )
        .with_for_update(of=SupplyProcurementNeed)
    )
    included = session.scalar(
        select(SupplyRequestLineDebtLink.request_line_id)
        .join(
            SupplyRequestLine,
            SupplyRequestLine.id == SupplyRequestLineDebtLink.request_line_id,
        )
        .join(SupplyRequest, SupplyRequest.id == SupplyRequestLine.request_id)
        .where(
            SupplyRequestLineDebtLink.tenant_id == debt.tenant_id,
            SupplyRequestLineDebtLink.included_debt_id == debt.id,
            SupplyRequestLineDebtLink.inclusion_confirmed.is_(True),
            SupplyRequest.tenant_id == debt.tenant_id,
            SupplyRequest.status.in_(("DRAFT", "SUBMITTED", "IN_REVIEW", "PLANNED")),
        )
        .limit(1)
    ) is not None
    changed_at = now or datetime.now(timezone.utc)
    eligible = (
        debt.status == "ACTIVE"
        and debt.outstanding_quantity > Decimal("0")
        and not included
        and need_date is not None
        and debt.product_id is not None
    )
    if not eligible:
        if existing is not None:
            _close(existing, changed_at)
        return None
    if existing is None:
        existing = SupplyProcurementNeed(
            tenant_id=debt.tenant_id,
            source_type=SupplyProcurementNeedSourceType.DEPARTMENT_DEBT,
            department_debt_id=debt.id,
            supply_request_line_id=None,
            basis_stock_calculation_line_id=None,
            product_id=debt.product_id,
            unit_id=debt.unit_id,
            quantity=debt.outstanding_quantity,
            need_date=need_date,
            status=SupplyProcurementNeedStatus.OPEN,
            reason=SupplyProcurementNeedReason.DEBT_CARRY_FORWARD,
            version=1,
            reserved_purchase_request_id=None,
        )
        session.add(existing)
        return existing
    if (
        existing.product_id != debt.product_id
        or existing.unit_id != debt.unit_id
        or existing.quantity != debt.outstanding_quantity
        or existing.need_date != need_date
    ):
        existing.product_id = debt.product_id
        existing.unit_id = debt.unit_id
        existing.quantity = debt.outstanding_quantity
        existing.need_date = need_date
        existing.version += 1
    return existing
