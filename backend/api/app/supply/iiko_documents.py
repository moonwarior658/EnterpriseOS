from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.integrations.iiko.document_intent import (
    IikoDocumentReconciliationRequiredError,
    IikoDocumentRetryNotAllowedError,
    create_persistent_outgoing_invoice,
    reconcile_outgoing_invoice_intent,
)
from app.integrations.iiko.document_routing import (
    internal_transfer_flows_for_department,
    outgoing_invoice_flows_for_department,
    resolve_outgoing_invoice_route,
)
from app.integrations.iiko.document_write import IikoOutgoingInvoiceLineInput
from app.integrations.iiko.exceptions import IikoError
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import IikoOutgoingInvoiceDto
from app.models.iiko import (
    IikoDocumentType,
    IikoDocumentWrite,
    IikoDocumentWriteStatus,
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
    SupplyRequestVersionConflictError,
    get_supply_request,
    fulfill_supply_request_as_planned,
    plan_supply_request,
)
from app.schemas.supply import SupplyRequestFulfillmentItem


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


class SupplyIikoDocumentFinalizationError(SupplyIikoDocumentWorkflowError):
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
    # Planning documents describe the approved request quantity. The pending
    # fulfillment fact is finalized separately and must not rewrite the plan.
    quantity = line.quantity
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
            intent = await create_persistent_outgoing_invoice(
                session,
                provider,
                supply_request_id=request_id,
                date_incoming=planned_at,
                department_code=department_code,
                flow=group.flow,
                lines=group.lines,
            )
            if (
                intent.status == IikoDocumentWriteStatus.CREATED
                and intent.iiko_document_id is None
            ):
                await reconcile_outgoing_invoice_intent(
                    session,
                    provider,
                    intent_id=intent.id,
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


@dataclass(frozen=True, slots=True)
class _FinalizationDocument:
    iiko_document_id: UUID
    document_number: str
    date_incoming: datetime
    source_store_id: UUID
    product_ids: tuple[UUID, ...]
    actual_quantities: tuple[Decimal, ...]


def _finalization_documents(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    expected_version: int,
    items: list[SupplyRequestFulfillmentItem] | None,
) -> tuple[SupplyRequest, tuple[_FinalizationDocument, ...]]:
    request = session.scalar(
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == tenant_id,
        )
        .options(selectinload(SupplyRequest.lines))
    )
    if request is None:
        raise SupplyRequestNotFoundError
    if request.status in {"FULFILLED", "PARTIALLY_FULFILLED"}:
        return request, ()
    if request.status != "PLANNED":
        raise SupplyIikoDocumentFinalizationError(
            "SUPPLY_REQUEST_NOT_FULFILLABLE"
        )
    if request.version != expected_version:
        raise SupplyRequestVersionConflictError(
            current_version=request.version,
            expected_version=expected_version,
        )

    actual_by_line = (
        {item.line_id: item.fulfilled_quantity for item in items}
        if items is not None else None
    )
    if actual_by_line is not None and (
        len(actual_by_line) != len(request.lines)
        or set(actual_by_line) != {line.id for line in request.lines}
    ):
        raise SupplyIikoDocumentFinalizationError(
            "SUPPLY_FULFILLMENT_INVALID_ACTION"
        )

    intents = list(session.scalars(
        select(IikoDocumentWrite)
        .where(
            IikoDocumentWrite.supply_request_id == request_id,
            IikoDocumentWrite.document_type == IikoDocumentType.OUTGOING_INVOICE,
        )
        .order_by(IikoDocumentWrite.created_at, IikoDocumentWrite.id)
    ).all())
    if not intents:
        return request, ()

    product_ids = {
        line.product_id for line in request.lines if line.product_id is not None
    }
    product_mappings = {
        mapping.eos_product_id: mapping
        for mapping in session.scalars(select(IikoProductMapping).where(
            IikoProductMapping.tenant_id == tenant_id,
            IikoProductMapping.eos_product_id.in_(product_ids),
            IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
            IikoProductMapping.is_deleted.is_(False),
        )).all()
    } if product_ids else {}
    source_mappings = {
        mapping.eos_product_id: mapping
        for mapping in session.scalars(select(SupplyProductSourceMapping).where(
            SupplyProductSourceMapping.tenant_id == tenant_id,
            SupplyProductSourceMapping.eos_product_id.in_(product_ids),
            SupplyProductSourceMapping.legal_contour
            == request.department.legal_contour,
        )).all()
    } if product_ids else {}
    source_ids = {
        mapping.source_warehouse_mapping_id
        for mapping in source_mappings.values()
    }
    sources = {
        source.id: source
        for source in session.scalars(select(IikoWarehouseMapping).where(
            IikoWarehouseMapping.id.in_(source_ids)
        )).all()
    } if source_ids else {}

    lines_by_store: dict[UUID, list[tuple[UUID, Decimal]]] = defaultdict(list)
    for line in sorted(request.lines, key=lambda value: value.position):
        if line.quantity is None or line.quantity <= 0:
            continue
        product_mapping = product_mappings.get(line.product_id)
        source_mapping = source_mappings.get(line.product_id)
        source = (
            sources.get(source_mapping.source_warehouse_mapping_id)
            if source_mapping is not None else None
        )
        if product_mapping is None or source is None:
            raise SupplyIikoDocumentFinalizationError(
                "SUPPLY_IIKO_DOCUMENT_PREPARATION_INCOMPLETE"
            )
        quantity = (
            actual_by_line[line.id]
            if actual_by_line is not None
            else line.send_quantity
        )
        if quantity is None or not quantity.is_finite() or quantity < 0:
            raise SupplyIikoDocumentFinalizationError(
                "SUPPLY_SEND_QUANTITY_INVALID"
            )
        if (
            line.requested_unit is not None
            and not line.requested_unit.allows_fraction
            and quantity != quantity.to_integral_value()
        ):
            raise SupplyIikoDocumentFinalizationError(
                "SUPPLY_SEND_QUANTITY_INVALID"
            )
        lines_by_store[source.iiko_warehouse_id].append((
            product_mapping.iiko_product_id,
            quantity,
        ))

    documents: list[_FinalizationDocument] = []
    for intent in intents:
        if (
            intent.status != IikoDocumentWriteStatus.CREATED
            or intent.iiko_document_id is None
            or not intent.iiko_document_number
            or intent.expected_payload is None
        ):
            raise SupplyIikoDocumentFinalizationError(
                "SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED"
            )
        try:
            date_incoming = datetime.fromisoformat(
                str(intent.expected_payload["date_incoming"])
            )
            expected_product_ids = tuple(
                UUID(str(item["product_id"]))
                for item in intent.expected_payload["items"]
            )
        except (KeyError, TypeError, ValueError) as error:
            raise SupplyIikoDocumentFinalizationError(
                "SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED"
            ) from error
        actual_lines = lines_by_store.pop(intent.source_store_id, None)
        if actual_lines is None or tuple(
            product_id for product_id, _ in actual_lines
        ) != expected_product_ids:
            raise SupplyIikoDocumentFinalizationError(
                "SUPPLY_IIKO_DOCUMENT_ITEMS_MISMATCH"
            )
        documents.append(_FinalizationDocument(
            iiko_document_id=intent.iiko_document_id,
            document_number=intent.iiko_document_number,
            date_incoming=date_incoming,
            source_store_id=intent.source_store_id,
            product_ids=expected_product_ids,
            actual_quantities=tuple(quantity for _, quantity in actual_lines),
        ))
    if lines_by_store:
        raise SupplyIikoDocumentFinalizationError(
            "SUPPLY_IIKO_DOCUMENT_ITEMS_MISMATCH"
        )
    return request, tuple(documents)


async def _authoritative_finalization_invoice(
    provider: IikoProvider,
    document: _FinalizationDocument,
) -> IikoOutgoingInvoiceDto:
    invoices = await provider.get_outgoing_invoices(
        date_from=document.date_incoming.date() - timedelta(days=1),
        date_to=document.date_incoming.date() + timedelta(days=1),
    )
    matches = []
    for invoice in invoices:
        try:
            invoice_id = UUID(invoice.external_id or "")
        except ValueError:
            continue
        if (
            invoice_id == document.iiko_document_id
            and invoice.document_number == document.document_number
        ):
            matches.append(invoice)
    if len(matches) != 1:
        raise SupplyIikoDocumentFinalizationError(
            "SUPPLY_IIKO_DOCUMENT_READBACK_NOT_FOUND"
        )
    return matches[0]


def _verify_actual_invoice(
    invoice: IikoOutgoingInvoiceDto,
    document: _FinalizationDocument,
    *,
    required_status: str,
) -> None:
    if invoice.status != required_status:
        raise SupplyIikoDocumentFinalizationError(
            "SUPPLY_IIKO_DOCUMENT_FINAL_STATUS_INVALID"
            if required_status == "PROCESSED"
            else "SUPPLY_IIKO_DOCUMENT_UPDATE_NOT_VERIFIED"
        )
    if tuple((item.product_id, item.amount) for item in invoice.items) != tuple(
        zip(document.product_ids, document.actual_quantities, strict=True)
    ):
        raise SupplyIikoDocumentFinalizationError(
            "SUPPLY_IIKO_DOCUMENT_QUANTITIES_MISMATCH"
        )


async def finalize_supply_request_with_iiko_documents(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    request_id: UUID,
    expected_version: int,
    user_id: int,
    items: list[SupplyRequestFulfillmentItem] | None,
) -> SupplyRequest:
    request, documents = _finalization_documents(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        expected_version=expected_version,
        items=items,
    )
    if request.status in {"FULFILLED", "PARTIALLY_FULFILLED"}:
        session.rollback()
        return get_supply_request(session, request_id, tenant_id=tenant_id)
    session.rollback()

    if documents:
        try:
            to_process: list[_FinalizationDocument] = []
            for document in documents:
                authoritative = await _authoritative_finalization_invoice(
                    provider, document
                )
                if authoritative.status == "PROCESSED":
                    _verify_actual_invoice(
                        authoritative, document, required_status="PROCESSED"
                    )
                    continue
                if authoritative.status != "NEW" or authoritative.revision is None:
                    raise SupplyIikoDocumentFinalizationError(
                        "SUPPLY_IIKO_DOCUMENT_NOT_NEW"
                    )
                update_result = await provider.update_outgoing_invoice(
                    authoritative,
                    actual_quantities=document.actual_quantities,
                )
                if (
                    not update_result.valid
                    or update_result.document_number != document.document_number
                ):
                    raise SupplyIikoDocumentFinalizationError(
                        "SUPPLY_IIKO_DOCUMENT_UPDATE_VALIDATION_FAILED"
                    )
                updated = await _authoritative_finalization_invoice(
                    provider, document
                )
                _verify_actual_invoice(updated, document, required_status="NEW")
                to_process.append(document)

            if to_process:
                first_results = await provider.process_outgoing_invoices(
                    [document.iiko_document_id for document in to_process],
                    enable_warnings=True,
                )
                result_by_number = {
                    result.document_number: result for result in first_results
                    if result.document_number is not None
                }
                if len(result_by_number) != len(to_process):
                    raise SupplyIikoDocumentFinalizationError(
                        "SUPPLY_IIKO_DOCUMENT_PROCESS_RESPONSE_INVALID"
                    )
                warning_documents: list[_FinalizationDocument] = []
                for document in to_process:
                    result = result_by_number.get(document.document_number)
                    if result is None:
                        raise SupplyIikoDocumentFinalizationError(
                            "SUPPLY_IIKO_DOCUMENT_PROCESS_RESPONSE_INVALID"
                        )
                    if result.valid:
                        continue
                    if result.warning:
                        warning_documents.append(document)
                        continue
                    raise SupplyIikoDocumentFinalizationError(
                        "SUPPLY_IIKO_DOCUMENT_PROCESS_VALIDATION_FAILED"
                    )
                if warning_documents:
                    ack_results = await provider.process_outgoing_invoices(
                        [document.iiko_document_id for document in warning_documents],
                        enable_warnings=False,
                    )
                    ack_by_number = {
                        result.document_number: result for result in ack_results
                        if result.document_number is not None
                    }
                    if any(
                        (result := ack_by_number.get(document.document_number)) is None
                        or not result.valid
                        for document in warning_documents
                    ):
                        raise SupplyIikoDocumentFinalizationError(
                            "SUPPLY_IIKO_DOCUMENT_WARNING_ACK_FAILED"
                        )

            for document in documents:
                processed = await _authoritative_finalization_invoice(
                    provider, document
                )
                _verify_actual_invoice(
                    processed, document, required_status="PROCESSED"
                )
        except SupplyIikoDocumentFinalizationError:
            session.rollback()
            raise
        except IikoError as error:
            session.rollback()
            raise SupplyIikoDocumentFinalizationError(
                "SUPPLY_IIKO_DOCUMENT_FINALIZATION_FAILED"
            ) from error

    current = get_supply_request(session, request_id, tenant_id=tenant_id)
    if current.status in {"FULFILLED", "PARTIALLY_FULFILLED"}:
        session.rollback()
        return current
    session.rollback()
    return fulfill_supply_request_as_planned(
        session,
        request_id,
        expected_version=expected_version,
        user_id=user_id,
        items=items,
    )
