"""Role-scoped API. No source IDs, raw events or seller-selectable identity."""
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.action_context import action_context_http_error
from app.core.action_context import ActionContextError
from app.db.session import get_db
from app.models.supply import Department
from app.models.user import User
from app.sales import metrics as service
from app.schemas.sales import (AnalyticsRead, EmployeeAnalyticsRead, PointAnalyticsRead,
    FreshnessRead, PeriodKind, ProductsRead, StaffFilter, TargetCreate, TargetRead, TargetMetric)

router = APIRouter(prefix="/sales/analytics", tags=["sales analytics"])
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


@router.get("/me", response_model=AnalyticsRead)
def me(db: Db, current_user: Actor, period: PeriodKind = PeriodKind.MONTH,
       anchor: date | None = None, start: date | None = None, end: date | None = None):
    require(db, current_user, "self")
    state, selected = selection(db, current_user, period, anchor, start, end)
    orders = service.scoped_orders(db, state, selected, user=current_user)
    return service.analytics(orders, selected, service.latest_targets(db, current_user.tenant_id))


@router.get("/overview", response_model=AnalyticsRead)
def overview(db: Db, current_user: Actor, period: PeriodKind = PeriodKind.MONTH,
             anchor: date | None = None, start: date | None = None, end: date | None = None,
             department_id: UUID | None = None, employee_id: UUID | None = None):
    require(db, current_user, "full")
    state, selected = selection(db, current_user, period, anchor, start, end)
    return service.analytics(service.scoped_orders(db, state, selected, department_id=department_id, employee_id=employee_id),
                             selected, service.latest_targets(db, current_user.tenant_id),
                             network=department_id is None and employee_id is None)


@router.get("/points", response_model=list[PointAnalyticsRead])
def points(db: Db, current_user: Actor, period: PeriodKind = PeriodKind.MONTH,
           anchor: date | None = None, start: date | None = None, end: date | None = None):
    require(db, current_user, "full")
    state, selected = selection(db, current_user, period, anchor, start, end)
    orders = service.scoped_orders(db, state, selected)
    ids = {o.department_id for o in orders if selected.previous_start <= o.business_date <= selected.end}
    targets = service.latest_targets(db, current_user.tenant_id)
    return [dict(department_id=d.id, department_name=d.name,
                 **service.analytics([o for o in orders if o.department_id == d.id], selected, targets).model_dump())
            for d in db.scalars(select(Department).where(Department.tenant_id == current_user.tenant_id,
                                                        Department.id.in_(ids)).order_by(Department.name, Department.id))]


@router.get("/sellers", response_model=list[EmployeeAnalyticsRead])
def sellers(db: Db, current_user: Actor, period: PeriodKind = PeriodKind.MONTH,
            anchor: date | None = None, start: date | None = None, end: date | None = None,
            department_id: UUID | None = None, employee_id: UUID | None = None,
            staff: StaffFilter = StaffFilter.ACTIVE):
    require(db, current_user, "full")
    state, selected = selection(db, current_user, period, anchor, start, end)
    return service.staff_analytics(db, current_user.tenant_id,
        service.scoped_orders(db, state, selected, department_id=department_id), selected,
        service.latest_targets(db, current_user.tenant_id), staff=staff, employee_id=employee_id)


@router.get("/attention", response_model=list[EmployeeAnalyticsRead],
            description="Два активных продавца с худшим выполнением одного KPI ниже 85%. "
                        "При разных месячных целях используется худший месячный сегмент.")
def attention(db: Db, current_user: Actor, period: PeriodKind = PeriodKind.MONTH,
              anchor: date | None = None, start: date | None = None, end: date | None = None):
    require(db, current_user, "full")
    state, selected = selection(db, current_user, period, anchor, start, end)
    rows = service.staff_analytics(db, current_user.tenant_id, service.scoped_orders(db, state, selected),
                                   selected, service.latest_targets(db, current_user.tenant_id))
    return service.attention(rows)


@router.get("/products", response_model=ProductsRead)
def products(db: Db, current_user: Actor, period: PeriodKind = PeriodKind.MONTH,
             anchor: date | None = None, start: date | None = None, end: date | None = None,
             department_id: UUID | None = None, iiko_product_id: UUID | None = None, category: str | None = None):
    require(db, current_user, "product")
    state, selected = selection(db, current_user, period, anchor, start, end)
    return service.product_analytics(db, state, selected, department_id=department_id,
                                     iiko_product_id=iiko_product_id, category=category)


@router.get("/status", response_model=FreshnessRead)
def status(db: Db, current_user: Actor):
    try:
        service.sales_context(db, current_user, "product")
    except ActionContextError:
        require(db, current_user, "self")
    return service.freshness(service.source_state(db, current_user.tenant_id))



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
    return service.target_history(db, current_user.tenant_id, month=month, metric_name=metric, kpi_only=kpi_only)


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
