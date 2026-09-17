from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.iiko import (
    IikoMappingStatus,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
)

from app.models.supply import (
    SupplyAcceptanceResolution,
    SupplyProcurementNeed,
    SupplyProcurementNeedReason,
    SupplyProcurementNeedSourceType,
    SupplyProcurementNeedStatus,
    SupplyIikoIncomingReceipt,
    SupplyIikoIncomingReceiptLine,
    SupplyProduct,
    SupplyPurchaseRequest,
    SupplySupplierAcceptance,
    SupplySupplierAcceptanceLine,
    SupplySupplierAcceptanceLineSource,
    SupplySupplierConfirmation,
    SupplySupplierConfirmationLine,
    SupplySupplierDocument,
    SupplySupplierDocumentLine,
    SupplySupplierOrder,
    SupplySupplierOrderLine,
    SupplySupplierOrderLineSource,
    SupplyUnit,
)
from app.schemas.supplier_acceptance import (
    SupplyAcceptanceResolutionNeedRead,
    SupplyAcceptanceResolutionRead,
    SupplyAcceptanceResolutionResolve,
    SupplySupplierAcceptanceCreate,
    SupplySupplierAcceptanceCumulativeLineRead,
    SupplySupplierAcceptanceDestinationRead,
    SupplySupplierAcceptanceLineCreate,
    SupplySupplierAcceptanceLineRead,
    SupplySupplierAcceptanceLineSourceRead,
    SupplySupplierAcceptanceLineSourceWrite,
    SupplySupplierAcceptanceLineUpdate,
    SupplySupplierAcceptanceRead,
    SupplySupplierAcceptanceUpdate,
    SupplySupplierAcceptanceSummary,
)

Q = Decimal("0.000001")


class SupplierAcceptanceNotFoundError(LookupError): pass
class SupplierAcceptanceStateError(ValueError): pass
class SupplierAcceptanceValidationError(ValueError): pass
class SupplierAcceptanceLinkError(ValueError): pass
class SupplierAcceptanceConflictError(ValueError): pass
class SupplierAcceptanceUnitError(ValueError): pass
class SupplierAcceptanceDestinationError(ValueError): pass
class SupplierAcceptanceResolutionNotFoundError(LookupError): pass
class SupplierAcceptanceResolutionStateError(ValueError): pass
class SupplierAcceptanceResolutionTypeError(ValueError): pass
class SupplierAcceptanceResolutionSourceError(ValueError): pass
class SupplierAcceptanceResolutionNeedDateError(ValueError): pass
class SupplierAcceptanceResolutionQuantityError(ValueError): pass


def _options():
    return (
        selectinload(SupplySupplierAcceptance.lines).selectinload(
            SupplySupplierAcceptanceLine.sources
        ).joinedload(SupplySupplierAcceptanceLineSource.order_line_source),
        selectinload(SupplySupplierAcceptance.resolutions).selectinload(
            SupplyAcceptanceResolution.procurement_need
        ),
        selectinload(SupplySupplierAcceptance.resolutions).selectinload(
            SupplyAcceptanceResolution.acceptance_line
        ),
        selectinload(SupplySupplierAcceptance.resolutions).selectinload(
            SupplyAcceptanceResolution.unit
        ),
        joinedload(SupplySupplierAcceptance.destination_mapping).joinedload(
            IikoWarehouseMapping.eos_department
        ),
    )


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _downstream_quantities(
    line: SupplySupplierAcceptanceLine,
    resolutions: list[SupplyAcceptanceResolution],
) -> tuple[Decimal, Decimal | None]:
    rejected_excess = sum(
        (
            Decimal(value.quantity)
            for value in resolutions
            if value.issue_type == "EXCESS"
            and value.status == "RESOLVED"
            and value.resolution_type == "REJECT_EXCESS"
        ),
        Decimal("0"),
    )
    downstream = max(Decimal(line.accepted_quantity) - rejected_excess, Decimal("0"))
    has_open_excess = any(
        value.issue_type == "EXCESS" and value.status == "OPEN"
        for value in resolutions
    )
    return downstream, None if has_open_excess else downstream


def _resolution_read(
    resolution: SupplyAcceptanceResolution,
    line_resolutions: list[SupplyAcceptanceResolution],
):
    line = resolution.acceptance_line
    need = resolution.procurement_need
    downstream, _ = _downstream_quantities(line, line_resolutions)
    return SupplyAcceptanceResolutionRead(
        id=resolution.id,
        supplier_acceptance_id=resolution.supplier_acceptance_id,
        acceptance_line_id=resolution.acceptance_line_id,
        product_name=line.product_name_snapshot,
        product_id=line.product_id,
        issue_type=resolution.issue_type,
        status=resolution.status,
        resolution_type=resolution.resolution_type,
        quantity=resolution.quantity,
        unit_id=resolution.unit_id,
        unit_name=resolution.unit.short_name_ru,
        comment=resolution.comment,
        resolved_by_user_id=resolution.resolved_by_user_id,
        resolved_at=resolution.resolved_at,
        created_at=resolution.created_at,
        updated_at=resolution.updated_at,
        procurement_need=(
            SupplyAcceptanceResolutionNeedRead(
                id=need.id, quantity=need.quantity, need_date=need.need_date,
                status=_enum_value(need.status), reason=_enum_value(need.reason),
            ) if need is not None else None
        ),
        downstream_accepted_quantity=downstream,
    )


def _destination_mapping(
    session: Session,
    mapping_id: UUID | None,
    *,
    tenant_id: str,
    lock: bool = False,
) -> IikoWarehouseMapping | None:
    if mapping_id is None:
        return None
    query = (
        select(IikoWarehouseMapping)
        .where(
            IikoWarehouseMapping.id == mapping_id,
            IikoWarehouseMapping.tenant_id == tenant_id,
            IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
            IikoWarehouseMapping.destination_type
            == IikoWarehouseDestinationType.DESTINATION,
            IikoWarehouseMapping.is_deleted.is_(False),
            IikoWarehouseMapping.eos_department_id.is_not(None),
            IikoWarehouseMapping.role.is_not(None),
        )
        .options(joinedload(IikoWarehouseMapping.eos_department))
    )
    if lock:
        query = query.with_for_update(of=IikoWarehouseMapping)
    mapping = session.scalar(query)
    if mapping is None or mapping.eos_department is None:
        raise SupplierAcceptanceDestinationError
    return mapping


def _get(session: Session, acceptance_id: UUID, *, tenant_id: str, lock: bool = False):
    query = select(SupplySupplierAcceptance).where(
        SupplySupplierAcceptance.id == acceptance_id,
        SupplySupplierAcceptance.tenant_id == tenant_id,
    ).options(*_options()).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update(of=SupplySupplierAcceptance)
    value = session.scalar(query)
    if value is None:
        raise SupplierAcceptanceNotFoundError
    return value


def _source_quantities(session: Session, line: SupplySupplierAcceptanceLine):
    ordered = confirmed = None
    if line.supplier_order_line_id:
        ordered = session.scalar(select(SupplySupplierOrderLine.quantity_base).where(
            SupplySupplierOrderLine.id == line.supplier_order_line_id,
            SupplySupplierOrderLine.tenant_id == line.tenant_id,
        ))
    if line.supplier_confirmation_line_id:
        confirmed = session.scalar(select(SupplySupplierConfirmationLine.confirmed_quantity_base).where(
            SupplySupplierConfirmationLine.id == line.supplier_confirmation_line_id,
            SupplySupplierConfirmationLine.tenant_id == line.tenant_id,
        ))
    return ordered, confirmed


def _accepted_for_order_source(
    session: Session, order_source_id: UUID, *, exclude_acceptance_line_id: UUID,
) -> Decimal:
    value = session.scalar(
        select(func.coalesce(func.sum(SupplySupplierAcceptanceLineSource.accepted_quantity), 0))
        .join(
            SupplySupplierAcceptanceLine,
            SupplySupplierAcceptanceLine.id
            == SupplySupplierAcceptanceLineSource.acceptance_line_id,
        )
        .join(
            SupplySupplierAcceptance,
            SupplySupplierAcceptance.id == SupplySupplierAcceptanceLine.acceptance_id,
        )
        .where(
            SupplySupplierAcceptanceLineSource.supplier_order_line_source_id == order_source_id,
            SupplySupplierAcceptanceLineSource.acceptance_line_id != exclude_acceptance_line_id,
            SupplySupplierAcceptance.status == "RECORDED",
        )
    )
    return Decimal(value or 0)


def _order_sources(
    session: Session, line: SupplySupplierAcceptanceLine, *, lock: bool,
) -> list[SupplySupplierOrderLineSource]:
    if line.supplier_order_line_id is None:
        return []
    statement = select(SupplySupplierOrderLineSource).where(
        SupplySupplierOrderLineSource.tenant_id == line.tenant_id,
        SupplySupplierOrderLineSource.order_line_id == line.supplier_order_line_id,
    ).order_by(SupplySupplierOrderLineSource.id)
    if lock:
        statement = statement.with_for_update()
    return list(session.scalars(statement).all())


def _acceptance_distribution_target(
    session: Session, line: SupplySupplierAcceptanceLine,
    order_sources: list[SupplySupplierOrderLineSource],
) -> Decimal:
    remaining = sum((
        max(
            Decimal(source.planned_quantity) - _accepted_for_order_source(
                session, source.id, exclude_acceptance_line_id=line.id,
            ),
            Decimal("0"),
        )
        for source in order_sources
    ), Decimal("0"))
    return min(Decimal(line.accepted_quantity), remaining)


def _acceptance_source_label(source: SupplySupplierOrderLineSource) -> str:
    if source.source_type_snapshot == "MANUAL_FUTURE":
        return "Будущая потребность"
    line_source = source.purchase_request_line_source
    need = line_source.procurement_need
    reason_value = _enum_value(need.reason) if need is not None else None
    reason = {
        "INTERNAL_STOCK_DEFICIT": "Дефицит после расчёта остатков",
        "DEBT_CARRY_FORWARD": "Перенос долга подразделения",
        "SUPPLIER_SHORTAGE": "Недопоставка поставщика",
        "SUPPLIER_REJECTION": "Отклонение при приёмке",
    }.get(reason_value, "Потребность")
    department = None
    if need is not None and need.request_line is not None:
        department = need.request_line.request.department.name
    elif need is not None and need.department_debt is not None:
        department = need.department_debt.department.name
    return f"{department} · {reason}" if department else reason


def _autofill_acceptance_single_source(
    session: Session, line: SupplySupplierAcceptanceLine,
) -> None:
    sources = _order_sources(session, line, lock=True)
    if len(sources) != 1:
        return
    target = _acceptance_distribution_target(session, line, sources)
    if target <= 0:
        line.sources.clear()
    elif line.sources:
        line.sources[0].supplier_order_line_source_id = sources[0].id
        line.sources[0].accepted_quantity = target
        for extra in line.sources[1:]:
            session.delete(extra)
    else:
        line.sources.append(SupplySupplierAcceptanceLineSource(
            tenant_id=line.tenant_id,
            supplier_order_line_source_id=sources[0].id,
            accepted_quantity=target,
        ))


def _validate_acceptance_distribution(
    session: Session, line: SupplySupplierAcceptanceLine, *, lock: bool,
) -> None:
    if line.supplier_order_line_id is None:
        return
    order_sources = _order_sources(session, line, lock=lock)
    if not order_sources:
        raise SupplierAcceptanceConflictError
    source_by_id = {source.id: source for source in order_sources}
    total = Decimal("0")
    seen: set[UUID] = set()
    for item in line.sources:
        source = source_by_id.get(item.supplier_order_line_source_id)
        if source is None or source.id in seen:
            raise SupplierAcceptanceValidationError
        already = _accepted_for_order_source(
            session, source.id, exclude_acceptance_line_id=line.id,
        )
        if Decimal(item.accepted_quantity) > Decimal(source.planned_quantity) - already:
            raise SupplierAcceptanceConflictError
        seen.add(source.id)
        total += Decimal(item.accepted_quantity)
    if total != _acceptance_distribution_target(session, line, order_sources):
        raise SupplierAcceptanceValidationError


def _line_read(
    session: Session,
    line: SupplySupplierAcceptanceLine,
    resolutions: list[SupplyAcceptanceResolution],
):
    documented = Decimal(line.documented_quantity) if line.documented_quantity is not None else None
    received = Decimal(line.received_quantity)
    shortage = max((documented or received) - received, Decimal("0")) if documented is not None else Decimal("0")
    excess = max(received - (documented or received), Decimal("0")) if documented is not None else Decimal("0")
    ordered, confirmed = _source_quantities(session, line)
    accepted = Decimal(line.accepted_quantity)
    accepted_excess = (
        max(accepted - documented, Decimal("0"))
        if documented is not None else Decimal("0")
    )
    downstream, receipt_eligible = _downstream_quantities(line, resolutions)
    accounted_quantity, accounted_sum = session.execute(
        select(
            func.coalesce(func.sum(SupplyIikoIncomingReceiptLine.quantity), 0),
            func.coalesce(func.sum(SupplyIikoIncomingReceiptLine.allocated_sum), 0),
        )
        .join(
            SupplyIikoIncomingReceipt,
            SupplyIikoIncomingReceipt.id == SupplyIikoIncomingReceiptLine.receipt_id,
        )
        .where(
            SupplyIikoIncomingReceiptLine.tenant_id == line.tenant_id,
            SupplyIikoIncomingReceiptLine.acceptance_line_id == line.id,
            SupplyIikoIncomingReceipt.status == "POSTED",
        )
    ).one()
    source_reads: list[SupplySupplierAcceptanceLineSourceRead] = []
    if line.supplier_order_line_id:
        order_sources = list(session.scalars(
            select(SupplySupplierOrderLineSource).where(
                SupplySupplierOrderLineSource.tenant_id == line.tenant_id,
                SupplySupplierOrderLineSource.order_line_id == line.supplier_order_line_id,
            ).order_by(SupplySupplierOrderLineSource.created_at)
        ).all())
        current_by_source = {
            item.supplier_order_line_source_id: item for item in line.sources
        }
        for source in order_sources:
            already = _accepted_for_order_source(
                session, source.id, exclude_acceptance_line_id=line.id,
            )
            current = current_by_source.get(source.id)
            source_reads.append(SupplySupplierAcceptanceLineSourceRead(
                supplier_order_line_source_id=source.id,
                source_type=source.source_type_snapshot,
                procurement_need_id=source.procurement_need_id_snapshot,
                source_label=_acceptance_source_label(source),
                planned_quantity=source.planned_quantity,
                already_accepted_quantity=already,
                remaining_quantity=max(Decimal(source.planned_quantity) - already, Decimal("0")),
                accepted_quantity=(current.accepted_quantity if current else Decimal("0")),
            ))
    source_accepted = sum(
        (Decimal(item.accepted_quantity) for item in line.sources), Decimal("0")
    )
    return SupplySupplierAcceptanceLineRead(
        id=line.id, supplier_document_line_id=line.supplier_document_line_id,
        supplier_order_line_id=line.supplier_order_line_id,
        supplier_confirmation_line_id=line.supplier_confirmation_line_id,
        product_name_snapshot=line.product_name_snapshot, product_id=line.product_id,
        unit_id=line.unit_id, unit_name_snapshot=line.unit_name_snapshot,
        ordered_quantity=ordered, confirmed_quantity=confirmed,
        documented_quantity=documented, received_quantity=received,
        accepted_quantity=line.accepted_quantity, rejected_quantity=line.rejected_quantity,
        ordered_vs_confirmed=(confirmed - ordered if ordered is not None and confirmed is not None else None),
        confirmed_vs_documented=(documented - confirmed if confirmed is not None and documented is not None else None),
        documented_vs_received=(received - documented if documented is not None else None),
        received_vs_accepted=accepted - received,
        shortage_quantity=shortage, excess_quantity=excess,
        accepted_excess_quantity=accepted_excess,
        downstream_accepted_quantity=downstream,
        receipt_eligible_quantity=receipt_eligible,
        accounted_quantity=Decimal(accounted_quantity),
        accounted_sum=Decimal(accounted_sum),
        documented_unit_price=line.documented_unit_price,
        accepted_unit_price=line.accepted_unit_price, accepted_amount=line.accepted_amount,
        currency=line.currency, rejection_reason=line.rejection_reason,
        comment=line.comment,
        is_unmatched=line.supplier_document_line_id is None and line.supplier_order_line_id is None,
        traceability_status=(
            "NOT_APPLICABLE" if line.supplier_order_line_id is None
            else "TRACEABLE" if line.sources
            else "INCOMPLETE" if line.acceptance.status == "DRAFT"
            else "UNTRACEABLE_LEGACY"
        ),
        source_accepted_quantity=source_accepted,
        unassigned_accepted_surplus=max(accepted - source_accepted, Decimal("0")),
        sources=source_reads,
    )


def _result(lines: list[SupplySupplierAcceptanceLineRead]) -> str:
    if lines and all(line.accepted_quantity == 0 and line.rejected_quantity > 0 for line in lines):
        return "REJECTED"
    if any(line.excess_quantity > 0 for line in lines):
        return "OVER_DELIVERED"
    if any(line.shortage_quantity > 0 or line.rejected_quantity > 0 for line in lines):
        return "PARTIALLY_ACCEPTED"
    return "FULLY_ACCEPTED" if lines else "MIXED"


def _read(session: Session, acceptance: SupplySupplierAcceptance):
    resolutions_by_line: dict[UUID, list[SupplyAcceptanceResolution]] = {}
    for resolution in acceptance.resolutions:
        resolutions_by_line.setdefault(resolution.acceptance_line_id, []).append(resolution)
    lines = [
        _line_read(session, line, resolutions_by_line.get(line.id, []))
        for line in acceptance.lines
    ]
    source = "DOCUMENT" if acceptance.supplier_document_id else (
        "CONFIRMATION" if acceptance.supplier_confirmation_id else "ORDER"
    )
    mapping = acceptance.destination_mapping
    if mapping is None and acceptance.destination_mapping_id is not None:
        mapping = session.scalar(
            select(IikoWarehouseMapping)
            .where(
                IikoWarehouseMapping.id == acceptance.destination_mapping_id,
                IikoWarehouseMapping.tenant_id == acceptance.tenant_id,
            )
            .options(joinedload(IikoWarehouseMapping.eos_department))
        )
    destination = (
        SupplySupplierAcceptanceDestinationRead(
            mapping_id=mapping.id,
            department_name=mapping.eos_department.name,
            role=mapping.role.value,
            iiko_store_name=mapping.source_name,
            iiko_store_code=mapping.source_code,
        )
        if mapping is not None
        and mapping.eos_department is not None
        and mapping.role is not None
        else None
    )
    resolutions = [
        _resolution_read(
            value, resolutions_by_line.get(value.acceptance_line_id, [])
        )
        for value in acceptance.resolutions
    ]
    if not resolutions:
        resolution_state = "CLEAN"
    elif any(value.status == "OPEN" for value in acceptance.resolutions):
        resolution_state = "OPEN_ISSUES"
    else:
        resolution_state = "RESOLVED"
    return SupplySupplierAcceptanceRead(
        id=acceptance.id, supplier_order_id=acceptance.supplier_order_id,
        supplier_document_id=acceptance.supplier_document_id,
        supplier_confirmation_id=acceptance.supplier_confirmation_id,
        destination_mapping_id=acceptance.destination_mapping_id,
        destination=destination,
        source=source, status=acceptance.status, result=_result(lines),
        accepted_at=acceptance.accepted_at, received_at=acceptance.received_at,
        comment=acceptance.comment, recorded_by_user_id=acceptance.recorded_by_user_id,
        recorded_at=acceptance.recorded_at, created_by_user_id=acceptance.created_by_user_id,
        created_at=acceptance.created_at, updated_at=acceptance.updated_at, lines=lines,
        resolution_state=resolution_state,
        open_issues_count=sum(value.status == "OPEN" for value in acceptance.resolutions),
        resolutions=resolutions,
    )


def list_acceptance_resolutions(session: Session, acceptance_id: UUID, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id)
    by_line: dict[UUID, list[SupplyAcceptanceResolution]] = {}
    for value in acceptance.resolutions:
        by_line.setdefault(value.acceptance_line_id, []).append(value)
    return [
        _resolution_read(value, by_line[value.acceptance_line_id])
        for value in acceptance.resolutions
    ]


def read_acceptance_resolution(session: Session, resolution_id: UUID, *, tenant_id: str):
    value = session.scalar(
        select(SupplyAcceptanceResolution).where(
            SupplyAcceptanceResolution.id == resolution_id,
            SupplyAcceptanceResolution.tenant_id == tenant_id,
        ).options(
            selectinload(SupplyAcceptanceResolution.acceptance_line),
            selectinload(SupplyAcceptanceResolution.unit),
            selectinload(SupplyAcceptanceResolution.procurement_need),
        ).execution_options(populate_existing=True)
    )
    if value is None:
        raise SupplierAcceptanceResolutionNotFoundError
    line_resolutions = session.scalars(
        select(SupplyAcceptanceResolution).where(
            SupplyAcceptanceResolution.tenant_id == tenant_id,
            SupplyAcceptanceResolution.acceptance_line_id == value.acceptance_line_id,
        )
    ).all()
    return _resolution_read(value, list(line_resolutions))


def _generate_resolution_issues(session: Session, acceptance: SupplySupplierAcceptance) -> None:
    existing = {
        (value.acceptance_line_id, value.issue_type)
        for value in session.scalars(select(SupplyAcceptanceResolution).where(
            SupplyAcceptanceResolution.tenant_id == acceptance.tenant_id,
            SupplyAcceptanceResolution.supplier_acceptance_id == acceptance.id,
        )).all()
    }
    for line in acceptance.lines:
        if line.unit_id is None:
            raise SupplierAcceptanceUnitError
        documented = Decimal(line.documented_quantity) if line.documented_quantity is not None else None
        received = Decimal(line.received_quantity)
        accepted = Decimal(line.accepted_quantity)
        rejected = Decimal(line.rejected_quantity)
        issues: list[tuple[str, Decimal]] = []
        if documented is not None and documented > received:
            issues.append(("SHORTAGE", documented - received))
        if documented is not None and accepted > documented:
            issues.append(("EXCESS", accepted - documented))
        if rejected > 0:
            issues.append(("REJECTED", rejected))
        for issue_type, quantity in issues:
            if (line.id, issue_type) in existing:
                continue
            session.add(SupplyAcceptanceResolution(
                tenant_id=acceptance.tenant_id,
                supplier_acceptance_id=acceptance.id,
                acceptance_line_id=line.id,
                issue_type=issue_type,
                quantity=quantity,
                unit_id=line.unit_id,
            ))


def _resolution_need_date(
    session: Session,
    resolution: SupplyAcceptanceResolution,
    payload: SupplyAcceptanceResolutionResolve,
):
    line = resolution.acceptance_line
    derived = None
    if line.supplier_order_line_id is not None:
        derived = session.scalar(
            select(SupplyPurchaseRequest.need_date)
            .join(
                SupplySupplierOrder,
                SupplySupplierOrder.purchase_request_id == SupplyPurchaseRequest.id,
            )
            .join(
                SupplySupplierOrderLine,
                SupplySupplierOrderLine.supplier_order_id == SupplySupplierOrder.id,
            )
            .where(
                SupplyPurchaseRequest.tenant_id == resolution.tenant_id,
                SupplySupplierOrder.tenant_id == resolution.tenant_id,
                SupplySupplierOrder.id == resolution.acceptance.supplier_order_id,
                SupplySupplierOrderLine.tenant_id == resolution.tenant_id,
                SupplySupplierOrderLine.id == line.supplier_order_line_id,
            )
        )
    if derived is not None:
        if payload.need_date is not None and payload.need_date != derived:
            raise SupplierAcceptanceResolutionNeedDateError
        return derived
    if payload.need_date is None:
        raise SupplierAcceptanceResolutionNeedDateError
    return payload.need_date


def resolve_acceptance_resolution(
    session: Session,
    resolution_id: UUID,
    payload: SupplyAcceptanceResolutionResolve,
    *,
    tenant_id: str,
    user_id: int,
):
    resolution = session.scalar(
        select(SupplyAcceptanceResolution).where(
            SupplyAcceptanceResolution.id == resolution_id,
            SupplyAcceptanceResolution.tenant_id == tenant_id,
        ).options(
            joinedload(SupplyAcceptanceResolution.acceptance),
            joinedload(SupplyAcceptanceResolution.acceptance_line),
            joinedload(SupplyAcceptanceResolution.unit),
            joinedload(SupplyAcceptanceResolution.procurement_need),
        ).with_for_update(of=SupplyAcceptanceResolution)
    )
    if resolution is None:
        raise SupplierAcceptanceResolutionNotFoundError
    if resolution.status != "OPEN":
        raise SupplierAcceptanceResolutionStateError
    resolution_type = _enum_value(payload.resolution_type)
    allowed = {
        "SHORTAGE": {"WAIT_FOR_DELIVERY", "CLOSE_SHORTAGE", "RETURN_TO_PROCUREMENT"},
        "REJECTED": {"WAIT_FOR_REPLACEMENT", "CLOSE_REJECTION", "RETURN_TO_PROCUREMENT"},
        "EXCESS": {"ACCEPT_EXCESS", "REJECT_EXCESS"},
    }
    if resolution_type not in allowed[resolution.issue_type]:
        raise SupplierAcceptanceResolutionTypeError
    if resolution_type == "REJECT_EXCESS":
        facts = list(session.scalars(
            select(SupplySupplierAcceptanceLineSource).where(
                SupplySupplierAcceptanceLineSource.tenant_id == tenant_id,
                SupplySupplierAcceptanceLineSource.acceptance_line_id
                == resolution.acceptance_line_id,
            ).with_for_update()
        ).all())
        assigned = sum((Decimal(item.accepted_quantity) for item in facts), Decimal("0"))
        unassigned = max(
            Decimal(resolution.acceptance_line.accepted_quantity) - assigned,
            Decimal("0"),
        )
        source_reduction = Decimal(resolution.quantity) - min(
            Decimal(resolution.quantity), unassigned
        )
        if source_reduction > 0:
            if len(facts) != 1 or source_reduction > Decimal(facts[0].accepted_quantity):
                raise SupplierAcceptanceConflictError
            facts[0].accepted_quantity = Decimal(facts[0].accepted_quantity) - source_reduction
            if facts[0].accepted_quantity == 0:
                session.delete(facts[0])
    if resolution_type == "RETURN_TO_PROCUREMENT":
        line = resolution.acceptance_line
        if line.product_id is None or line.unit_id is None:
            raise SupplierAcceptanceResolutionSourceError
        if Decimal(resolution.quantity) != Decimal(resolution.quantity).quantize(Decimal("0.001")):
            raise SupplierAcceptanceResolutionQuantityError
        need_date = _resolution_need_date(session, resolution, payload)
        reason = (
            SupplyProcurementNeedReason.SUPPLIER_SHORTAGE
            if resolution.issue_type == "SHORTAGE"
            else SupplyProcurementNeedReason.SUPPLIER_REJECTION
        )
        session.add(SupplyProcurementNeed(
            tenant_id=tenant_id,
            source_type=SupplyProcurementNeedSourceType.ACCEPTANCE_RESOLUTION,
            acceptance_resolution_id=resolution.id,
            product_id=line.product_id,
            unit_id=line.unit_id,
            quantity=resolution.quantity,
            need_date=need_date,
            status=SupplyProcurementNeedStatus.OPEN,
            reason=reason,
        ))
    resolution.status = "RESOLVED"
    resolution.resolution_type = resolution_type
    resolution.comment = (payload.comment or "").strip() or None
    resolution.resolved_by_user_id = user_id
    resolution.resolved_at = datetime.now(timezone.utc)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierAcceptanceConflictError from error
    return read_acceptance_resolution(session, resolution_id, tenant_id=tenant_id)


def read_acceptance(session: Session, acceptance_id: UUID, *, tenant_id: str):
    return _read(session, _get(session, acceptance_id, tenant_id=tenant_id))


def list_acceptances(session: Session, order_id: UUID, *, tenant_id: str):
    if session.scalar(select(SupplySupplierOrder.id).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    )) is None:
        raise SupplierAcceptanceNotFoundError
    values = session.scalars(select(SupplySupplierAcceptance).where(
        SupplySupplierAcceptance.supplier_order_id == order_id,
        SupplySupplierAcceptance.tenant_id == tenant_id,
    ).options(*_options()).order_by(SupplySupplierAcceptance.created_at.desc())).all()
    return [_read(session, value) for value in values]


def acceptance_summary(session: Session, values: list[SupplySupplierAcceptance]):
    reads = [_read(session, value) for value in values]
    recorded = [item for item in reads if item.status == "RECORDED"]
    cumulative: dict[tuple[str, UUID], dict] = {}
    for item in recorded:
        for line in item.lines:
            if line.supplier_document_line_id is not None:
                source_type = "DOCUMENT"
                source_line_id = line.supplier_document_line_id
                source_quantity = session.scalar(
                    select(SupplySupplierDocumentLine.quantity_base).where(
                        SupplySupplierDocumentLine.id == source_line_id,
                        SupplySupplierDocumentLine.tenant_id == values[0].tenant_id,
                    )
                )
            elif line.supplier_confirmation_line_id is not None:
                source_type = "CONFIRMATION"
                source_line_id = line.supplier_confirmation_line_id
                source_quantity = session.scalar(
                    select(SupplySupplierConfirmationLine.confirmed_quantity_base).where(
                        SupplySupplierConfirmationLine.id == source_line_id,
                        SupplySupplierConfirmationLine.tenant_id == values[0].tenant_id,
                    )
                )
            elif line.supplier_order_line_id is not None:
                source_type = "ORDER"
                source_line_id = line.supplier_order_line_id
                source_quantity = session.scalar(
                    select(SupplySupplierOrderLine.quantity_base).where(
                        SupplySupplierOrderLine.id == source_line_id,
                        SupplySupplierOrderLine.tenant_id == values[0].tenant_id,
                    )
                )
            else:
                source_type = "MANUAL"
                source_line_id = line.id
                source_quantity = None
            key = (source_type, source_line_id)
            bucket = cumulative.setdefault(key, {
                "source_type": source_type,
                "source_line_id": None if source_type == "MANUAL" else source_line_id,
                "product_name": line.product_name_snapshot,
                "unit_name": line.unit_name_snapshot,
                "source_quantity": (
                    Decimal(source_quantity) if source_quantity is not None else None
                ),
                "total_received": Decimal("0"),
                "total_accepted": Decimal("0"),
                "total_rejected": Decimal("0"),
                "downstream_accepted_quantity": Decimal("0"),
                "receipt_eligible_quantity": Decimal("0"),
            })
            bucket["total_received"] += line.received_quantity
            bucket["total_accepted"] += line.accepted_quantity
            bucket["total_rejected"] += line.rejected_quantity
            bucket["downstream_accepted_quantity"] += line.downstream_accepted_quantity
            if line.receipt_eligible_quantity is None:
                bucket["receipt_eligible_quantity"] = None
            elif bucket["receipt_eligible_quantity"] is not None:
                bucket["receipt_eligible_quantity"] += line.receipt_eligible_quantity
    cumulative_lines = []
    totals: dict[str, dict[str, Decimal]] = {}
    for bucket in cumulative.values():
        source_quantity = bucket["source_quantity"]
        bucket["remaining_quantity"] = (
            max(source_quantity - bucket["total_received"], Decimal("0"))
            if source_quantity is not None else None
        )
        cumulative_lines.append(SupplySupplierAcceptanceCumulativeLineRead(**bucket))
        unit = bucket["unit_name"] or "—"
        unit_totals = totals.setdefault(unit, {
            "documented": Decimal("0"), "received": Decimal("0"),
            "accepted": Decimal("0"), "rejected": Decimal("0"),
            "remaining": Decimal("0"),
        })
        if bucket["source_type"] == "DOCUMENT" and source_quantity is not None:
            unit_totals["documented"] += source_quantity
        unit_totals["received"] += bucket["total_received"]
        unit_totals["accepted"] += bucket["total_accepted"]
        unit_totals["rejected"] += bucket["total_rejected"]
        if bucket["remaining_quantity"] is not None:
            unit_totals["remaining"] += bucket["remaining_quantity"]
    latest = max(reads, key=lambda item: item.created_at) if reads else None
    return SupplySupplierAcceptanceSummary(
        draft_count=sum(item.status == "DRAFT" for item in reads),
        recorded_count=len(recorded), latest_acceptance=latest,
        quantities_by_unit=totals,
        cumulative_lines=cumulative_lines,
        open_issues_count=sum(item.open_issues_count for item in recorded),
        has_shortage=any(line.shortage_quantity > 0 for item in recorded for line in item.lines),
        has_excess=any(line.excess_quantity > 0 for item in recorded for line in item.lines),
    )


def _unit_price(document_line: SupplySupplierDocumentLine) -> Decimal | None:
    if document_line.pricing_basis == "UNIT":
        return Decimal(document_line.unit_price)
    if document_line.pricing_basis == "PACKAGE" and document_line.quantity_base:
        return (Decimal(document_line.line_amount) / Decimal(document_line.quantity_base)).quantize(Q)
    return None


def _remaining(session: Session, line: SupplySupplierDocumentLine) -> Decimal:
    used = session.scalar(select(func.coalesce(func.sum(SupplySupplierAcceptanceLine.received_quantity), 0)).join(
        SupplySupplierAcceptance,
        SupplySupplierAcceptance.id == SupplySupplierAcceptanceLine.acceptance_id,
    ).where(
        SupplySupplierAcceptanceLine.tenant_id == line.tenant_id,
        SupplySupplierAcceptanceLine.supplier_document_line_id == line.id,
        SupplySupplierAcceptance.status == "RECORDED",
    ))
    return max(Decimal(line.quantity_base) - Decimal(used), Decimal("0"))


def _document_defaults(session: Session, acceptance: SupplySupplierAcceptance, document: SupplySupplierDocument):
    order_lines = {line.id: line for line in session.scalars(select(SupplySupplierOrderLine).where(
        SupplySupplierOrderLine.tenant_id == acceptance.tenant_id,
        SupplySupplierOrderLine.supplier_order_id == acceptance.supplier_order_id,
    )).all()}
    for line in document.lines:
        if line.quantity_base is None or line.package_unit_id_snapshot is None:
            continue
        remaining = _remaining(session, line)
        if remaining <= 0:
            continue
        ordered = order_lines.get(line.supplier_order_line_id)
        price = _unit_price(line)
        acceptance.lines.append(SupplySupplierAcceptanceLine(
            tenant_id=acceptance.tenant_id, supplier_order_id=acceptance.supplier_order_id,
            supplier_confirmation_id=line.supplier_confirmation_id,
            supplier_document_line_id=line.id, supplier_order_line_id=line.supplier_order_line_id,
            supplier_confirmation_line_id=line.supplier_confirmation_line_id,
            product_name_snapshot=line.product_name_snapshot,
            product_id=ordered.product_id if ordered else None,
            unit_id=line.package_unit_id_snapshot, unit_name_snapshot=line.unit_name_snapshot,
            documented_quantity=remaining, received_quantity=remaining,
            accepted_quantity=remaining, rejected_quantity=Decimal("0"),
            documented_unit_price=price, accepted_unit_price=price,
            accepted_amount=(remaining * price).quantize(Q) if price else None,
            currency="RUB",
        ))


def _confirmation_defaults(acceptance: SupplySupplierAcceptance, confirmation: SupplySupplierConfirmation):
    for line in confirmation.lines:
        if line.response_status == "REJECTED" or not line.confirmed_quantity_base or not line.confirmed_package_unit_id:
            continue
        quantity = Decimal(line.confirmed_quantity_base)
        price = (Decimal(line.confirmed_planned_amount) / quantity).quantize(Q) if line.confirmed_planned_amount else None
        acceptance.lines.append(SupplySupplierAcceptanceLine(
            tenant_id=acceptance.tenant_id, supplier_order_id=acceptance.supplier_order_id,
            supplier_confirmation_id=confirmation.id,
            supplier_order_line_id=line.supplier_order_line_id,
            supplier_confirmation_line_id=line.id,
            product_name_snapshot=line.product_name_snapshot,
            product_id=line.supplier_order_line.product_id,
            unit_id=line.confirmed_package_unit_id,
            unit_name_snapshot=line.confirmed_package_unit.short_name_ru,
            documented_quantity=None, received_quantity=quantity,
            accepted_quantity=quantity, rejected_quantity=Decimal("0"),
            documented_unit_price=price, accepted_unit_price=price,
            accepted_amount=(quantity * price).quantize(Q) if price else None, currency="RUB",
        ))


def _order_defaults(acceptance: SupplySupplierAcceptance, order: SupplySupplierOrder):
    for line in order.lines:
        quantity = Decimal(line.quantity_base)
        acceptance.lines.append(SupplySupplierAcceptanceLine(
            tenant_id=acceptance.tenant_id, supplier_order_id=order.id,
            supplier_order_line_id=line.id, product_name_snapshot=line.product_name_snapshot,
            product_id=line.product_id, unit_id=line.package_unit_id_snapshot,
            unit_name_snapshot=line.package_unit_snapshot.short_name_ru,
            documented_quantity=None, received_quantity=quantity,
            accepted_quantity=quantity, rejected_quantity=Decimal("0"),
            documented_unit_price=line.base_unit_price_snapshot,
            accepted_unit_price=line.base_unit_price_snapshot,
            accepted_amount=line.planned_amount, currency="RUB",
        ))


def create_acceptance(session: Session, order_id: UUID, payload: SupplySupplierAcceptanceCreate, *, tenant_id: str, user_id: int):
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).with_for_update(of=SupplySupplierOrder))
    if order is None:
        raise SupplierAcceptanceNotFoundError
    if order.status != "SENT":
        raise SupplierAcceptanceStateError
    order = session.scalar(select(SupplySupplierOrder).where(
        SupplySupplierOrder.id == order_id, SupplySupplierOrder.tenant_id == tenant_id,
    ).options(selectinload(SupplySupplierOrder.lines).selectinload(SupplySupplierOrderLine.package_unit_snapshot)).execution_options(populate_existing=True))
    document = None
    confirmation = None
    if payload.supplier_document_id:
        document = session.scalar(select(SupplySupplierDocument).where(
            SupplySupplierDocument.id == payload.supplier_document_id,
            SupplySupplierDocument.tenant_id == tenant_id,
            SupplySupplierDocument.supplier_order_id == order_id,
            SupplySupplierDocument.status == "RECORDED",
        ).options(selectinload(SupplySupplierDocument.lines)))
        if document is None:
            raise SupplierAcceptanceLinkError
    else:
        confirmation = session.scalar(select(SupplySupplierConfirmation).where(
            SupplySupplierConfirmation.tenant_id == tenant_id,
            SupplySupplierConfirmation.supplier_order_id == order_id,
            SupplySupplierConfirmation.status == "RECORDED",
        ).options(
            selectinload(SupplySupplierConfirmation.lines).selectinload(SupplySupplierConfirmationLine.supplier_order_line),
            selectinload(SupplySupplierConfirmation.lines).selectinload(SupplySupplierConfirmationLine.confirmed_package_unit),
        ).order_by(SupplySupplierConfirmation.revision_number.desc()).limit(1))
    destination = _destination_mapping(
        session, payload.destination_mapping_id, tenant_id=tenant_id
    )
    acceptance = SupplySupplierAcceptance(
        tenant_id=tenant_id, supplier_order_id=order_id,
        supplier_document_id=document.id if document else None,
        supplier_confirmation_id=document.supplier_confirmation_id if document else (confirmation.id if confirmation else None),
        destination_mapping_id=destination.id if destination else None,
        received_at=payload.received_at, comment=payload.comment, created_by_user_id=user_id,
    )
    session.add(acceptance); session.flush()
    if document:
        _document_defaults(session, acceptance, document)
    elif confirmation:
        _confirmation_defaults(acceptance, confirmation)
    else:
        _order_defaults(acceptance, order)
    session.flush()
    for line in acceptance.lines:
        _autofill_acceptance_single_source(session, line)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback(); raise SupplierAcceptanceConflictError from error
    return read_acceptance(session, acceptance.id, tenant_id=tenant_id)


def update_acceptance(session: Session, acceptance_id: UUID, payload: SupplySupplierAcceptanceUpdate, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    if "destination_mapping_id" in payload.model_fields_set:
        destination = _destination_mapping(
            session, payload.destination_mapping_id, tenant_id=tenant_id
        )
        acceptance.destination_mapping_id = destination.id if destination else None
    for field in payload.model_fields_set - {"destination_mapping_id"}:
        setattr(acceptance, field, getattr(payload, field))
    session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def _validate_values(values: dict):
    received = Decimal(values["received_quantity"]); accepted = Decimal(values["accepted_quantity"]); rejected = Decimal(values["rejected_quantity"])
    reason = values.get("rejection_reason")
    if hasattr(reason, "value"): reason = reason.value
    comment = (values.get("comment") or "").strip() or None
    if accepted + rejected != received or (rejected > 0 and not reason) or (rejected == 0 and reason) or (reason == "OTHER" and not comment):
        raise SupplierAcceptanceValidationError
    price = values.get("accepted_unit_price")
    return received, accepted, rejected, reason, comment, ((accepted * Decimal(price)).quantize(Q) if price else None)


def create_line(session: Session, acceptance_id: UUID, payload: SupplySupplierAcceptanceLineCreate, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    unit = session.scalar(select(SupplyUnit).where(SupplyUnit.id == payload.unit_id, SupplyUnit.tenant_id == tenant_id))
    if unit is None: raise SupplierAcceptanceUnitError
    if payload.product_id and session.scalar(select(SupplyProduct.id).where(SupplyProduct.id == payload.product_id, SupplyProduct.tenant_id == tenant_id)) is None:
        raise SupplierAcceptanceLinkError
    values = payload.model_dump(); received, accepted, rejected, reason, comment, amount = _validate_values(values)
    acceptance.lines.append(SupplySupplierAcceptanceLine(
        tenant_id=tenant_id, supplier_order_id=acceptance.supplier_order_id,
        product_name_snapshot=payload.product_name_snapshot.strip(), product_id=payload.product_id,
        unit_id=unit.id, unit_name_snapshot=unit.short_name_ru,
        received_quantity=received, accepted_quantity=accepted, rejected_quantity=rejected,
        accepted_unit_price=payload.accepted_unit_price, accepted_amount=amount, currency="RUB",
        rejection_reason=reason, comment=comment,
    ))
    session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def update_line(session: Session, acceptance_id: UUID, line_id: UUID, payload: SupplySupplierAcceptanceLineUpdate, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    line = next((item for item in acceptance.lines if item.id == line_id), None)
    if line is None: raise SupplierAcceptanceNotFoundError
    values = {"received_quantity": line.received_quantity, "accepted_quantity": line.accepted_quantity, "rejected_quantity": line.rejected_quantity, "accepted_unit_price": line.accepted_unit_price, "rejection_reason": line.rejection_reason, "comment": line.comment}
    values.update(payload.model_dump(exclude_unset=True))
    received, accepted, rejected, reason, comment, amount = _validate_values(values)
    line.received_quantity=received; line.accepted_quantity=accepted; line.rejected_quantity=rejected
    line.accepted_unit_price=values.get("accepted_unit_price"); line.accepted_amount=amount
    line.rejection_reason=reason; line.comment=comment
    if "accepted_quantity" in payload.model_fields_set:
        if len(_order_sources(session, line, lock=True)) == 1:
            _autofill_acceptance_single_source(session, line)
        else:
            line.sources.clear()
    session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def update_acceptance_line_sources(
    session: Session, acceptance_id: UUID, line_id: UUID,
    values: list[SupplySupplierAcceptanceLineSourceWrite], *, tenant_id: str,
):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT":
        raise SupplierAcceptanceStateError
    line = next((item for item in acceptance.lines if item.id == line_id), None)
    if line is None:
        raise SupplierAcceptanceNotFoundError
    if len({value.supplier_order_line_source_id for value in values}) != len(values):
        raise SupplierAcceptanceValidationError
    line.sources.clear()
    session.flush()
    for value in values:
        line.sources.append(SupplySupplierAcceptanceLineSource(
            tenant_id=tenant_id,
            supplier_order_line_source_id=value.supplier_order_line_source_id,
            accepted_quantity=value.accepted_quantity,
        ))
    _validate_acceptance_distribution(session, line, lock=True)
    session.commit()
    return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def delete_line(session: Session, acceptance_id: UUID, line_id: UUID, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    line = next((item for item in acceptance.lines if item.id == line_id), None)
    if line is None: raise SupplierAcceptanceNotFoundError
    session.delete(line); session.commit(); return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def record_acceptance(session: Session, acceptance_id: UUID, *, tenant_id: str, user_id: int):
    ref = session.scalar(select(SupplySupplierAcceptance).where(SupplySupplierAcceptance.id == acceptance_id, SupplySupplierAcceptance.tenant_id == tenant_id))
    if ref is None: raise SupplierAcceptanceNotFoundError
    order = session.scalar(select(SupplySupplierOrder).where(SupplySupplierOrder.id == ref.supplier_order_id, SupplySupplierOrder.tenant_id == tenant_id).with_for_update(of=SupplySupplierOrder))
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if order is None or order.status != "SENT" or acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    if acceptance.destination_mapping_id is None:
        raise SupplierAcceptanceDestinationError
    _destination_mapping(
        session,
        acceptance.destination_mapping_id,
        tenant_id=tenant_id,
        lock=True,
    )
    if not acceptance.lines: raise SupplierAcceptanceValidationError
    document_line_ids = sorted(
        (line.supplier_document_line_id for line in acceptance.lines if line.supplier_document_line_id),
        key=str,
    )
    if document_line_ids:
        locked_lines = session.scalars(select(SupplySupplierDocumentLine).where(
            SupplySupplierDocumentLine.tenant_id == tenant_id,
            SupplySupplierDocumentLine.id.in_(document_line_ids),
        ).order_by(SupplySupplierDocumentLine.id).with_for_update()).all()
        locked_by_id = {line.id: line for line in locked_lines}
        for line in acceptance.lines:
            if line.supplier_document_line_id is None:
                continue
            source = locked_by_id.get(line.supplier_document_line_id)
            if source is None or line.documented_quantity != _remaining(session, source):
                raise SupplierAcceptanceConflictError
    for line in acceptance.lines:
        if line.unit_id is None: raise SupplierAcceptanceUnitError
        _validate_values({"received_quantity": line.received_quantity, "accepted_quantity": line.accepted_quantity, "rejected_quantity": line.rejected_quantity, "accepted_unit_price": line.accepted_unit_price, "rejection_reason": line.rejection_reason, "comment": line.comment})
        _validate_acceptance_distribution(session, line, lock=True)
    acceptance.status="RECORDED"; acceptance.recorded_by_user_id=user_id
    acceptance.recorded_at=datetime.now(timezone.utc); acceptance.accepted_at=acceptance.recorded_at
    _generate_resolution_issues(session, acceptance)
    try: session.commit()
    except IntegrityError as error: session.rollback(); raise SupplierAcceptanceConflictError from error
    return read_acceptance(session, acceptance_id, tenant_id=tenant_id)


def cancel_acceptance(session: Session, acceptance_id: UUID, *, tenant_id: str):
    acceptance = _get(session, acceptance_id, tenant_id=tenant_id, lock=True)
    if acceptance.status != "DRAFT": raise SupplierAcceptanceStateError
    acceptance.status="CANCELLED"; session.commit()
    return read_acceptance(session, acceptance_id, tenant_id=tenant_id)
