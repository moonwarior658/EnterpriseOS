import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal
from html import escape
from io import BytesIO
from pathlib import Path
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.integrations.iiko.document_intent import (
    IikoDocumentAuthoritativeReadBackError,
    IikoDocumentIntentStateError,
    read_verified_outgoing_invoice,
)
from app.integrations.iiko.provider import IikoProvider
from app.models.iiko import (
    IikoDocumentType,
    IikoDocumentWrite,
    IikoDocumentWriteStatus,
    IikoMappingStatus,
    IikoProductMapping,
    IikoUnitMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
)
from app.models.supply import SupplyProductSourceRole, SupplyRequest
from app.supply.service import SupplyRequestNotFoundError


class SupplyIikoDocumentPrintError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SupplyIikoPrintableLine:
    position_number: int
    iiko_product_id: UUID
    product_article: str | None
    product_name: str
    quantity: Decimal
    unit_name: str


@dataclass(frozen=True, slots=True)
class SupplyIikoPrintableDocument:
    document_number: str
    document_date: date
    document_status: str
    source_store_id: UUID
    source_store_name: str
    destination_department_name: str
    counteragent_representation: str
    lines: tuple[SupplyIikoPrintableLine, ...]
    iiko_document_id: UUID
    supply_request_id: UUID
    flow: SupplyProductSourceRole
    version_fingerprint: str


@dataclass(frozen=True, slots=True)
class SupplyIikoPdfResult:
    content: bytes
    version_fingerprint: str


_FLOW_ORDER = {
    SupplyProductSourceRole.MAIN: 0,
    SupplyProductSourceRole.PACKAGING: 1,
    SupplyProductSourceRole.HOUSEHOLD: 2,
}


def _fingerprint(document: SupplyIikoPrintableDocument) -> str:
    normalized = asdict(document)
    normalized.pop("version_fingerprint")
    normalized.pop("document_status")
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _get_request_and_writes(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
    document_write_id: UUID | None,
) -> tuple[SupplyRequest, list[IikoDocumentWrite]]:
    request = session.scalar(
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == tenant_id,
        )
        .options(joinedload(SupplyRequest.department))
    )
    if request is None:
        raise SupplyRequestNotFoundError
    query = select(IikoDocumentWrite).where(
        IikoDocumentWrite.supply_request_id == request_id,
        IikoDocumentWrite.document_type == IikoDocumentType.OUTGOING_INVOICE,
    )
    if document_write_id is not None:
        query = query.where(IikoDocumentWrite.id == document_write_id)
    writes = list(session.scalars(query).all())
    if document_write_id is not None and not writes:
        raise SupplyRequestNotFoundError
    printable = [
        write for write in writes
        if write.status == IikoDocumentWriteStatus.CREATED
        and write.iiko_document_id is not None
    ]
    if document_write_id is not None and not printable:
        raise SupplyIikoDocumentPrintError(
            "SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED"
        )
    if not printable:
        raise SupplyIikoDocumentPrintError(
            "SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED"
        )
    return request, printable


def _resolve_source_name(
    session: Session,
    *,
    tenant_id: str,
    source_store_id: UUID,
) -> str:
    mappings = list(session.scalars(select(IikoWarehouseMapping).where(
        IikoWarehouseMapping.tenant_id == tenant_id,
        IikoWarehouseMapping.iiko_warehouse_id == source_store_id,
        IikoWarehouseMapping.destination_type
        == IikoWarehouseDestinationType.SOURCE,
        IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
        IikoWarehouseMapping.is_deleted.is_(False),
    )).all())
    if len(mappings) != 1 or not mappings[0].source_name.strip():
        raise SupplyIikoDocumentPrintError(
            "SUPPLY_IIKO_DOCUMENT_PRINT_DATA_INCOMPLETE"
        )
    return mappings[0].source_name.strip()


def _resolve_lines(
    session: Session,
    *,
    tenant_id: str,
    items,
) -> tuple[SupplyIikoPrintableLine, ...]:
    lines: list[SupplyIikoPrintableLine] = []
    for position, item in enumerate(items, start=1):
        product_mappings = list(session.scalars(
            select(IikoProductMapping)
            .where(
                IikoProductMapping.tenant_id == tenant_id,
                IikoProductMapping.iiko_product_id == item.product_id,
                IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
                IikoProductMapping.is_deleted.is_(False),
            )
        ).all())
        if (
            len(product_mappings) != 1
            or not product_mappings[0].source_name.strip()
        ):
            raise SupplyIikoDocumentPrintError(
                "SUPPLY_IIKO_DOCUMENT_PRODUCT_UNRESOLVED"
            )
        product_mapping = product_mappings[0]
        if product_mapping.source_unit_id is None:
            raise SupplyIikoDocumentPrintError(
                "SUPPLY_IIKO_DOCUMENT_UNIT_UNRESOLVED"
            )
        unit_mappings = list(session.scalars(
            select(IikoUnitMapping)
            .where(
                IikoUnitMapping.tenant_id == tenant_id,
                IikoUnitMapping.iiko_unit_id
                == product_mapping.source_unit_id,
                IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
                IikoUnitMapping.is_deleted.is_(False),
            )
            .options(joinedload(IikoUnitMapping.eos_unit))
        ).all())
        if (
            len(unit_mappings) != 1
            or unit_mappings[0].eos_unit is None
            or not unit_mappings[0].eos_unit.short_name_ru.strip()
        ):
            raise SupplyIikoDocumentPrintError(
                "SUPPLY_IIKO_DOCUMENT_UNIT_UNRESOLVED"
            )
        article = product_mapping.source_sku or product_mapping.source_code
        lines.append(SupplyIikoPrintableLine(
            position_number=position,
            iiko_product_id=item.product_id,
            product_article=article.strip() if article else None,
            product_name=product_mapping.source_name.strip(),
            quantity=item.amount,
            unit_name=unit_mappings[0].eos_unit.short_name_ru.strip(),
        ))
    if not lines:
        raise SupplyIikoDocumentPrintError(
            "SUPPLY_IIKO_DOCUMENT_PRINT_DATA_INCOMPLETE"
        )
    return tuple(lines)


async def build_printable_iiko_documents(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    request_id: UUID,
    document_write_id: UUID | None = None,
) -> tuple[SupplyIikoPrintableDocument, ...]:
    request, writes = _get_request_and_writes(
        session,
        tenant_id=tenant_id,
        request_id=request_id,
        document_write_id=document_write_id,
    )
    department_name = request.department.name.strip()
    if not department_name:
        raise SupplyIikoDocumentPrintError(
            "SUPPLY_IIKO_DOCUMENT_PRINT_DATA_INCOMPLETE"
        )
    documents: list[SupplyIikoPrintableDocument] = []
    for write in writes:
        try:
            invoice = await read_verified_outgoing_invoice(
                provider,
                intent=write,
            )
        except IikoDocumentAuthoritativeReadBackError as error:
            raise SupplyIikoDocumentPrintError(str(error)) from error
        except IikoDocumentIntentStateError as error:
            raise SupplyIikoDocumentPrintError(
                "SUPPLY_IIKO_DOCUMENT_PRINT_DATA_INCOMPLETE"
            ) from error
        if (
            invoice.date_incoming is None
            or write.iiko_document_id is None
            or not invoice.document_number.strip()
        ):
            raise SupplyIikoDocumentPrintError(
                "SUPPLY_IIKO_DOCUMENT_PRINT_DATA_INCOMPLETE"
            )
        source_name = _resolve_source_name(
            session,
            tenant_id=tenant_id,
            source_store_id=write.source_store_id,
        )
        lines = _resolve_lines(
            session,
            tenant_id=tenant_id,
            items=invoice.items,
        )
        from app.integrations.iiko.document_routing import (
            outgoing_invoice_flow_for_source_store,
        )
        document = SupplyIikoPrintableDocument(
            document_number=invoice.document_number.strip(),
            document_date=invoice.date_incoming.date(),
            document_status=invoice.status,
            source_store_id=write.source_store_id,
            source_store_name=source_name,
            destination_department_name=department_name,
            counteragent_representation=department_name,
            lines=lines,
            iiko_document_id=write.iiko_document_id,
            supply_request_id=request_id,
            flow=outgoing_invoice_flow_for_source_store(write.source_store_id),
            version_fingerprint="",
        )
        documents.append(replace(
            document,
            version_fingerprint=_fingerprint(document),
        ))
    return tuple(sorted(documents, key=lambda item: _FLOW_ORDER[item.flow]))


def _register_fonts() -> tuple[str, str]:
    font_pairs = (
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ),
    )
    font_pair = next(
        (
            pair for pair in font_pairs
            if pair[0].is_file() and pair[1].is_file()
        ),
        None,
    )
    if font_pair is None:
        raise SupplyIikoDocumentPrintError(
            "SUPPLY_IIKO_DOCUMENT_PRINT_DATA_INCOMPLETE"
        )
    regular_name = "EOSPrintRegular"
    bold_name = "EOSPrintBold"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular_name, font_pair[0]))
    if bold_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(bold_name, font_pair[1]))
    return regular_name, bold_name


def _format_quantity(value: Decimal) -> str:
    return f"{value:.3f}".replace(".", ",")


def _print_product_name(value: str) -> str:
    return value[2:] if value.startswith("т ") else value


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def render_iiko_documents_pdf(
    documents: tuple[SupplyIikoPrintableDocument, ...],
) -> SupplyIikoPdfResult:
    regular, bold = _register_fonts()
    buffer = BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="Расходная накладная",
        author="EnterpriseOS",
    )
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "EOSNormal", parent=styles["Normal"], fontName=regular,
        fontSize=9, leading=11,
    )
    bold_style = ParagraphStyle(
        "EOSBold", parent=normal, fontName=bold,
    )
    title = ParagraphStyle(
        "EOSTitle", parent=bold_style, fontSize=14, leading=17,
        alignment=TA_CENTER,
    )
    compact = ParagraphStyle(
        "EOSCompact", parent=normal, fontSize=8, leading=10,
    )
    story = []
    for document_index, document in enumerate(documents):
        if document_index:
            story.append(PageBreak())
        document_identity = Table(
            [[Paragraph(
                f"EnterpriseOS iiko {_text(document.document_number)}",
                compact,
            )]],
            colWidths=[174 * mm],
        )
        document_identity.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        document_metadata = Table(
            [
                [
                    Paragraph("Номер документа", compact),
                    Paragraph("Дата документа", compact),
                ],
                [
                    Paragraph(_text(document.document_number), normal),
                    Paragraph(document.document_date.strftime("%d.%m.%Y"), normal),
                ],
            ],
            colWidths=[35 * mm, 35 * mm],
            rowHeights=[6 * mm, 7 * mm],
        )
        document_metadata.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        title_block = Table(
            [[
                Paragraph("РАСХОДНАЯ НАКЛАДНАЯ", title),
                document_metadata,
            ]],
            colWidths=[104 * mm, 70 * mm],
        )
        title_block.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.extend([
            document_identity,
            Spacer(1, 5 * mm),
            title_block,
            Spacer(1, 6 * mm),
            Paragraph(
                f"<b>Поставщик:</b> {_text(document.source_store_name)}",
                normal,
            ),
            Spacer(1, 1.5 * mm),
            Paragraph(
                f"<b>Получатель:</b> "
                f"{_text(document.destination_department_name)}",
                normal,
            ),
            Spacer(1, 1.5 * mm),
            Paragraph(
                f"<b>Склад:</b> {_text(document.source_store_name)}", normal
            ),
            Spacer(1, 1.5 * mm),
            Paragraph("<b>Примечание:</b>", normal),
            Spacer(1, 5 * mm),
        ])
        rows = [[
            Paragraph("№", bold_style),
            Paragraph("Код", bold_style),
            Paragraph("Продукт", bold_style),
            Paragraph("Ед. изм.", bold_style),
            Paragraph("Количество", bold_style),
        ]]
        rows.extend([
            [
                str(line.position_number),
                Paragraph(_text(line.product_article or "—"), normal),
                Paragraph(
                    _text(_print_product_name(line.product_name)), normal
                ),
                Paragraph(_text(line.unit_name), normal),
                _format_quantity(line.quantity),
            ]
            for line in document.lines
        ])
        table = Table(
            rows,
            colWidths=[9 * mm, 27 * mm, 82 * mm, 23 * mm, 33 * mm],
            repeatRows=1,
        )
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), regular),
            ("FONTNAME", (0, 0), (-1, 0), bold),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEADING", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("ALIGN", (0, 1), (1, -1), "CENTER"),
            ("ALIGN", (3, 1), (3, -1), "CENTER"),
            ("ALIGN", (4, 1), (4, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        signature_table = Table(
            [[
                Paragraph("Отпустил __________________________", normal),
                Paragraph("Получил ___________________________", normal),
            ]],
            colWidths=[87 * mm, 87 * mm],
        )
        signature_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 5 * mm),
            ("LEFTPADDING", (1, 0), (1, 0), 5 * mm),
            ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.extend([
            table,
            Spacer(1, 10 * mm),
            KeepTogether([
                signature_table,
            ]),
        ])

    def deterministic_canvas(*args, **kwargs):
        kwargs["invariant"] = 1
        kwargs["pageCompression"] = 1
        return canvas.Canvas(*args, **kwargs)

    def paint_page_background(page_canvas, _document):
        page_canvas.saveState()
        page_canvas.setFillColor(colors.white)
        page_canvas.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        page_canvas.restoreState()

    pdf.build(
        story,
        canvasmaker=deterministic_canvas,
        onFirstPage=paint_page_background,
        onLaterPages=paint_page_background,
    )
    combined_fingerprint = (
        documents[0].version_fingerprint
        if len(documents) == 1
        else hashlib.sha256(json.dumps(
            [
                {
                    key: value
                    for key, value in asdict(item).items()
                    if key not in {"version_fingerprint", "document_status"}
                }
                for item in documents
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")).hexdigest()
    )
    return SupplyIikoPdfResult(
        content=buffer.getvalue(),
        version_fingerprint=combined_fingerprint,
    )


async def create_iiko_documents_pdf(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    request_id: UUID,
    document_write_id: UUID | None = None,
) -> SupplyIikoPdfResult:
    documents = await build_printable_iiko_documents(
        session,
        provider,
        tenant_id=tenant_id,
        request_id=request_id,
        document_write_id=document_write_id,
    )
    return render_iiko_documents_pdf(documents)
