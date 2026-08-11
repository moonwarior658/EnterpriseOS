from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from app.models.supply import SupplyProductSourceRole


OUTGOING_INVOICE_ACCOUNT_TO_CODE = "21"
OUTGOING_INVOICE_REVENUE_ACCOUNT_CODE = "20"


@dataclass(frozen=True, slots=True)
class IikoOutgoingInvoiceRoute:
    source_store_id: UUID
    destination_store_id: UUID
    counteragent_id: UUID
    account_to_code: str = OUTGOING_INVOICE_ACCOUNT_TO_CODE
    revenue_account_code: str = OUTGOING_INVOICE_REVENUE_ACCOUNT_CODE


@dataclass(frozen=True, slots=True)
class IikoInternalTransferRoute:
    from_store_id: UUID
    to_store_id: UUID


class IikoDocumentRouteNotConfiguredError(LookupError):
    def __init__(
        self,
        document_type: str,
        department_code: str,
        flow: object,
    ) -> None:
        super().__init__(
            f"{document_type} route is not configured for "
            f"department_code={department_code!r} flow={flow!r}"
        )


_MAIN_SOURCE_STORE_ID = UUID("24b90a5f-1a58-4f6b-9b55-368d7a92ec3e")
_PACKAGING_SOURCE_STORE_ID = UUID("bf44ec50-91d2-48b3-a927-2e3e2490f1d6")
_HOUSEHOLD_SOURCE_STORE_ID = UUID("9ea20084-9182-4633-8c52-a968a15e0b3b")

_OUTGOING_INVOICE_ROUTES = MappingProxyType({
    ("М15", SupplyProductSourceRole.MAIN): IikoOutgoingInvoiceRoute(
        source_store_id=_MAIN_SOURCE_STORE_ID,
        destination_store_id=UUID("d8ac1fa7-73d3-4164-9651-fa2c0b806d0f"),
        counteragent_id=UUID("47c6accc-4bc7-6be1-0194-ccf9367e20cd"),
    ),
    ("М15", SupplyProductSourceRole.PACKAGING): IikoOutgoingInvoiceRoute(
        source_store_id=_PACKAGING_SOURCE_STORE_ID,
        destination_store_id=UUID("d8ac1fa7-73d3-4164-9651-fa2c0b806d0f"),
        counteragent_id=UUID("47c6accc-4bc7-6be1-0194-ccf9367e20cd"),
    ),
    ("М15", SupplyProductSourceRole.HOUSEHOLD): IikoOutgoingInvoiceRoute(
        source_store_id=_HOUSEHOLD_SOURCE_STORE_ID,
        destination_store_id=UUID("c3f43576-66fd-421d-a2c2-6ed3bf208ea1"),
        counteragent_id=UUID("cbc5afd7-6e03-a56d-0197-0acc172e7633"),
    ),
    ("М35", SupplyProductSourceRole.MAIN): IikoOutgoingInvoiceRoute(
        source_store_id=_MAIN_SOURCE_STORE_ID,
        destination_store_id=UUID("a6f406c7-de56-4021-b94b-3e8610f13960"),
        counteragent_id=UUID("eac6f3d4-a2f2-0113-0195-53afd17de4dc"),
    ),
    ("М35", SupplyProductSourceRole.PACKAGING): IikoOutgoingInvoiceRoute(
        source_store_id=_PACKAGING_SOURCE_STORE_ID,
        destination_store_id=UUID("a6f406c7-de56-4021-b94b-3e8610f13960"),
        counteragent_id=UUID("eac6f3d4-a2f2-0113-0195-53afd17de4dc"),
    ),
    ("М35", SupplyProductSourceRole.HOUSEHOLD): IikoOutgoingInvoiceRoute(
        source_store_id=_HOUSEHOLD_SOURCE_STORE_ID,
        destination_store_id=UUID("d9144d36-f4cb-47d4-afff-f6b3ad8a4ca7"),
        counteragent_id=UUID("cbc5afd7-6e03-a56d-0197-0acc172e7647"),
    ),
    ("М6А", SupplyProductSourceRole.MAIN): IikoOutgoingInvoiceRoute(
        source_store_id=_MAIN_SOURCE_STORE_ID,
        destination_store_id=UUID("10f8add8-163d-47a7-b4ce-7b766fe9d6f0"),
        counteragent_id=UUID("47c6accc-4bc7-6be1-0194-ccf9367e20cb"),
    ),
    ("М6А", SupplyProductSourceRole.PACKAGING): IikoOutgoingInvoiceRoute(
        source_store_id=_PACKAGING_SOURCE_STORE_ID,
        destination_store_id=UUID("10f8add8-163d-47a7-b4ce-7b766fe9d6f0"),
        counteragent_id=UUID("47c6accc-4bc7-6be1-0194-ccf9367e20cb"),
    ),
    ("М6А", SupplyProductSourceRole.HOUSEHOLD): IikoOutgoingInvoiceRoute(
        source_store_id=_HOUSEHOLD_SOURCE_STORE_ID,
        destination_store_id=UUID("1d5e0f78-5c64-4458-99da-51c643f21208"),
        counteragent_id=UUID("cbc5afd7-6e03-a56d-0197-0acc172e765e"),
    ),
})

_INTERNAL_TRANSFER_ROUTES = MappingProxyType({
    ("ЦЕХ", SupplyProductSourceRole.MAIN): IikoInternalTransferRoute(
        from_store_id=_MAIN_SOURCE_STORE_ID,
        to_store_id=UUID("1c22edc0-7ded-41c9-b781-0389462c7247"),
    ),
    ("ЦЕХ", SupplyProductSourceRole.PACKAGING): IikoInternalTransferRoute(
        from_store_id=_PACKAGING_SOURCE_STORE_ID,
        to_store_id=UUID("1c22edc0-7ded-41c9-b781-0389462c7247"),
    ),
    ("ЦЕХ", SupplyProductSourceRole.HOUSEHOLD): IikoInternalTransferRoute(
        from_store_id=_HOUSEHOLD_SOURCE_STORE_ID,
        to_store_id=UUID("db13589d-68fd-4140-b1de-550f3e07c88a"),
    ),
})


def _route_flow(flow: SupplyProductSourceRole | str) -> SupplyProductSourceRole:
    return SupplyProductSourceRole(flow)


def resolve_outgoing_invoice_route(
    department_code: str,
    flow: SupplyProductSourceRole | str,
) -> IikoOutgoingInvoiceRoute:
    try:
        return _OUTGOING_INVOICE_ROUTES[(department_code, _route_flow(flow))]
    except (ValueError, KeyError) as error:
        raise IikoDocumentRouteNotConfiguredError(
            "OUTGOING_INVOICE",
            department_code,
            flow,
        ) from error


def resolve_internal_transfer_route(
    department_code: str,
    flow: SupplyProductSourceRole | str,
) -> IikoInternalTransferRoute:
    try:
        return _INTERNAL_TRANSFER_ROUTES[(department_code, _route_flow(flow))]
    except (ValueError, KeyError) as error:
        raise IikoDocumentRouteNotConfiguredError(
            "INTERNAL_TRANSFER",
            department_code,
            flow,
        ) from error


def outgoing_invoice_flows_for_department(
    department_code: str,
) -> frozenset[SupplyProductSourceRole]:
    return frozenset(
        flow
        for route_department_code, flow in _OUTGOING_INVOICE_ROUTES
        if route_department_code == department_code
    )


def internal_transfer_flows_for_department(
    department_code: str,
) -> frozenset[SupplyProductSourceRole]:
    return frozenset(
        flow
        for route_department_code, flow in _INTERNAL_TRANSFER_ROUTES
        if route_department_code == department_code
    )


def outgoing_invoice_flow_for_source_store(
    source_store_id: UUID,
) -> SupplyProductSourceRole:
    matches = {
        flow
        for (_, flow), route in _OUTGOING_INVOICE_ROUTES.items()
        if route.source_store_id == source_store_id
    }
    if len(matches) != 1:
        raise IikoDocumentRouteNotConfiguredError(
            "OUTGOING_INVOICE",
            "<source>",
            source_store_id,
        )
    return next(iter(matches))
