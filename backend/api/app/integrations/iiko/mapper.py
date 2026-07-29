from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, TypeVar

from pydantic import ValidationError

from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.schemas import (
    IikoOrganizationDto,
    IikoPackageDto,
    IikoProductCategoryDto,
    IikoProductDto,
    IikoProductGroupDto,
    IikoRecord,
    IikoStockBalanceDto,
    IikoUnitDto,
    IikoWarehouseDto,
)


DtoT = TypeVar(
    "DtoT",
    IikoOrganizationDto,
    IikoWarehouseDto,
    IikoProductGroupDto,
    IikoProductCategoryDto,
    IikoProductDto,
    IikoUnitDto,
    IikoPackageDto,
    IikoStockBalanceDto,
)


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise IikoContractError(f"Missing required iiko field: {field}")
    return value.strip()


def _optional_text(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise IikoContractError(f"Invalid iiko field: {field}")
    value = value.strip()
    return value or None


def _record(
    *,
    entity_type: str,
    payload: dict[str, Any],
    dto: DtoT,
    parent_external_id: str | None = None,
    organization_external_id: str | None = None,
    source_updated_at: datetime | None = None,
) -> IikoRecord[DtoT]:
    return IikoRecord(
        entity_type=entity_type,
        external_id=dto.external_id,
        parent_external_id=parent_external_id,
        organization_external_id=organization_external_id,
        is_active=getattr(dto, "is_active", True),
        dto=dto,
        raw_payload=payload,
        source_updated_at=source_updated_at,
    )


def map_organization(
    payload: dict[str, Any],
) -> IikoRecord[IikoOrganizationDto]:
    external_id = _required_text(payload, "id")
    name = _required_text(payload, "name")
    organization_type = _optional_text(payload, "type")
    parent = _optional_text(payload, "parentId") or _optional_text(
        payload, "parent"
    )
    try:
        dto = IikoOrganizationDto(
            external_id=external_id,
            name=name,
            code=_optional_text(payload, "code"),
            organization_type=organization_type,
            parent_external_id=parent,
            is_active=not bool(payload.get("deleted", False)),
        )
    except ValidationError as error:
        raise IikoContractError("Invalid organization contract") from error
    entity_type = (
        "enterprise" if organization_type == "DEPARTMENT" else "organization"
    )
    return _record(
        entity_type=entity_type,
        payload=payload,
        dto=dto,
        parent_external_id=parent,
    )


def map_warehouse(
    payload: dict[str, Any],
) -> IikoRecord[IikoWarehouseDto]:
    external_id = _required_text(payload, "id")
    name = _required_text(payload, "name")
    parent = (
        _optional_text(payload, "accountParentId")
        or _optional_text(payload, "parentId")
        or _optional_text(payload, "parent")
    )
    enterprise = (
        _optional_text(payload, "parentCorporateId")
        or _optional_text(payload, "departmentId")
        or _optional_text(payload, "department")
    )
    deleted = bool(payload.get("deleted", False))
    dto = IikoWarehouseDto(
        external_id=external_id,
        enterprise_external_id=enterprise,
        parent_external_id=parent,
        name=name,
        code=_optional_text(payload, "code"),
        warehouse_type=_optional_text(payload, "type"),
        is_active=not deleted,
        is_deleted=deleted,
    )
    return _record(
        entity_type="warehouse",
        payload=payload,
        dto=dto,
        parent_external_id=parent,
        organization_external_id=enterprise,
    )


def map_stock_balance(
    payload: dict[str, Any],
    *,
    calculated_at: datetime,
    product: IikoProductDto | None = None,
    warehouse: IikoWarehouseDto | None = None,
) -> IikoRecord[IikoStockBalanceDto]:
    warehouse_external_id = _required_text(payload, "store")
    product_external_id = _required_text(payload, "product")
    raw_quantity = payload.get("amount")
    try:
        quantity = Decimal(str(raw_quantity))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise IikoContractError("Invalid stock balance amount") from error
    if not quantity.is_finite():
        raise IikoContractError("Invalid stock balance amount")
    dto = IikoStockBalanceDto(
        warehouse_external_id=warehouse_external_id,
        product_external_id=product_external_id,
        quantity=quantity,
        unit_external_id=(
            product.base_unit_external_id if product is not None else None
        ),
        calculated_at=calculated_at,
        product_name=product.name if product is not None else None,
        warehouse_name=warehouse.name if warehouse is not None else None,
    )
    external_id = (
        f"{warehouse_external_id}:{product_external_id}:"
        f"{calculated_at.date().isoformat()}"
    )
    return IikoRecord(
        entity_type="stock_balance",
        external_id=external_id,
        organization_external_id=warehouse_external_id,
        is_active=True,
        dto=dto,
        raw_payload=payload,
    )


def map_product_group(
    payload: dict[str, Any],
) -> IikoRecord[IikoProductGroupDto]:
    deleted = bool(payload.get("deleted", False))
    parent = _optional_text(payload, "parent")
    dto = IikoProductGroupDto(
        external_id=_required_text(payload, "id"),
        parent_external_id=parent,
        name=_required_text(payload, "name"),
        code=_optional_text(payload, "code"),
        is_active=not deleted,
        is_deleted=deleted,
    )
    return _record(
        entity_type="product_group",
        payload=payload,
        dto=dto,
        parent_external_id=parent,
    )


def map_product_category(
    payload: dict[str, Any],
) -> IikoRecord[IikoProductCategoryDto]:
    deleted = bool(payload.get("deleted", False))
    dto = IikoProductCategoryDto(
        external_id=_required_text(payload, "id"),
        name=_required_text(payload, "name"),
        is_active=not deleted,
        is_deleted=deleted,
    )
    return _record(
        entity_type="product_category",
        payload=payload,
        dto=dto,
    )


def map_product(payload: dict[str, Any]) -> IikoRecord[IikoProductDto]:
    deleted = bool(payload.get("deleted", False))
    parent = _optional_text(payload, "parent")
    dto = IikoProductDto(
        external_id=_required_text(payload, "id"),
        name=_required_text(payload, "name"),
        code=_optional_text(payload, "code"),
        sku=_optional_text(payload, "num"),
        group_external_id=parent,
        category_external_id=_optional_text(payload, "category"),
        base_unit_external_id=_optional_text(payload, "mainUnit"),
        is_active=not deleted,
        is_deleted=deleted,
        product_type=_optional_text(payload, "type"),
    )
    return _record(
        entity_type="product",
        payload=payload,
        dto=dto,
        parent_external_id=parent,
    )


def map_unit(payload: dict[str, Any]) -> IikoRecord[IikoUnitDto]:
    deleted = bool(payload.get("deleted", False))
    code = _optional_text(payload, "code")
    dto = IikoUnitDto(
        external_id=_required_text(payload, "id"),
        name=_required_text(payload, "name"),
        short_name=code,
        code=code,
        is_active=not deleted,
    )
    return _record(entity_type="unit", payload=payload, dto=dto)


def map_packages(
    product_payload: dict[str, Any],
) -> list[IikoRecord[IikoPackageDto]]:
    product_id = _required_text(product_payload, "id")
    unit_id = _optional_text(product_payload, "mainUnit")
    containers = product_payload.get("containers") or []
    if not isinstance(containers, list):
        raise IikoContractError("Invalid containers contract")
    result: list[IikoRecord[IikoPackageDto]] = []
    for index, payload in enumerate(containers):
        if not isinstance(payload, dict):
            raise IikoContractError("Invalid container contract")
        try:
            coefficient = Decimal(str(payload.get("count")))
        except (InvalidOperation, TypeError) as error:
            raise IikoContractError("Invalid container coefficient") from error
        deleted = bool(payload.get("deleted", False))
        dto = IikoPackageDto(
            external_id=_required_text(payload, "id"),
            product_external_id=product_id,
            unit_external_id=unit_id,
            name=_required_text(payload, "name"),
            coefficient=coefficient,
            is_default=index == 0,
            is_active=not deleted,
        )
        result.append(
            _record(
                entity_type="package",
                payload={
                    **payload,
                    "_product_external_id": product_id,
                    "_unit_external_id": unit_id,
                },
                dto=dto,
                parent_external_id=product_id,
            )
        )
    return result


def map_collection(
    payloads: list[dict[str, Any]],
    mapper: Callable[[dict[str, Any]], IikoRecord[DtoT]],
) -> list[IikoRecord[DtoT]]:
    records = [mapper(payload) for payload in payloads]
    ids = [record.external_id for record in records]
    if len(ids) != len(set(ids)):
        raise IikoContractError("Duplicate external IDs in iiko response")
    return records
