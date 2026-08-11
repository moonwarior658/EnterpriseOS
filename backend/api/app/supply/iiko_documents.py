from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.integrations.iiko.document_intent import (
    IikoDocumentReconciliationRequiredError,
    IikoDocumentRetryNotAllowedError,
    create_persistent_outgoing_invoice,
)
from app.integrations.iiko.document_routing import (
    internal_transfer_flows_for_department,
    outgoing_invoice_flows_for_department,
    resolve_outgoing_invoice_route,
)
from app.integrations.iiko.document_write import IikoOutgoingInvoiceLineInput
from app.integrations.iiko.provider import IikoProvider
from app.models.iiko import (
    IikoDocumentType,
    IikoDocumentWrite,
    IikoMappingStatus,
    IikoProductMapping,
    IikoUnitMapping,
    IikoWarehouseMapping,
)
from app.models.supply import (
    SupplyProductSourceMapping,
    SupplyProductSourceRole,
    SupplyRequest,
    SupplyRequestLine,
)
from app.supply.service import (
    SupplyRequestAlreadyPlannedError,
    SupplyRequestNotFoundError,
    get_supply_request,
    plan_supply_request,
)


class SupplyIikoDocumentWorkflowError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SupplyInternalTransferWriteUnsupportedError(
    SupplyIikoDocumentWorkflowError
):
    pass


class SupplyIikoDocumentPreparationError(SupplyIikoDocumentWorkflowError):
    pass


@dataclass(frozen=True, slots=True)
class SupplyOutgoingInvoiceGroup:
    flow: SupplyProductSourceRole
    lines: tuple[IikoOutgoingInvoiceLineInput, ...]


def list_supply_iiko_document_writes(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
) -> list[IikoDocumentWrite]:
    request_exists = session.scalar(select(SupplyRequest.id).where(
        SupplyRequest.id == request_id,
        SupplyRequest.tenant_id == tenant_id,
    ))
    if request_exists is None:
        raise SupplyRequestNotFoundError
    return list(session.scalars(
        select(IikoDocumentWrite)
        .where(IikoDocumentWrite.supply_request_id == request_id)
        .order_by(IikoDocumentWrite.created_at, IikoDocumentWrite.id)
    ).all())


def _document_quantity(line: SupplyRequestLine) -> Decimal | None:
    quantity = line.send_quantity if line.send_quantity is not None else line.quantity
    if quantity is None or quantity <= 0:
        return None
    return quantity


def prepare_outgoing_invoice_groups(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
) -> tuple[SupplyOutgoingInvoiceGroup, ...]:
    request = session.scalar(
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == tenant_id,
        )
        .options(
            joinedload(SupplyRequest.department),
            selectinload(SupplyRequest.lines),
        )
    )
    if request is None:
        raise SupplyRequestNotFoundError

    document_lines = [
        (line, quantity)
        for line in request.lines
        if (quantity := _document_quantity(line)) is not None
    ]
    department_code = request.department.code
    if (
        document_lines
        and internal_transfer_flows_for_department(department_code)
    ):
        raise SupplyInternalTransferWriteUnsupportedError(
            "SUPPLY_INTERNAL_TRANSFER_DOCUMENT_WRITE_UNSUPPORTED"
        )

    supported_flows = outgoing_invoice_flows_for_department(department_code)
    if (
        not document_lines
        or not supported_flows
        or request.department.legal_contour is None
    ):
        return ()

    product_ids = {
        line.product_id for line, _ in document_lines if line.product_id is not None
    }
    unit_ids = {
        line.requested_unit_id
        for line, _ in document_lines
        if line.requested_unit_id is not None
    }
    product_mappings = {
        item.eos_product_id: item
        for item in session.scalars(select(IikoProductMapping).where(
            IikoProductMapping.tenant_id == tenant_id,
            IikoProductMapping.eos_product_id.in_(product_ids),
            IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
            IikoProductMapping.is_deleted.is_(False),
        )).all()
    } if product_ids else {}
    unit_mappings = {
        item.eos_unit_id: item
        for item in session.scalars(select(IikoUnitMapping).where(
            IikoUnitMapping.tenant_id == tenant_id,
            IikoUnitMapping.eos_unit_id.in_(unit_ids),
            IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
            IikoUnitMapping.is_deleted.is_(False),
        )).all()
    } if unit_ids else {}
    source_mappings = {
        item.eos_product_id: item
        for item in session.scalars(select(SupplyProductSourceMapping).where(
            SupplyProductSourceMapping.tenant_id == tenant_id,
            SupplyProductSourceMapping.eos_product_id.in_(product_ids),
            SupplyProductSourceMapping.legal_contour
            == request.department.legal_contour,
        )).all()
    } if product_ids and request.department.legal_contour is not None else {}
    source_ids = {
        item.source_warehouse_mapping_id for item in source_mappings.values()
    }
    sources = {
        item.id: item
        for item in session.scalars(select(IikoWarehouseMapping).where(
            IikoWarehouseMapping.id.in_(source_ids)
        )).all()
    } if source_ids else {}

    grouped: dict[
        SupplyProductSourceRole,
        list[IikoOutgoingInvoiceLineInput],
    ] = defaultdict(list)
    for line, quantity in document_lines:
        product_mapping = product_mappings.get(line.product_id)
        unit_mapping = unit_mappings.get(line.requested_unit_id)
        source_mapping = source_mappings.get(line.product_id)
        source = (
            sources.get(source_mapping.source_warehouse_mapping_id)
            if source_mapping is not None else None
        )
        if (
            line.match_status != "MATCHED"
            or line.product_id is None
            or product_mapping is None
            or unit_mapping is None
            or source_mapping is None
            or source is None
            or source_mapping.role not in supported_flows
        ):
            raise SupplyIikoDocumentPreparationError(
                "SUPPLY_IIKO_DOCUMENT_PREPARATION_INCOMPLETE"
            )
        route = resolve_outgoing_invoice_route(
            department_code,
            source_mapping.role,
        )
        if source.iiko_warehouse_id != route.source_store_id:
            raise SupplyIikoDocumentPreparationError(
                "SUPPLY_IIKO_DOCUMENT_SOURCE_MISMATCH"
            )
        grouped[source_mapping.role].append(IikoOutgoingInvoiceLineInput(
            iiko_product_id=product_mapping.iiko_product_id,
            product_mapping_status=product_mapping.status,
            iiko_unit_id=unit_mapping.iiko_unit_id,
            quantity=quantity,
        ))

    flow_order = {
        SupplyProductSourceRole.MAIN: 0,
        SupplyProductSourceRole.PACKAGING: 1,
        SupplyProductSourceRole.HOUSEHOLD: 2,
    }
    return tuple(
        SupplyOutgoingInvoiceGroup(flow=flow, lines=tuple(lines))
        for flow, lines in sorted(
            grouped.items(), key=lambda item: flow_order[item[0]]
        )
    )


async def plan_supply_request_with_iiko_documents(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    request_id: UUID,
    expected_version: int,
    user_id: int,
    simple_mode: bool,
) -> SupplyRequest:
    groups = prepare_outgoing_invoice_groups(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
    )
    session.rollback()

    try:
        request = plan_supply_request(
            session,
            request_id,
            expected_version=expected_version,
            user_id=user_id,
            simple_mode=simple_mode,
        )
    except SupplyRequestAlreadyPlannedError:
        session.rollback()
        request = get_supply_request(
            session,
            request_id,
            tenant_id=tenant_id,
        )

    planned_at = request.planned_at
    department_code = request.department.code
    if planned_at is None:
        raise SupplyIikoDocumentWorkflowError(
            "SUPPLY_IIKO_DOCUMENT_REQUEST_NOT_PLANNED"
        )
    if planned_at.tzinfo is None or planned_at.utcoffset() is None:
        planned_at = planned_at.replace(tzinfo=timezone.utc)
    session.rollback()

    for group in groups:
        try:
            await create_persistent_outgoing_invoice(
                session,
                provider,
                supply_request_id=request_id,
                date_incoming=planned_at,
                department_code=department_code,
                flow=group.flow,
                lines=group.lines,
            )
        except (
            IikoDocumentReconciliationRequiredError,
            IikoDocumentRetryNotAllowedError,
        ):
            # Existing PENDING/UNKNOWN/FAILED intents are deliberately inert.
            continue
        except Exception:
            session.rollback()
            existing = session.scalar(select(IikoDocumentWrite.id).where(
                IikoDocumentWrite.supply_request_id == request_id,
                IikoDocumentWrite.source_store_id
                == resolve_outgoing_invoice_route(
                    department_code,
                    group.flow,
                ).source_store_id,
                IikoDocumentWrite.document_type
                == IikoDocumentType.OUTGOING_INVOICE,
            ))
            session.rollback()
            if existing is None:
                raise SupplyIikoDocumentWorkflowError(
                    "SUPPLY_IIKO_DOCUMENT_WRITE_NOT_STARTED"
                )

    return get_supply_request(
        session,
        request_id,
        tenant_id=tenant_id,
    )
