"""Validate complete daily snapshots, resolve identities, reconcile source receipts."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, func
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import Session, defer
from app.models.employee import Employee, IikoDepartmentMapping, IikoEmployeeLink
from app.models.iiko import IikoProductMapping, IikoMappingStatus
from app.models.sales import SalesDaySync, SalesFact, SalesSyncState
from app.models.supply import Department, DepartmentBusinessType

DIMENSIONS = (
    "Department.Id", "RestorauntGroup.Id", "UniqOrderId.Id", "OrderNum",
    "OpenDate.Typed", "OpenTime", "CloseTime", "Cashier.Id", "Cashier",
    "OrderWaiter.Id", "OrderWaiter.Name", "WaiterName.ID", "WaiterName",
    "DishId", "DishName", "DishCategory", "DishMeasureUnit", "ItemSaleEvent.Id",
    "Storned", "OrderDeleted", "DeletedWithWriteoff", "SourceOrderId",
    "SoldWithItem.Id", "DishType",
)
MEASURES = ("DishAmountInt", "DishSumInt", "DishDiscountSumInt", "UniqOrderId", "DishReturnSum")


class SalesContractError(ValueError):
    """Safe code only: never include a source row in an exception."""


def daily_query(day: date, department_ids: list[UUID]) -> dict:
    if not department_ids:
        raise SalesContractError("SALES_NO_CONFIRMED_POINTS")
    return {
        "reportType": "SALES", "buildSummary": False,
        "groupByRowFields": list(DIMENSIONS), "groupByColFields": [],
        "aggregateFields": list(MEASURES),
        "filters": {
            "OpenDate.Typed": {
                "filterType": "DateRange", "periodType": "CUSTOM",
                "from": f"{day.isoformat()}T00:00:00.000",
                "to": f"{(day + timedelta(days=1)).isoformat()}T00:00:00.000",
                "includeLow": True, "includeHigh": False,
            },
            "Department.Id": {"filterType": "IncludeValues", "values": [str(v) for v in department_ids]},
        },
    }


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def retail_mappings(db: Session, tenant_id: str) -> dict[UUID, UUID]:
    return dict(db.execute(select(IikoDepartmentMapping.olap_department_id, Department.id).join(
        Department, (Department.id == IikoDepartmentMapping.eos_department_id)
        & (Department.tenant_id == IikoDepartmentMapping.tenant_id),
    ).where(
        IikoDepartmentMapping.tenant_id == tenant_id,
        IikoDepartmentMapping.olap_department_id.is_not(None),
        Department.business_type == DepartmentBusinessType.RETAIL_POINT,
    )).all())


def historical_links(db: Session, tenant_id: str, facts) -> dict:
    users = sorted({f.iiko_employee_id for f in facts if f.iiko_employee_id})
    result = defaultdict(list)
    for offset in range(0, len(users), 400):
        for link in db.scalars(select(IikoEmployeeLink).where(
            IikoEmployeeLink.tenant_id == tenant_id,
            IikoEmployeeLink.iiko_user_id.in_(users[offset:offset + 400]),
        )):
            result[link.iiko_user_id].append(link)
    return result


def employee_for_fact(db: Session | None, fact: SalesFact, source_timezone: str, *, links_by_user=None) -> UUID | None:
    if not fact.iiko_employee_id:
        return None
    local = fact.opened_at.replace(tzinfo=ZoneInfo(source_timezone))
    # An ambiguous wall time cannot establish historical identity safely.
    if (local.utcoffset() != local.replace(fold=1).utcoffset()
            or local.astimezone(timezone.utc).astimezone(ZoneInfo(source_timezone)).replace(tzinfo=None) != fact.opened_at):
        return None
    instant = local.astimezone(timezone.utc)
    links = links_by_user.get(fact.iiko_employee_id, []) if links_by_user is not None else db.scalars(select(IikoEmployeeLink).where(
        IikoEmployeeLink.tenant_id == fact.tenant_id,
        IikoEmployeeLink.iiko_user_id == fact.iiko_employee_id,
    )).all()
    matches = [link.employee_id for link in links if as_utc(link.valid_from) <= instant
               and (link.valid_to is None or instant < as_utc(link.valid_to))]
    if matches:
        return matches[0] if len(matches) == 1 else None
    # A first, still-confirmed stable identity can identify sales predating
    # registration in EOS. Do not backdate records or extend closed/reused IDs.
    if len(links) == 1 and links[0].valid_to is None and instant < as_utc(links[0].valid_from):
        return links[0].employee_id
    return None


def parse_fact(row: dict, *, tenant_id: str, source_id: str, day: date, seen_at: datetime) -> SalesFact:
    def uid(field, required=False):
        value = row.get(field)
        if value is None and not required:
            return None
        return UUID(str(value))

    def number(field):
        value = row[field]
        if isinstance(value, bool) or value is None:
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result

    def timestamp(field, required=False):
        value = row.get(field)
        if value is None and not required:
            return None
        result = datetime.fromisoformat(value)
        if result.tzinfo is not None:
            raise ValueError
        return result

    try:
        if date.fromisoformat(row["OpenDate.Typed"]) != day:
            raise ValueError
        if row["Storned"] not in ("TRUE", "FALSE"):
            raise ValueError
        if row["OrderDeleted"] not in ("NOT_DELETED", "DELETED"):
            raise ValueError
        if row["DeletedWithWriteoff"] not in ("NOT_DELETED", "DELETED_WITH_WRITEOFF", "DELETED_WITHOUT_WRITEOFF"):
            raise ValueError
        quantity, amount = number("DishAmountInt"), number("DishDiscountSumInt")
        return SalesFact(
            tenant_id=tenant_id, source_id=source_id, business_date=day,
            opened_at=timestamp("OpenTime", True), closed_at=timestamp("CloseTime"),
            iiko_department_id=uid("Department.Id", True), iiko_group_id=uid("RestorauntGroup.Id"),
            iiko_order_id=uid("UniqOrderId.Id", True), iiko_item_id=uid("ItemSaleEvent.Id", True),
            source_order_id=uid("SourceOrderId"), sold_with_item_id=uid("SoldWithItem.Id"),
            iiko_employee_id=row.get("Cashier.Id"), order_waiter_id=row.get("OrderWaiter.Id"),
            item_waiter_id=row.get("WaiterName.ID"), iiko_product_id=uid("DishId", True),
            product_name=row.get("DishName"), product_category=row.get("DishCategory"),
            quantity=quantity, amount_before_discount=number("DishSumInt"),
            amount_after_discount=amount, return_amount=number("DishReturnSum"),
            is_free=quantity > 0 and amount == 0, is_returned=row["Storned"] == "TRUE",
            is_deleted=row["OrderDeleted"] != "NOT_DELETED" or row["DeletedWithWriteoff"] != "NOT_DELETED",
            is_present=True, raw_payload={k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()},
            seen_at=seen_at,
        )
    except (ValueError, KeyError, TypeError, InvalidOperation) as error:
        raise SalesContractError("SALES_ROW_INVALID") from error


def ingest_day(db: Session, rows: list[dict], *, state: SalesSyncState, day: date,
               department_ids: list[UUID], seen_at: datetime) -> int:
    """Caller owns transaction. Validate the entire response before any mutation."""
    parsed = [parse_fact(row, tenant_id=state.tenant_id, source_id=state.source_id, day=day, seen_at=seen_at) for row in rows]
    def key(fact):
        return fact.iiko_department_id, fact.iiko_order_id, fact.iiko_item_id
    keys = {key(fact) for fact in parsed}
    if len(keys) != len(parsed):
        raise SalesContractError("SALES_DUPLICATE_IDENTITY")
    if any(f.iiko_department_id not in department_ids for f in parsed):
        raise SalesContractError("SALES_POINT_OUTSIDE_REQUEST")
    mappings = retail_mappings(db, state.tenant_id)
    product_mappings = dict(db.execute(select(IikoProductMapping.iiko_product_id, IikoProductMapping.eos_product_id).where(
        IikoProductMapping.tenant_id == state.tenant_id,
        IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
        IikoProductMapping.eos_product_id.is_not(None),
    )).all())
    # Query by stable identity across days so a corrected business date updates the same event.
    existing = {key(f): f for f in db.scalars(select(SalesFact).where(
        SalesFact.tenant_id == state.tenant_id, SalesFact.source_id == state.source_id,
        SalesFact.iiko_department_id.in_(department_ids),
        or_(SalesFact.business_date == day, SalesFact.iiko_item_id.in_([f.iiko_item_id for f in parsed])),
    )).all()}
    for fact in existing.values():
        if fact.business_date == day and key(fact) not in keys:
            fact.is_present = False
    links = historical_links(db, state.tenant_id, parsed)
    for fact in parsed:
        fact.product_id = product_mappings.get(fact.iiko_product_id)
        fact.department_id = mappings.get(fact.iiko_department_id)
        fact.employee_id = employee_for_fact(db, fact, state.source_timezone, links_by_user=links)
        stored = existing.get(key(fact))
        if stored is None:
            db.add(fact)
        else:
            for column in SalesFact.__table__.columns:
                if column.name != "id":
                    setattr(stored, column.name, getattr(fact, column.name))
    checkpoint = db.get(SalesDaySync, (state.tenant_id, state.source_id, day))
    if checkpoint is None:
        checkpoint = SalesDaySync(tenant_id=state.tenant_id, source_id=state.source_id, business_date=day)
        db.add(checkpoint)
    checkpoint.last_success_at, checkpoint.row_count = seen_at, len(parsed)
    db.flush()
    return len(parsed)


@dataclass
class ReconciledOrder:
    order_id: UUID
    business_date: date
    department_id: UUID | None
    employee_id: UUID | None
    revenue: Decimal
    quantity: Decimal
    fullness_quantity: Decimal
    products: dict[UUID, tuple[Decimal, Decimal]]
    excluded: bool = False
    issue: str | None = None


def reconciliation_facts(db: Session, state: SalesSyncState, *,
                         start: date | None = None, end: date | None = None) -> list[SalesFact]:
    """Bound original receipts by date, then fetch their complete return component.

    Expand both directions and fetch whole receipts: malformed multi-source rows,
    missing roots, chains and cycles must retain A1's fail-closed semantics.
    Refund dates are deliberately unbounded; they restate the original sale day.
    The unbounded mode is retained for A1 diagnostics, never used by analytics.
    """
    scope = (SalesFact.tenant_id == state.tenant_id,
             SalesFact.source_id == state.source_id, SalesFact.is_present)
    if start is None and end is None:
        return list(db.scalars(select(SalesFact).where(*scope)).all())
    if start is None or end is None or start > end:
        raise SalesContractError("SALES_PERIOD_INVALID")
    # PostgreSQL walks only the connected receipts via indexed order/source-order edges.
    # UNION deduplicates visited IDs, including cycles; refund dates remain unbounded.
    if db.bind.dialect.name == "postgresql":
        reach = select(SalesFact.iiko_order_id.label("order_id")).where(
            *scope, SalesFact.business_date.between(start, end), SalesFact.source_order_id.is_(None),
        ).distinct().cte("sales_receipts", recursive=True)
        reach = reach.union(select(func.unnest(array([SalesFact.iiko_order_id, SalesFact.source_order_id]))).select_from(
            SalesFact).join(reach, or_(SalesFact.iiko_order_id == reach.c.order_id,
                                      SalesFact.source_order_id == reach.c.order_id)).where(*scope))
        return list(db.scalars(select(SalesFact).join(reach, SalesFact.iiko_order_id == reach.c.order_id)
                               .where(*scope).options(defer(SalesFact.raw_payload, raiseload=True))).all())
    frontier = set(db.scalars(select(SalesFact.iiko_order_id).where(
        *scope, SalesFact.business_date.between(start, end), SalesFact.source_order_id.is_(None),
    ).distinct()).all())
    visited, facts = set(), {}
    while frontier:
        # Batch IN predicates to keep the number of bound parameters bounded.
        pending = list(frontier)
        discovered = set()
        for offset in range(0, len(pending), 400):
            batch = pending[offset:offset + 400]
            rows = db.scalars(select(SalesFact).options(defer(SalesFact.raw_payload, raiseload=True)).where(*scope, or_(
                SalesFact.iiko_order_id.in_(batch), SalesFact.source_order_id.in_(batch),
            ))).all()
            for fact in rows:
                facts[fact.id] = fact
                discovered.add(fact.iiko_order_id)
                if fact.source_order_id is not None:
                    discovered.add(fact.source_order_id)
        visited.update(frontier)
        frontier = discovered - visited
    return list(facts.values())


def reconcile(db: Session, state: SalesSyncState, *,
              start: date | None = None, end: date | None = None) -> list[ReconciledOrder]:
    """Returns restate the original sale day and inherit its seller/point.

    Missing sources/ambiguous identities stay unresolved. Never count a linked
    refund receipt as an additional check. Keep raw signed measures unchanged.
    """
    facts = reconciliation_facts(db, state, start=start, end=end)
    return reconcile_loaded(facts, source_timezone=state.source_timezone,
                            mappings=retail_mappings(db, state.tenant_id),
                            links=historical_links(db, state.tenant_id, facts), start=start, end=end)


def reconcile_loaded(facts, *, source_timezone, mappings, links, start=None, end=None):
    """Pure reconciliation: all DB reads finish before this function runs."""
    receipts = defaultdict(list)
    for fact in facts:
        receipts[fact.iiko_order_id].append(fact)
    groups = defaultdict(list)
    unresolved = set()
    for order_id, items in receipts.items():
        sources = {f.source_order_id for f in items if f.source_order_id}
        if len(sources) > 1 or (sources and any(f.source_order_id is None for f in items)):
            unresolved.add(order_id)
            unresolved.update(sources)
            continue
        root = next(iter(sources)) if sources else order_id
        if root not in receipts or (sources and any(f.source_order_id for f in receipts[root])):
            unresolved.add(root)
        groups[root].extend(items)
    result = []
    for root, items in groups.items():
        originals = [f for f in items if f.iiko_order_id == root and not f.source_order_id]
        if not originals:
            continue
        employees = {employee_for_fact(None, f, source_timezone, links_by_user=links) for f in originals if f.quantity > 0 and not f.is_deleted}
        departments = {mappings.get(f.iiko_department_id) for f in originals}
        days = {f.business_date for f in originals}
        issue = "SALES_RETURN_UNRESOLVED" if (root in unresolved or any(f.iiko_order_id in unresolved for f in items)) else None
        if len(employees) != 1 or len(departments) != 1 or len(days) != 1:
            issue = "SALES_ORDER_IDENTITY_UNRESOLVED"
        products = defaultdict(lambda: [Decimal(0), Decimal(0)])
        fullness = Decimal(0)
        for fact in items:
            refund = fact.quantity < 0 and (fact.is_returned or fact.source_order_id is not None)
            if fact.is_deleted and not refund:
                continue
            money = fact.amount_after_discount
            # A0: deleted refund rows carry signed quantity, zero sales sum,
            # and positive return sum. Signed negative sales sums already include refund.
            if refund and money == 0:
                money = -abs(fact.return_amount)
            if refund and money > 0:
                issue = "SALES_RETURN_SIGN_UNRESOLVED"
            products[fact.iiko_product_id][0] += fact.quantity
            products[fact.iiko_product_id][1] += money
            if not fact.is_free and not (refund and money == 0):
                fullness += fact.quantity
        qty = sum((v[0] for v in products.values()), Decimal(0))
        revenue = sum((v[1] for v in products.values()), Decimal(0))
        if any(v[0] < 0 or v[1] < 0 for v in products.values()) or fullness < 0:
            issue = "SALES_RETURN_BALANCE_UNRESOLVED"
        result.append(ReconciledOrder(
            root, min(days), next(iter(departments)) if len(departments) == 1 else None,
            next(iter(employees)) if len(employees) == 1 else None,
            revenue, qty, fullness, {k: tuple(v) for k, v in products.items()},
            excluded=issue is not None or (qty == 0 and revenue == 0), issue=issue,
        ))
    return [order for order in result if start is None or start <= order.business_date <= end]


def seller_orders(db: Session, state: SalesSyncState, *, user,
                  start: date | None = None, end: date | None = None) -> list[ReconciledOrder]:
    """A2 seam: derive identity from authenticated User, never client employee ID."""
    if user.tenant_id != state.tenant_id or not user.is_active:
        return []
    employee_ids = db.scalars(select(Employee.id).where(
        Employee.tenant_id == state.tenant_id, Employee.linked_user_id == user.id,
    )).all()
    if len(employee_ids) != 1:
        return []
    return [order for order in reconcile(db, state, start=start, end=end) if not order.excluded
            and order.employee_id == employee_ids[0] and order.department_id is not None]


def sync_health(state: SalesSyncState, *, now: datetime) -> dict:
    stale = state.last_success_at is None or as_utc(now) - as_utc(state.last_success_at) > timedelta(minutes=30)
    return {"last_success_at": state.last_success_at, "stale": stale,
            "state": "error" if state.error_code else "stale" if stale else "ok", "error_code": state.error_code}


def unmapped_entities(db: Session, state: SalesSyncState) -> dict:
    """Internal diagnostics only; never expose this inventory in SELLER scope."""
    facts = db.scalars(select(SalesFact).where(
        SalesFact.tenant_id == state.tenant_id, SalesFact.source_id == state.source_id,
        SalesFact.is_present.is_(True),
    )).all()
    points = retail_mappings(db, state.tenant_id)
    products = set(db.scalars(select(IikoProductMapping.iiko_product_id).where(
        IikoProductMapping.tenant_id == state.tenant_id,
        IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
        IikoProductMapping.eos_product_id.is_not(None),
    )).all())
    order_ids = {f.iiko_order_id for f in facts}
    return {
        "departments": sorted({str(f.iiko_department_id) for f in facts if f.iiko_department_id not in points}),
        "employees": sorted({f.iiko_employee_id or "<missing>" for f in facts if employee_for_fact(db, f, state.source_timezone) is None}),
        "products": sorted({str(f.iiko_product_id) for f in facts if f.iiko_product_id not in products}),
        "missing_source_orders": sorted({str(f.source_order_id) for f in facts if f.source_order_id and f.source_order_id not in order_ids}),
        "unresolved_orders": {str(o.order_id): o.issue for o in reconcile(db, state) if o.issue},
    }
