from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.integrations.iiko.document_routing import (
    OUTGOING_INVOICE_ACCOUNT_TO_CODE,
    OUTGOING_INVOICE_REVENUE_ACCOUNT_CODE,
    IikoOutgoingInvoiceRoute,
    resolve_outgoing_invoice_route,
)
from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import (
    IikoOutgoingInvoiceCreateDto,
    IikoOutgoingInvoiceCreateResultDto,
    IikoOutgoingInvoiceItemCreateDto,
)
from app.models.iiko import IikoMappingStatus
from app.models.supply import SupplyProductSourceRole


class IikoOutgoingInvoiceValidationError(IikoContractError):
    pass


@dataclass(frozen=True, slots=True)
class IikoOutgoingInvoiceLineInput:
    iiko_product_id: UUID | None
    product_mapping_status: IikoMappingStatus | str | None
    iiko_unit_id: UUID | None
    quantity: Decimal


def _validated_route(route: IikoOutgoingInvoiceRoute) -> None:
    required_uuid_fields = {
        "source_store_id": route.source_store_id,
        "counteragent_id": route.counteragent_id,
    }
    for field, value in required_uuid_fields.items():
        if not isinstance(value, UUID):
            raise IikoOutgoingInvoiceValidationError(
                f"IIKO_OUTGOING_INVOICE_ROUTE_INVALID field={field}"
            )
    required_codes = {
        "account_to_code": (
            route.account_to_code,
            OUTGOING_INVOICE_ACCOUNT_TO_CODE,
        ),
        "revenue_account_code": (
            route.revenue_account_code,
            OUTGOING_INVOICE_REVENUE_ACCOUNT_CODE,
        ),
    }
    for field, (value, expected) in required_codes.items():
        if value != expected:
            raise IikoOutgoingInvoiceValidationError(
                f"IIKO_OUTGOING_INVOICE_ROUTE_INVALID field={field}"
            )


def _validated_items(
    lines: Sequence[IikoOutgoingInvoiceLineInput],
) -> tuple[IikoOutgoingInvoiceItemCreateDto, ...]:
    if not lines:
        raise IikoOutgoingInvoiceValidationError(
            "IIKO_OUTGOING_INVOICE_EMPTY"
        )
    items: list[IikoOutgoingInvoiceItemCreateDto] = []
    for index, line in enumerate(lines):
        try:
            mapping_status = IikoMappingStatus(line.product_mapping_status)
        except (TypeError, ValueError):
            mapping_status = None
        if (
            not isinstance(line.iiko_product_id, UUID)
            or mapping_status != IikoMappingStatus.CONFIRMED
        ):
            raise IikoOutgoingInvoiceValidationError(
                f"IIKO_PRODUCT_MAPPING_REQUIRED line={index}"
            )
        if not isinstance(line.iiko_unit_id, UUID):
            raise IikoOutgoingInvoiceValidationError(
                f"IIKO_UNIT_REQUIRED line={index}"
            )
        if (
            not isinstance(line.quantity, Decimal)
            or not line.quantity.is_finite()
            or line.quantity <= 0
        ):
            raise IikoOutgoingInvoiceValidationError(
                f"IIKO_QUANTITY_INVALID line={index}"
            )
        items.append(IikoOutgoingInvoiceItemCreateDto(
            product_id=line.iiko_product_id,
            amount=line.quantity,
        ))
    return tuple(items)


def build_controlled_outgoing_invoice(
    *,
    document_id: UUID,
    date_incoming: datetime,
    department_code: str,
    flow: SupplyProductSourceRole | str,
    lines: Sequence[IikoOutgoingInvoiceLineInput],
) -> IikoOutgoingInvoiceCreateDto:
    if not isinstance(document_id, UUID):
        raise IikoOutgoingInvoiceValidationError(
            "IIKO_DOCUMENT_ID_REQUIRED"
        )
    if not isinstance(date_incoming, datetime):
        raise IikoOutgoingInvoiceValidationError(
            "IIKO_DOCUMENT_DATE_REQUIRED"
        )
    if date_incoming.tzinfo is None or date_incoming.utcoffset() is None:
        raise IikoOutgoingInvoiceValidationError(
            "IIKO_DOCUMENT_TIMEZONE_REQUIRED"
        )
    route = resolve_outgoing_invoice_route(department_code, flow)
    _validated_route(route)
    return IikoOutgoingInvoiceCreateDto(
        document_id=document_id,
        date_incoming=date_incoming,
        default_store_id=route.source_store_id,
        counteragent_id=route.counteragent_id,
        account_to_code=route.account_to_code,
        revenue_account_code=route.revenue_account_code,
        items=_validated_items(lines),
    )


async def create_controlled_outgoing_invoice(
    provider: IikoProvider,
    *,
    document_id: UUID,
    date_incoming: datetime,
    department_code: str,
    flow: SupplyProductSourceRole | str,
    lines: Sequence[IikoOutgoingInvoiceLineInput],
) -> IikoOutgoingInvoiceCreateResultDto:
    document = build_controlled_outgoing_invoice(
        document_id=document_id,
        date_incoming=date_incoming,
        department_code=department_code,
        flow=flow,
        lines=lines,
    )
    return await provider.create_outgoing_invoice(document)
