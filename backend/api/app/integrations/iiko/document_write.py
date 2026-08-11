from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.integrations.iiko.document_routing import resolve_internal_transfer_route
from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import (
    IikoInternalTransferCreateDto,
    IikoInternalTransferItemCreateDto,
)
from app.models.supply import SupplyProductSourceRole


class IikoInternalTransferValidationError(IikoContractError):
    pass


@dataclass(frozen=True, slots=True)
class IikoInternalTransferLineInput:
    iiko_product_id: UUID | None
    iiko_unit_id: UUID | None
    quantity: Decimal


def _validated_items(
    lines: Sequence[IikoInternalTransferLineInput],
) -> tuple[IikoInternalTransferItemCreateDto, ...]:
    if not lines:
        raise IikoInternalTransferValidationError(
            "IIKO_INTERNAL_TRANSFER_EMPTY"
        )
    items: list[IikoInternalTransferItemCreateDto] = []
    for index, line in enumerate(lines):
        if not isinstance(line.iiko_product_id, UUID):
            raise IikoInternalTransferValidationError(
                f"IIKO_PRODUCT_MAPPING_REQUIRED line={index}"
            )
        if not isinstance(line.iiko_unit_id, UUID):
            raise IikoInternalTransferValidationError(
                f"IIKO_UNIT_REQUIRED line={index}"
            )
        if (
            not isinstance(line.quantity, Decimal)
            or not line.quantity.is_finite()
            or line.quantity <= 0
        ):
            raise IikoInternalTransferValidationError(
                f"IIKO_QUANTITY_INVALID line={index}"
            )
        items.append(IikoInternalTransferItemCreateDto(
            product_id=line.iiko_product_id,
            amount=line.quantity,
        ))
    return tuple(items)


async def create_controlled_internal_transfer(
    provider: IikoProvider,
    *,
    document_id: UUID,
    date_incoming: datetime,
    department_code: str,
    flow: SupplyProductSourceRole | str,
    lines: Sequence[IikoInternalTransferLineInput],
) -> UUID:
    if not isinstance(document_id, UUID):
        raise IikoInternalTransferValidationError(
            "IIKO_DOCUMENT_ID_REQUIRED"
        )
    if not isinstance(date_incoming, datetime):
        raise IikoInternalTransferValidationError(
            "IIKO_DOCUMENT_DATE_REQUIRED"
        )
    route = resolve_internal_transfer_route(department_code, flow)
    document = IikoInternalTransferCreateDto(
        document_id=document_id,
        date_incoming=date_incoming,
        store_from_id=route.from_store_id,
        store_to_id=route.to_store_id,
        items=_validated_items(lines),
    )
    return await provider.create_internal_transfer(document)
