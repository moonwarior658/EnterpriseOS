from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload, selectinload

from app.models.iiko import (
    IikoMappingStatus,
    IikoProductMapping,
    IikoUnitMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import (
    SupplyProductSourceMapping,
    SupplyRequest,
    SupplyRequestLine,
    SupplyStockCalculation,
    SupplyStockCalculationAuditAction,
    SupplyStockCalculationAuditEvent,
    SupplyStockCalculationLine,
    SupplyStockCalculationStatus,
)
from app.schemas.supply import (
    SupplyStockCalculationGroupRead,
    SupplyStockCalculationLineRead,
    SupplyStockCalculationRead,
)
from app.supply.iiko_stock import _latest_balances, _load_request
from app.supply.source_mapping import product_source_role


class SupplyStockCalculationNotFoundError(LookupError):
    pass


class SupplyStockCalculationUnavailableError(ValueError):
    pass


class SupplyStockCalculationConfirmedError(ValueError):
    pass


class SupplyStockTransferQuantityInvalidError(ValueError):
    pass


class SupplyStockTransferFractionInvalidError(ValueError):
    pass


class SupplyStockCalculationBlockedError(ValueError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Blocked stock calculation cannot be confirmed")


class SupplyStockCalculationVersionConflictError(ValueError):
    def __init__(
        self,
        *,
        current_calculation_id: UUID | None,
        current_revision: int | None,
        current_version: int | None,
        current_line_version: int | None = None,
    ):
        self.current_calculation_id = current_calculation_id
        self.current_revision = current_revision
        self.current_version = current_version
        self.current_line_version = current_line_version
        super().__init__("Supply stock calculation version conflict")


@dataclass(frozen=True)
class _EligibleLine:
    line: SupplyRequestLine
    source: IikoWarehouseMapping
    product_mapping: IikoProductMapping
    available: Decimal
    snapshot_at: datetime


def _latest_calculation(
    session: Session, *, tenant_id: str, request_id: UUID, for_update: bool = False
) -> SupplyStockCalculation | None:
    statement = (
        select(SupplyStockCalculation)
        .where(
            SupplyStockCalculation.tenant_id == tenant_id,
            SupplyStockCalculation.request_id == request_id,
        )
        .order_by(SupplyStockCalculation.revision.desc())
        .limit(1)
    )
    if for_update:
        statement = statement.options(lazyload("*")).with_for_update(
            of=SupplyStockCalculation
        )
    else:
        statement = statement.options(
            selectinload(SupplyStockCalculation.lines).joinedload(
                SupplyStockCalculationLine.requested_unit
            )
        )
    return session.scalar(statement)


def _locked_latest_calculation(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    lock_lines: bool,
) -> SupplyStockCalculation | None:
    calculation = _latest_calculation(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        for_update=True,
    )
    if calculation is None or not lock_lines:
        return calculation
    session.scalars(
        select(SupplyStockCalculationLine)
        .where(SupplyStockCalculationLine.calculation_id == calculation.id)
        .order_by(
            SupplyStockCalculationLine.position,
            SupplyStockCalculationLine.id,
        )
        .with_for_update(of=SupplyStockCalculationLine)
    ).all()
    return session.scalar(
        select(SupplyStockCalculation)
        .where(SupplyStockCalculation.id == calculation.id)
        .options(
            selectinload(SupplyStockCalculation.lines).joinedload(
                SupplyStockCalculationLine.requested_unit
            )
        )
        .execution_options(populate_existing=True)
    )


def _read(calculation: SupplyStockCalculation) -> SupplyStockCalculationRead:
    grouped: dict[UUID | None, list[SupplyStockCalculationLine]] = defaultdict(list)
    for line in calculation.lines:
        grouped[line.source_warehouse_mapping_id].append(line)
    groups = [
        SupplyStockCalculationGroupRead(
            source_mapping_id=source_id,
            source_name=lines[0].source_name,
            snapshot_at=min(
                (line.iiko_snapshot_at for line in lines if line.iiko_snapshot_at),
                default=None,
            ),
            lines=[SupplyStockCalculationLineRead.model_validate(line) for line in lines],
        )
        for source_id, lines in sorted(
            grouped.items(),
            key=lambda item: (item[1][0].source_name is None, item[1][0].source_name or ""),
        )
    ]
    return SupplyStockCalculationRead(
        id=calculation.id,
        request_id=calculation.request_id,
        revision=calculation.revision,
        version=calculation.version,
        status=calculation.status,
        is_preliminary=(
            calculation.status == SupplyStockCalculationStatus.PRELIMINARY
        ),
        calculated_at=calculation.calculated_at,
        snapshot_at=calculation.snapshot_at,
        confirmed_at=calculation.confirmed_at,
        groups=groups,
    )


def get_stock_calculation(
    session: Session, *, tenant_id: str, request_id: UUID
) -> SupplyStockCalculationRead | None:
    try:
        request = _load_request(
            session, tenant_id=tenant_id, request_id=request_id
        )
    except LookupError as error:
        raise SupplyStockCalculationNotFoundError from error
    calculation = _latest_calculation(
        session, tenant_id=tenant_id, request_id=request_id
    )
    if (
        calculation is not None
        and calculation.status == SupplyStockCalculationStatus.PRELIMINARY
        and not _calculation_matches_request(calculation, request)
    ):
        return None
    return _read(calculation) if calculation else None


def _calculation_matches_request(
    calculation: SupplyStockCalculation,
    request: SupplyRequest,
) -> bool:
    current = {
        line.id: (
            line.product_id,
            line.requested_unit_id,
            line.quantity,
        )
        for line in request.lines
        if line.match_status == "MATCHED" and line.product_id is not None
    }
    persisted = {
        line.request_line_id: (
            line.product_id,
            line.requested_unit_id,
            line.requested_quantity,
        )
        for line in calculation.lines
    }
    return current == persisted


def _source_is_valid(
    source: IikoWarehouseMapping | None,
    mapping: SupplyProductSourceMapping | None,
    request: SupplyRequest,
) -> bool:
    return bool(
        source
        and mapping
        and request.department.legal_contour is not None
        and source.tenant_id == request.tenant_id
        and source.destination_type == IikoWarehouseDestinationType.SOURCE
        and source.status == IikoMappingStatus.CONFIRMED
        and not source.is_deleted
        and source.legal_contour == request.department.legal_contour
        and source.role == IikoWarehouseRole(mapping.role.value)
    )


def calculate_stock(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    actor_user_id: int | None,
) -> SupplyStockCalculationRead:
    now = datetime.now(timezone.utc)
    try:
        request = _load_request(
            session,
            tenant_id=tenant_id,
            request_id=request_id,
            for_update=True,
        )
    except LookupError as error:
        raise SupplyStockCalculationNotFoundError from error
    matched_lines = sorted((
        line for line in request.lines
        if line.match_status == "MATCHED" and line.product_id is not None
    ), key=lambda line: line.position)
    if not matched_lines:
        raise SupplyStockCalculationUnavailableError

    product_ids = {line.product_id for line in matched_lines}
    product_mappings = {
        item.eos_product_id: item
        for item in session.scalars(select(IikoProductMapping).where(
            IikoProductMapping.tenant_id == tenant_id,
            IikoProductMapping.eos_product_id.in_(product_ids),
            IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
            IikoProductMapping.is_deleted.is_(False),
        )).all()
    }
    contour = request.department.legal_contour
    source_mappings = {
        item.eos_product_id: item
        for item in session.scalars(select(SupplyProductSourceMapping).where(
            SupplyProductSourceMapping.tenant_id == tenant_id,
            SupplyProductSourceMapping.eos_product_id.in_(product_ids),
            SupplyProductSourceMapping.legal_contour == contour,
        )).all()
    } if contour is not None else {}
    source_ids = {item.source_warehouse_mapping_id for item in source_mappings.values()}
    sources = {
        item.id: item
        for item in session.scalars(select(IikoWarehouseMapping).where(
            IikoWarehouseMapping.id.in_(source_ids)
        )).all()
    } if source_ids else {}
    unit_mappings = {
        item.iiko_unit_id: item
        for item in session.scalars(select(IikoUnitMapping).where(
            IikoUnitMapping.tenant_id == tenant_id,
            IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
            IikoUnitMapping.is_deleted.is_(False),
        )).all()
    }

    source_stock: dict[UUID, tuple[dict[UUID, Decimal], datetime | None]] = {}
    for source in sources.values():
        if source.id not in source_stock:
            source_stock[source.id] = _latest_balances(
                session,
                tenant_id=tenant_id,
                source_warehouse_mapping_id=source.id,
            )

    eligible: dict[UUID, _EligibleLine] = {}
    reasons: dict[UUID, str] = {}
    for line in matched_lines:
        product_mapping = product_mappings.get(line.product_id)
        product_source = source_mappings.get(line.product_id)
        source = sources.get(product_source.source_warehouse_mapping_id) \
            if product_source else None
        if contour is None:
            reasons[line.id] = "У подразделения не указан legal contour"
        elif product_mapping is None:
            reasons[line.id] = "Нет подтверждённого mapping товара iiko"
        elif product_source is not None and product_source.role != product_source_role(
            product_mapping.source_name
        ):
            reasons[line.id] = "SOURCE mapping не соответствует роли товара iiko"
        elif not _source_is_valid(source, product_source, request):
            reasons[line.id] = "SOURCE не назначен или больше не подтверждён"
        elif line.requested_unit_id is None or line.quantity is None:
            reasons[line.id] = "В строке не указаны количество или единица"
        else:
            unit_mapping = unit_mappings.get(product_mapping.source_unit_id)
            if unit_mapping is None:
                reasons[line.id] = "Нет подтверждённого mapping единицы iiko"
            elif unit_mapping.eos_unit_id != line.requested_unit_id:
                reasons[line.id] = "Единица заявки не совпадает с unit_id iiko"
            else:
                balances, snapshot_at = source_stock[source.id]
                if snapshot_at is None:
                    reasons[line.id] = "Нет успешного снимка остатков iiko для SOURCE"
                else:
                    eligible[line.id] = _EligibleLine(
                        line=line,
                        source=source,
                        product_mapping=product_mapping,
                        available=balances.get(
                            product_mapping.iiko_product_id,
                            Decimal("0"),
                        ),
                        snapshot_at=snapshot_at,
                    )

    previous = _locked_latest_calculation(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        lock_lines=False,
    )
    remaining: dict[tuple[UUID, UUID], Decimal] = {}
    for item in eligible.values():
        remaining.setdefault(
            (item.source.id, item.product_mapping.iiko_product_id),
            max(item.available, Decimal("0")),
        )

    previous_revision = previous.revision if previous else 0
    calculation = SupplyStockCalculation(
        tenant_id=tenant_id,
        request_id=request_id,
        revision=previous_revision + 1,
        version=1,
        status=SupplyStockCalculationStatus.PRELIMINARY,
        calculated_at=now,
        snapshot_at=min(
            (item.snapshot_at for item in eligible.values()), default=None
        ),
        calculated_by_user_id=actor_user_id,
    )
    session.add(calculation)
    session.flush()
    for line in matched_lines:
        assert line.quantity is not None
        item = eligible.get(line.id)
        if item is None:
            calculation.lines.append(SupplyStockCalculationLine(
                tenant_id=tenant_id,
                request_id=request.id,
                request_line_id=line.id,
                version=1,
                position=line.position,
                product_id=line.product_id,
                product_name=line.product.name if line.product else line.working_name,
                requested_unit_id=line.requested_unit_id,
                requested_quantity=line.quantity,
                unavailable_reason=reasons[line.id],
            ))
            continue
        key = (item.source.id, item.product_mapping.iiko_product_id)
        transferable = min(line.quantity, remaining[key])
        remaining[key] -= transferable
        calculation.lines.append(SupplyStockCalculationLine(
            tenant_id=tenant_id,
            request_id=request.id,
            request_line_id=line.id,
            version=1,
            position=line.position,
            product_id=line.product_id,
            product_name=line.product.name if line.product else line.working_name,
            requested_unit_id=line.requested_unit_id,
            requested_quantity=line.quantity,
            source_warehouse_mapping_id=item.source.id,
            source_name=item.source.source_name,
            iiko_snapshot_at=item.snapshot_at,
            available_quantity=item.available,
            transferable_quantity=transferable,
            deficit_quantity=line.quantity - transferable,
        ))
    session.flush()
    session.add(SupplyStockCalculationAuditEvent(
        tenant_id=tenant_id,
        calculation_id=calculation.id,
        action=(
            SupplyStockCalculationAuditAction.AUTO_CALCULATED
            if previous_revision == 0
            else SupplyStockCalculationAuditAction.RECALCULATED
        ),
        actor_user_id=actor_user_id,
    ))
    session.commit()
    return _read(calculation)


def adjust_transferable_quantity(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    calculation_id: UUID,
    expected_revision: int,
    expected_version: int,
    line_id: UUID,
    expected_line_version: int,
    quantity: Decimal,
    actor_user_id: int | None,
) -> SupplyStockCalculationRead:
    try:
        request = _load_request(
            session,
            tenant_id=tenant_id,
            request_id=request_id,
            for_update=True,
        )
    except LookupError as error:
        raise SupplyStockCalculationNotFoundError from error
    calculation = _locked_latest_calculation(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        lock_lines=True,
    )
    if calculation is None:
        raise SupplyStockCalculationNotFoundError
    if (
        calculation.id != calculation_id
        or calculation.revision != expected_revision
        or calculation.version != expected_version
    ):
        raise SupplyStockCalculationVersionConflictError(
            current_calculation_id=calculation.id,
            current_revision=calculation.revision,
            current_version=calculation.version,
        )
    if calculation.status == SupplyStockCalculationStatus.CONFIRMED:
        raise SupplyStockCalculationConfirmedError
    if not _calculation_matches_request(calculation, request):
        raise SupplyStockCalculationVersionConflictError(
            current_calculation_id=None,
            current_revision=None,
            current_version=None,
        )
    line = next((item for item in calculation.lines if item.id == line_id), None)
    if line is None or line.unavailable_reason is not None:
        raise SupplyStockCalculationNotFoundError
    if line.version != expected_line_version:
        raise SupplyStockCalculationVersionConflictError(
            current_calculation_id=calculation.id,
            current_revision=calculation.revision,
            current_version=calculation.version,
            current_line_version=line.version,
        )
    if quantity < 0 or quantity > line.requested_quantity:
        raise SupplyStockTransferQuantityInvalidError
    if (
        line.requested_unit is not None
        and not line.requested_unit.allows_fraction
        and quantity != quantity.to_integral_value()
    ):
        raise SupplyStockTransferFractionInvalidError
    siblings = [
        item for item in calculation.lines
        if item.source_warehouse_mapping_id == line.source_warehouse_mapping_id
        and item.product_id == line.product_id
        and item.unavailable_reason is None
    ]
    group_total = sum(
        (quantity if item.id == line.id else item.transferable_quantity)
        for item in siblings
    )
    available = max(item.available_quantity for item in siblings)
    if group_total > available:
        raise SupplyStockTransferQuantityInvalidError
    previous = line.transferable_quantity
    line.transferable_quantity = quantity
    line.deficit_quantity = line.requested_quantity - quantity
    line.version += 1
    calculation.version += 1
    session.add(SupplyStockCalculationAuditEvent(
        tenant_id=tenant_id,
        calculation_id=calculation.id,
        calculation_line_id=line.id,
        action=SupplyStockCalculationAuditAction.MANUALLY_ADJUSTED,
        previous_quantity=previous,
        quantity=quantity,
        actor_user_id=actor_user_id,
    ))
    session.commit()
    return _read(calculation)


def confirm_stock_calculation(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    calculation_id: UUID,
    expected_revision: int,
    expected_version: int,
    actor_user_id: int | None,
) -> SupplyStockCalculationRead:
    try:
        request = _load_request(
            session,
            tenant_id=tenant_id,
            request_id=request_id,
            for_update=True,
        )
    except LookupError as error:
        raise SupplyStockCalculationNotFoundError from error
    calculation = _locked_latest_calculation(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        lock_lines=True,
    )
    if calculation is None:
        raise SupplyStockCalculationNotFoundError
    if (
        calculation.id != calculation_id
        or calculation.revision != expected_revision
        or calculation.version != expected_version
    ):
        raise SupplyStockCalculationVersionConflictError(
            current_calculation_id=calculation.id,
            current_revision=calculation.revision,
            current_version=calculation.version,
        )
    if calculation.status == SupplyStockCalculationStatus.CONFIRMED:
        raise SupplyStockCalculationConfirmedError
    if not _calculation_matches_request(calculation, request):
        raise SupplyStockCalculationVersionConflictError(
            current_calculation_id=None,
            current_revision=None,
            current_version=None,
        )
    blocked_reasons = sorted({
        line.unavailable_reason
        for line in calculation.lines
        if line.unavailable_reason is not None
    })
    if blocked_reasons:
        raise SupplyStockCalculationBlockedError(blocked_reasons)
    calculation.status = SupplyStockCalculationStatus.CONFIRMED
    calculation.confirmed_at = datetime.now(timezone.utc)
    calculation.confirmed_by_user_id = actor_user_id
    calculation.version += 1
    session.add(SupplyStockCalculationAuditEvent(
        tenant_id=tenant_id,
        calculation_id=calculation.id,
        action=SupplyStockCalculationAuditAction.CONFIRMED,
        actor_user_id=actor_user_id,
    ))
    session.commit()
    return _read(calculation)
