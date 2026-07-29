from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
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
    IikoWarehouseDestinationType,
    IikoWarehouseRole,
)
from app.models.supply import (
    Department,
    LegalContour,
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


@dataclass(frozen=True)
class CatalogBootstrapResult:
    created: int = 0
    linked: int = 0
    existing: int = 0
    conflicts: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ProductSource:
    original_name: str
    search_name: str
    mapping_type: str


@dataclass(frozen=True)
class GenerationProgress:
    generation_id: UUID
    status: str
    result: GenerationResult | None = None


_generation_lock = Lock()
_generation_progress: dict[tuple[str, UUID], GenerationProgress] = {}
_active_generation: dict[str, UUID] = {}


def start_generation(tenant_id: str, generation_id: UUID) -> bool:
    with _generation_lock:
        active_id = _active_generation.get(tenant_id)
        if active_id is not None:
            return False
        completed = [
            key
            for key, progress in _generation_progress.items()
            if key[0] == tenant_id and progress.status != "RUNNING"
        ]
        for key in completed[:-20]:
            _generation_progress.pop(key, None)
        _active_generation[tenant_id] = generation_id
        _generation_progress[(tenant_id, generation_id)] = GenerationProgress(
            generation_id=generation_id,
            status="RUNNING",
        )
        return True


def finish_generation(
    tenant_id: str,
    generation_id: UUID,
    *,
    result: GenerationResult | None,
) -> None:
    with _generation_lock:
        key = (tenant_id, generation_id)
        current = _generation_progress.get(key)
        if current is None:
            return
        _generation_progress[key] = GenerationProgress(
            generation_id=generation_id,
            status="SUCCEEDED" if result is not None else "FAILED",
            result=result,
        )
        if _active_generation.get(tenant_id) == generation_id:
            _active_generation.pop(tenant_id, None)


def get_generation_progress(
    tenant_id: str,
    generation_id: UUID,
) -> GenerationProgress:
    with _generation_lock:
        current = _generation_progress.get((tenant_id, generation_id))
        if current is None:
            return GenerationProgress(
                generation_id=generation_id,
                status="UNKNOWN",
            )
        return current


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _normalized(value: str | None) -> str:
    return normalize_product_text(value or "")


def _product_source(
    payload: dict[str, Any],
    *,
    is_active: bool,
) -> ProductSource | None:
    if not is_active or bool(payload.get("deleted", False)):
        return None
    original_name = str(payload.get("name") or "")
    name = original_name.lstrip()
    if not name or name.startswith("-"):
        return None
    folded = name.casefold()
    for prefix, mapping_type in (
        ("тх ", "HOUSEHOLD"),
        ("ту ", "PACKAGING"),
        ("т ", "PRODUCT"),
    ):
        if folded.startswith(prefix):
            search_name = name[len(prefix):].strip()
            if not search_name:
                return None
            return ProductSource(
                original_name=original_name,
                search_name=search_name,
                mapping_type=mapping_type,
            )
    return None


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
        result["destination_type"] = (
            mapping.destination_type.value
            if mapping.destination_type
            else IikoWarehouseDestinationType.DESTINATION.value
        )
        result["eos_department_id"] = (
            str(mapping.eos_department_id)
            if mapping.eos_department_id
            else None
        )
        result["role"] = mapping.role.value if mapping.role else None
        legal_contour = (
            mapping.eos_department.legal_contour
            if (
                mapping.destination_type
                == IikoWarehouseDestinationType.DESTINATION
                and mapping.eos_department is not None
            )
            else mapping.legal_contour
        )
        result["legal_contour"] = (
            legal_contour.value if legal_contour else None
        )
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
    source_search_name: str,
    product: SupplyProduct,
    aliases: set[str],
    confirmed_units: dict[UUID, UUID],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    source_name = _normalized(source_search_name)
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


def bootstrap_product_catalog(
    session: Session,
    *,
    tenant_id: str,
    actor_user_id: int,
) -> CatalogBootstrapResult:
    products = session.scalars(
        select(SupplyProduct).where(SupplyProduct.tenant_id == tenant_id)
    ).all()
    aliases = session.execute(
        select(SupplyProductAlias.product_id, SupplyProductAlias.normalized_alias)
        .where(
            SupplyProductAlias.tenant_id == tenant_id,
            SupplyProductAlias.status == "APPROVED",
        )
    ).all()
    product_mappings = {
        mapping.iiko_product_id: mapping
        for mapping in session.scalars(
            select(IikoProductMapping).where(
                IikoProductMapping.tenant_id == tenant_id
            )
        ).all()
    }
    confirmed_product_targets = {
        mapping.eos_product_id: mapping.iiko_product_id
        for mapping in product_mappings.values()
        if (
            mapping.status == IikoMappingStatus.CONFIRMED
            and mapping.eos_product_id is not None
        )
    }
    confirmed_units = {
        mapping.iiko_unit_id: mapping.eos_unit
        for mapping in session.scalars(
            select(IikoUnitMapping).where(
                IikoUnitMapping.tenant_id == tenant_id,
                IikoUnitMapping.status == IikoMappingStatus.CONFIRMED,
                IikoUnitMapping.is_deleted.is_(False),
                IikoUnitMapping.eos_unit_id.is_not(None),
            )
        ).all()
        if mapping.eos_unit is not None and mapping.eos_unit.is_active
    }
    products_by_id = {product.id: product for product in products}
    products_by_name: dict[str, set[UUID]] = {}
    products_by_iiko_id = {
        product.iiko_id: product
        for product in products
        if product.iiko_id is not None
    }
    for product in products:
        products_by_name.setdefault(product.normalized_name, set()).add(
            product.id
        )
    for product_id, normalized_alias in aliases:
        products_by_name.setdefault(normalized_alias, set()).add(product_id)

    counts = {
        "created": 0,
        "linked": 0,
        "existing": 0,
        "conflicts": 0,
        "skipped": 0,
    }

    def set_conflict(
        mapping: IikoProductMapping,
        *,
        before: dict[str, Any],
        reason: str,
        candidate: SupplyProduct | None = None,
    ) -> None:
        mapping.eos_product_id = candidate.id if candidate else None
        mapping.status = IikoMappingStatus.CONFLICT
        mapping.confidence = None
        mapping.reasons = [reason]
        if before != _state(mapping):
            _audit(
                session,
                mapping,
                kind=IikoMappingKind.PRODUCT,
                action=IikoMappingAction.GENERATED,
                actor_user_id=actor_user_id,
                before=before,
            )
        counts["conflicts"] += 1

    for raw in _latest_raw_entities(
        session,
        tenant_id=tenant_id,
        entity_type="product",
    ):
        source = _product_source(raw.payload, is_active=raw.is_active)
        external_id = _uuid(raw.external_id)
        if (
            source is None
            or external_id is None
            or len(source.search_name) > 240
            or not _normalized(source.search_name)
        ):
            counts["skipped"] += 1
            continue

        mapping = product_mappings.get(external_id)
        if mapping is None:
            mapping = IikoProductMapping(
                id=uuid4(),
                tenant_id=tenant_id,
                iiko_product_id=external_id,
                source_name=source.original_name,
                status=IikoMappingStatus.UNMAPPED,
                is_deleted=False,
                reasons=[],
            )
            session.add(mapping)
            product_mappings[external_id] = mapping
        if _should_preserve(mapping):
            counts[
                "existing"
                if mapping.status == IikoMappingStatus.CONFIRMED
                else "skipped"
            ] += 1
            continue

        before = _state(mapping)
        mapping.source_name = source.original_name
        mapping.source_code = raw.payload.get("code")
        mapping.source_sku = raw.payload.get("num")
        mapping.source_unit_id = _uuid(raw.payload.get("mainUnit"))
        mapping.is_deleted = False
        base_reasons = [f"Тип iiko: {source.mapping_type}"]
        unit = confirmed_units.get(mapping.source_unit_id)
        if unit is None:
            set_conflict(
                mapping,
                before=before,
                reason="Единица iiko не подтверждена в EOS",
            )
            continue

        normalized_name = _normalized(source.search_name)
        product_with_iiko_id = products_by_iiko_id.get(str(external_id))
        if product_with_iiko_id is not None:
            if (
                product_with_iiko_id.normalized_name != normalized_name
                or product_with_iiko_id.default_unit_id != unit.id
                or not product_with_iiko_id.is_active
            ):
                set_conflict(
                    mapping,
                    before=before,
                    reason="Связанный товар EOS отличается по названию или единице",
                    candidate=product_with_iiko_id,
                )
                continue
            mapping.eos_product_id = product_with_iiko_id.id
            mapping.status = IikoMappingStatus.CONFIRMED
            mapping.confidence = 100
            mapping.reasons = [
                *base_reasons,
                "Связь восстановлена по iiko external_id",
            ]
            if before != _state(mapping):
                _audit(
                    session,
                    mapping,
                    kind=IikoMappingKind.PRODUCT,
                    action=IikoMappingAction.CONFIRMED,
                    actor_user_id=actor_user_id,
                    before=before,
                )
                counts["linked"] += 1
            counts["existing"] += 1
            continue

        candidate_ids = products_by_name.get(normalized_name, set())
        candidates = [products_by_id[product_id] for product_id in candidate_ids]
        active_candidates = [
            candidate for candidate in candidates if candidate.is_active
        ]
        if len(candidates) != 1 or len(active_candidates) != 1:
            if candidates:
                set_conflict(
                    mapping,
                    before=before,
                    reason="Найдено неоднозначное или неактивное совпадение EOS",
                )
                continue
        elif active_candidates[0].default_unit_id != unit.id:
            set_conflict(
                mapping,
                before=before,
                reason="Название совпало, но единица товара отличается",
                candidate=active_candidates[0],
            )
            continue
        else:
            candidate = active_candidates[0]
            if (
                candidate.iiko_id not in {None, str(external_id)}
                or confirmed_product_targets.get(candidate.id)
                not in {None, external_id}
            ):
                set_conflict(
                    mapping,
                    before=before,
                    reason="Товар EOS уже связан с другой позицией iiko",
                    candidate=candidate,
                )
                continue
            mapping.eos_product_id = candidate.id
            mapping.status = IikoMappingStatus.SUGGESTED
            mapping.confidence = 80
            mapping.reasons = [
                *base_reasons,
                "Совпали нормализованное название и единица",
            ]
            if before != _state(mapping):
                _audit(
                    session,
                    mapping,
                    kind=IikoMappingKind.PRODUCT,
                    action=IikoMappingAction.GENERATED,
                    actor_user_id=actor_user_id,
                    before=before,
                )
            counts["existing"] += 1
            continue

        product = SupplyProduct(
            id=uuid4(),
            tenant_id=tenant_id,
            name=source.search_name,
            normalized_name=normalized_name,
            iiko_id=str(external_id),
            default_unit_id=unit.id,
            is_active=True,
        )
        session.add(product)
        products.append(product)
        products_by_id[product.id] = product
        products_by_name.setdefault(normalized_name, set()).add(product.id)
        products_by_iiko_id[str(external_id)] = product
        mapping.eos_product_id = product.id
        mapping.status = IikoMappingStatus.CONFIRMED
        mapping.confidence = 100
        mapping.reasons = [
            *base_reasons,
            "Товар EOS создан из staging iiko",
        ]
        _audit(
            session,
            mapping,
            kind=IikoMappingKind.PRODUCT,
            action=IikoMappingAction.CONFIRMED,
            actor_user_id=actor_user_id,
            before=before,
        )
        counts["created"] += 1
        counts["linked"] += 1

    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise MappingError(
            "Каталог изменился параллельно. Повторите инициализацию"
        ) from error
    return CatalogBootstrapResult(**counts)


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
    product_mappings = {
        mapping.iiko_product_id: mapping
        for mapping in session.scalars(
            select(IikoProductMapping).where(
                IikoProductMapping.tenant_id == tenant_id
            )
        ).all()
    }
    unit_mappings = {
        mapping.iiko_unit_id: mapping
        for mapping in session.scalars(
            select(IikoUnitMapping).where(
                IikoUnitMapping.tenant_id == tenant_id
            )
        ).all()
    }
    warehouse_mappings = {
        mapping.iiko_warehouse_id: mapping
        for mapping in session.scalars(
            select(IikoWarehouseMapping).where(
                IikoWarehouseMapping.tenant_id == tenant_id
            )
        ).all()
    }
    confirmed_units = {
        mapping.iiko_unit_id: mapping.eos_unit_id
        for mapping in unit_mappings.values()
        if (
            mapping.status == IikoMappingStatus.CONFIRMED
            and mapping.eos_unit_id is not None
        )
    }
    confirmed_product_targets = {
        mapping.eos_product_id
        for mapping in product_mappings.values()
        if (
            mapping.status == IikoMappingStatus.CONFIRMED
            and mapping.eos_product_id is not None
            and not mapping.is_deleted
        )
    }
    confirmed_unit_targets = {
        mapping.eos_unit_id
        for mapping in unit_mappings.values()
        if (
            mapping.status == IikoMappingStatus.CONFIRMED
            and mapping.eos_unit_id is not None
            and not mapping.is_deleted
        )
    }
    confirmed_warehouse_roles = {
        (mapping.eos_department_id, mapping.role)
        for mapping in warehouse_mappings.values()
        if (
            mapping.status == IikoMappingStatus.CONFIRMED
            and mapping.destination_type
            == IikoWarehouseDestinationType.DESTINATION
            and mapping.eos_department_id is not None
            and mapping.role is not None
            and not mapping.is_deleted
        )
    }
    products_by_id = {product.id: product for product in products}
    products_by_name: dict[str, set[UUID]] = {}
    products_by_alias: dict[str, set[UUID]] = {}
    for product in products:
        for name in {_normalized(product.name), product.normalized_name}:
            if name:
                products_by_name.setdefault(name, set()).add(product.id)
        for alias in aliases.get(product.id, set()):
            products_by_alias.setdefault(alias, set()).add(product.id)
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
        mapping = product_mappings.get(external_id)
        source = _product_source(
            raw.payload,
            is_active=raw.is_active,
        )
        if source is None:
            if mapping is not None and _should_preserve(mapping):
                mapping.source_name = str(
                    raw.payload.get("name") or raw.external_id
                )
                mapping.source_code = raw.payload.get("code")
                mapping.source_sku = raw.payload.get("num")
                mapping.source_unit_id = _uuid(raw.payload.get("mainUnit"))
                mapping.is_deleted = (
                    not raw.is_active
                    or bool(raw.payload.get("deleted", False))
                )
            elif mapping is not None:
                session.delete(mapping)
            continue
        created = mapping is None
        if mapping is None:
            mapping = IikoProductMapping(
                id=uuid4(),
                tenant_id=tenant_id,
                iiko_product_id=external_id,
                source_name=source.original_name,
                status=IikoMappingStatus.UNMAPPED,
                is_deleted=False,
                reasons=[],
            )
            session.add(mapping)
            product_mappings[external_id] = mapping
        before = _state(mapping)
        mapping.source_name = source.original_name
        mapping.source_code = raw.payload.get("code")
        mapping.source_sku = raw.payload.get("num")
        mapping.source_unit_id = _uuid(raw.payload.get("mainUnit"))
        mapping.is_deleted = False
        if not _should_preserve(mapping):
            source_name = _normalized(source.search_name)
            candidate_ids = set(products_by_name.get(source_name, set()))
            candidate_ids.update(products_by_alias.get(source_name, set()))
            candidate_ids.update(
                products_by_name.get(_normalized(raw.payload.get("code")), set())
            )
            candidate_ids.update(
                products_by_name.get(_normalized(raw.payload.get("num")), set())
            )
            candidate, state, score, reasons = _best_candidate(
                [
                    (
                        *_score_product(
                            raw.payload,
                            source.search_name,
                            product,
                            aliases.get(product.id, set()),
                            confirmed_units,
                        ),
                        product,
                    )
                    for product in (
                        products_by_id[product_id]
                        for product_id in candidate_ids
                    )
                ],
                minimum=55,
            )
            reasons = [f"Тип iiko: {source.mapping_type}", *reasons]
            if (
                candidate is not None
                and candidate.id in confirmed_product_targets
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
        mapping = unit_mappings.get(external_id)
        created = mapping is None
        if mapping is None:
            mapping = IikoUnitMapping(
                id=uuid4(),
                tenant_id=tenant_id,
                iiko_unit_id=external_id,
                source_name=str(raw.payload.get("name") or raw.external_id),
                status=IikoMappingStatus.UNMAPPED,
                is_deleted=False,
                reasons=[],
            )
            session.add(mapping)
            unit_mappings[external_id] = mapping
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
            if candidate is not None and candidate.id in confirmed_unit_targets:
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
        mapping = warehouse_mappings.get(external_id)
        created = mapping is None
        if mapping is None:
            mapping = IikoWarehouseMapping(
                id=uuid4(),
                tenant_id=tenant_id,
                iiko_warehouse_id=external_id,
                source_name=str(raw.payload.get("name") or raw.external_id),
                destination_type=IikoWarehouseDestinationType.DESTINATION,
                status=IikoMappingStatus.UNMAPPED,
                is_deleted=False,
                reasons=[],
            )
            session.add(mapping)
            warehouse_mappings[external_id] = mapping
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
                and (candidate.id, mapping.role) in confirmed_warehouse_roles
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
    destination_type: IikoWarehouseDestinationType,
    eos_department_id: UUID | None,
    role: IikoWarehouseRole | None,
    legal_contour: LegalContour | None,
    actor_user_id: int,
    replace: bool = False,
) -> IikoWarehouseMapping:
    mapping = _get_mapping(
        session,
        IikoWarehouseMapping,
        tenant_id=tenant_id,
        mapping_id=mapping_id,
    )
    if destination_type == IikoWarehouseDestinationType.DESTINATION:
        if eos_department_id is None or role is None:
            raise MappingError(
                "Для склада подразделения нужны подразделение и роль"
            )
        department = session.scalar(
            select(Department).where(
                Department.id == eos_department_id,
                Department.tenant_id == tenant_id,
            )
        )
        if department is None:
            raise MappingError("Подразделение EOS не найдено")
        if department.legal_contour is None:
            raise MappingError(
                "Для подразделения не настроен юридический контур"
            )
        conflict = session.scalar(
            select(IikoWarehouseMapping.id).where(
                IikoWarehouseMapping.tenant_id == tenant_id,
                IikoWarehouseMapping.destination_type
                == IikoWarehouseDestinationType.DESTINATION,
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
    else:
        if legal_contour is None or role is None:
            raise MappingError("Для источника снабжения нужны контур и роль")
    before = _state(mapping)
    mapping.destination_type = destination_type
    if destination_type == IikoWarehouseDestinationType.DESTINATION:
        mapping.eos_department = department
        mapping.role = role
        mapping.legal_contour = None
    else:
        mapping.eos_department_id = None
        mapping.role = role
        mapping.legal_contour = legal_contour
    mapping.status = IikoMappingStatus.CONFIRMED
    mapping.confidence = 100
    mapping.reasons = ["Подтверждено администратором"]
    try:
        return _finish_decision(
            session,
            mapping,
            kind=IikoMappingKind.WAREHOUSE,
            action=(
                IikoMappingAction.REPLACED
                if replace
                else IikoMappingAction.CONFIRMED
            ),
            actor_user_id=actor_user_id,
            before=before,
        )
    except IntegrityError as error:
        session.rollback()
        raise MappingError(
            "Такая активная подтверждённая связь склада уже существует"
        ) from error


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
        mapping.destination_type = IikoWarehouseDestinationType.DESTINATION
        mapping.legal_contour = None
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
        mapping.destination_type = IikoWarehouseDestinationType.DESTINATION
        mapping.legal_contour = None
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
