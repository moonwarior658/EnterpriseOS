"""Final reports use EOS facts only; live analytics and final snapshots stay separate."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select
from fastapi import HTTPException
from app.models.sales import SalesPeriodSnapshot, SalesSyncState, SalesDaySync, SalesTarget
from app.sales import metrics
from app.schemas.sales import PeriodKind, StaffFilter, WorkspaceRead, TargetRead

ACTION = 'sales.finalize_reports'


def closed_periods(state, kind, *, today=None):
    today = today or metrics.source_today(state)
    first = max(state.history_from, metrics.shift_month(today, -6))
    anchor = today - timedelta(days=today.weekday() + 7) if kind == 'week' else metrics.shift_month(today.replace(day=1), -1)
    periods = []
    while anchor >= first:
        selected = metrics.period(PeriodKind(kind), anchor=anchor, today=today)
        periods.append(selected)
        anchor = anchor - timedelta(days=7) if kind == 'week' else metrics.shift_month(anchor, -1)
    return periods


def readiness(db, state, selected):
    coverage = metrics.coverage(db, state, selected)
    if selected.end >= metrics.source_today(state):
        return coverage, 'Период ещё не закрыт'
    if coverage['warning']:
        return coverage, ('Период ещё не догружен: отсутствуют дни выбранного периода или периода сравнения')
    # A successful intraday read is not a complete closed day.
    checkpoints = list(db.execute(select(SalesDaySync.business_date, SalesDaySync.last_success_at).where(
        SalesDaySync.tenant_id == state.tenant_id, SalesDaySync.source_id == state.source_id,
        SalesDaySync.business_date.between(selected.previous_start, selected.end))))
    zone = ZoneInfo(state.source_timezone)
    for day, stamp in checkpoints:
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
        if stamp.astimezone(zone).date() <= day:
            return coverage, 'Ожидается загрузка полных закрытых дней после окончания периода'
    return coverage, None


def product_changes(products):
    rows = [dict(iiko_product_id=p['iiko_product_id'], product_name=p['product_name'],
                 quantity=p['quantity'], previous_quantity=p['previous_quantity'],
                 revenue=p['revenue'], previous_revenue=p['previous_revenue'],
                 revenue_change=str(Decimal(p['revenue']) - Decimal(p['previous_revenue'])))
            for p in products['summaries']]
    return dict(growth=sorted((p for p in rows if Decimal(p['revenue_change']) > 0),
                             key=lambda p: (-Decimal(p['revenue_change']), str(p['iiko_product_id'])))[:5],
                decline=sorted((p for p in rows if Decimal(p['revenue_change']) < 0),
                              key=lambda p: (Decimal(p['revenue_change']), str(p['iiko_product_id'])))[:5])


def capture(db, state, selected, *, now):
    # The caller holds this source row lock, shared with daily ingestion.
    existing = db.scalar(select(SalesPeriodSnapshot).where(SalesPeriodSnapshot.tenant_id == state.tenant_id,
        SalesPeriodSnapshot.kind == selected.kind.value, SalesPeriodSnapshot.period_start == selected.start))
    if existing is not None:
        return existing, None
    completeness, reason = readiness(db, state, selected)
    if reason:
        return None, reason
    targets = list(db.scalars(select(SalesTarget).where(SalesTarget.tenant_id == state.tenant_id,
        SalesTarget.month.between(selected.start.replace(day=1), selected.end.replace(day=1)))
        .order_by(SalesTarget.month, SalesTarget.metric, SalesTarget.revision)))
    snapshot = metrics.read_snapshot(db, state, selected, close_session=False)
    # Freeze the same revisions as the stored target history, even if a later revision is appended concurrently.
    snapshot.targets = {(t.month, t.metric): t.value for t in targets}
    payload = WorkspaceRead(status=snapshot.status, completeness=completeness,
        analytics=metrics.overview_read(snapshot), points=metrics.points_read(snapshot),
        sellers=metrics.sellers_read(snapshot, staff=StaffFilter.ALL),
        products=metrics.product_analytics(snapshot)).model_dump(mode='json')
    payload['targets'] = [TargetRead.model_validate(t).model_dump(mode='json') for t in targets]
    payload['product_changes'] = product_changes(payload['products'])
    row = SalesPeriodSnapshot(tenant_id=state.tenant_id, source_id=state.source_id,
        kind=selected.kind.value, period_start=selected.start, period_end=selected.end,
        format_version=1, created_at=now, payload=payload)
    db.add(row); db.flush()
    return row, None


def finalize_reports(db, context, payload):
    # Runs in the existing local executor transaction: snapshots and terminal result commit together.
    if payload:
        raise ValueError('SALES_REPORT_PAYLOAD_INVALID')
    state = metrics.source_state(db, context.tenant_id)
    state = db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == state.tenant_id,
        SalesSyncState.source_id == state.source_id).with_for_update())
    results = []
    for kind in ('week', 'month'):
        for selected in closed_periods(state, kind):
            row, reason = capture(db, state, selected, now=context.executed_at)
            results.append(dict(kind=kind, start=str(selected.start), ready=row is not None, reason=reason, snapshot_id=str(row.id) if row else None))
    return dict(periods=results)


def report_list(db, tenant_id, kind):
    state = metrics.source_state(db, tenant_id)
    periods = closed_periods(state, kind)
    rows = {row.period_start: row for row in db.scalars(select(SalesPeriodSnapshot).where(
        SalesPeriodSnapshot.tenant_id == tenant_id, SalesPeriodSnapshot.kind == kind,
        SalesPeriodSnapshot.period_start.in_([p.start for p in periods])))}
    result = []
    for selected in periods:
        row = rows.get(selected.start)
        completeness, reason = (row.payload['completeness'], None) if row else readiness(db, state, selected)
        result.append(dict(id=str(row.id) if row else None, kind=kind, start=str(selected.start), end=str(selected.end),
            created_at=row.created_at if row else None, ready=row is not None,
            reason=reason or ('Ожидается автоматическое формирование' if row is None else None), completeness=completeness))
    return result


def report_read(db, tenant_id, report_id, *, products_only=False):
    row = db.scalar(select(SalesPeriodSnapshot).where(SalesPeriodSnapshot.id == report_id,
                                                  SalesPeriodSnapshot.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(404, 'Отчёт не найден')
    state = metrics.source_state(db, tenant_id)
    if row.period_start < metrics.shift_month(metrics.source_today(state), -6):
        raise HTTPException(422, 'Доступны отчёты последних шести месяцев')
    payload = row.payload
    if products_only:
        payload = {k: payload[k] for k in ('products', 'product_changes', 'completeness', 'status')}
    return dict(id=str(row.id), kind=row.kind, start=str(row.period_start), end=str(row.period_end),
        created_at=row.created_at, format_version=row.format_version, data=payload)
