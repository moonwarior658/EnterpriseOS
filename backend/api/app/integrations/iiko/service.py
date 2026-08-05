from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.integrations.iiko.exceptions import IikoContractError, IikoError
from app.integrations.iiko.provider import IikoProvider
from app.integrations.iiko.schemas import IikoRecord
from app.models.iiko import (
    IikoMappingStatus,
    IikoRawEntity,
    IikoStockBalanceSnapshotLine,
    IikoStockBalanceSnapshotSource,
    IikoStockBalanceSnapshotSourceStatus,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
)
from app.models.supply import Department


FORBIDDEN_PAYLOAD_KEYS = {
    "password",
    "pass",
    "token",
    "access_token",
    "apikey",
    "api_key",
    "clientsecret",
    "client_secret",
}


class IikoStockSnapshotScopeError(ValueError):
    pass


@dataclass(frozen=True)
class _StockSnapshotLineValue:
    iiko_warehouse_id: UUID
    iiko_product_id: UUID
    iiko_unit_id: UUID
    quantity: Decimal


@dataclass(frozen=True)
class _StockSnapshotSourceResult:
    source_mapping_id: UUID
    iiko_warehouse_id: UUID
    status: IikoStockBalanceSnapshotSourceStatus
    lines: tuple[_StockSnapshotLineValue, ...]
    records_received: int
    error_code: str | None = None
    error_message: str | None = None


def safe_error_message(error: Exception) -> str:
    if isinstance(error, IikoError):
        return error.code
    return "IIKO_INTERNAL_ERROR"


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_payload(item)
            for key, item in value.items()
            if key.lower() not in FORBIDDEN_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_sync_run(
    session: Session,
    *,
    tenant_id: str,
    sync_type: IikoSyncType,
    requested_by: int | None,
    source_api_type: str,
    source_organization_id: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> IikoSyncRun:
    run = IikoSyncRun(
        tenant_id=tenant_id,
        sync_type=sync_type,
        status=IikoSyncStatus.RUNNING,
        requested_by=requested_by,
        source_api_type=source_api_type,
        source_organization_id=source_organization_id,
        parameters=sanitize_payload(parameters or {}),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


async def sync_warehouses(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    requested_by: int | None,
    source_api_type: str,
) -> IikoSyncRun:
    run = create_sync_run(
        session,
        tenant_id=tenant_id,
        sync_type=IikoSyncType.WAREHOUSES,
        requested_by=requested_by,
        source_api_type=source_api_type,
        parameters={"scope": "full", "include_deleted": True},
    )
    try:
        records = await provider.get_warehouses()
        stage_records(session, run, records)
        run.status = IikoSyncStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(run)
        return run
    except Exception as error:
        session.rollback()
        run = session.get(IikoSyncRun, run.id)
        if run is not None:
            run.status = IikoSyncStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.records_failed += 1
            run.error_code = safe_error_message(error)
            run.error_message = "Склады iiko не сохранены"
            session.commit()
        raise


async def sync_stock_balances(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    requested_by: int | None,
    source_api_type: str,
    balance_date: date,
    warehouse_external_ids: Sequence[str],
    product_external_ids: Sequence[str] | None = None,
    include_zero: bool = True,
    include_deleted: bool = True,
) -> IikoSyncRun:
    warehouse_ids = list(dict.fromkeys(warehouse_external_ids))
    product_ids = (
        list(dict.fromkeys(product_external_ids))
        if product_external_ids
        else None
    )
    run = create_sync_run(
        session,
        tenant_id=tenant_id,
        sync_type=IikoSyncType.STOCK_BALANCES,
        requested_by=requested_by,
        source_api_type=source_api_type,
        parameters={
            "balance_date": balance_date.isoformat(),
            "warehouse_external_ids": warehouse_ids,
            "product_external_ids": product_ids,
            "include_zero": include_zero,
            "include_deleted": include_deleted,
            "scope": "partial",
        },
    )
    try:
        records = await provider.get_stock_balances(
            balance_date=balance_date,
            warehouse_external_ids=warehouse_ids,
            product_external_ids=product_ids,
            include_zero=include_zero,
            include_deleted=include_deleted,
        )
        stage_records(session, run, records)
        run.status = IikoSyncStatus.SUCCEEDED
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(run)
        return run
    except Exception as error:
        session.rollback()
        run = session.get(IikoSyncRun, run.id)
        if run is not None:
            run.status = IikoSyncStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.records_failed += 1
            run.error_code = safe_error_message(error)
            run.error_message = "Остатки iiko не сохранены"
            session.commit()
        raise


async def sync_stock_balance_snapshot(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    requested_by: int | None,
    source_api_type: str,
    snapshot_at: datetime,
    department_id: UUID,
    source_warehouse_mapping_ids: Sequence[UUID],
) -> IikoSyncRun:
    started_at = datetime.now(timezone.utc)
    if snapshot_at.tzinfo is None or snapshot_at.utcoffset() is None:
        raise IikoStockSnapshotScopeError("SNAPSHOT_TIMEZONE_REQUIRED")
    source_ids = list(source_warehouse_mapping_ids)
    if not source_ids:
        raise IikoStockSnapshotScopeError("SOURCE_REQUIRED")
    if len(source_ids) != len(set(source_ids)):
        raise IikoStockSnapshotScopeError("SOURCE_DUPLICATE")
    department = session.scalar(select(Department).where(
        Department.id == department_id,
        Department.tenant_id == tenant_id,
        Department.is_active.is_(True),
    ))
    if department is None:
        raise IikoStockSnapshotScopeError("DEPARTMENT_NOT_FOUND")
    sources = list(session.scalars(select(IikoWarehouseMapping).where(
        IikoWarehouseMapping.id.in_(source_ids),
        IikoWarehouseMapping.tenant_id == tenant_id,
        IikoWarehouseMapping.destination_type
        == IikoWarehouseDestinationType.SOURCE,
        IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
        IikoWarehouseMapping.is_deleted.is_(False),
    )))
    sources_by_id = {source.id: source for source in sources}
    if set(sources_by_id) != set(source_ids):
        raise IikoStockSnapshotScopeError("SOURCE_NOT_FOUND_OR_NOT_CONFIRMED")
    if department.legal_contour is None or any(
        source.legal_contour != department.legal_contour
        for source in sources
    ):
        raise IikoStockSnapshotScopeError("SOURCE_LEGAL_CONTOUR_MISMATCH")

    source_scopes = [
        (source_id, sources_by_id[source_id].iiko_warehouse_id)
        for source_id in source_ids
    ]
    source_results: list[_StockSnapshotSourceResult] = []
    first_error: Exception | None = None
    for source_id, iiko_warehouse_id in source_scopes:
        try:
            records = await provider.get_stock_balances(
                snapshot_at=snapshot_at,
                warehouse_external_ids=[str(iiko_warehouse_id)],
                include_zero=True,
                include_deleted=False,
            )
            lines: list[_StockSnapshotLineValue] = []
            seen_products: set[UUID] = set()
            for record in records:
                dto = record.dto
                try:
                    warehouse_id = UUID(dto.warehouse_external_id)
                    product_id = UUID(dto.product_external_id)
                    unit_id = (
                        UUID(dto.unit_external_id)
                        if dto.unit_external_id else None
                    )
                except (TypeError, ValueError) as error:
                    raise IikoContractError(
                        "Invalid stock snapshot UUID"
                    ) from error
                if warehouse_id != iiko_warehouse_id or unit_id is None:
                    raise IikoContractError(
                        "IIKO_STOCK_SNAPSHOT_ROW_INVALID"
                    )
                decimal_places = max(-dto.quantity.as_tuple().exponent, 0)
                if decimal_places > 6:
                    raise IikoContractError(
                        "IIKO_STOCK_SNAPSHOT_QUANTITY_SCALE_INVALID"
                    )
                if product_id in seen_products:
                    raise IikoContractError(
                        "IIKO_STOCK_SNAPSHOT_PRODUCT_DUPLICATE"
                    )
                seen_products.add(product_id)
                lines.append(_StockSnapshotLineValue(
                    iiko_warehouse_id=warehouse_id,
                    iiko_product_id=product_id,
                    iiko_unit_id=unit_id,
                    quantity=dto.quantity,
                ))
            source_results.append(_StockSnapshotSourceResult(
                source_mapping_id=source_id,
                iiko_warehouse_id=iiko_warehouse_id,
                status=IikoStockBalanceSnapshotSourceStatus.SUCCEEDED,
                lines=tuple(lines),
                records_received=len(records),
            ))
        except Exception as error:
            first_error = first_error or error
            source_results.append(_StockSnapshotSourceResult(
                source_mapping_id=source_id,
                iiko_warehouse_id=iiko_warehouse_id,
                status=IikoStockBalanceSnapshotSourceStatus.FAILED,
                lines=(),
                records_received=0,
                error_code=safe_error_message(error),
                error_message="Остатки SOURCE не получены или невалидны",
            ))

    completed = [
        str(result.source_mapping_id) for result in source_results
        if result.status == IikoStockBalanceSnapshotSourceStatus.SUCCEEDED
    ]
    failed = [
        str(result.source_mapping_id) for result in source_results
        if result.status == IikoStockBalanceSnapshotSourceStatus.FAILED
    ]
    if failed and completed:
        run_status = IikoSyncStatus.PARTIALLY_SUCCEEDED
    elif failed:
        run_status = IikoSyncStatus.FAILED
    else:
        run_status = IikoSyncStatus.SUCCEEDED
    finished_at = datetime.now(timezone.utc)
    run = IikoSyncRun(
        tenant_id=tenant_id,
        sync_type=IikoSyncType.STOCK_BALANCE_SNAPSHOT,
        status=run_status,
        started_at=started_at,
        finished_at=finished_at,
        requested_by=requested_by,
        source_api_type=source_api_type,
        parameters={
            "snapshot_at": snapshot_at.isoformat(),
            "department_id": str(department_id),
            "source_warehouse_mapping_ids": [str(value) for value in source_ids],
            "completed_source_warehouse_mapping_ids": completed,
            "failed_source_warehouse_mapping_ids": failed,
            "scope": "explicit_sources",
        },
        records_received=sum(
            result.records_received for result in source_results
        ),
        records_created=sum(len(result.lines) for result in source_results),
        records_failed=len(failed),
        error_code=(safe_error_message(first_error) if first_error else None),
        error_message=(
            "Остатки сохранены не для всех SOURCE" if first_error else None
        ),
    )
    session.rollback()
    try:
        with session.begin():
            session.add(run)
            session.flush()
            for result in source_results:
                session.add(IikoStockBalanceSnapshotSource(
                    tenant_id=tenant_id,
                    sync_run_id=run.id,
                    department_id=department_id,
                    source_warehouse_mapping_id=result.source_mapping_id,
                    snapshot_at=snapshot_at,
                    status=result.status,
                    error_code=result.error_code,
                    error_message=result.error_message,
                ))
                if result.status == IikoStockBalanceSnapshotSourceStatus.SUCCEEDED:
                    session.add_all([
                        IikoStockBalanceSnapshotLine(
                            tenant_id=tenant_id,
                            sync_run_id=run.id,
                            department_id=department_id,
                            source_warehouse_mapping_id=result.source_mapping_id,
                            iiko_warehouse_id=line.iiko_warehouse_id,
                            iiko_product_id=line.iiko_product_id,
                            iiko_unit_id=line.iiko_unit_id,
                            quantity=line.quantity,
                            snapshot_at=snapshot_at,
                        )
                        for line in result.lines
                    ])
            session.flush()
    except Exception:
        session.rollback()
        raise
    session.refresh(run)
    return run


async def test_connection(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    requested_by: int | None,
    source_api_type: str,
) -> IikoSyncRun:
    run = create_sync_run(
        session,
        tenant_id=tenant_id,
        sync_type=IikoSyncType.CONNECTION_CHECK,
        requested_by=requested_by,
        source_api_type=source_api_type,
    )
    try:
        await provider.check_connection()
    except Exception as error:
        session.rollback()
        run = session.get(IikoSyncRun, run.id)
        if run is None:
            raise
        run.status = IikoSyncStatus.FAILED
        run.finished_at = datetime.now(timezone.utc)
        run.records_failed = 1
        run.error_code = safe_error_message(error)
        run.error_message = "Проверка подключения iiko не выполнена"
        session.commit()
        raise
    run.status = IikoSyncStatus.SUCCEEDED
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(run)
    return run


def stage_records(
    session: Session,
    run: IikoSyncRun,
    records: list[IikoRecord[Any]],
) -> None:
    seen: set[tuple[str, str]] = set()
    entity_types = {record.entity_type for record in records}
    existing_rows = session.execute(
        select(
            IikoRawEntity.entity_type,
            IikoRawEntity.external_id,
            IikoRawEntity.payload_hash,
        ).where(
            IikoRawEntity.tenant_id == run.tenant_id,
            IikoRawEntity.entity_type.in_(entity_types),
        )
    ).all()
    existing_versions = {
        (entity_type, external_id, digest)
        for entity_type, external_id, digest in existing_rows
    }
    existing_identities = {
        (entity_type, external_id)
        for entity_type, external_id, _ in existing_rows
    }
    for record in records:
        identity = (record.entity_type, record.external_id)
        if identity in seen:
            raise ValueError("Duplicate iiko entity in one snapshot")
        seen.add(identity)
        payload = sanitize_payload(record.raw_payload)
        digest = payload_hash(payload)
        run.records_received += 1
        if (
            record.entity_type,
            record.external_id,
            digest,
        ) in existing_versions:
            run.records_unchanged += 1
            continue
        identity_exists = identity in existing_identities
        session.add(
            IikoRawEntity(
                tenant_id=run.tenant_id,
                sync_run_id=run.id,
                entity_type=record.entity_type,
                external_id=record.external_id,
                parent_external_id=record.parent_external_id,
                organization_external_id=record.organization_external_id,
                payload=payload,
                payload_hash=digest,
                source_updated_at=record.source_updated_at,
                is_active=record.is_active,
            )
        )
        if identity_exists:
            run.records_updated += 1
        else:
            run.records_created += 1
        existing_versions.add(
            (record.entity_type, record.external_id, digest)
        )
        existing_identities.add(identity)


async def sync_reference_snapshot(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    requested_by: int | None,
    source_api_type: str,
    source_organization_id: str | None = None,
) -> IikoSyncRun:
    run = create_sync_run(
        session,
        tenant_id=tenant_id,
        sync_type=IikoSyncType.FULL_REFERENCE_SNAPSHOT,
        requested_by=requested_by,
        source_api_type=source_api_type,
        source_organization_id=source_organization_id,
    )
    readers: list[
        tuple[str, Callable[[], Awaitable[list[IikoRecord[Any]]]]]
    ] = [
        ("organizations", provider.get_organizations),
        ("warehouses", provider.get_warehouses),
        ("product_groups", provider.get_product_groups),
        ("product_categories", provider.get_product_categories),
        ("products", provider.get_products),
        ("units", provider.get_units),
        ("packages", provider.get_packages),
    ]
    errors: list[tuple[str, Exception]] = []
    try:
        for name, reader in readers:
            try:
                records = await reader()
                stage_records(session, run, records)
                session.commit()
                run = session.get(IikoSyncRun, run.id)
                if run is None:
                    raise RuntimeError("iiko sync run disappeared")
            except Exception as error:
                session.rollback()
                run = session.get(IikoSyncRun, run.id)
                if run is None:
                    raise
                errors.append((name, error))
                run.records_failed += 1
                session.commit()
                run = session.get(IikoSyncRun, run.id)
                if run is None:
                    raise RuntimeError("iiko sync run disappeared")
        run.finished_at = datetime.now(timezone.utc)
        if errors and run.records_received:
            run.status = IikoSyncStatus.PARTIALLY_SUCCEEDED
        elif errors:
            run.status = IikoSyncStatus.FAILED
        else:
            run.status = IikoSyncStatus.SUCCEEDED
        if errors:
            run.error_code = safe_error_message(errors[0][1])
            run.error_message = (
                "Часть справочников iiko недоступна текущим правам"
                if run.records_received
                else "Справочники iiko не получены"
            )
        session.commit()
        session.refresh(run)
        return run
    except Exception as error:
        session.rollback()
        run = session.get(IikoSyncRun, run.id)
        if run is not None:
            run.status = IikoSyncStatus.FAILED
            run.finished_at = datetime.now(timezone.utc)
            run.records_failed += 1
            run.error_code = safe_error_message(error)
            run.error_message = "Снимок iiko не сохранён"
            session.commit()
        raise


def list_sync_runs(
    session: Session,
    *,
    tenant_id: str,
    limit: int,
    offset: int,
) -> list[IikoSyncRun]:
    return list(
        session.scalars(
            select(IikoSyncRun)
            .where(IikoSyncRun.tenant_id == tenant_id)
            .order_by(desc(IikoSyncRun.started_at), desc(IikoSyncRun.id))
            .limit(limit)
            .offset(offset)
        )
    )


def get_sync_run(
    session: Session,
    *,
    tenant_id: str,
    run_id: UUID,
) -> IikoSyncRun | None:
    return session.scalar(
        select(IikoSyncRun).where(
            IikoSyncRun.id == run_id,
            IikoSyncRun.tenant_id == tenant_id,
        )
    )


def latest_run(
    session: Session,
    *,
    tenant_id: str,
    sync_type: IikoSyncType | None = None,
    statuses: set[IikoSyncStatus] | None = None,
) -> IikoSyncRun | None:
    statement = select(IikoSyncRun).where(
        IikoSyncRun.tenant_id == tenant_id
    )
    if sync_type is not None:
        statement = statement.where(IikoSyncRun.sync_type == sync_type)
    if statuses:
        statement = statement.where(IikoSyncRun.status.in_(statuses))
    return session.scalar(
        statement.order_by(
            desc(IikoSyncRun.started_at),
            desc(IikoSyncRun.id),
        ).limit(1)
    )
