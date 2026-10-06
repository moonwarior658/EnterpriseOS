"""Metrics consume the reconciled A1 view, including cross-period refunds."""
import calendar
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.core.action_context import ActionContextError, resolve_action_context
from app.models.employee import Employee, EmployeeRole, EmployeeStatus
from app.models.sales import SalesSyncState, SalesTarget
from app.sales.service import reconcile, seller_orders
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


def latest_targets(db, tenant_id):
    return {(t.month, t.metric): t.value for t in target_history(db, tenant_id)}


def analytics(orders, selected: PeriodRead, targets, *, network=False):
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
    return AnalyticsRead(period=selected, metrics=MetricsRead(**result), target_segments=segments)


def staff_analytics(db, tenant_id, orders, selected, targets, *, staff=StaffFilter.ACTIVE, employee_id=None):
    query = select(Employee).where(Employee.tenant_id == tenant_id)
    if staff != StaffFilter.ALL:
        query = query.where(Employee.status == (EmployeeStatus.ACTIVE if staff == StaffFilter.ACTIVE else EmployeeStatus.DISMISSED))
    if employee_id is not None:
        query = query.where(Employee.id == employee_id)
    # Include only attributable sellers in current or comparison period; no current-role inference.
    ids = {o.employee_id for o in orders if selected.previous_start <= o.business_date <= selected.end}
    result = []
    for employee in db.scalars(query.where(Employee.id.in_(ids)).order_by(Employee.full_name, Employee.id)):
        data = analytics([o for o in orders if o.employee_id == employee.id], selected, targets)
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
