from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.supply import (
    SupplyProduct,
    SupplyProductSupplier,
    SupplyPurchaseAllocation,
    SupplyPurchaseRequest,
    SupplyPurchaseRequestLine,
)
from app.schemas.purchase_allocation import (
    SupplyEligibleSupplierRead,
    SupplyPurchaseAllocationLineRead,
    SupplyPurchaseAllocationRead,
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
        )
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
        )
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
                status=allocation.status, current_terms_changed=_terms_changed(allocation),
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
