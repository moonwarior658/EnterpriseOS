from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_supply_reader, get_supply_operator
from app.core.action_context import ActionContextError, resolve_action_context
from app.core.authorization import Capability, Scope, authorize, scoped_department_ids
from app.db.session import get_db
from app.models.employee import EmployeeRole
from app.models.supply import (
    SupplyPurchaseRequest, SupplyPurchaseRequestLine, SupplyPurchaseRequestLineSource,
    SupplyPurchaseAllocationSource, SupplyPurchaseAllocation, SupplyProcurementNeed,
    SupplyRequestLine, SupplyRequest,
)
from app.models.user import User
from app.schemas.purchase_request import (
    SupplyPurchaseRequestCreate,
    SupplyPurchaseRequestLineCreate,
    SupplyPurchaseRequestLineUpdate,
    SupplyPurchaseRequestPage,
    SupplyPurchaseRequestRead,
    SupplyPurchaseRequestCoverageRead,
    SupplyPurchaseRequestUpdate,
    ProductionProcurementCardRead,
)
from app.schemas.purchase_allocation import (
    SupplyPurchaseAllocationCreate,
    SupplyPurchaseAllocationSourcesUpdate,
    SupplyPurchaseAllocationUpdate,
    SupplyPurchaseAllocationWorkspaceRead,
)
from app.supply.purchase_allocations import (
    DuplicatePurchaseAllocationError,
    PurchaseAllocationEligibilityError,
    PurchaseAllocationNotFoundError,
    PurchaseAllocationStateError,
    confirm_purchase_allocation,
    create_purchase_allocation,
    delete_purchase_allocation,
    get_purchase_allocation_workspace,
    update_purchase_allocation,
    update_purchase_allocation_sources,
)
from app.supply.purchase_requests import (
    DuplicatePurchaseRequestLineError,
    PurchaseRequestEmptyError,
    PurchaseRequestLineNotFoundError,
    PurchaseRequestNotFoundError,
    PurchaseRequestProductNotFoundError,
    PurchaseRequestSourceConflictError,
    PurchaseRequestStateError,
    PurchaseRequestUnitNotFoundError,
    add_purchase_request_line,
    cancel_purchase_request,
    collect_purchase_request_needs,
    create_purchase_request,
    delete_purchase_request_line,
    get_purchase_request,
    get_purchase_request_coverage,
    list_purchase_requests,
    mark_purchase_request_ready,
    update_purchase_request,
    update_purchase_request_line,
)
from app.schemas.supplier_order import SupplySupplierOrderCreationResult
from app.supply.supplier_orders import (
    SupplierOrderConflictError,
    SupplierOrderNotFoundError,
    SupplierOrderStateError,
    create_supplier_orders,
)


router = APIRouter(prefix="/supply/purchase-requests", tags=["supply"])


def _production_procurement(db: Session, user: User, request_id: UUID | None = None):
    try:
        actor = resolve_action_context(db, user, write=False)
    except ActionContextError as error:
        raise HTTPException(status_code=403, detail=error.message) from error
    if not actor.roles.intersection({EmployeeRole.HEAD_OF_PRODUCTION, EmployeeRole.CHEF_CONFECTIONER}):
        raise HTTPException(status_code=403, detail="Недостаточно прав для просмотра закупок производства")
    departments = scoped_department_ids(db, user, Scope.PRODUCTION, actor)
    if not departments:
        return []
    query = (select(SupplyPurchaseRequest, SupplyPurchaseRequestLineSource)
             .join(SupplyPurchaseRequestLine, SupplyPurchaseRequestLine.purchase_request_id == SupplyPurchaseRequest.id)
             .join(SupplyPurchaseRequestLineSource, SupplyPurchaseRequestLineSource.purchase_request_line_id == SupplyPurchaseRequestLine.id)
             .join(SupplyProcurementNeed, SupplyProcurementNeed.id == SupplyPurchaseRequestLineSource.procurement_need_id)
             .join(SupplyRequestLine, SupplyRequestLine.id == SupplyProcurementNeed.supply_request_line_id)
             .join(SupplyRequest, SupplyRequest.id == SupplyRequestLine.request_id)
             .where(SupplyPurchaseRequest.tenant_id == user.tenant_id,
                    SupplyRequest.tenant_id == user.tenant_id,
                    SupplyRequest.department_id.in_(departments),
                    SupplyProcurementNeed.source_type == "REQUEST_LINE"))
    if request_id is not None:
        query = query.where(SupplyPurchaseRequest.id == request_id)
    rows = db.execute(query.order_by(SupplyPurchaseRequest.created_at.desc())).all()
    cards = {}
    for purchase, source in rows:
        line = source.line
        card = cards.setdefault(purchase.id, {
            "id": purchase.id, "number": purchase.number,
            "need_date": purchase.need_date, "status": purchase.status, "lines": {},
        })
        scoped_line = card["lines"].setdefault(line.id, {
            "product_name": line.product.name, "quantity": Decimal(0),
            "unit_name": line.unit.short_name_ru, "allocations": [],
        })
        scoped_line["quantity"] += source.quantity
        for allocated_source in source.allocation_sources:
            allocation = allocated_source.allocation
            quantity = allocated_source.allocated_quantity
            scoped_line["allocations"].append({
                "quantity": quantity,
                "unit_price": allocation.base_unit_price_snapshot,
                "amount": quantity * allocation.base_unit_price_snapshot,
            })
    return [{**card, "lines": list(card["lines"].values())} for card in cards.values()]


@router.get("/production", response_model=list[ProductionProcurementCardRead])
def read_production_procurement(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[ProductionProcurementCardRead]:
    return _production_procurement(db, user)


@router.get("/production/{request_id}", response_model=ProductionProcurementCardRead)
def read_production_procurement_card(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ProductionProcurementCardRead:
    cards = _production_procurement(db, user, request_id)
    if not cards:
        raise _not_found()
    return cards[0]


@router.post(
    "/{request_id}/supplier-orders",
    response_model=SupplySupplierOrderCreationResult,
    status_code=status.HTTP_201_CREATED,
)
def create_orders_from_allocations(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplySupplierOrderCreationResult:
    try:
        context = authorize(db, admin, Capability.SUPPLY_OPERATE, write=True)
        return SupplySupplierOrderCreationResult(orders=create_supplier_orders(
            db, request_id, tenant_id=admin.tenant_id, user_id=admin.id,
            audit_context=context, actor_user=admin,
        ))
    except SupplierOrderNotFoundError as error:
        raise _not_found() from error
    except SupplierOrderStateError as error:
        raise HTTPException(status_code=409, detail="Формировать заказы можно только из зафиксированного закупочного запроса") from error
    except SupplierOrderConflictError as error:
        raise HTTPException(status_code=409, detail="Заказы уже формируются или распределения уже используются") from error


def _not_found(detail: str = "Закупочный запрос не найден") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _state_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Изменять можно только черновик закупочного запроса",
    )


def _get(
    db: Session, request_id: UUID, admin: User
) -> SupplyPurchaseRequest:
    try:
        return get_purchase_request(db, request_id, tenant_id=admin.tenant_id)
    except PurchaseRequestNotFoundError as error:
        raise _not_found() from error


@router.get("", response_model=SupplyPurchaseRequestPage)
def read_purchase_requests(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_reader)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplyPurchaseRequestPage:
    items, total = list_purchase_requests(
        db, tenant_id=admin.tenant_id, limit=limit, offset=offset
    )
    return SupplyPurchaseRequestPage(
        items=items, total=total, limit=limit, offset=offset
    )


@router.post(
    "", response_model=SupplyPurchaseRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: SupplyPurchaseRequestCreate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    return create_purchase_request(
        db, payload, tenant_id=admin.tenant_id, user_id=admin.id
    )


@router.get("/{request_id}", response_model=SupplyPurchaseRequestRead)
def read_purchase_request(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_reader)],
) -> SupplyPurchaseRequest:
    return _get(db, request_id, admin)


@router.get("/{request_id}/coverage", response_model=SupplyPurchaseRequestCoverageRead)
def read_purchase_request_coverage(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_reader)],
) -> SupplyPurchaseRequestCoverageRead:
    try:
        return get_purchase_request_coverage(db, request_id, tenant_id=admin.tenant_id)
    except PurchaseRequestNotFoundError as error:
        raise _not_found() from error


@router.patch("/{request_id}", response_model=SupplyPurchaseRequestRead)
def update_request(
    request_id: UUID,
    payload: SupplyPurchaseRequestUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    try:
        return update_purchase_request(db, _get(db, request_id, admin), payload)
    except PurchaseRequestStateError as error:
        raise _state_error() from error


@router.post("/{request_id}/ready", response_model=SupplyPurchaseRequestRead)
def ready_request(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    try:
        return mark_purchase_request_ready(db, _get(db, request_id, admin))
    except PurchaseRequestEmptyError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Добавьте хотя бы одну строку",
        ) from error
    except PurchaseRequestSourceConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Потребность изменилась. Повторно соберите потребность перед фиксацией",
        ) from error
    except PurchaseRequestStateError as error:
        raise _state_error() from error


@router.post("/{request_id}/collect-needs", response_model=SupplyPurchaseRequestRead)
def collect_needs(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    try:
        return collect_purchase_request_needs(db, _get(db, request_id, admin))
    except PurchaseRequestStateError as error:
        raise _state_error() from error
    except PurchaseRequestSourceConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Не удалось безопасно собрать потребность. Обновите запрос и повторите",
        ) from error


@router.post("/{request_id}/cancel", response_model=SupplyPurchaseRequestRead)
def cancel_request(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    try:
        return cancel_purchase_request(db, _get(db, request_id, admin))
    except PurchaseRequestStateError as error:
        raise _state_error() from error


@router.post(
    "/{request_id}/lines", response_model=SupplyPurchaseRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def add_line(
    request_id: UUID,
    payload: SupplyPurchaseRequestLineCreate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    try:
        return add_purchase_request_line(db, _get(db, request_id, admin), payload)
    except PurchaseRequestStateError as error:
        raise _state_error() from error
    except PurchaseRequestProductNotFoundError as error:
        raise _not_found("Товар не найден") from error
    except PurchaseRequestUnitNotFoundError as error:
        raise _not_found("Единица измерения не найдена") from error
    except DuplicatePurchaseRequestLineError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот товар в выбранной единице уже добавлен",
        ) from error


@router.patch(
    "/{request_id}/lines/{line_id}", response_model=SupplyPurchaseRequestRead
)
def update_line(
    request_id: UUID,
    line_id: UUID,
    payload: SupplyPurchaseRequestLineUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    try:
        return update_purchase_request_line(
            db, _get(db, request_id, admin), line_id, payload
        )
    except PurchaseRequestStateError as error:
        raise _state_error() from error
    except PurchaseRequestLineNotFoundError as error:
        raise _not_found("Строка закупочного запроса не найдена") from error
    except PurchaseRequestUnitNotFoundError as error:
        raise _not_found("Единица измерения не найдена") from error
    except DuplicatePurchaseRequestLineError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот товар в выбранной единице уже добавлен",
        ) from error
    except PurchaseRequestSourceConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Изменять можно только будущую потребность",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Будущая потребность должна совпадать с количеством",
        ) from error


@router.delete(
    "/{request_id}/lines/{line_id}", response_model=SupplyPurchaseRequestRead
)
def delete_line(
    request_id: UUID,
    line_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseRequest:
    try:
        return delete_purchase_request_line(
            db, _get(db, request_id, admin), line_id
        )
    except PurchaseRequestStateError as error:
        raise _state_error() from error
    except PurchaseRequestLineNotFoundError as error:
        raise _not_found("Строка закупочного запроса не найдена") from error
    except PurchaseRequestSourceConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Автоматическую потребность нельзя удалить вручную",
        ) from error


def _allocation_error(error: Exception) -> HTTPException:
    if isinstance(error, PurchaseAllocationNotFoundError):
        return _not_found("Строка или распределение не найдено")
    if isinstance(error, DuplicatePurchaseAllocationError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот поставщик уже добавлен к строке",
        )
    if isinstance(error, PurchaseAllocationEligibilityError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Поставщик недоступен для этой строки: проверьте товар, единицу, "
                "активность, доступность и цену"
            ),
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Распределение доступно только для зафиксированного запроса; подтверждённую строку менять нельзя",
    )


@router.get(
    "/{request_id}/allocations",
    response_model=SupplyPurchaseAllocationWorkspaceRead,
)
def read_allocations(
    request_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_reader)],
) -> SupplyPurchaseAllocationWorkspaceRead:
    try:
        return get_purchase_allocation_workspace(db, request_id, tenant_id=admin.tenant_id)
    except (PurchaseAllocationNotFoundError, PurchaseAllocationStateError) as error:
        raise _allocation_error(error) from error


@router.post(
    "/{request_id}/lines/{line_id}/allocations",
    response_model=SupplyPurchaseAllocationWorkspaceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_allocation(
    request_id: UUID, line_id: UUID, payload: SupplyPurchaseAllocationCreate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseAllocationWorkspaceRead:
    try:
        return create_purchase_allocation(
            db, request_id, line_id, payload.product_supplier_id,
            payload.packages_count, tenant_id=admin.tenant_id,
        )
    except (
        PurchaseAllocationNotFoundError, PurchaseAllocationStateError,
        PurchaseAllocationEligibilityError, DuplicatePurchaseAllocationError,
    ) as error:
        raise _allocation_error(error) from error


@router.patch(
    "/{request_id}/lines/{line_id}/allocations/{allocation_id}",
    response_model=SupplyPurchaseAllocationWorkspaceRead,
)
def update_allocation(
    request_id: UUID, line_id: UUID, allocation_id: UUID,
    payload: SupplyPurchaseAllocationUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseAllocationWorkspaceRead:
    try:
        return update_purchase_allocation(
            db, request_id, line_id, allocation_id, payload.packages_count,
            tenant_id=admin.tenant_id,
        )
    except (
        PurchaseAllocationNotFoundError, PurchaseAllocationStateError,
        PurchaseAllocationEligibilityError,
    ) as error:
        raise _allocation_error(error) from error


@router.delete(
    "/{request_id}/lines/{line_id}/allocations/{allocation_id}",
    response_model=SupplyPurchaseAllocationWorkspaceRead,
)
def delete_allocation(
    request_id: UUID, line_id: UUID, allocation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseAllocationWorkspaceRead:
    try:
        return delete_purchase_allocation(
            db, request_id, line_id, allocation_id, tenant_id=admin.tenant_id
        )
    except (PurchaseAllocationNotFoundError, PurchaseAllocationStateError) as error:
        raise _allocation_error(error) from error


@router.post(
    "/{request_id}/lines/{line_id}/allocations/{allocation_id}/confirm",
    response_model=SupplyPurchaseAllocationWorkspaceRead,
)
def confirm_allocation(
    request_id: UUID, line_id: UUID, allocation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseAllocationWorkspaceRead:
    try:
        return confirm_purchase_allocation(
            db, request_id, line_id, allocation_id, tenant_id=admin.tenant_id
        )
    except (
        PurchaseAllocationNotFoundError, PurchaseAllocationStateError,
        PurchaseAllocationEligibilityError,
    ) as error:
        raise _allocation_error(error) from error


@router.put(
    "/{request_id}/lines/{line_id}/allocations/{allocation_id}/sources",
    response_model=SupplyPurchaseAllocationWorkspaceRead,
)
def update_allocation_sources(
    request_id: UUID, line_id: UUID, allocation_id: UUID,
    payload: SupplyPurchaseAllocationSourcesUpdate,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(get_supply_operator)],
) -> SupplyPurchaseAllocationWorkspaceRead:
    try:
        return update_purchase_allocation_sources(
            db, request_id, line_id, allocation_id, payload.sources,
            tenant_id=admin.tenant_id,
        )
    except (
        PurchaseAllocationNotFoundError, PurchaseAllocationStateError,
    ) as error:
        raise _allocation_error(error) from error
