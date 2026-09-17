from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.iiko import (
    IikoRawEntity,
    IikoSupplierMapping,
    IikoSupplierMappingStatus,
)
from app.models.supply import SupplySupplier


class SupplierMappingError(ValueError):
    pass


def _latest_supplier_rows(session: Session, tenant_id: str) -> list[IikoRawEntity]:
    latest_ids = (
        select(func.max(IikoRawEntity.id))
        .where(
            IikoRawEntity.tenant_id == tenant_id,
            IikoRawEntity.entity_type == "supplier",
        )
        .group_by(IikoRawEntity.external_id)
    )
    return list(session.scalars(
        select(IikoRawEntity).where(IikoRawEntity.id.in_(latest_ids))
    ))


def list_iiko_suppliers(
    session: Session,
    *,
    tenant_id: str,
    search: str | None,
    include_deleted: bool,
) -> list[IikoRawEntity]:
    rows = _latest_supplier_rows(session, tenant_id)
    needle = (search or "").strip().casefold()
    result = []
    for row in rows:
        payload = row.payload
        if not bool(payload.get("supplier", False)):
            continue
        if not include_deleted and bool(payload.get("deleted", False)):
            continue
        haystack = " ".join(
            str(payload.get(key) or "") for key in ("name", "code", "inn")
        ).casefold()
        if needle and needle not in haystack:
            continue
        result.append(row)
    return sorted(
        result,
        key=lambda row: (str(row.payload.get("name") or "").casefold(), row.external_id),
    )


def get_mapping_state(
    session: Session,
    *,
    tenant_id: str,
    supplier_id: UUID,
) -> tuple[SupplySupplier, IikoSupplierMapping | None, list[IikoSupplierMapping]]:
    supplier = session.scalar(select(SupplySupplier).where(
        SupplySupplier.tenant_id == tenant_id,
        SupplySupplier.id == supplier_id,
    ))
    if supplier is None:
        raise SupplierMappingError("Поставщик не найден")
    history = list(session.scalars(
        select(IikoSupplierMapping).where(
            IikoSupplierMapping.tenant_id == tenant_id,
            IikoSupplierMapping.supplier_id == supplier_id,
        ).order_by(desc(IikoSupplierMapping.confirmed_at), desc(IikoSupplierMapping.id))
    ))
    current = next(
        (item for item in history if item.status == IikoSupplierMappingStatus.CONFIRMED),
        None,
    )
    return supplier, current, history


def confirm_supplier_mapping(
    session: Session,
    *,
    tenant_id: str,
    supplier_id: UUID,
    iiko_supplier_id: UUID,
    actor_user_id: int,
) -> IikoSupplierMapping:
    supplier = session.scalar(
        select(SupplySupplier).where(
            SupplySupplier.tenant_id == tenant_id,
            SupplySupplier.id == supplier_id,
        ).with_for_update()
    )
    if supplier is None:
        raise SupplierMappingError("Поставщик не найден")

    references = [
        row for row in _latest_supplier_rows(session, tenant_id)
        if row.external_id == str(iiko_supplier_id)
    ]
    if not references:
        raise SupplierMappingError("Поставщик iiko не найден в актуальном снимке")
    reference = references[0]
    payload = reference.payload
    if not bool(payload.get("supplier", False)):
        raise SupplierMappingError("Выбранная запись iiko не является поставщиком")
    if bool(payload.get("deleted", False)) or not reference.is_active:
        raise SupplierMappingError("Удалённого поставщика iiko нельзя сопоставить")

    current = session.scalar(select(IikoSupplierMapping).where(
        IikoSupplierMapping.tenant_id == tenant_id,
        IikoSupplierMapping.supplier_id == supplier_id,
        IikoSupplierMapping.status == IikoSupplierMappingStatus.CONFIRMED,
    ))
    if current is not None and current.iiko_supplier_id == iiko_supplier_id:
        return current

    occupied = session.scalar(select(IikoSupplierMapping.id).where(
        IikoSupplierMapping.tenant_id == tenant_id,
        IikoSupplierMapping.iiko_supplier_id == iiko_supplier_id,
        IikoSupplierMapping.status == IikoSupplierMappingStatus.CONFIRMED,
        IikoSupplierMapping.supplier_id != supplier_id,
    ))
    if occupied is not None:
        raise SupplierMappingError("Этот поставщик iiko уже сопоставлен")

    now = datetime.now(timezone.utc)
    if current is not None:
        current.status = IikoSupplierMappingStatus.ARCHIVED
        current.archived_at = now
        current.archived_by_user_id = actor_user_id

    mapping = IikoSupplierMapping(
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        iiko_supplier_id=iiko_supplier_id,
        iiko_supplier_name=str(payload.get("name") or "").strip(),
        iiko_supplier_code=(str(payload["code"]).strip() if payload.get("code") else None),
        iiko_supplier_inn=(str(payload["inn"]).strip() if payload.get("inn") else None),
        iiko_supplier_deleted=False,
        status=IikoSupplierMappingStatus.CONFIRMED,
        created_by_user_id=actor_user_id,
        confirmed_at=now,
    )
    session.add(mapping)
    try:
        session.flush()
        if current is not None:
            current.superseded_by_id = mapping.id
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SupplierMappingError("Сопоставление уже изменено другим пользователем") from error
    session.refresh(mapping)
    return mapping


def current_reference_warning(
    session: Session,
    *,
    tenant_id: str,
    mapping: IikoSupplierMapping | None,
) -> str | None:
    if mapping is None:
        return None
    rows = [
        row for row in _latest_supplier_rows(session, tenant_id)
        if row.external_id == str(mapping.iiko_supplier_id)
    ]
    if not rows:
        return "Поставщик iiko отсутствует в актуальном снимке"
    if bool(rows[0].payload.get("deleted", False)) or not rows[0].is_active:
        return "Связанный поставщик удалён или неактивен в iiko"
    return None
