"""Role-scoped API. No source IDs, raw events or seller-selectable identity."""
import asyncio
from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from weakref import WeakKeyDictionary

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.action_context import action_context_http_error
from app.core.action_context import ActionContextError
from app.db.session import get_db
from app.models.user import User
from app.sales import metrics as service
from app.schemas.sales import (AnalyticsRead, EmployeeAnalyticsRead, PointAnalyticsRead,
    WorkspaceRead, FreshnessRead, PeriodKind, ProductsRead, StaffFilter, TargetCreate, TargetRead, TargetMetric)

router = APIRouter(prefix="/sales/analytics", tags=["sales analytics"])
_read_slots = WeakKeyDictionary()


async def analytics_read_slot(request: Request):
    """Queue reads before authentication checks out a connection; leave pool room for other work."""
    if request.method != "GET":
        yield
        return
    loop = asyncio.get_running_loop()
    slots = _read_slots.setdefault(loop, asyncio.Semaphore(4))
    async with slots:
        yield


router.dependencies.append(Depends(analytics_read_slot))
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]


def require(db, user, scope):
    try:
        return service.sales_context(db, user, scope)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


def no_extra_query(request: Request, response: Response):
    allowed = {p.alias for p in request.scope["route"].dependant.query_params}
    if set(request.query_params) - allowed:
        raise HTTPException(422, "Недопустимый фильтр статистики")
    response.headers["Cache-Control"] = "no-store"


router.dependencies.append(Depends(no_extra_query))


def selection(db, user, kind, anchor, start, end):
    state = service.source_state(db, user.tenant_id)
    selected = service.period(kind, anchor=anchor, start=start, end=end, today=service.source_today(state))
    return state, selected


def read(db, user, response, scope, kind, anchor, start, end):
    context = require(db, user, scope)
    state, selected = selection(db, user, kind, anchor, start, end)
    snapshot = service.read_snapshot(db, state, selected,
        self_employee_id=context.employee_id if scope == "self" else None)
    response.headers["X-Sales-Data-Complete"] = str(not snapshot.completeness['warning']).lower()
    return snapshot


@router.get("/me", response_model=AnalyticsRead)
def me(db: Db, current_user: Actor, response: Response, period: PeriodKind = PeriodKind.MONTH,
       anchor: date | None = None, start: date | None = None, end: date | None = None):
    snapshot = read(db, current_user, response, "self", period, anchor, start, end)
    return service.analytics(snapshot.orders, snapshot.selected, snapshot.targets, completeness=snapshot.completeness)


@router.get("/overview", response_model=AnalyticsRead)
def overview(db: Db, current_user: Actor, response: Response, period: PeriodKind = PeriodKind.MONTH,
             anchor: date | None = None, start: date | None = None, end: date | None = None,
             department_id: UUID | None = None, employee_id: UUID | None = None):
    snapshot = read(db, current_user, response, "full", period, anchor, start, end)
    return service.overview_read(snapshot, department_id=department_id, employee_id=employee_id)


@router.get("/points", response_model=list[PointAnalyticsRead])
def points(db: Db, current_user: Actor, response: Response, period: PeriodKind = PeriodKind.MONTH,
           anchor: date | None = None, start: date | None = None, end: date | None = None):
    return service.points_read(read(db, current_user, response, "full", period, anchor, start, end))


@router.get("/sellers", response_model=list[EmployeeAnalyticsRead])
def sellers(db: Db, current_user: Actor, response: Response, period: PeriodKind = PeriodKind.MONTH,
            anchor: date | None = None, start: date | None = None, end: date | None = None,
            department_id: UUID | None = None, employee_id: UUID | None = None,
            staff: StaffFilter = StaffFilter.ACTIVE):
    snapshot = read(db, current_user, response, "full", period, anchor, start, end)
    return service.sellers_read(snapshot, department_id=department_id, employee_id=employee_id, staff=staff)


@router.get("/attention", response_model=list[EmployeeAnalyticsRead])
def attention(db: Db, current_user: Actor, response: Response, period: PeriodKind = PeriodKind.MONTH,
              anchor: date | None = None, start: date | None = None, end: date | None = None):
    snapshot = read(db, current_user, response, "full", period, anchor, start, end)
    return service.attention(service.sellers_read(snapshot))


@router.get("/products", response_model=ProductsRead)
def products(db: Db, current_user: Actor, response: Response, period: PeriodKind = PeriodKind.MONTH,
             anchor: date | None = None, start: date | None = None, end: date | None = None,
             department_id: UUID | None = None, iiko_product_id: UUID | None = None, category: str | None = None):
    snapshot = read(db, current_user, response, "product", period, anchor, start, end)
    return service.product_analytics(snapshot, department_id=department_id, iiko_product_id=iiko_product_id, category=category)


@router.get("/status", response_model=FreshnessRead)
def status(db: Db, current_user: Actor):
    try:
        service.sales_context(db, current_user, "product")
    except ActionContextError:
        require(db, current_user, "self")
    result = service.freshness(service.source_state(db, current_user.tenant_id))
    db.close()
    return result


@router.get("/workspace", response_model=WorkspaceRead)
def workspace(db: Db, current_user: Actor, response: Response,
              view: Literal["overview", "points", "sellers", "products", "me"] = "overview",
              period: PeriodKind = PeriodKind.MONTH, anchor: date | None = None,
              start: date | None = None, end: date | None = None,
              department_id: UUID | None = None, employee_id: UUID | None = None,
              staff: StaffFilter = StaffFilter.ACTIVE,
              iiko_product_id: UUID | None = None, category: str | None = None):
    if view == "me" and (department_id is not None or employee_id is not None or staff != StaffFilter.ACTIVE
                         or iiko_product_id is not None or category is not None):
        raise HTTPException(422, "Недопустимый фильтр личной статистики")
    if view == "products" and (employee_id is not None or staff != StaffFilter.ACTIVE):
        raise HTTPException(422, "Недопустимый фильтр продукции")
    scope = "self" if view == "me" else "product" if view == "products" else "full"
    snapshot = read(db, current_user, response, scope, period, anchor, start, end)
    return service.workspace_read(snapshot, view=view, department_id=department_id,
        employee_id=employee_id, staff=staff, iiko_product_id=iiko_product_id, category=category)


@router.get("/targets", response_model=list[TargetRead])
def targets(db: Db, current_user: Actor, month: date | None = None, metric: TargetMetric | None = None):
    try:
        service.sales_context(db, current_user, "full")
        kpi_only = False
    except ActionContextError:
        require(db, current_user, "self")
        kpi_only = True
        if metric == TargetMetric.REVENUE:
            raise HTTPException(403, "План выручки сети недоступен")
    result = service.target_history(db, current_user.tenant_id, month=month, metric_name=metric, kpi_only=kpi_only)
    db.close()
    return result


@router.post("/targets", response_model=TargetRead, status_code=201)
def set_target(body: TargetCreate, db: Db, current_user: Actor):
    require(db, current_user, "write")
    try:
        target = service.create_target(db, current_user, body)
        db.commit()
        db.refresh(target)
        return target
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "Цель уже изменена. Обновите историю и повторите действие") from error
    except Exception:
        db.rollback()
        raise


@router.get('/reports')
def list_reports(db: Db, current_user: Actor, kind: Literal['week', 'month'] = 'week',
                 scope: Literal['full', 'products'] = 'full'):
    from app.sales.reports import report_list
    require(db, current_user, 'product' if scope == 'products' else 'full')
    return report_list(db, current_user.tenant_id, kind)


@router.get('/reports/{report_id}')
def get_report(report_id: UUID, db: Db, current_user: Actor,
               scope: Literal['full', 'products'] = 'full'):
    from app.sales.reports import report_read
    require(db, current_user, 'product' if scope == 'products' else 'full')
    return report_read(db, current_user.tenant_id, report_id, products_only=scope == 'products')


def export_response(data, *, view, file_format, metadata):
    from app.sales.export import excel, pdf, export_tables
    tables = export_tables(data, view=view, metadata=metadata)
    try:
        content = excel(tables) if file_format == 'xlsx' else pdf(tables)
    except Exception as error:
        raise HTTPException(503, 'Не удалось сформировать файл экспорта') from error
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if file_format == 'xlsx' else 'application/pdf',
        headers={'Content-Disposition': f'attachment; filename="sales-{view}.{file_format}"', 'Cache-Control': 'no-store'})


@router.get('/reports/{report_id}/export')
def export_report(report_id: UUID, db: Db, current_user: Actor,
                  format: Literal['xlsx', 'pdf'] = 'xlsx', scope: Literal['full', 'products'] = 'full'):
    from app.sales.reports import report_read
    require(db, current_user, 'product' if scope == 'products' else 'full')
    report = report_read(db, current_user.tenant_id, report_id, products_only=scope == 'products')
    db.close()
    return export_response(report['data'], view='report', file_format=format,
        metadata={'Отчёт': 'Неделя' if report['kind'] == 'week' else 'Месяц', 'С': report['start'],
                  'По': report['end'], 'Зафиксирован': report['created_at'], 'Область': scope})


@router.get('/export')
def export_live(db: Db, current_user: Actor, response: Response,
                view: Literal['overview', 'points', 'sellers', 'products'] = 'overview',
                format: Literal['xlsx', 'pdf'] = 'xlsx', period: PeriodKind = PeriodKind.MONTH,
                anchor: date | None = None, start: date | None = None, end: date | None = None,
                department_id: UUID | None = None, employee_id: UUID | None = None,
                staff: StaffFilter = StaffFilter.ACTIVE, iiko_product_id: UUID | None = None,
                category: str | None = None):
    require(db, current_user, 'product' if view == 'products' else 'full')
    if view == 'products' and (employee_id is not None or staff != StaffFilter.ACTIVE):
        raise HTTPException(422, 'Недопустимый фильтр продукции')
    state, selected = selection(db, current_user, period, anchor, start, end)
    snapshot = service.read_snapshot(db, state, selected)
    data = WorkspaceRead.model_validate(service.workspace_read(snapshot, view=view, department_id=department_id,
        employee_id=employee_id, staff=staff, iiko_product_id=iiko_product_id, category=category)).model_dump(mode='json')
    # Match the visible tables, including client-side selection within the workspace.
    data['points'] = [p for p in data['points'] if department_id is None or p['department_id'] == str(department_id)] if employee_id is None else []
    data['sellers'] = [s for s in data['sellers'] if employee_id is None or s['employee_id'] == str(employee_id)]
    return export_response(data, view=view, file_format=format, metadata={
        'Режим': 'Актуальная статистика', 'С': selected.start, 'По': selected.end,
        'Сравнение с': selected.previous_start, 'Сравнение по': selected.previous_end,
        'Раздел': view, 'Точка': department_id or 'Все', 'Продавец': employee_id or 'Все',
        'Статус продавцов': staff.value, 'Позиция': iiko_product_id or 'Все', 'Категория': category or 'Все'})
