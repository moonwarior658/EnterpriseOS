from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, lazyload, selectinload

from app.models.iiko import (
    IikoMappingStatus,
    IikoProductMapping,
    IikoStockBalanceSnapshotLine,
    IikoStockBalanceSnapshotSource,
    IikoStockBalanceSnapshotSourceStatus,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
    IikoUnitMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import SupplyRequest, SupplyRequestLine
from app.schemas.supply import (
    SupplyIikoSourceWarehouseRead,
    SupplyIikoStockCheckRead,
    SupplyIikoStockLineRead,
)


class SupplyIikoRequestNotFoundError(LookupError):
    pass


class SupplyIikoSourceNotAllowedError(ValueError):
    pass


class SupplyIikoVersionConflictError(ValueError):
    def __init__(self, current_version: int, expected_version: int):
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__("Supply request version conflict")


class SupplyIikoTerminalRequestError(ValueError):
    pass


TERMINAL_REQUEST_STATUSES = {
    "PARTIALLY_FULFILLED",
    "FULFILLED",
    "CANCELLED",
}


def _required_source_role(request: SupplyRequest) -> IikoWarehouseRole:
    code = request.direction.code.strip().upper()
    name = request.direction.name.strip().casefold()
    if code in {"MAIN", "PRODUCT", "PRODUCTS"} or name == "продукты":
        return IikoWarehouseRole.MAIN
    if code == "PACKAGING" or name == "упаковка":
        return IikoWarehouseRole.PACKAGING
    if code == "HOUSEHOLD" or name in {"хозка", "хозтовары", "хозяйственный"}:
        return IikoWarehouseRole.HOUSEHOLD
    return IikoWarehouseRole.OTHER


def _locked_request_statement(*, tenant_id: str, request_id: UUID):
    return (
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == tenant_id,
        )
        .options(lazyload("*"))
        .with_for_update(of=SupplyRequest)
    )


def _source_read(mapping: IikoWarehouseMapping) -> SupplyIikoSourceWarehouseRead:
    return SupplyIikoSourceWarehouseRead(
        mapping_id=mapping.id,
        iiko_warehouse_id=mapping.iiko_warehouse_id,
        name=mapping.source_name,
        role=mapping.role,
        legal_contour=mapping.legal_contour,
    )


def list_allowed_sources(
    session: Session,
    request: SupplyRequest,
) -> list[IikoWarehouseMapping]:
    legal_contour = request.department.legal_contour
    if legal_contour is None:
        return []
    statement = (
        select(IikoWarehouseMapping)
        .where(
            IikoWarehouseMapping.tenant_id == request.tenant_id,
            IikoWarehouseMapping.destination_type
            == IikoWarehouseDestinationType.SOURCE,
            IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
            IikoWarehouseMapping.is_deleted.is_(False),
            IikoWarehouseMapping.legal_contour == legal_contour,
        )
        .order_by(IikoWarehouseMapping.source_name, IikoWarehouseMapping.id)
    )
    required_role = _required_source_role(request)
    if required_role is not None:
        if required_role == IikoWarehouseRole.OTHER:
            return []
        statement = statement.where(IikoWarehouseMapping.role == required_role)
    return list(session.scalars(statement).all())


def _load_request(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    for_update: bool = False,
) -> SupplyRequest:
    request_filter = (
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == tenant_id,
        )
    )
    if for_update:
        locked = session.scalar(
            _locked_request_statement(
                tenant_id=tenant_id,
                request_id=request_id,
            )
        )
        if locked is None:
            raise SupplyIikoRequestNotFoundError
        statement = (
            select(SupplyRequest)
            .where(SupplyRequest.id == locked.id)
            .options(
                joinedload(SupplyRequest.department),
                joinedload(SupplyRequest.direction),
                selectinload(SupplyRequest.lines).joinedload(
                    SupplyRequestLine.product
                ),
                selectinload(SupplyRequest.lines).joinedload(
                    SupplyRequestLine.requested_unit
                ),
            )
            .execution_options(populate_existing=True)
        )
    else:
        statement = request_filter.options(
            joinedload(SupplyRequest.department),
            joinedload(SupplyRequest.direction),
            selectinload(SupplyRequest.lines).joinedload(SupplyRequestLine.product),
            selectinload(SupplyRequest.lines).joinedload(
                SupplyRequestLine.requested_unit
            ),
        )
    request = session.scalar(statement)
    if request is None:
        raise SupplyIikoRequestNotFoundError
    return request


def select_source_warehouse(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    mapping_id: UUID,
    expected_version: int,
) -> SupplyIikoStockCheckRead:
    request = _load_request(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        for_update=True,
    )
    if request.version != expected_version:
        raise SupplyIikoVersionConflictError(request.version, expected_version)
    if request.status in TERMINAL_REQUEST_STATUSES:
        raise SupplyIikoTerminalRequestError
    allowed = list_allowed_sources(session, request)
    if mapping_id not in {item.id for item in allowed}:
        raise SupplyIikoSourceNotAllowedError
    request.iiko_source_warehouse_mapping_id = mapping_id
    request.version += 1
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_stock_check(session, tenant_id=tenant_id, request_id=request_id)


def _confirmed_mappings(
    session: Session,
    *,
    tenant_id: str,
    lines: list[SupplyRequestLine],
) -> tuple[dict[UUID, IikoProductMapping], dict[UUID, IikoUnitMapping]]:
    product_ids = {line.product_id for line in lines if line.product_id is not None}
    product_mappings = session.scalars(
        select(IikoProductMapping).where(
            IikoProductMapping.tenant_id == tenant_id,
            IikoProductMapping.eos_product_id.in_(product_ids),
            IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
            IikoProductMapping.is_deleted.is_(False),
        )
    ).all() if product_ids else []
    unit_mappings = session.scalars(
        select(IikoUnitMapping).where(
            IikoUnitMapping.tenant_id == tenant_id,
            IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
            IikoUnitMapping.is_deleted.is_(False),
        )
    ).all()
    return (
        {mapping.eos_product_id: mapping for mapping in product_mappings},
        {mapping.iiko_unit_id: mapping for mapping in unit_mappings},
    )


def _latest_balances(
    session: Session,
    *,
    tenant_id: str,
    source_warehouse_mapping_id: UUID,
) -> tuple[dict[UUID, Decimal], datetime | None]:
    latest = session.execute(
        select(IikoStockBalanceSnapshotSource, IikoSyncRun)
        .join(
            IikoSyncRun,
            IikoSyncRun.id == IikoStockBalanceSnapshotSource.sync_run_id,
        )
        .where(
            IikoSyncRun.tenant_id == tenant_id,
            IikoSyncRun.sync_type
            == IikoSyncType.STOCK_BALANCE_SNAPSHOT,
            IikoSyncRun.status == IikoSyncStatus.SUCCEEDED,
            IikoSyncRun.finished_at.is_not(None),
            IikoStockBalanceSnapshotSource.tenant_id == tenant_id,
            IikoStockBalanceSnapshotSource.source_warehouse_mapping_id
            == source_warehouse_mapping_id,
            IikoStockBalanceSnapshotSource.status
            == IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
        )
        .order_by(
            IikoStockBalanceSnapshotSource.snapshot_at.desc(),
            IikoSyncRun.finished_at.desc(),
            IikoSyncRun.started_at.desc(),
            IikoSyncRun.id.desc(),
        )
        .limit(1)
    ).first()
    if latest is None:
        return {}, None
    source_snapshot, run = latest
    records = session.scalars(
        select(IikoStockBalanceSnapshotLine)
        .where(
            IikoStockBalanceSnapshotLine.tenant_id == tenant_id,
            IikoStockBalanceSnapshotLine.sync_run_id == run.id,
            IikoStockBalanceSnapshotLine.source_warehouse_mapping_id
            == source_warehouse_mapping_id,
        )
        .order_by(IikoStockBalanceSnapshotLine.id)
    ).all()
    balances = {record.iiko_product_id: record.quantity for record in records}
    snapshot_at = min(
        (record.snapshot_at for record in records),
        default=source_snapshot.snapshot_at,
    )
    return balances, snapshot_at


def _unavailable_line(
    line: SupplyRequestLine,
    reason: str,
) -> SupplyIikoStockLineRead:
    return SupplyIikoStockLineRead(
        line_id=line.id,
        position=line.position,
        product_name=line.product.name if line.product else line.working_name,
        requested_quantity=line.quantity,
        requested_unit=line.requested_unit,
        stock_quantity=None,
        is_sufficient=None,
        deficit=None,
        unavailable_reason=reason,
    )


def get_stock_check(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
) -> SupplyIikoStockCheckRead:
    request = _load_request(session, tenant_id=tenant_id, request_id=request_id)
    allowed = list_allowed_sources(session, request)
    allowed_by_id = {item.id: item for item in allowed}
    selected = allowed_by_id.get(request.iiko_source_warehouse_mapping_id)
    matched_lines = [
        line for line in request.lines
        if line.match_status == "MATCHED" and line.product_id is not None
    ]
    if request.department.legal_contour is None:
        lines = [
            _unavailable_line(line, "У подразделения не указан legal contour")
            for line in matched_lines
        ]
        return SupplyIikoStockCheckRead(
            request_version=request.version,
            legal_contour=None,
            available_sources=[],
            selected_source=None,
            last_sync_at=None,
            lines=lines,
        )
    if selected is None:
        lines = [
            _unavailable_line(line, "Не выбран склад-источник")
            for line in matched_lines
        ]
        return SupplyIikoStockCheckRead(
            request_version=request.version,
            legal_contour=request.department.legal_contour,
            available_sources=[_source_read(item) for item in allowed],
            selected_source=None,
            last_sync_at=None,
            lines=lines,
        )

    product_mappings, unit_mappings = _confirmed_mappings(
        session,
        tenant_id=tenant_id,
        lines=matched_lines,
    )
    balances, last_sync_at = _latest_balances(
        session,
        tenant_id=tenant_id,
        source_warehouse_mapping_id=selected.id,
    )
    result_lines: list[SupplyIikoStockLineRead] = []
    for line in matched_lines:
        product_mapping = product_mappings.get(line.product_id)
        if product_mapping is None:
            result_lines.append(_unavailable_line(
                line, "Нет подтверждённого mapping товара iiko"
            ))
            continue
        if line.requested_unit_id is None or line.quantity is None:
            result_lines.append(_unavailable_line(
                line, "В строке не указаны количество или единица"
            ))
            continue
        unit_mapping = unit_mappings.get(product_mapping.source_unit_id)
        if unit_mapping is None:
            result_lines.append(_unavailable_line(
                line, "Нет подтверждённого mapping единицы iiko"
            ))
            continue
        if unit_mapping.eos_unit_id != line.requested_unit_id:
            result_lines.append(_unavailable_line(
                line, "Единица заявки не совпадает с unit_id iiko"
            ))
            continue
        stock_quantity = balances.get(product_mapping.iiko_product_id)
        if stock_quantity is None:
            result_lines.append(_unavailable_line(
                line, "Нет остатка iiko для товара на выбранном складе"
            ))
            continue
        is_sufficient = stock_quantity >= line.quantity
        result_lines.append(SupplyIikoStockLineRead(
            line_id=line.id,
            position=line.position,
            product_name=line.product.name if line.product else line.working_name,
            requested_quantity=line.quantity,
            requested_unit=line.requested_unit,
            stock_quantity=stock_quantity,
            is_sufficient=is_sufficient,
            deficit=max(line.quantity - stock_quantity, Decimal("0")),
            unavailable_reason=None,
        ))
    return SupplyIikoStockCheckRead(
        request_version=request.version,
        legal_contour=request.department.legal_contour,
        available_sources=[_source_read(item) for item in allowed],
        selected_source=_source_read(selected),
        last_sync_at=last_sync_at,
        lines=result_lines,
    )
