from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.iiko import (
    IikoMappingAction,
    IikoMappingAuditEvent,
    IikoMappingKind,
    IikoMappingStatus,
    IikoProductMapping,
    IikoRawEntity,
    IikoUnitMapping,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import (
    Department,
    SupplyProduct,
    SupplyProductAlias,
    SupplyUnit,
)
from app.supply.normalization import normalize_product_text


class MappingError(ValueError):
    pass


MappingT = TypeVar(
    "MappingT",
    IikoProductMapping,
    IikoUnitMapping,
    IikoWarehouseMapping,
)


@dataclass(frozen=True)
class MappingPage(Generic[MappingT]):
    items: list[MappingT]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class GenerationResult:
    products_created: int = 0
    products_updated: int = 0
    units_created: int = 0
    units_updated: int = 0
    warehouses_created: int = 0
    warehouses_updated: int = 0


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _normalized(value: str | None) -> str:
    return normalize_product_text(value or "")


def _latest_raw_entities(
    session: Session,
    *,
    tenant_id: str,
    entity_type: str,
) -> list[IikoRawEntity]:
    rows = session.scalars(
        select(IikoRawEntity)
        .where(
            IikoRawEntity.tenant_id == tenant_id,
            IikoRawEntity.entity_type == entity_type,
        )
        .order_by(
            IikoRawEntity.external_id,
            IikoRawEntity.received_at.desc(),
            IikoRawEntity.id.desc(),
        )
    ).all()
    latest: dict[str, IikoRawEntity] = {}
    for row in rows:
        latest.setdefault(row.external_id, row)
    return list(latest.values())


def _state(mapping: MappingT) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": mapping.status.value,
        "confidence": mapping.confidence,
        "reasons": list(mapping.reasons),
    }
    if isinstance(mapping, IikoProductMapping):
        result["eos_product_id"] = (
            str(mapping.eos_product_id) if mapping.eos_product_id else None
        )
    elif isinstance(mapping, IikoUnitMapping):
        result["eos_unit_id"] = (
            str(mapping.eos_unit_id) if mapping.eos_unit_id else None
        )
    else:
        result["eos_department_id"] = (
            str(mapping.eos_department_id)
            if mapping.eos_department_id
            else None
        )
        result["role"] = mapping.role.value if mapping.role else None
    return result


def _audit(
    session: Session,
    mapping: MappingT,
    *,
    kind: IikoMappingKind,
    action: IikoMappingAction,
    actor_user_id: int | None,
    before: dict[str, Any],
) -> None:
    session.add(
        IikoMappingAuditEvent(
            tenant_id=mapping.tenant_id,
            mapping_kind=kind,
            mapping_id=mapping.id,
            action=action,
            actor_user_id=actor_user_id,
            before=before,
            after=_state(mapping),
        )
    )


def _score_product(
    payload: dict[str, Any],
    product: SupplyProduct,
    aliases: set[str],
    confirmed_units: dict[UUID, UUID],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    source_name = _normalized(payload.get("name"))
    if source_name and source_name == product.normalized_name:
        score += 60
        reasons.append("Название совпадает")
    if source_name and source_name in aliases:
        score += 55
        reasons.append("Совпадает подтверждённый алиас")
    source_code = _normalized(payload.get("code"))
    source_sku = _normalized(payload.get("num"))
    product_name = _normalized(product.name)
    if source_code and source_code in {product_name, product.normalized_name}:
        score += 30
        reasons.append("Код совпадает с карточкой EOS")
    if source_sku and source_sku in {product_name, product.normalized_name}:
        score += 35
        reasons.append("Артикул совпадает с карточкой EOS")
    unit_id = _uuid(payload.get("mainUnit"))
    if unit_id and confirmed_units.get(unit_id) == product.default_unit_id:
        score += 20
        reasons.append("Единица подтверждена")
    return score, reasons


def _score_unit(
    payload: dict[str, Any],
    unit: SupplyUnit,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    source_code = _normalized(payload.get("code"))
    if source_code and source_code in {
        _normalized(unit.code),
        _normalized(unit.short_name_ru),
    }:
        score += 70
        reasons.append("Код единицы совпадает")
    if _normalized(payload.get("name")) == _normalized(unit.name_ru):
        score += 60
        reasons.append("Название единицы совпадает")
    return score, reasons


def _warehouse_role(name: str) -> IikoWarehouseRole:
    normalized = _normalized(name)
    if any(word in normalized for word in ("упаков", "тара")):
        return IikoWarehouseRole.PACKAGING
    if any(word in normalized for word in ("хоз", "быт")):
        return IikoWarehouseRole.HOUSEHOLD
    if any(word in normalized for word in ("основн средств", "ос ", "инвентар")):
        return IikoWarehouseRole.FIXED_ASSETS
    if any(word in normalized for word in ("основн", "главн")):
        return IikoWarehouseRole.MAIN
    return IikoWarehouseRole.OTHER


def _score_department(
    payload: dict[str, Any],
    department: Department,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if _normalized(payload.get("name")) == _normalized(department.name):
        score += 60
        reasons.append("Название подразделения совпадает")
    source_code = _normalized(payload.get("code"))
    if source_code and source_code == _normalized(department.code):
        score += 70
        reasons.append("Код подразделения совпадает")
    return score, reasons


def _best_candidate(
    scored: list[tuple[int, list[str], Any]],
    *,
    minimum: int,
) -> tuple[Any | None, IikoMappingStatus, int | None, list[str]]:
    eligible = [item for item in scored if item[0] >= minimum]
    if not eligible:
        return None, IikoMappingStatus.UNMAPPED, None, []
    best_score = max(item[0] for item in eligible)
    best = [item for item in eligible if item[0] == best_score]
    if len(best) > 1:
        return (
            best[0][2],
            IikoMappingStatus.CONFLICT,
            best_score,
            ["Несколько равных кандидатов", *best[0][1]],
        )
    return best[0][2], IikoMappingStatus.SUGGESTED, best_score, best[0][1]


def _should_preserve(mapping: MappingT) -> bool:
    return mapping.status in {
        IikoMappingStatus.CONFIRMED,
        IikoMappingStatus.IGNORED,
    }


def generate_mapping_candidates(
    session: Session,
    *,
    tenant_id: str,
) -> GenerationResult:
    products = session.scalars(
        select(SupplyProduct).where(SupplyProduct.tenant_id == tenant_id)
    ).all()
    units = session.scalars(
        select(SupplyUnit).where(SupplyUnit.tenant_id == tenant_id)
    ).all()
    departments = session.scalars(
        select(Department).where(Department.tenant_id == tenant_id)
    ).all()
    alias_rows = session.execute(
        select(SupplyProductAlias.product_id, SupplyProductAlias.normalized_alias)
        .where(
            SupplyProductAlias.tenant_id == tenant_id,
            SupplyProductAlias.status == "APPROVED",
        )
    ).all()
    aliases: dict[UUID, set[str]] = {}
    for product_id, alias in alias_rows:
        aliases.setdefault(product_id, set()).add(alias)
    confirmed_units = dict(
        session.execute(
            select(IikoUnitMapping.iiko_unit_id, IikoUnitMapping.eos_unit_id)
            .where(
                IikoUnitMapping.tenant_id == tenant_id,
                IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
                IikoUnitMapping.eos_unit_id.is_not(None),
            )
        ).all()
    )
    counts = {
        "products_created": 0,
        "products_updated": 0,
        "units_created": 0,
        "units_updated": 0,
        "warehouses_created": 0,
        "warehouses_updated": 0,
    }

    for raw in _latest_raw_entities(
        session, tenant_id=tenant_id, entity_type="product"
    ):
        external_id = _uuid(raw.external_id)
        if external_id is None:
            continue
        mapping = session.scalar(
            select(IikoProductMapping).where(
                IikoProductMapping.tenant_id == tenant_id,
                IikoProductMapping.iiko_product_id == external_id,
            )
        )
        created = mapping is None
        if mapping is None:
            mapping = IikoProductMapping(
                tenant_id=tenant_id,
                iiko_product_id=external_id,
                source_name=str(raw.payload.get("name") or raw.external_id),
            )
            session.add(mapping)
            session.flush()
        before = _state(mapping)
        mapping.source_name = str(raw.payload.get("name") or raw.external_id)
        mapping.source_code = raw.payload.get("code")
        mapping.source_sku = raw.payload.get("num")
        mapping.source_unit_id = _uuid(raw.payload.get("mainUnit"))
        mapping.is_deleted = bool(raw.payload.get("deleted", False))
        if not _should_preserve(mapping):
            candidate, state, score, reasons = _best_candidate(
                [
                    (
                        *_score_product(
                            raw.payload,
                            product,
                            aliases.get(product.id, set()),
                            confirmed_units,
                        ),
                        product,
                    )
                    for product in products
                ],
                minimum=55,
            )
            if candidate is not None and session.scalar(
                select(IikoProductMapping.id).where(
                    IikoProductMapping.tenant_id == tenant_id,
                    IikoProductMapping.eos_product_id == candidate.id,
                    IikoProductMapping.status
                    == IikoMappingStatus.CONFIRMED,
                    IikoProductMapping.is_deleted.is_(False),
                    IikoProductMapping.id != mapping.id,
                )
            ):
                state = IikoMappingStatus.CONFLICT
                reasons = [
                    "Кандидат уже подтверждён для другого UUID iiko",
                    *reasons,
                ]
            mapping.eos_product_id = candidate.id if candidate else None
            mapping.status = state
            mapping.confidence = score
            mapping.reasons = reasons
        after = _state(mapping)
        if created or after != before:
            _audit(
                session,
                mapping,
                kind=IikoMappingKind.PRODUCT,
                action=IikoMappingAction.GENERATED,
                actor_user_id=None,
                before=before,
            )
            counts["products_created" if created else "products_updated"] += 1

    for raw in _latest_raw_entities(
        session, tenant_id=tenant_id, entity_type="unit"
    ):
        external_id = _uuid(raw.external_id)
        if external_id is None:
            continue
        mapping = session.scalar(
            select(IikoUnitMapping).where(
                IikoUnitMapping.tenant_id == tenant_id,
                IikoUnitMapping.iiko_unit_id == external_id,
            )
        )
        created = mapping is None
        if mapping is None:
            mapping = IikoUnitMapping(
                tenant_id=tenant_id,
                iiko_unit_id=external_id,
                source_name=str(raw.payload.get("name") or raw.external_id),
            )
            session.add(mapping)
            session.flush()
        before = _state(mapping)
        mapping.source_name = str(raw.payload.get("name") or raw.external_id)
        mapping.source_code = raw.payload.get("code")
        mapping.is_deleted = bool(raw.payload.get("deleted", False))
        if not _should_preserve(mapping):
            candidate, state, score, reasons = _best_candidate(
                [
                    (*_score_unit(raw.payload, unit), unit)
                    for unit in units
                ],
                minimum=60,
            )
            if candidate is not None and session.scalar(
                select(IikoUnitMapping.id).where(
                    IikoUnitMapping.tenant_id == tenant_id,
                    IikoUnitMapping.eos_unit_id == candidate.id,
                    IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
                    IikoUnitMapping.is_deleted.is_(False),
                    IikoUnitMapping.id != mapping.id,
                )
            ):
                state = IikoMappingStatus.CONFLICT
                reasons = [
                    "Кандидат уже подтверждён для другого UUID iiko",
                    *reasons,
                ]
            mapping.eos_unit_id = candidate.id if candidate else None
            mapping.status = state
            mapping.confidence = score
            mapping.reasons = reasons
        after = _state(mapping)
        if created or after != before:
            _audit(
                session,
                mapping,
                kind=IikoMappingKind.UNIT,
                action=IikoMappingAction.GENERATED,
                actor_user_id=None,
                before=before,
            )
            counts["units_created" if created else "units_updated"] += 1

    for raw in _latest_raw_entities(
        session, tenant_id=tenant_id, entity_type="warehouse"
    ):
        external_id = _uuid(raw.external_id)
        if external_id is None:
            continue
        mapping = session.scalar(
            select(IikoWarehouseMapping).where(
                IikoWarehouseMapping.tenant_id == tenant_id,
                IikoWarehouseMapping.iiko_warehouse_id == external_id,
            )
        )
        created = mapping is None
        if mapping is None:
            mapping = IikoWarehouseMapping(
                tenant_id=tenant_id,
                iiko_warehouse_id=external_id,
                source_name=str(raw.payload.get("name") or raw.external_id),
            )
            session.add(mapping)
            session.flush()
        before = _state(mapping)
        mapping.source_name = str(raw.payload.get("name") or raw.external_id)
        mapping.source_code = raw.payload.get("code")
        mapping.is_deleted = bool(raw.payload.get("deleted", False))
        if not _should_preserve(mapping):
            candidate, state, score, reasons = _best_candidate(
                [
                    (*_score_department(raw.payload, department), department)
                    for department in departments
                ],
                minimum=60,
            )
            mapping.eos_department_id = candidate.id if candidate else None
            mapping.role = (
                _warehouse_role(mapping.source_name) if candidate else None
            )
            if (
                candidate is not None
                and mapping.role is not None
                and session.scalar(
                    select(IikoWarehouseMapping.id).where(
                        IikoWarehouseMapping.tenant_id == tenant_id,
                        IikoWarehouseMapping.eos_department_id
                        == candidate.id,
                        IikoWarehouseMapping.role == mapping.role,
                        IikoWarehouseMapping.status
                        == IikoMappingStatus.CONFIRMED,
                        IikoWarehouseMapping.is_deleted.is_(False),
                        IikoWarehouseMapping.id != mapping.id,
                    )
                )
            ):
                state = IikoMappingStatus.CONFLICT
                reasons = [
                    "Для роли уже подтверждён другой склад iiko",
                    *reasons,
                ]
            mapping.status = state
            mapping.confidence = score
            mapping.reasons = reasons
        after = _state(mapping)
        if created or after != before:
            _audit(
                session,
                mapping,
                kind=IikoMappingKind.WAREHOUSE,
                action=IikoMappingAction.GENERATED,
                actor_user_id=None,
                before=before,
            )
            counts[
                "warehouses_created" if created else "warehouses_updated"
            ] += 1
    session.commit()
    return GenerationResult(**counts)


def list_mappings(
    session: Session,
    model: type[MappingT],
    *,
    tenant_id: str,
    status: IikoMappingStatus | None,
    search: str | None,
    include_deleted: bool,
    conflicts_only: bool,
    limit: int,
    offset: int,
) -> MappingPage[MappingT]:
    query = select(model).where(model.tenant_id == tenant_id)
    if status is not None:
        query = query.where(model.status == status)
    if conflicts_only:
        query = query.where(model.status == IikoMappingStatus.CONFLICT)
    if not include_deleted:
        query = query.where(model.is_deleted.is_(False))
    if search:
        pattern = f"%{search.strip()}%"
        predicates = [
            model.source_name.ilike(pattern),
            model.source_code.ilike(pattern),
        ]
        if model is IikoProductMapping:
            predicates.append(
                IikoProductMapping.eos_product.has(
                    SupplyProduct.name.ilike(pattern)
                )
            )
        elif model is IikoUnitMapping:
            predicates.append(
                IikoUnitMapping.eos_unit.has(
                    SupplyUnit.name_ru.ilike(pattern)
                )
            )
        else:
            predicates.append(
                IikoWarehouseMapping.eos_department.has(
                    Department.name.ilike(pattern)
                )
            )
        query = query.where(or_(*predicates))
    rows = session.scalars(query.order_by(model.source_name, model.id)).all()
    return MappingPage(
        items=list(rows[offset : offset + limit]),
        total=len(rows),
        limit=limit,
        offset=offset,
    )


def _get_mapping(
    session: Session,
    model: type[MappingT],
    *,
    tenant_id: str,
    mapping_id: UUID,
) -> MappingT:
    mapping = session.scalar(
        select(model)
        .where(model.id == mapping_id, model.tenant_id == tenant_id)
        .with_for_update()
    )
    if mapping is None:
        raise MappingError("Mapping не найден")
    return mapping


def _finish_decision(
    session: Session,
    mapping: MappingT,
    *,
    kind: IikoMappingKind,
    action: IikoMappingAction,
    actor_user_id: int,
    before: dict[str, Any],
) -> MappingT:
    mapping.decided_by_user_id = actor_user_id
    mapping.decided_at = datetime.now(timezone.utc)
    _audit(
        session,
        mapping,
        kind=kind,
        action=action,
        actor_user_id=actor_user_id,
        before=before,
    )
    session.commit()
    session.refresh(mapping)
    return mapping


def confirm_product_mapping(
    session: Session,
    *,
    tenant_id: str,
    mapping_id: UUID,
    eos_product_id: UUID,
    actor_user_id: int,
    replace: bool = False,
) -> IikoProductMapping:
    mapping = _get_mapping(
        session, IikoProductMapping, tenant_id=tenant_id, mapping_id=mapping_id
    )
    product = session.scalar(
        select(SupplyProduct).where(
            SupplyProduct.id == eos_product_id,
            SupplyProduct.tenant_id == tenant_id,
        )
    )
    if product is None:
        raise MappingError("Товар EOS не найден")
    conflict = session.scalar(
        select(IikoProductMapping.id).where(
            IikoProductMapping.tenant_id == tenant_id,
            IikoProductMapping.eos_product_id == eos_product_id,
            IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
            IikoProductMapping.is_deleted.is_(False),
            IikoProductMapping.id != mapping.id,
        )
    )
    if conflict:
        raise MappingError("Товар EOS уже подтверждён для другого UUID iiko")
    before = _state(mapping)
    mapping.eos_product_id = eos_product_id
    mapping.status = IikoMappingStatus.CONFIRMED
    mapping.confidence = 100
    mapping.reasons = ["Подтверждено администратором"]
    return _finish_decision(
        session,
        mapping,
        kind=IikoMappingKind.PRODUCT,
        action=(
            IikoMappingAction.REPLACED if replace else IikoMappingAction.CONFIRMED
        ),
        actor_user_id=actor_user_id,
        before=before,
    )


def confirm_unit_mapping(
    session: Session,
    *,
    tenant_id: str,
    mapping_id: UUID,
    eos_unit_id: UUID,
    actor_user_id: int,
    replace: bool = False,
) -> IikoUnitMapping:
    mapping = _get_mapping(
        session, IikoUnitMapping, tenant_id=tenant_id, mapping_id=mapping_id
    )
    unit = session.scalar(
        select(SupplyUnit).where(
            SupplyUnit.id == eos_unit_id,
            SupplyUnit.tenant_id == tenant_id,
        )
    )
    if unit is None:
        raise MappingError("Единица EOS не найдена")
    conflict = session.scalar(
        select(IikoUnitMapping.id).where(
            IikoUnitMapping.tenant_id == tenant_id,
            IikoUnitMapping.eos_unit_id == eos_unit_id,
            IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
            IikoUnitMapping.is_deleted.is_(False),
            IikoUnitMapping.id != mapping.id,
        )
    )
    if conflict:
        raise MappingError("Единица EOS уже подтверждена для другого UUID iiko")
    before = _state(mapping)
    mapping.eos_unit_id = eos_unit_id
    mapping.status = IikoMappingStatus.CONFIRMED
    mapping.confidence = 100
    mapping.reasons = ["Подтверждено администратором"]
    return _finish_decision(
        session,
        mapping,
        kind=IikoMappingKind.UNIT,
        action=(
            IikoMappingAction.REPLACED if replace else IikoMappingAction.CONFIRMED
        ),
        actor_user_id=actor_user_id,
        before=before,
    )


def confirm_warehouse_mapping(
    session: Session,
    *,
    tenant_id: str,
    mapping_id: UUID,
    eos_department_id: UUID,
    role: IikoWarehouseRole,
    actor_user_id: int,
    replace: bool = False,
) -> IikoWarehouseMapping:
    mapping = _get_mapping(
        session,
        IikoWarehouseMapping,
        tenant_id=tenant_id,
        mapping_id=mapping_id,
    )
    department = session.scalar(
        select(Department).where(
            Department.id == eos_department_id,
            Department.tenant_id == tenant_id,
        )
    )
    if department is None:
        raise MappingError("Подразделение EOS не найдено")
    conflict = session.scalar(
        select(IikoWarehouseMapping.id).where(
            IikoWarehouseMapping.tenant_id == tenant_id,
            IikoWarehouseMapping.eos_department_id == eos_department_id,
            IikoWarehouseMapping.role == role,
            IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
            IikoWarehouseMapping.is_deleted.is_(False),
            IikoWarehouseMapping.id != mapping.id,
        )
    )
    if conflict:
        raise MappingError(
            "Для подразделения уже подтверждён активный склад этой роли"
        )
    before = _state(mapping)
    mapping.eos_department_id = eos_department_id
    mapping.role = role
    mapping.status = IikoMappingStatus.CONFIRMED
    mapping.confidence = 100
    mapping.reasons = ["Подтверждено администратором"]
    return _finish_decision(
        session,
        mapping,
        kind=IikoMappingKind.WAREHOUSE,
        action=(
            IikoMappingAction.REPLACED if replace else IikoMappingAction.CONFIRMED
        ),
        actor_user_id=actor_user_id,
        before=before,
    )


def set_mapping_ignored(
    session: Session,
    model: type[MappingT],
    *,
    tenant_id: str,
    mapping_id: UUID,
    actor_user_id: int,
) -> MappingT:
    mapping = _get_mapping(
        session, model, tenant_id=tenant_id, mapping_id=mapping_id
    )
    before = _state(mapping)
    if isinstance(mapping, IikoProductMapping):
        mapping.eos_product_id = None
        kind = IikoMappingKind.PRODUCT
    elif isinstance(mapping, IikoUnitMapping):
        mapping.eos_unit_id = None
        kind = IikoMappingKind.UNIT
    else:
        mapping.eos_department_id = None
        mapping.role = None
        kind = IikoMappingKind.WAREHOUSE
    mapping.status = IikoMappingStatus.IGNORED
    mapping.confidence = None
    mapping.reasons = ["Игнорировано администратором"]
    return _finish_decision(
        session,
        mapping,
        kind=kind,
        action=IikoMappingAction.IGNORED,
        actor_user_id=actor_user_id,
        before=before,
    )


def unmap_mapping(
    session: Session,
    model: type[MappingT],
    *,
    tenant_id: str,
    mapping_id: UUID,
    actor_user_id: int,
) -> MappingT:
    mapping = _get_mapping(
        session, model, tenant_id=tenant_id, mapping_id=mapping_id
    )
    before = _state(mapping)
    if isinstance(mapping, IikoProductMapping):
        mapping.eos_product_id = None
        kind = IikoMappingKind.PRODUCT
    elif isinstance(mapping, IikoUnitMapping):
        mapping.eos_unit_id = None
        kind = IikoMappingKind.UNIT
    else:
        mapping.eos_department_id = None
        mapping.role = None
        kind = IikoMappingKind.WAREHOUSE
    mapping.status = IikoMappingStatus.UNMAPPED
    mapping.confidence = None
    mapping.reasons = []
    return _finish_decision(
        session,
        mapping,
        kind=kind,
        action=IikoMappingAction.UNMAPPED,
        actor_user_id=actor_user_id,
        before=before,
    )
