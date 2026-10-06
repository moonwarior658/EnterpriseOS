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
    result = dict(status=snapshot.status, completeness=snapshot.completeness)
    if view == "me":
        result['analytics'] = service.analytics(snapshot.orders, snapshot.selected, snapshot.targets,
                                                completeness=snapshot.completeness)
        return result
    if view != "products":
        result['analytics'] = service.overview_read(snapshot, department_id=department_id, employee_id=employee_id)
        result['points'] = service.points_read(snapshot)
        result['sellers'] = service.sellers_read(snapshot, department_id=department_id, staff=staff)
    if view == "products" or (view in {"overview", "points"} and employee_id is None):
        result['products'] = service.product_analytics(snapshot, department_id=department_id,
                                                       iiko_product_id=iiko_product_id, category=category)
    return result


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
