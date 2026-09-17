from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.supply import (
    SupplyProduct,
    SupplyProductSupplier,
    SupplyPurchaseAllocation,
    SupplyPurchaseAllocationSource,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
    SupplyPurchaseRequestLineSource,
)
from app.schemas.purchase_allocation import (
    SupplyEligibleSupplierRead,
    SupplyPurchaseAllocationLineRead,
    SupplyPurchaseAllocationRead,
    SupplyPurchaseAllocationSourceRead,
    SupplyPurchaseAllocationSourceWrite,
    SupplyPurchaseAllocationSupplierSubtotalRead,
    SupplyPurchaseAllocationWorkspaceRead,
    SupplyMinimumOrderStatus,
)


QUANTITY_QUANTUM = Decimal("0.000001")
PRICE_QUANTUM = Decimal("0.000001")


class PurchaseAllocationNotFoundError(LookupError):
    pass


class PurchaseAllocationStateError(ValueError):
    pass


class PurchaseAllocationEligibilityError(ValueError):
    pass


class DuplicatePurchaseAllocationError(ValueError):
    pass


def _request_options():
    return (
        selectinload(SupplyPurchaseRequest.lines).joinedload(SupplyPurchaseRequestLine.product),
        selectinload(SupplyPurchaseRequest.lines).joinedload(SupplyPurchaseRequestLine.unit),
        selectinload(SupplyPurchaseRequest.lines)
        .selectinload(SupplyPurchaseRequestLine.purchase_allocations)
        .joinedload(SupplyPurchaseAllocation.product_supplier)
        .joinedload(SupplyProductSupplier.supplier),
        selectinload(SupplyPurchaseRequest.lines)
        .selectinload(SupplyPurchaseRequestLine.purchase_allocations)
        .joinedload(SupplyPurchaseAllocation.package_unit_snapshot),
        selectinload(SupplyPurchaseRequest.lines)
        .selectinload(SupplyPurchaseRequestLine.sources)
        .joinedload(SupplyPurchaseRequestLineSource.procurement_need),
        selectinload(SupplyPurchaseRequest.lines)
        .selectinload(SupplyPurchaseRequestLine.purchase_allocations)
        .selectinload(SupplyPurchaseAllocation.sources)
        .joinedload(SupplyPurchaseAllocationSource.purchase_request_line_source)
        .joinedload(SupplyPurchaseRequestLineSource.procurement_need),
    )


def _get_ready_request(
    session: Session, request_id: UUID, *, tenant_id: str, lock: bool = False
) -> SupplyPurchaseRequest:
    statement = select(SupplyPurchaseRequest).where(
        SupplyPurchaseRequest.id == request_id,
        SupplyPurchaseRequest.tenant_id == tenant_id,
    )
    if lock:
        statement = statement.with_for_update()
    item = session.scalar(statement)
    if item is None:
        raise PurchaseAllocationNotFoundError
    if item.status != "READY":
        raise PurchaseAllocationStateError
    return item


def _get_line(
    session: Session, request: SupplyPurchaseRequest, line_id: UUID
) -> SupplyPurchaseRequestLine:
    line = session.scalar(
        select(SupplyPurchaseRequestLine).where(
            SupplyPurchaseRequestLine.id == line_id,
            SupplyPurchaseRequestLine.purchase_request_id == request.id,
            SupplyPurchaseRequestLine.tenant_id == request.tenant_id,
        ).options(selectinload(SupplyPurchaseRequestLine.sources))
    )
    if line is None:
        raise PurchaseAllocationNotFoundError
    return line


def _relation_options():
    return (
        joinedload(SupplyProductSupplier.supplier),
        joinedload(SupplyProductSupplier.package_unit),
        joinedload(SupplyProductSupplier.product).joinedload(SupplyProduct.default_unit),
    )


def _get_relation(
    session: Session, relation_id: UUID, *, tenant_id: str
) -> SupplyProductSupplier:
    relation = session.scalar(
        select(SupplyProductSupplier)
        .where(
            SupplyProductSupplier.id == relation_id,
            SupplyProductSupplier.tenant_id == tenant_id,
        )
        .options(*_relation_options())
    )
    if relation is None:
        raise PurchaseAllocationEligibilityError
    return relation


def _is_eligible(relation: SupplyProductSupplier, line: SupplyPurchaseRequestLine) -> bool:
    return bool(
        relation.tenant_id == line.tenant_id
        and relation.product_id == line.product_id
        and relation.is_active
        and relation.supplier.is_active
        and relation.is_available
        and (relation.unavailable_until is None or relation.unavailable_until <= date.today())
        and relation.price_per_package is not None
        and relation.price_per_package > 0
        and relation.package_quantity > 0
        and relation.package_unit_id == line.unit_id
    )


def _require_eligible(
    relation: SupplyProductSupplier, line: SupplyPurchaseRequestLine
) -> None:
    if not _is_eligible(relation, line):
        raise PurchaseAllocationEligibilityError


def _values(relation: SupplyProductSupplier, packages_count: int) -> dict:
    package_quantity = Decimal(relation.package_quantity)
    package_price = Decimal(relation.price_per_package)
    return {
        "packages_count": packages_count,
        "quantity_base": (Decimal(packages_count) * package_quantity).quantize(
            QUANTITY_QUANTUM, rounding=ROUND_HALF_UP
        ),
        "package_quantity_snapshot": package_quantity,
        "package_unit_id_snapshot": relation.package_unit_id,
        "price_per_package_snapshot": package_price,
        "base_unit_price_snapshot": (package_price / package_quantity).quantize(
            PRICE_QUANTUM, rounding=ROUND_HALF_UP
        ),
        "currency": relation.currency,
        "planned_amount": (Decimal(packages_count) * package_price).quantize(
            PRICE_QUANTUM, rounding=ROUND_HALF_UP
        ),
    }


def _snapshot_values(
    allocation: SupplyPurchaseAllocation, packages_count: int
) -> dict:
    return {
        "packages_count": packages_count,
        "quantity_base": (
            Decimal(packages_count) * Decimal(allocation.package_quantity_snapshot)
        ).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP),
        "planned_amount": (
            Decimal(packages_count) * Decimal(allocation.price_per_package_snapshot)
        ).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP),
    }


def create_purchase_allocation(
    session: Session, request_id: UUID, line_id: UUID, relation_id: UUID,
    packages_count: int, *, tenant_id: str,
) -> SupplyPurchaseAllocationWorkspaceRead:
    request = _get_ready_request(session, request_id, tenant_id=tenant_id, lock=True)
    line = _get_line(session, request, line_id)
    relation = _get_relation(session, relation_id, tenant_id=tenant_id)
    _require_eligible(relation, line)
    allocation = SupplyPurchaseAllocation(
        tenant_id=tenant_id, purchase_request_line_id=line.id,
        product_supplier_id=relation.id, status="DRAFT",
        **_values(relation, packages_count),
    )
    try:
        session.add(allocation)
        session.flush()
        _autofill_single_source(session, line, allocation)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicatePurchaseAllocationError from error
    except Exception:
        session.rollback()
        raise
    return get_purchase_allocation_workspace(session, request_id, tenant_id=tenant_id)


def _get_allocation(
    session: Session, line: SupplyPurchaseRequestLine, allocation_id: UUID
) -> SupplyPurchaseAllocation:
    allocation = session.scalar(
        select(SupplyPurchaseAllocation).where(
            SupplyPurchaseAllocation.id == allocation_id,
            SupplyPurchaseAllocation.tenant_id == line.tenant_id,
            SupplyPurchaseAllocation.purchase_request_line_id == line.id,
        ).options(selectinload(SupplyPurchaseAllocation.sources))
    )
    if allocation is None:
        raise PurchaseAllocationNotFoundError
    return allocation


def update_purchase_allocation(
    session: Session, request_id: UUID, line_id: UUID, allocation_id: UUID,
    packages_count: int, *, tenant_id: str,
) -> SupplyPurchaseAllocationWorkspaceRead:
    request = _get_ready_request(session, request_id, tenant_id=tenant_id, lock=True)
    line = _get_line(session, request, line_id)
    allocation = _get_allocation(session, line, allocation_id)
    if allocation.status != "DRAFT":
        raise PurchaseAllocationStateError
    relation = _get_relation(session, allocation.product_supplier_id, tenant_id=tenant_id)
    _require_eligible(relation, line)
    for key, value in _snapshot_values(allocation, packages_count).items():
        setattr(allocation, key, value)
    if len(line.sources) == 1:
        _autofill_single_source(session, line, allocation)
    else:
        allocation.sources.clear()
    session.commit()
    return get_purchase_allocation_workspace(session, request_id, tenant_id=tenant_id)


def delete_purchase_allocation(
    session: Session, request_id: UUID, line_id: UUID, allocation_id: UUID,
    *, tenant_id: str,
) -> SupplyPurchaseAllocationWorkspaceRead:
    request = _get_ready_request(session, request_id, tenant_id=tenant_id, lock=True)
    line = _get_line(session, request, line_id)
    allocation = _get_allocation(session, line, allocation_id)
    if allocation.status != "DRAFT":
        raise PurchaseAllocationStateError
    session.delete(allocation)
    session.commit()
    return get_purchase_allocation_workspace(session, request_id, tenant_id=tenant_id)


def confirm_purchase_allocation(
    session: Session, request_id: UUID, line_id: UUID, allocation_id: UUID,
    *, tenant_id: str,
) -> SupplyPurchaseAllocationWorkspaceRead:
    request = _get_ready_request(session, request_id, tenant_id=tenant_id, lock=True)
    line = _get_line(session, request, line_id)
    allocation = _get_allocation(session, line, allocation_id)
    if allocation.status != "DRAFT":
        raise PurchaseAllocationStateError
    relation = _get_relation(session, allocation.product_supplier_id, tenant_id=tenant_id)
    _require_eligible(relation, line)
    _validate_source_distribution(session, line, allocation, lock=True)
    allocation.status = "CONFIRMED"
    session.commit()
    return get_purchase_allocation_workspace(session, request_id, tenant_id=tenant_id)


def _terms_changed(allocation: SupplyPurchaseAllocation) -> bool:
    relation = allocation.product_supplier
    return bool(
        relation.package_quantity != allocation.package_quantity_snapshot
        or relation.package_unit_id != allocation.package_unit_id_snapshot
        or relation.price_per_package != allocation.price_per_package_snapshot
        or relation.currency != allocation.currency
    )


def _locked_line_sources(
    session: Session, line: SupplyPurchaseRequestLine, *, lock: bool,
) -> list[SupplyPurchaseRequestLineSource]:
    statement = (
        select(SupplyPurchaseRequestLineSource)
        .where(
            SupplyPurchaseRequestLineSource.tenant_id == line.tenant_id,
            SupplyPurchaseRequestLineSource.purchase_request_line_id == line.id,
        )
        .order_by(SupplyPurchaseRequestLineSource.id)
    )
    if lock:
        statement = statement.with_for_update()
    return list(session.scalars(statement).all())


def _confirmed_by_source(
    session: Session, source_ids: list[UUID], *, exclude_allocation_id: UUID,
) -> dict[UUID, Decimal]:
    if not source_ids:
        return {}
    rows = session.execute(
        select(
            SupplyPurchaseAllocationSource.purchase_request_line_source_id,
            func.coalesce(func.sum(SupplyPurchaseAllocationSource.allocated_quantity), 0),
        )
        .join(
            SupplyPurchaseAllocation,
            SupplyPurchaseAllocation.id == SupplyPurchaseAllocationSource.allocation_id,
        )
        .where(
            SupplyPurchaseAllocationSource.purchase_request_line_source_id.in_(source_ids),
            SupplyPurchaseAllocation.status == "CONFIRMED",
            SupplyPurchaseAllocation.id != exclude_allocation_id,
        )
        .group_by(SupplyPurchaseAllocationSource.purchase_request_line_source_id)
    ).all()
    return {source_id: Decimal(quantity) for source_id, quantity in rows}


def _distribution_target(
    allocation: SupplyPurchaseAllocation,
    sources: list[SupplyPurchaseRequestLineSource],
    confirmed: dict[UUID, Decimal],
) -> Decimal:
    remaining = sum(
        (max(Decimal(source.quantity) - confirmed.get(source.id, Decimal("0")), Decimal("0"))
         for source in sources),
        Decimal("0"),
    )
    return min(Decimal(allocation.quantity_base), remaining)


def _autofill_single_source(
    session: Session, line: SupplyPurchaseRequestLine,
    allocation: SupplyPurchaseAllocation,
) -> None:
    sources = _locked_line_sources(session, line, lock=True)
    if len(sources) != 1:
        return
    confirmed = _confirmed_by_source(
        session, [sources[0].id], exclude_allocation_id=allocation.id,
    )
    target = _distribution_target(allocation, sources, confirmed)
    if target <= 0:
        allocation.sources.clear()
    elif allocation.sources:
        allocation.sources[0].purchase_request_line_source_id = sources[0].id
        allocation.sources[0].allocated_quantity = target
        for extra in allocation.sources[1:]:
            session.delete(extra)
    else:
        allocation.sources.append(SupplyPurchaseAllocationSource(
            tenant_id=line.tenant_id,
            purchase_request_line_source_id=sources[0].id,
            allocated_quantity=target,
        ))


def _validate_source_distribution(
    session: Session, line: SupplyPurchaseRequestLine,
    allocation: SupplyPurchaseAllocation, *, lock: bool,
) -> None:
    sources = _locked_line_sources(session, line, lock=lock)
    source_by_id = {source.id: source for source in sources}
    confirmed = _confirmed_by_source(
        session, list(source_by_id), exclude_allocation_id=allocation.id,
    )
    seen: set[UUID] = set()
    total = Decimal("0")
    for item in allocation.sources:
        source = source_by_id.get(item.purchase_request_line_source_id)
        quantity = Decimal(item.allocated_quantity)
        if source is None or source.id in seen:
            raise PurchaseAllocationStateError
        if quantity > Decimal(source.quantity) - confirmed.get(source.id, Decimal("0")):
            raise PurchaseAllocationStateError
        seen.add(source.id)
        total += quantity
    if total != _distribution_target(allocation, sources, confirmed):
        raise PurchaseAllocationStateError


def update_purchase_allocation_sources(
    session: Session, request_id: UUID, line_id: UUID, allocation_id: UUID,
    values: list[SupplyPurchaseAllocationSourceWrite], *, tenant_id: str,
) -> SupplyPurchaseAllocationWorkspaceRead:
    request = _get_ready_request(session, request_id, tenant_id=tenant_id, lock=True)
    line = _get_line(session, request, line_id)
    allocation = _get_allocation(session, line, allocation_id)
    if allocation.status != "DRAFT":
        raise PurchaseAllocationStateError
    if len({value.purchase_request_line_source_id for value in values}) != len(values):
        raise PurchaseAllocationStateError
    allocation.sources.clear()
    session.flush()
    for value in values:
        allocation.sources.append(SupplyPurchaseAllocationSource(
            tenant_id=tenant_id,
            purchase_request_line_source_id=value.purchase_request_line_source_id,
            allocated_quantity=value.allocated_quantity,
        ))
    _validate_source_distribution(session, line, allocation, lock=True)
    session.commit()
    return get_purchase_allocation_workspace(session, request_id, tenant_id=tenant_id)


def _source_label(source: SupplyPurchaseRequestLineSource) -> str:
    if source.source_type == "MANUAL_FUTURE":
        return "Будущая потребность"
    need = source.procurement_need
    reason_value = getattr(getattr(need, "reason", None), "value", getattr(need, "reason", None))
    reason = {
        "INTERNAL_STOCK_DEFICIT": "Дефицит после расчёта остатков",
        "DEBT_CARRY_FORWARD": "Перенос долга подразделения",
        "SUPPLIER_SHORTAGE": "Недопоставка поставщика",
        "SUPPLIER_REJECTION": "Отклонение при приёмке",
    }.get(reason_value, "Потребность")
    department = None
    if need is not None and need.request_line is not None:
        department = need.request_line.request.department.name
    elif need is not None and need.department_debt is not None:
        department = need.department_debt.department.name
    return f"{department} · {reason}" if department else reason


def get_purchase_allocation_workspace(
    session: Session, request_id: UUID, *, tenant_id: str
) -> SupplyPurchaseAllocationWorkspaceRead:
    _get_ready_request(session, request_id, tenant_id=tenant_id)
    request = session.scalar(
        select(SupplyPurchaseRequest)
        .where(
            SupplyPurchaseRequest.id == request_id,
            SupplyPurchaseRequest.tenant_id == tenant_id,
        )
        .options(*_request_options())
        .execution_options(populate_existing=True)
    )
    relations = list(session.scalars(
        select(SupplyProductSupplier)
        .where(
            SupplyProductSupplier.tenant_id == tenant_id,
            SupplyProductSupplier.product_id.in_([line.product_id for line in request.lines]),
        )
        .options(*_relation_options())
        .order_by(
            case((SupplyProductSupplier.role == "PRIMARY", 0), else_=1),
            SupplyProductSupplier.priority.asc(),
            SupplyProductSupplier.created_at.asc(),
        )
    ).all()) if request.lines else []
    by_product: dict[UUID, list[SupplyProductSupplier]] = {}
    for relation in relations:
        by_product.setdefault(relation.product_id, []).append(relation)

    total = Decimal("0")
    subtotals: dict[UUID, tuple[str, Decimal | None, Decimal, int]] = {}
    line_reads = []
    for line in request.lines:
        allocations = []
        allocated = Decimal("0")
        line_amount = Decimal("0")
        for allocation in line.purchase_allocations:
            relation = allocation.product_supplier
            amount = Decimal(allocation.planned_amount)
            allocated += Decimal(allocation.quantity_base)
            line_amount += amount
            name, minimum, subtotal, count = subtotals.get(
                relation.supplier_id,
                (
                    relation.supplier.display_name,
                    relation.supplier.minimum_order_amount,
                    Decimal("0"),
                    0,
                ),
            )
            subtotals[relation.supplier_id] = (
                name,
                minimum,
                subtotal + amount,
                count + 1,
            )
            source_ids = [source.id for source in line.sources]
            confirmed = _confirmed_by_source(
                session, source_ids, exclude_allocation_id=allocation.id,
            )
            allocation_by_source = {
                item.purchase_request_line_source_id: item for item in allocation.sources
            }
            source_reads = []
            for source in line.sources:
                current = allocation_by_source.get(source.id)
                already = confirmed.get(source.id, Decimal("0"))
                source_reads.append(SupplyPurchaseAllocationSourceRead(
                    purchase_request_line_source_id=source.id,
                    source_type=source.source_type,
                    procurement_need_id=source.procurement_need_id,
                    source_label=_source_label(source),
                    need_date=(source.procurement_need.need_date if source.procurement_need else None),
                    required_quantity=source.quantity,
                    already_allocated_quantity=already,
                    remaining_quantity=max(Decimal(source.quantity) - already, Decimal("0")),
                    allocated_quantity=(current.allocated_quantity if current else Decimal("0")),
                ))
            covered = sum((Decimal(item.allocated_quantity) for item in allocation.sources), Decimal("0"))
            allocations.append(SupplyPurchaseAllocationRead(
                id=allocation.id, product_supplier_id=relation.id,
                supplier_id=relation.supplier_id,
                supplier_display_name=relation.supplier.display_name,
                role=relation.role, priority=relation.priority,
                packages_count=allocation.packages_count,
                quantity_base=allocation.quantity_base,
                package_quantity_snapshot=allocation.package_quantity_snapshot,
                package_unit_id_snapshot=allocation.package_unit_id_snapshot,
                package_unit_snapshot=allocation.package_unit_snapshot,
                price_per_package_snapshot=allocation.price_per_package_snapshot,
                base_unit_price_snapshot=allocation.base_unit_price_snapshot,
                currency=allocation.currency, planned_amount=allocation.planned_amount,
                status=allocation.status,
                traceability_status=(
                    "TRACEABLE" if allocation.sources
                    else "INCOMPLETE" if allocation.status == "DRAFT"
                    else "UNTRACEABLE_LEGACY"
                ),
                source_covered_quantity=covered,
                procurement_surplus_quantity=max(Decimal(allocation.quantity_base) - covered, Decimal("0")),
                sources=source_reads,
                current_terms_changed=_terms_changed(allocation),
                created_at=allocation.created_at, updated_at=allocation.updated_at,
            ))
        eligible = [SupplyEligibleSupplierRead(
            product_supplier_id=relation.id, supplier_id=relation.supplier_id,
            supplier_display_name=relation.supplier.display_name,
            role=relation.role, priority=relation.priority,
            package_quantity=relation.package_quantity,
            package_unit_id=relation.package_unit_id,
            package_unit=relation.package_unit,
            price_per_package=relation.price_per_package,
            base_unit_price=(Decimal(relation.price_per_package) / Decimal(relation.package_quantity)).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP),
            currency=relation.currency, is_available=relation.is_available,
            unavailable_until=relation.unavailable_until,
        ) for relation in by_product.get(line.product_id, []) if _is_eligible(relation, line)]
        required = Decimal(line.quantity)
        total += line_amount
        line_reads.append(SupplyPurchaseAllocationLineRead(
            line_id=line.id, product_id=line.product_id, product_name=line.product.name,
            required_quantity=required, unit_id=line.unit_id, unit=line.unit,
            allocations=allocations, eligible_suppliers=eligible,
            allocated_quantity=allocated,
            remaining_quantity=max(required - allocated, Decimal("0")),
            overallocated_quantity=max(allocated - required, Decimal("0")),
            planned_amount=line_amount,
        ))
    return SupplyPurchaseAllocationWorkspaceRead(
        request_id=request.id, request_number=request.number, request_status=request.status,
        lines=line_reads, planned_total_amount=total,
        supplier_subtotals=[SupplyPurchaseAllocationSupplierSubtotalRead(
            supplier_id=supplier_id,
            supplier_display_name=name,
            planned_total_amount=amount,
            minimum_order_amount=minimum,
            minimum_order_status=(
                SupplyMinimumOrderStatus.NOT_CONFIGURED
                if minimum is None
                else SupplyMinimumOrderStatus.MET
                if amount >= minimum
                else SupplyMinimumOrderStatus.BELOW_MINIMUM
            ),
            minimum_order_shortfall=(
                Decimal("0") if minimum is None or amount >= minimum
                else minimum - amount
            ),
            allocation_count=count,
        ) for supplier_id, (name, minimum, amount, count) in sorted(
            subtotals.items(), key=lambda item: item[1][0].lower()
        )],
    )
