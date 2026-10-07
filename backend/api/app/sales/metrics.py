"""Metrics consume the reconciled A1 view, including cross-period refunds."""
import calendar
from collections import defaultdict
from dataclasses import replace, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.core.action_context import ActionContextError, resolve_action_context
from app.models.supply import Department
from app.models.employee import Employee, EmployeeRole, EmployeeStatus
from app.models.sales import SalesSyncState, SalesTarget, SalesFact, SalesDaySync
from app.sales.service import reconcile, seller_orders, reconciliation_facts, historical_links, retail_mappings, reconcile_loaded
from app.schemas.sales import (AnalyticsRead, MetricsRead, MetricRead, PeriodKind,
    PeriodRead, StaffFilter, TargetCreate, TargetSegment)

FULL_ROLES = (EmployeeRole.ADMIN, EmployeeRole.DIRECTOR, EmployeeRole.DEPUTY_DIRECTOR,
              EmployeeRole.NETWORK_MANAGER)
PRODUCT_ROLES = FULL_ROLES + (EmployeeRole.CHEF_CONFECTIONER, EmployeeRole.HEAD_OF_PRODUCTION)


def sales_context(db, user, scope):
    """Analytics uses historical facts, never requires today's shift/department."""
    base = resolve_action_context(db, user, write=False)
    allowed = {"full": FULL_ROLES, "product": PRODUCT_ROLES,
               "self": (EmployeeRole.SELLER,), "write": (EmployeeRole.DEPUTY_DIRECTOR,)}[scope]
    role = next((r for r in allowed if r in base.roles), None)
    if role is None:
        raise ActionContextError("PERMISSION_DENIED", "Недостаточно прав для статистики продаж")
    return replace(base, authorized_as=role)


def shift_month(day: date, count: int):
    year, month = divmod(day.year * 12 + day.month - 1 + count, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period(kind: PeriodKind, *, anchor: date | None = None, start: date | None = None,
           end: date | None = None, today: date) -> PeriodRead:
    if kind == PeriodKind.CUSTOM:
        if anchor is not None or start is None or end is None:
            raise HTTPException(422, "Для произвольного периода укажите start и end без anchor")
    else:
        if start is not None or end is not None:
            raise HTTPException(422, "Для недели или месяца используйте anchor")
        anchor = anchor or today
        if anchor > today:
            raise HTTPException(422, "Будущий период недоступен")
        start = anchor - timedelta(days=anchor.weekday()) if kind == PeriodKind.WEEK else anchor.replace(day=1)
        end = start + timedelta(days=6) if kind == PeriodKind.WEEK else shift_month(start, 1) - timedelta(days=1)
    if start > end or (kind == PeriodKind.CUSTOM and end > today) or start < shift_month(today, -6):
        raise HTTPException(422, "Период должен находиться в последних шести месяцах")
    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    return PeriodRead(kind=kind, start=start, end=end, previous_start=previous_start, previous_end=previous_end)


def source_state(db, tenant_id):
    states = db.scalars(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant_id)).all()
    if len(states) != 1:
        raise HTTPException(409, "Источник статистики не определён однозначно")
    return states[0]


def source_today(state, now=None):
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(state.source_timezone)).date()


def scoped_orders(db, state, selected: PeriodRead, *, user=None, department_id=None, employee_id=None):
    bounds = dict(start=selected.previous_start, end=selected.end)
    orders = seller_orders(db, state, user=user, **bounds) if user else [
        o for o in reconcile(db, state, **bounds) if not o.excluded and o.department_id is not None]
    return [o for o in orders if (department_id is None or o.department_id == department_id)
            and (employee_id is None or o.employee_id == employee_id)]


def totals(orders):
    count = len(orders)
    revenue = sum((o.revenue for o in orders), Decimal(0))
    quantity = sum((o.fullness_quantity for o in orders), Decimal(0))
    return {"revenue": revenue, "check_count": Decimal(count),
            "average_check": revenue / count if count else None,
            "fullness": quantity / count if count else None}


def metric(fact, previous=None, target=None, *, mixed=False):
    completion = fact / target * 100 if fact is not None and target is not None else None
    status = ("no_data" if fact is None else "mixed_targets" if mixed else "no_target" if target is None
              else "green" if completion >= 100 else "red" if completion < 85 else "warning")
    change = fact - previous if fact is not None and previous is not None else None
    return MetricRead(fact=fact, previous=previous, target=target, completion_percent=completion,
                      status=status, change=change,
                      change_percent=change / previous * 100 if change is not None and previous != 0 else None)


def target_history(db, tenant_id, *, month=None, metric_name=None, kpi_only=False):
    query = select(SalesTarget).where(SalesTarget.tenant_id == tenant_id)
    if month is not None:
        query = query.where(SalesTarget.month == month)
    if metric_name is not None:
        query = query.where(SalesTarget.metric == metric_name)
    if kpi_only:
        query = query.where(SalesTarget.metric != "revenue")
    return list(db.scalars(query.order_by(SalesTarget.month, SalesTarget.metric, SalesTarget.revision)).all())


def latest_targets(db, tenant_id, *, start=None, end=None):
    ranked = select(SalesTarget.month, SalesTarget.metric, SalesTarget.value,
                    func.row_number().over(partition_by=(SalesTarget.month, SalesTarget.metric),
                                           order_by=SalesTarget.revision.desc()).label("rank")).where(
                                               SalesTarget.tenant_id == tenant_id)
    if start is not None:
        ranked = ranked.where(SalesTarget.month.between(start.replace(day=1), end.replace(day=1)))
    ranked = ranked.subquery()
    return {(month, name): value for month, name, value in db.execute(
        select(ranked.c.month, ranked.c.metric, ranked.c.value).where(ranked.c.rank == 1))}



def analytics(orders, selected: PeriodRead, targets, *, network=False, completeness=None):
    current = [o for o in orders if selected.start <= o.business_date <= selected.end]
    previous = [o for o in orders if selected.previous_start <= o.business_date <= selected.previous_end]
    actual, before = totals(current), totals(previous)
    segments = []
    day = selected.start
    while day <= selected.end:
        month = day.replace(day=1)
        stop = min(selected.end, shift_month(month, 1) - timedelta(days=1))
        values = totals([o for o in current if day <= o.business_date <= stop])
        segment = {}
        for name, fact in values.items():
            target = targets.get((month, name)) if name in {"average_check", "fullness"} else None
            # A monthly network plan is not a daily/weekly or personal KPI.
            if name == "revenue" and network and day == month and stop == shift_month(month, 1) - timedelta(days=1):
                target = targets.get((month, name))
            segment[name] = metric(fact, target=target)
        segments.append(TargetSegment(start=day, end=stop, metrics=MetricsRead(**segment)))
        day = stop + timedelta(days=1)
    result = {}
    for name, fact in actual.items():
        values = [getattr(s.metrics, name).target for s in segments]
        common = values[0] if len(set(values)) == 1 else None
        if name == "revenue" and len(segments) != 1:
            common = None
        result[name] = metric(fact, before[name], common, mixed=len(set(values)) > 1)
    dynamics = []
    by_day = defaultdict(list)
    for order in current:
        by_day[order.business_date].append(order)
    day = selected.start
    while day <= selected.end:
        daily = totals(by_day[day])
        if completeness is not None and (str(day) in completeness["current"]["missing_dates"] or day > completeness["as_of"]):
            daily = {name: None for name in daily}
        dynamics.append(dict(date=day, metrics=MetricsRead(**{name: metric(value) for name, value in daily.items()})))
        day += timedelta(days=1)
    return AnalyticsRead(period=selected, metrics=MetricsRead(**result), target_segments=segments, dynamics=dynamics, completeness=completeness)


def staff_analytics(db, tenant_id, orders, selected, targets, *, staff=StaffFilter.ACTIVE, employee_id=None, employees=None, completeness=None):
    if employees is None:
        employees = db.execute(select(Employee.id, Employee.full_name, Employee.status).where(
            Employee.tenant_id == tenant_id, Employee.id.in_({o.employee_id for o in orders}))).all()
    expected_status = EmployeeStatus.ACTIVE if staff == StaffFilter.ACTIVE else EmployeeStatus.DISMISSED
    ids = {o.employee_id for o in orders}
    employees = [e for e in employees if e.id in ids and (staff == StaffFilter.ALL or e.status == expected_status)
                 and (employee_id is None or e.id == employee_id)]
    by_employee = defaultdict(list)
    for order in orders:
        by_employee[order.employee_id].append(order)
    result = []
    for employee in sorted(employees, key=lambda e: (e.full_name, str(e.id))):
        data = analytics(by_employee[employee.id], selected, targets, completeness=completeness)
        result.append(dict(employee_id=employee.id, employee_name=employee.full_name,
                           employee_status=employee.status.value, **data.model_dump()))
    return result


def attention(rows):
    def deviation(row):
        kpis = row["metrics"]
        values = [kpis[name]["completion_percent"] for name in ("average_check", "fullness")]
        # A custom period with changing targets has no invented blended KPI.
        # Rank by the worst explicit monthly segment in that case.
        for segment in (row.get("target_segments", []) if any(
                kpis[name].get("status") == "mixed_targets" for name in ("average_check", "fullness")) else []):
            values.extend(segment["metrics"][name]["completion_percent"]
                          for name in ("average_check", "fullness"))
        return min((v for v in values if v is not None), default=Decimal(100))
    return sorted((r for r in rows if deviation(r) < 85),
                  key=lambda r: (deviation(r), str(r["employee_id"])))[:2]


def create_target(db: Session, user, body: TargetCreate):
    context = sales_context(db, user, "write")
    history = target_history(db, user.tenant_id, month=body.month, metric_name=body.metric)
    current = history[-1] if history else None
    revision = current.revision if current else 0
    if revision != body.expected_revision:
        raise HTTPException(409, "Цель уже изменена. Обновите историю и повторите действие")
    target = SalesTarget(tenant_id=user.tenant_id, metric=body.metric.value, month=body.month,
                         value=body.value, revision=revision + 1, created_by_user_id=user.id,
                         created_at=context.determined_at)
    db.add(target)
    db.flush()
    record_audit_event(db, tenant_id=user.tenant_id, event_type="SALES_TARGET_SET", entity_type="SalesTarget",
                       entity_id=target.id, operation="SET", context=context, actor_user=user,
                       before={"value": str(current.value), "revision": revision} if current else {},
                       after={"metric": body.metric.value, "month": str(body.month),
                              "value": str(body.value), "revision": target.revision})
    db.flush()
    return target


def freshness(state, now=None):
    now = now or datetime.now(timezone.utc)
    success = state.last_success_at
    if success is not None and success.tzinfo is None:
        success = success.replace(tzinfo=timezone.utc)
    return dict(last_success_at=success, stale=success is None or now - success > timedelta(minutes=30),
                update_failed=state.error_code is not None, today=source_today(state, now),
                history_from=max(state.history_from, shift_month(source_today(state, now), -6)),
                source_timezone=state.source_timezone)


def product_analytics(snapshot, *, department_id=None, iiko_product_id=None, category=None):
    selected = snapshot.selected
    values = defaultdict(lambda: [Decimal(0)] * 4)
    checks = defaultdict(set)
    days = defaultdict(lambda: defaultdict(lambda: [Decimal(0), Decimal(0)]))
    for order in snapshot.orders:
        if department_id is not None and order.department_id != department_id:
            continue
        offset = (0 if selected.start <= order.business_date <= selected.end else
                  2 if selected.previous_start <= order.business_date <= selected.previous_end else None)
        if offset is None:
            continue
        for product_id, (qty, money) in order.products.items():
            if iiko_product_id is not None and product_id != iiko_product_id:
                continue
            key = (product_id, order.department_id)
            values[key][offset] += qty
            values[key][offset + 1] += money
            if offset == 0 and (qty != 0 or money != 0):
                checks[key].add(order.order_id)
                days[key][order.business_date][0] += qty
                days[key][order.business_date][1] += money
    names = snapshot.product_names
    points = {d.id: d.name for d in snapshot.departments}
    categories = sorted({names.get(key, (None, None))[1] or "Без категории" for key in values})
    if category is not None:
        values = {key: value for key, value in values.items()
                  if (names.get(key, (None, None))[1] or "Без категории") == category}
    summaries = []
    product_ids = sorted({p for p, _ in values}, key=str)
    total_days = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for product in product_ids:
        keys = [key for key in values if key[0] == product]
        summed = [sum((values[key][i] for key in keys), Decimal(0)) for i in range(4)]
        combined_days = defaultdict(lambda: [Decimal(0), Decimal(0)])
        for key in keys:
            for day, measures in days[key].items():
                for i in range(2):
                    combined_days[day][i] += measures[i]
                    total_days[day][i] += measures[i]
        title, product_category = names.get(keys[0], (None, None))
        summaries.append(dict(iiko_product_id=product, department_id=None, product_name=title,
            category=product_category, quantity=summed[0], revenue=summed[1],
            previous_quantity=summed[2], previous_revenue=summed[3],
            check_count=len(set().union(*(checks[key] for key in keys))),
            dynamics=product_days(combined_days, selected, snapshot.completeness)))
    return dict(period=selected, completeness=snapshot.completeness, categories=categories, summaries=summaries, dynamics=product_days(total_days, selected, snapshot.completeness), products=[dict(iiko_product_id=p, department_id=d,
        product_name=names.get((p, d), (None, None))[0], category=names.get((p, d), (None, None))[1],
        department_name=points.get(d), check_count=len(checks[(p, d)]),
        dynamics=product_days(days[(p, d)], selected, snapshot.completeness),
        quantity=v[0], revenue=v[1], previous_quantity=v[2], previous_revenue=v[3])
        for (p, d), v in sorted(values.items(), key=lambda item: tuple(map(str, item[0])))])



def coverage(db, state, selected):
    today = source_today(state)
    days = set(db.scalars(select(SalesDaySync.business_date).where(
        SalesDaySync.tenant_id == state.tenant_id, SalesDaySync.source_id == state.source_id,
        SalesDaySync.business_date.between(selected.previous_start, min(selected.end, today)))))
    def segment(start, end):
        through = min(end, today)
        expected = max(0, (through - start).days + 1)
        missing = [str(start + timedelta(days=i)) for i in range(expected) if start + timedelta(days=i) not in days]
        return dict(complete=not missing, expected_days=expected, loaded_days=expected - len(missing),
                    missing_dates=missing, checked_through=through if expected else None)
    current = segment(selected.start, selected.end)
    previous = segment(selected.previous_start, selected.previous_end)
    return dict(current=current, previous=previous, as_of=today,
                warning=not current['complete'] or not previous['complete'])


@dataclass
class ReadSnapshot:
    selected: PeriodRead
    tenant_id: str
    orders: list
    targets: dict
    employees: list
    departments: list
    product_names: dict
    status: dict
    completeness: dict


def read_snapshot(db, state, selected, *, self_employee_id=None, close_session=True):
    """Load bounded, detached input; release the connection before CPU/serialization.

    No process-wide result cache: historical identity changes and late returns
    are reflected on the next read. All callers perform current RBAC first.
    """
    tenant_id, source_timezone = state.tenant_id, state.source_timezone
    status = freshness(state)
    completeness = coverage(db, state, selected)
    facts = reconciliation_facts(db, state, start=selected.previous_start, end=selected.end)
    links = historical_links(db, tenant_id, facts)
    mappings = retail_mappings(db, tenant_id)
    targets = latest_targets(db, tenant_id, start=selected.start, end=selected.end)
    employee_ids = {link.employee_id for group in links.values() for link in group}
    employees = db.execute(select(Employee.id, Employee.full_name, Employee.status).where(
        Employee.tenant_id == tenant_id, Employee.id.in_(employee_ids))).all()
    departments = db.execute(select(Department.id, Department.name).where(
        Department.tenant_id == tenant_id, Department.id.in_(set(mappings.values()))).order_by(Department.name, Department.id)).all()
    if close_session:
        db.close()
    orders = [o for o in reconcile_loaded(facts, source_timezone=source_timezone, mappings=mappings,
              links=links, start=selected.previous_start, end=selected.end) if not o.excluded and o.department_id is not None
              and (self_employee_id is None or o.employee_id == self_employee_id)]
    # Names from already-loaded factual rows. Never fetch raw JSON a second time.
    names = {}; versions = {}
    for fact in facts:
        if selected.previous_start <= fact.business_date <= selected.end:
            key = fact.iiko_product_id, mappings.get(fact.iiko_department_id)
            version = fact.seen_at, str(fact.id)
            if key not in versions or version > versions[key]:
                names[key] = fact.product_name, fact.product_category
                versions[key] = version
    return ReadSnapshot(selected, tenant_id, orders, targets, employees, departments, names, status, completeness)


def filtered_orders(snapshot, *, department_id=None, employee_id=None):
    return [o for o in snapshot.orders if (department_id is None or o.department_id == department_id)
            and (employee_id is None or o.employee_id == employee_id)]


def overview_read(snapshot, *, department_id=None, employee_id=None):
    return analytics(filtered_orders(snapshot, department_id=department_id, employee_id=employee_id),
                     snapshot.selected, snapshot.targets, network=department_id is None and employee_id is None,
                     completeness=snapshot.completeness)


def points_read(snapshot):
    grouped = defaultdict(list)
    for order in snapshot.orders: grouped[order.department_id].append(order)
    return [dict(department_id=d.id, department_name=d.name,
            **analytics(grouped[d.id], snapshot.selected, snapshot.targets, completeness=snapshot.completeness).model_dump())
            for d in snapshot.departments if d.id in grouped]


def sellers_read(snapshot, *, department_id=None, employee_id=None, staff=StaffFilter.ACTIVE):
    return staff_analytics(None, snapshot.tenant_id, filtered_orders(snapshot, department_id=department_id),
        snapshot.selected, snapshot.targets, staff=staff, employee_id=employee_id,
        employees=snapshot.employees, completeness=snapshot.completeness)


def product_days(values, selected, completeness):
    missing = set(completeness['current']['missing_dates'])
    rows = []
    day = selected.start
    while day <= selected.end:
        valid = str(day) not in missing and day <= completeness['as_of']
        quantity, revenue = values.get(day, (Decimal(0), Decimal(0))) if valid else (None, None)
        rows.append(dict(date=day, quantity=quantity, revenue=revenue))
        day += timedelta(days=1)
    return rows


def workspace_read(snapshot, *, view, department_id=None, employee_id=None, staff=StaffFilter.ACTIVE,
                   iiko_product_id=None, category=None):
    result = dict(status=snapshot.status, completeness=snapshot.completeness)
    if view == 'me':
        result['analytics'] = analytics(snapshot.orders, snapshot.selected, snapshot.targets,
                                       completeness=snapshot.completeness)
        return result
    if view != 'products':
        result['analytics'] = overview_read(snapshot, department_id=department_id, employee_id=employee_id)
        result['points'] = points_read(snapshot)
        result['sellers'] = sellers_read(snapshot, department_id=department_id, staff=staff)
    if view == 'products' or (view in {'overview', 'points'} and employee_id is None):
        result['products'] = product_analytics(snapshot, department_id=department_id,
                                              iiko_product_id=iiko_product_id, category=category)
    return result


def seller_product_mix(snapshot, *, employee_id, department_id=None, iiko_product_id=None, category=None):
    if employee_id is None:
        raise HTTPException(403, "Личная статистика недоступна без сотрудника")
    orders = filtered_orders(snapshot, department_id=department_id, employee_id=employee_id)
    total = sum((o.revenue for o in orders if snapshot.selected.start <= o.business_date <= snapshot.selected.end), Decimal(0))
    products = product_analytics(replace(snapshot, orders=orders),
        iiko_product_id=iiko_product_id, category=category)
    return dict(employee_id=employee_id, employee_name=next((e.full_name for e in snapshot.employees if e.id == employee_id), None),
        period=snapshot.selected, completeness=snapshot.completeness,
        revenue=total, dynamics=products['dynamics'], categories=products['categories'],
        products=[dict(row, share_percent=row['revenue'] / total * 100 if total else None,
            quantity_change=row['quantity'] - row['previous_quantity'],
            revenue_change=row['revenue'] - row['previous_revenue']) for row in products['summaries']])
