from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import (
    IikoIncomingInvoiceDto,
    IikoIncomingInvoicePreviewDto,
    IikoIncomingInvoicePreviewItemDto,
)
from app.integrations.iiko.service import safe_error_message
from app.models.iiko import (
    IikoMappingStatus,
    IikoProductMapping,
    IikoSupplierMapping,
    IikoSupplierMappingStatus,
    IikoUnitMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
)
from app.models.supply import (
    SupplyIikoIncomingReceipt,
    SupplyIikoIncomingReceiptLine,
    SupplySupplierAcceptance,
    SupplySupplierAcceptanceLine,
    SupplySupplierDocumentLine,
)
from app.schemas.iiko_incoming_receipt import (
    SupplyIikoIncomingReceiptLineRead,
    SupplyIikoIncomingReceiptRead,
)
from app.supply.incoming_receipt_readiness import (
    AcceptanceReceiptReadiness,
    ReceiptLineReadinessInput,
    build_incoming_invoice_preview,
    evaluate_acceptance_receipt,
)
from app.supply.supplier_acceptances import _downstream_quantities


ACTIVE_ALLOCATION_STATUSES = ("READY", "CREATING", "CREATED", "PROCESSING")
QUANTITY_QUANTUM = Decimal("0.000001")
PRICE_QUANTUM = Decimal("0.000000001")
MONEY_QUANTUM = Decimal("0.000001")


class IncomingReceiptNotFoundError(LookupError): pass
class IncomingReceiptStateError(ValueError): pass
class IncomingReceiptReadinessError(ValueError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("READINESS_BLOCKED")
class IncomingReceiptConflictError(ValueError): pass


def _receipt_options():
    return (
        selectinload(SupplyIikoIncomingReceipt.lines),
        joinedload(SupplyIikoIncomingReceipt.acceptance)
        .joinedload(SupplySupplierAcceptance.supplier_order),
    )


def _get_receipt(
    session: Session,
    receipt_id: UUID,
    *,
    tenant_id: str,
    lock: bool = False,
) -> SupplyIikoIncomingReceipt:
    query = (
        select(SupplyIikoIncomingReceipt)
        .where(
            SupplyIikoIncomingReceipt.id == receipt_id,
            SupplyIikoIncomingReceipt.tenant_id == tenant_id,
        )
        .options(*_receipt_options())
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update(of=SupplyIikoIncomingReceipt)
    value = session.scalar(query)
    if value is None:
        raise IncomingReceiptNotFoundError
    return value


def _get_acceptance(
    session: Session,
    acceptance_id: UUID,
    *,
    tenant_id: str,
    lock: bool,
) -> SupplySupplierAcceptance:
    query = (
        select(SupplySupplierAcceptance)
        .where(
            SupplySupplierAcceptance.id == acceptance_id,
            SupplySupplierAcceptance.tenant_id == tenant_id,
        )
        .options(
            joinedload(SupplySupplierAcceptance.supplier_order),
            selectinload(SupplySupplierAcceptance.lines),
            selectinload(SupplySupplierAcceptance.resolutions),
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update(of=SupplySupplierAcceptance)
    value = session.scalar(query)
    if value is None:
        raise IncomingReceiptNotFoundError
    if value.status != "RECORDED":
        raise IncomingReceiptStateError("ACCEPTANCE_NOT_RECORDED")
    return value


def _posted_facts(
    session: Session,
    document_line_ids: list[UUID],
) -> dict[UUID, tuple[Decimal, Decimal]]:
    rows = list(session.execute(
        select(
            SupplyIikoIncomingReceiptLine.supplier_document_line_id,
            SupplyIikoIncomingReceiptLine.accounted_quantity,
            SupplyIikoIncomingReceiptLine.accounted_sum,
        )
        .join(
            SupplyIikoIncomingReceipt,
            SupplyIikoIncomingReceipt.id
            == SupplyIikoIncomingReceiptLine.receipt_id,
        )
        .where(
            SupplyIikoIncomingReceiptLine.supplier_document_line_id.in_(document_line_ids),
            SupplyIikoIncomingReceipt.status == "POSTED",
        )
        .with_for_update(of=SupplyIikoIncomingReceiptLine)
    ))
    result: dict[UUID, tuple[Decimal, Decimal]] = {}
    for document_line_id, quantity, amount in rows:
        previous_quantity, previous_amount = result.get(
            document_line_id, (Decimal("0"), Decimal("0"))
        )
        result[document_line_id] = (
            previous_quantity + Decimal(quantity),
            previous_amount + Decimal(amount),
        )
    return result


def _readiness(
    session: Session,
    acceptance: SupplySupplierAcceptance,
    *,
    lock_allocation: bool,
    exclude_receipt_id: UUID | None = None,
) -> tuple[AcceptanceReceiptReadiness, IikoSupplierMapping | None, IikoWarehouseMapping | None]:
    tenant_id = acceptance.tenant_id
    supplier_id = acceptance.supplier_order.supplier_id
    supplier_mapping = session.scalar(select(IikoSupplierMapping).where(
        IikoSupplierMapping.tenant_id == tenant_id,
        IikoSupplierMapping.supplier_id == supplier_id,
        IikoSupplierMapping.status == IikoSupplierMappingStatus.CONFIRMED,
    ))
    destination = session.scalar(select(IikoWarehouseMapping).where(
        IikoWarehouseMapping.tenant_id == tenant_id,
        IikoWarehouseMapping.id == acceptance.destination_mapping_id,
        IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
        IikoWarehouseMapping.destination_type == IikoWarehouseDestinationType.DESTINATION,
        IikoWarehouseMapping.is_deleted.is_(False),
    )) if acceptance.destination_mapping_id is not None else None

    document_line_ids = [
        line.supplier_document_line_id for line in acceptance.lines
        if line.supplier_document_line_id is not None
    ]
    document_query = select(SupplySupplierDocumentLine).where(
        SupplySupplierDocumentLine.tenant_id == tenant_id,
        SupplySupplierDocumentLine.id.in_(document_line_ids or [uuid4()]),
    ).order_by(SupplySupplierDocumentLine.id)
    if lock_allocation:
        document_query = document_query.with_for_update()
    document_lines = {
        value.id: value for value in session.scalars(document_query).all()
    }
    if lock_allocation and document_line_ids:
        competing = session.scalar(
            select(SupplyIikoIncomingReceiptLine.id)
            .join(
                SupplyIikoIncomingReceipt,
                SupplyIikoIncomingReceipt.id
                == SupplyIikoIncomingReceiptLine.receipt_id,
            )
            .where(
                SupplyIikoIncomingReceiptLine.tenant_id == tenant_id,
                SupplyIikoIncomingReceiptLine.supplier_document_line_id.in_(document_line_ids),
                SupplyIikoIncomingReceipt.status.in_(ACTIVE_ALLOCATION_STATUSES),
                *(
                    (SupplyIikoIncomingReceipt.id != exclude_receipt_id,)
                    if exclude_receipt_id is not None else ()
                ),
            )
            .limit(1)
        )
        if competing is not None:
            raise IncomingReceiptConflictError("ACTIVE_DOCUMENT_LINE_RECEIPT_EXISTS")
    posted = _posted_facts(session, document_line_ids) if document_line_ids else {}

    product_ids = [line.product_id for line in acceptance.lines if line.product_id]
    unit_ids = [line.unit_id for line in acceptance.lines if line.unit_id]
    product_mappings = {
        value.eos_product_id: value for value in session.scalars(
            select(IikoProductMapping).where(
                IikoProductMapping.tenant_id == tenant_id,
                IikoProductMapping.eos_product_id.in_(product_ids or [uuid4()]),
                IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
                IikoProductMapping.is_deleted.is_(False),
            )
        ).all()
    }
    unit_mappings = {
        value.eos_unit_id: value for value in session.scalars(
            select(IikoUnitMapping).where(
                IikoUnitMapping.tenant_id == tenant_id,
                IikoUnitMapping.eos_unit_id.in_(unit_ids or [uuid4()]),
                IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
                IikoUnitMapping.is_deleted.is_(False),
            )
        ).all()
    }
    resolutions: dict[UUID, list] = {}
    for item in acceptance.resolutions:
        resolutions.setdefault(item.acceptance_line_id, []).append(item)

    inputs = []
    for line in acceptance.lines:
        document_line = document_lines.get(line.supplier_document_line_id)
        product_mapping = product_mappings.get(line.product_id)
        unit_mapping = unit_mappings.get(line.unit_id)
        _, eligible = _downstream_quantities(
            line, resolutions.get(line.id, [])
        )
        previous_quantity, previous_amount = posted.get(
            line.supplier_document_line_id, (Decimal("0"), Decimal("0"))
        )
        inputs.append(ReceiptLineReadinessInput(
            line_id=line.id,
            physical_line=(
                line.product_id is not None
                and line.unit_id is not None
                and line.supplier_document_line_id is not None
            ),
            receipt_eligible_quantity=eligible,
            unresolved_excess=eligible is None,
            pricing_basis=document_line.pricing_basis if document_line else None,
            supplier_document_line_id=line.supplier_document_line_id,
            document_quantity=(
                Decimal(document_line.quantity_base)
                if document_line is not None and document_line.quantity_base is not None
                else None
            ),
            historical_unit_price=(
                Decimal(document_line.unit_price)
                if document_line is not None and document_line.unit_price is not None
                else (
                    Decimal(document_line.line_amount) / Decimal(document_line.quantity_base)
                    if document_line is not None
                    and document_line.quantity_base is not None
                    and Decimal(document_line.quantity_base) > 0
                    and document_line.pricing_basis == "PACKAGE"
                    else None
                )
            ),
            historical_line_sum=(
                Decimal(document_line.line_amount) if document_line is not None else None
            ),
            iiko_supplier_id=(supplier_mapping.iiko_supplier_id if supplier_mapping else None),
            supplier_mapping_confirmed=supplier_mapping is not None,
            supplier_reference_current=(
                supplier_mapping is not None and not supplier_mapping.iiko_supplier_deleted
            ),
            iiko_store_id=(destination.iiko_warehouse_id if destination else None),
            store_mapping_confirmed=destination is not None,
            iiko_product_id=(product_mapping.iiko_product_id if product_mapping else None),
            product_mapping_confirmed=product_mapping is not None,
            iiko_unit_id=(unit_mapping.iiko_unit_id if unit_mapping else None),
            unit_mapping_confirmed=unit_mapping is not None,
            product_main_unit_id=(product_mapping.source_unit_id if product_mapping else None),
            vat_omission_safe=True,
            previously_accounted_quantity=previous_quantity,
            previously_accounted_amount=previous_amount,
        ))
    return evaluate_acceptance_receipt(tuple(inputs)), supplier_mapping, destination


def _replace_lines(
    session: Session,
    receipt: SupplyIikoIncomingReceipt,
    acceptance: SupplySupplierAcceptance,
    readiness: AcceptanceReceiptReadiness,
) -> None:
    acceptance_by_id = {line.id: line for line in acceptance.lines}
    receipt.lines.clear()
    if receipt in session:
        session.flush()
    line_no = 0
    for ready_line in readiness.lines:
        if ready_line.contract is None:
            continue
        source = acceptance_by_id[ready_line.line_id]
        if (
            source.supplier_document_line_id is None
            or source.product_id is None
            or source.unit_id is None
        ):
            raise IncomingReceiptReadinessError(["HISTORICAL_PRICE_MISSING"])
        line_no += 1
        contract = ready_line.contract
        receipt.lines.append(SupplyIikoIncomingReceiptLine(
            tenant_id=receipt.tenant_id,
            acceptance_line_id=source.id,
            supplier_document_line_id=source.supplier_document_line_id,
            product_id=source.product_id,
            unit_id=source.unit_id,
            iiko_product_id=contract.product_id,
            iiko_amount_unit_id=contract.amount_unit_id,
            iiko_store_id=contract.store_id,
            quantity=contract.amount.quantize(QUANTITY_QUANTUM),
            historical_unit_price=contract.price.quantize(PRICE_QUANTUM),
            allocated_sum=contract.sum_amount.quantize(MONEY_QUANTUM),
            line_no=line_no,
            accounted_quantity=Decimal("0"),
            accounted_sum=Decimal("0"),
        ))


def _build_preview(
    session: Session,
    receipt: SupplyIikoIncomingReceipt,
) -> IikoIncomingInvoicePreviewDto:
    supplier_mapping = session.scalar(select(IikoSupplierMapping).where(
        IikoSupplierMapping.id == receipt.iiko_supplier_mapping_id,
        IikoSupplierMapping.tenant_id == receipt.tenant_id,
    ))
    if supplier_mapping is None or not receipt.lines:
        raise IncomingReceiptStateError("RECEIPT_SNAPSHOT_INCOMPLETE")
    return IikoIncomingInvoicePreviewDto(
        document_number=receipt.eos_document_number,
        date_incoming=receipt.date_incoming,
        incoming_date=receipt.incoming_date,
        supplier_id=supplier_mapping.iiko_supplier_id,
        default_store_id=receipt.lines[0].iiko_store_id,
        items=tuple(IikoIncomingInvoicePreviewItemDto(
            num=line.line_no,
            product_id=line.iiko_product_id,
            store_id=line.iiko_store_id,
            amount=line.quantity,
            amount_unit_id=line.iiko_amount_unit_id,
            price=line.historical_unit_price,
            sum_amount=line.allocated_sum,
        ) for line in receipt.lines),
    )


def _read(
    session: Session,
    receipt: SupplyIikoIncomingReceipt,
) -> SupplyIikoIncomingReceiptRead:
    supplier_mapping = session.scalar(select(IikoSupplierMapping).where(
        IikoSupplierMapping.id == receipt.iiko_supplier_mapping_id,
        IikoSupplierMapping.tenant_id == receipt.tenant_id,
    ))
    destination = session.scalar(select(IikoWarehouseMapping).where(
        IikoWarehouseMapping.id == receipt.destination_mapping_id,
        IikoWarehouseMapping.tenant_id == receipt.tenant_id,
    ))
    acceptance_lines = {
        line.id: line for line in session.scalars(
            select(SupplySupplierAcceptanceLine).where(
                SupplySupplierAcceptanceLine.tenant_id == receipt.tenant_id,
                SupplySupplierAcceptanceLine.id.in_(
                    [line.acceptance_line_id for line in receipt.lines] or [uuid4()]
                ),
            )
        ).all()
    }
    preview = _build_preview(session, receipt) if receipt.lines else None
    return SupplyIikoIncomingReceiptRead(
        id=receipt.id,
        supplier_acceptance_id=receipt.supplier_acceptance_id,
        supplier_id=receipt.supplier_id,
        supplier_name=(
            receipt.acceptance.supplier_order.supplier.display_name
            if receipt.acceptance and receipt.acceptance.supplier_order.supplier
            else supplier_mapping.iiko_supplier_name
        ),
        destination_mapping_id=receipt.destination_mapping_id,
        destination_name=destination.source_name if destination else "",
        iiko_supplier_mapping_id=receipt.iiko_supplier_mapping_id,
        iiko_supplier_id=supplier_mapping.iiko_supplier_id,
        status=receipt.status,
        readiness_status=("READY" if receipt.lines else "BLOCKED"),
        readiness_reasons=[],
        eos_document_number=receipt.eos_document_number,
        date_incoming=receipt.date_incoming,
        incoming_date=receipt.incoming_date,
        iiko_document_id=receipt.iiko_document_id,
        iiko_document_number=receipt.iiko_document_number,
        iiko_status=receipt.iiko_status,
        payload_hash=receipt.payload_hash,
        payload_xml=(preview.to_iiko_xml().decode("utf-8") if preview else None),
        create_attempt_count=receipt.create_attempt_count,
        process_attempt_count=receipt.process_attempt_count,
        last_error_code=receipt.last_error_code,
        last_error_message=receipt.last_error_message,
        create_started_at=receipt.create_started_at,
        created_in_iiko_at=receipt.created_in_iiko_at,
        process_started_at=receipt.process_started_at,
        posted_at=receipt.posted_at,
        total_sum=sum((Decimal(line.allocated_sum) for line in receipt.lines), Decimal("0")),
        created_by_user_id=receipt.created_by_user_id,
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
        lines=[SupplyIikoIncomingReceiptLineRead(
            id=line.id,
            acceptance_line_id=line.acceptance_line_id,
            supplier_document_line_id=line.supplier_document_line_id,
            product_id=line.product_id,
            product_name=acceptance_lines[line.acceptance_line_id].product_name_snapshot,
            unit_id=line.unit_id,
            unit_name=acceptance_lines[line.acceptance_line_id].unit_name_snapshot or "",
            iiko_product_id=line.iiko_product_id,
            iiko_amount_unit_id=line.iiko_amount_unit_id,
            iiko_store_id=line.iiko_store_id,
            quantity=line.quantity,
            historical_unit_price=line.historical_unit_price,
            allocated_sum=line.allocated_sum,
            line_no=line.line_no,
            accounted_quantity=line.accounted_quantity,
            accounted_sum=line.accounted_sum,
        ) for line in receipt.lines],
    )


def read_receipt(session: Session, receipt_id: UUID, *, tenant_id: str):
    return _read(session, _get_receipt(session, receipt_id, tenant_id=tenant_id))


def read_acceptance_receipt(
    session: Session,
    acceptance_id: UUID,
    *,
    tenant_id: str,
):
    receipt = session.scalar(
        select(SupplyIikoIncomingReceipt)
        .where(
            SupplyIikoIncomingReceipt.tenant_id == tenant_id,
            SupplyIikoIncomingReceipt.supplier_acceptance_id == acceptance_id,
            SupplyIikoIncomingReceipt.status != "CANCELLED",
        )
        .options(*_receipt_options())
    )
    if receipt is None:
        raise IncomingReceiptNotFoundError
    return _read(session, receipt)


def prepare_receipt(
    session: Session,
    acceptance_id: UUID,
    *,
    tenant_id: str,
    user_id: int,
):
    acceptance = _get_acceptance(
        session, acceptance_id, tenant_id=tenant_id, lock=True
    )
    existing = session.scalar(select(SupplyIikoIncomingReceipt).where(
        SupplyIikoIncomingReceipt.tenant_id == tenant_id,
        SupplyIikoIncomingReceipt.supplier_acceptance_id == acceptance_id,
        SupplyIikoIncomingReceipt.status != "CANCELLED",
    ).options(*_receipt_options()).with_for_update(of=SupplyIikoIncomingReceipt))
    if existing is not None:
        return _read(session, existing)
    readiness, supplier_mapping, destination = _readiness(
        session, acceptance, lock_allocation=False
    )
    if not readiness.receipt_preview_ready or supplier_mapping is None or destination is None:
        raise IncomingReceiptReadinessError(
            [reason.value for reason in readiness.reason_codes]
        )
    receipt_id = uuid4()
    occurred_at = acceptance.received_at or acceptance.accepted_at or acceptance.recorded_at or datetime.now(timezone.utc)
    receipt = SupplyIikoIncomingReceipt(
        id=receipt_id,
        tenant_id=tenant_id,
        supplier_acceptance_id=acceptance.id,
        supplier_id=acceptance.supplier_order.supplier_id,
        destination_mapping_id=destination.id,
        iiko_supplier_mapping_id=supplier_mapping.id,
        status="DRAFT",
        eos_document_number=(
            f"EOS-IN-{occurred_at:%Y%m%d}-{acceptance.id.hex[:12].upper()}"
        ),
        date_incoming=occurred_at,
        incoming_date=occurred_at.date(),
        created_by_user_id=user_id,
    )
    _replace_lines(session, receipt, acceptance, readiness)
    session.add(receipt)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(SupplyIikoIncomingReceipt).where(
            SupplyIikoIncomingReceipt.tenant_id == tenant_id,
            SupplyIikoIncomingReceipt.supplier_acceptance_id == acceptance_id,
            SupplyIikoIncomingReceipt.status != "CANCELLED",
        ).options(*_receipt_options()))
        if existing is None:
            raise IncomingReceiptConflictError("RECEIPT_CREATE_CONFLICT")
        return _read(session, existing)
    return read_receipt(session, receipt.id, tenant_id=tenant_id)


def mark_receipt_ready(session: Session, receipt_id: UUID, *, tenant_id: str):
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    if receipt.status != "DRAFT":
        raise IncomingReceiptStateError("RECEIPT_NOT_DRAFT")
    acceptance = _get_acceptance(
        session, receipt.supplier_acceptance_id, tenant_id=tenant_id, lock=True
    )
    readiness, supplier_mapping, destination = _readiness(
        session, acceptance, lock_allocation=True, exclude_receipt_id=receipt.id
    )
    if not readiness.receipt_preview_ready or supplier_mapping is None or destination is None:
        raise IncomingReceiptReadinessError(
            [reason.value for reason in readiness.reason_codes]
        )
    if supplier_mapping.id != receipt.iiko_supplier_mapping_id or destination.id != receipt.destination_mapping_id:
        raise IncomingReceiptConflictError("RECEIPT_MAPPING_CHANGED")
    _replace_lines(session, receipt, acceptance, readiness)
    session.flush()
    preview = _build_preview(session, receipt)
    receipt.payload_hash = hashlib.sha256(preview.to_iiko_xml()).hexdigest()
    receipt.status = "READY"
    receipt.last_error_code = None
    receipt.last_error_message = None
    session.commit()
    return read_receipt(session, receipt.id, tenant_id=tenant_id)


def _line_key(item) -> tuple:
    return (
        str(item.product_id), str(item.store_id), Decimal(item.amount),
        str(item.amount_unit), Decimal(item.price), Decimal(item.sum_amount),
    )


def _expected_line_key(item: IikoIncomingInvoicePreviewItemDto) -> tuple:
    return (
        str(item.product_id), str(item.store_id), Decimal(item.amount),
        str(item.amount_unit_id), Decimal(item.price), Decimal(item.sum_amount),
    )


def _matches(invoice: IikoIncomingInvoiceDto, preview: IikoIncomingInvoicePreviewDto) -> bool:
    return (
        invoice.document_number == preview.document_number
        and invoice.supplier_id == preview.supplier_id
        and invoice.default_store_id == preview.default_store_id
        and sorted(_line_key(item) for item in invoice.items)
        == sorted(_expected_line_key(item) for item in preview.items)
    )


async def _reconcile(
    provider: IikoProvider,
    preview: IikoIncomingInvoicePreviewDto,
) -> tuple[str, IikoIncomingInvoiceDto | None]:
    invoices = await provider.get_incoming_invoices(
        date_from=preview.incoming_date,
        date_to=preview.incoming_date,
    )
    same_number = [
        invoice for invoice in invoices
        if invoice.document_number == preview.document_number
    ]
    matches = [invoice for invoice in same_number if _matches(invoice, preview)]
    if len(matches) == 1:
        return "MATCH", matches[0]
    if len(matches) > 1:
        return "READBACK_AMBIGUOUS", None
    if same_number:
        return "READBACK_MISMATCH", None
    return "READBACK_NOT_FOUND", None


def _capture_identity(
    session: Session,
    receipt_id: UUID,
    invoice: IikoIncomingInvoiceDto,
) -> SupplyIikoIncomingReceipt:
    receipt = session.scalar(
        select(SupplyIikoIncomingReceipt)
        .where(SupplyIikoIncomingReceipt.id == receipt_id)
        .with_for_update()
    )
    if receipt.iiko_document_id not in {None, invoice.external_id}:
        raise IncomingReceiptConflictError("IIKO_DOCUMENT_ID_IMMUTABLE")
    receipt.iiko_document_id = invoice.external_id
    receipt.iiko_document_number = invoice.document_number
    receipt.iiko_status = invoice.status.value
    receipt.created_in_iiko_at = receipt.created_in_iiko_at or datetime.now(timezone.utc)
    receipt.status = "POSTED" if invoice.status.value == "PROCESSED" else "CREATED"
    receipt.last_error_code = None
    receipt.last_error_message = None
    return receipt


async def create_receipt(
    session: Session,
    provider: IikoProvider,
    receipt_id: UUID,
    *,
    tenant_id: str,
):
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    if receipt.status != "READY":
        raise IncomingReceiptStateError("RECEIPT_NOT_READY")
    preview = _build_preview(session, receipt)
    if hashlib.sha256(preview.to_iiko_xml()).hexdigest() != receipt.payload_hash:
        raise IncomingReceiptConflictError("RECEIPT_PAYLOAD_CHANGED")
    receipt.status = "CREATING"
    receipt.create_attempt_count += 1
    receipt.create_started_at = datetime.now(timezone.utc)
    receipt.last_error_code = None
    receipt.last_error_message = None
    session.commit()

    validation = None
    network_error: Exception | None = None
    try:
        validation = await provider.create_incoming_invoice(preview)
    except Exception as error:
        network_error = error

    try:
        outcome, invoice = await _reconcile(provider, preview)
    except Exception:
        outcome, invoice = "READBACK_NOT_FOUND", None
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    if invoice is not None:
        _capture_identity(session, receipt_id, invoice)
        session.commit()
        if invoice.status.value == "PROCESSED":
            return await _finalize_posted(
                session, provider, receipt_id, tenant_id=tenant_id, invoice=invoice
            )
        return read_receipt(session, receipt_id, tenant_id=tenant_id)
    if validation is not None and not validation.valid:
        receipt.status = "FAILED"
        receipt.last_error_code = "WRITE_REJECTED"
        receipt.last_error_message = validation.error_message or "iiko отклонил приходную накладную"
    elif outcome in {"READBACK_AMBIGUOUS", "READBACK_MISMATCH"}:
        receipt.status = "FAILED"
        receipt.last_error_code = outcome
        receipt.last_error_message = "Авторитетная сверка iiko неоднозначна"
    else:
        receipt.status = "CREATING"
        receipt.last_error_code = "WRITE_RESULT_UNKNOWN"
        receipt.last_error_message = (
            safe_error_message(network_error) if network_error else "Документ пока не найден в iiko"
        )
    session.commit()
    return read_receipt(session, receipt_id, tenant_id=tenant_id)


def _verify_final(
    invoice: IikoIncomingInvoiceDto | None,
    preview: IikoIncomingInvoicePreviewDto,
    document_id: UUID,
) -> bool:
    return bool(
        invoice is not None
        and invoice.external_id == document_id
        and invoice.status.value == "PROCESSED"
        and _matches(invoice, preview)
    )


async def _stock_refresh(provider: IikoProvider, receipt: SupplyIikoIncomingReceipt) -> None:
    await provider.get_stock_balances(
        snapshot_at=datetime.now(timezone.utc),
        warehouse_external_ids=[str(receipt.lines[0].iiko_store_id)],
        product_external_ids=[str(line.iiko_product_id) for line in receipt.lines],
        include_zero=True,
        include_deleted=False,
    )


async def _finalize_posted(
    session: Session,
    provider: IikoProvider,
    receipt_id: UUID,
    *,
    tenant_id: str,
    invoice: IikoIncomingInvoiceDto,
):
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    receipt.iiko_document_id = invoice.external_id
    receipt.iiko_document_number = invoice.document_number
    receipt.iiko_status = invoice.status.value
    receipt.status = "POSTED"
    receipt.posted_at = receipt.posted_at or datetime.now(timezone.utc)
    receipt.last_error_code = None
    receipt.last_error_message = None
    for line in receipt.lines:
        line.accounted_quantity = line.quantity
        line.accounted_sum = line.allocated_sum
    session.commit()
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id)
    try:
        await _stock_refresh(provider, receipt)
    except Exception:
        receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
        receipt.last_error_code = "STOCK_REFRESH_FAILED"
        receipt.last_error_message = "Приход проведён, но свежие остатки iiko не получены"
        session.commit()
    return read_receipt(session, receipt_id, tenant_id=tenant_id)


async def process_receipt(
    session: Session,
    provider: IikoProvider,
    receipt_id: UUID,
    *,
    tenant_id: str,
):
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    if receipt.status != "CREATED" or receipt.iiko_document_id is None:
        raise IncomingReceiptStateError("RECEIPT_NOT_CREATED")
    preview = _build_preview(session, receipt)
    document_id = receipt.iiko_document_id
    receipt.status = "PROCESSING"
    receipt.process_attempt_count += 1
    receipt.process_started_at = datetime.now(timezone.utc)
    receipt.last_error_code = None
    receipt.last_error_message = None
    session.commit()

    validation = None
    process_error: Exception | None = None
    try:
        validation = await provider.process_incoming_invoice(document_id)
    except Exception as error:
        process_error = error
    try:
        invoice = await provider.get_incoming_invoice_by_id(
            document_id,
            date_from=preview.incoming_date,
            date_to=preview.incoming_date,
        )
    except Exception:
        invoice = None
    if _verify_final(invoice, preview, document_id):
        return await _finalize_posted(
            session, provider, receipt_id, tenant_id=tenant_id, invoice=invoice
        )
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    if invoice is not None and not _matches(invoice, preview):
        receipt.status = "FAILED"
        receipt.last_error_code = "FINAL_VERIFY_FAILED"
        receipt.last_error_message = "Проведённый документ iiko не совпал со snapshot"
    elif validation is not None and not validation.valid:
        receipt.status = "FAILED"
        receipt.last_error_code = "PROCESS_FAILED"
        receipt.last_error_message = validation.error_message or "iiko не провёл документ"
    else:
        receipt.status = "PROCESSING"
        receipt.last_error_code = "PROCESS_RESULT_UNKNOWN"
        receipt.last_error_message = (
            safe_error_message(process_error) if process_error else "Статус PROCESSED не подтверждён"
        )
    session.commit()
    return read_receipt(session, receipt_id, tenant_id=tenant_id)


async def retry_receipt(
    session: Session,
    provider: IikoProvider,
    receipt_id: UUID,
    *,
    tenant_id: str,
):
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    preview = _build_preview(session, receipt)
    if receipt.status in {"POSTED", "CANCELLED"}:
        return _read(session, receipt)
    if receipt.iiko_document_id is not None:
        document_id = receipt.iiko_document_id
        session.commit()
        try:
            invoice = await provider.get_incoming_invoice_by_id(
                document_id,
                date_from=preview.incoming_date,
                date_to=preview.incoming_date,
            )
        except Exception as error:
            receipt = _get_receipt(
                session, receipt_id, tenant_id=tenant_id, lock=True
            )
            receipt.last_error_code = "PROCESS_RESULT_UNKNOWN"
            receipt.last_error_message = safe_error_message(error)
            session.commit()
            return read_receipt(session, receipt_id, tenant_id=tenant_id)
        if _verify_final(invoice, preview, document_id):
            return await _finalize_posted(
                session, provider, receipt_id, tenant_id=tenant_id, invoice=invoice
            )
        if invoice is not None and invoice.status.value == "NEW" and _matches(invoice, preview):
            receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
            receipt.status = "CREATED"
            receipt.iiko_status = "NEW"
            receipt.last_error_code = None
            receipt.last_error_message = None
            session.commit()
            return read_receipt(session, receipt_id, tenant_id=tenant_id)
        receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
        receipt.status = "FAILED"
        receipt.last_error_code = "FINAL_VERIFY_FAILED"
        receipt.last_error_message = "Документ iiko не прошёл recovery-сверку"
        session.commit()
        return read_receipt(session, receipt_id, tenant_id=tenant_id)

    session.commit()
    try:
        outcome, invoice = await _reconcile(provider, preview)
    except Exception as error:
        receipt = _get_receipt(
            session, receipt_id, tenant_id=tenant_id, lock=True
        )
        receipt.last_error_code = "WRITE_RESULT_UNKNOWN"
        receipt.last_error_message = safe_error_message(error)
        session.commit()
        return read_receipt(session, receipt_id, tenant_id=tenant_id)
    if invoice is not None:
        receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
        _capture_identity(session, receipt.id, invoice)
        session.commit()
        if invoice.status.value == "PROCESSED":
            return await _finalize_posted(
                session, provider, receipt_id, tenant_id=tenant_id, invoice=invoice
            )
        return read_receipt(session, receipt_id, tenant_id=tenant_id)
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    previous_code = receipt.last_error_code
    if outcome in {"READBACK_AMBIGUOUS", "READBACK_MISMATCH"}:
        receipt.status = "FAILED"
        receipt.last_error_code = outcome
        receipt.last_error_message = "Recovery-сверка iiko неоднозначна"
        session.commit()
        return read_receipt(session, receipt_id, tenant_id=tenant_id)
    if previous_code not in {"READBACK_NOT_FOUND", "WRITE_REJECTED"}:
        receipt.status = "FAILED"
        receipt.last_error_code = "READBACK_NOT_FOUND"
        receipt.last_error_message = "Документ не найден; повторная отправка требует ещё одного явного действия"
        session.commit()
        return read_receipt(session, receipt_id, tenant_id=tenant_id)
    receipt.status = "READY"
    receipt.last_error_code = None
    receipt.last_error_message = None
    session.commit()
    return await create_receipt(session, provider, receipt_id, tenant_id=tenant_id)


def cancel_receipt(session: Session, receipt_id: UUID, *, tenant_id: str):
    receipt = _get_receipt(session, receipt_id, tenant_id=tenant_id, lock=True)
    if (
        receipt.status not in {"DRAFT", "READY"}
        or receipt.iiko_document_id is not None
        or receipt.create_attempt_count != 0
    ):
        raise IncomingReceiptStateError("RECEIPT_CANCEL_UNSAFE")
    receipt.status = "CANCELLED"
    receipt.last_error_code = None
    receipt.last_error_message = None
    session.commit()
    return read_receipt(session, receipt_id, tenant_id=tenant_id)
