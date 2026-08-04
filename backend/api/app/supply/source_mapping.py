from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.iiko import (
    IikoMappingStatus,
    IikoProductMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import (
    LegalContour,
    SupplyProduct,
    SupplyProductSourceAuditAction,
    SupplyProductSourceMapping,
    SupplyProductSourceMappingAuditEvent,
    SupplyProductSourceRole,
    SupplyRequest,
    SupplyRequestLine,
)
from app.schemas.supply import (
    SupplyProductSourceBootstrapRead,
    SupplyProductSourceGroupRead,
    SupplyProductSourceLineRead,
    SupplyProductSourceMappingRead,
    SupplyProductSourceOptionRead,
    SupplyProductSourcePreviewRead,
    SupplyProductSourceProductRead,
)


class SupplyProductSourceRequestNotFoundError(LookupError):
    pass


class SupplyProductSourceNotAllowedError(ValueError):
    pass


class SupplyProductSourceProductNotEligibleError(ValueError):
    pass


class SupplyProductSourceReplacementCommentRequiredError(ValueError):
    pass


class SupplyProductSourceVersionConflictError(ValueError):
    def __init__(
        self,
        current_version: int | None,
        expected_version: int | None,
    ):
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__("Supply product SOURCE mapping version conflict")


class SupplyProductSourceConcurrentAssignmentError(ValueError):
    pass


class SupplyProductSourceResolutionBlockedError(ValueError):
    def __init__(self, preview: SupplyProductSourcePreviewRead):
        self.preview = preview
        super().__init__("Supply request source resolution is incomplete")


PRODUCT_SOURCE_UNIQUE_CONSTRAINT = (
    "uq_supply_product_source_mapping_product_contour"
)


def _is_product_source_unique_conflict(error: IntegrityError) -> bool:
    constraint_name = getattr(
        getattr(error.orig, "diag", None), "constraint_name", None
    )
    if constraint_name is not None:
        return constraint_name == PRODUCT_SOURCE_UNIQUE_CONSTRAINT
    message = str(error.orig).casefold()
    return (
        "unique constraint failed" in message
        and "supply_product_source_mappings" in message
    )


@dataclass(frozen=True)
class _ProductRoute:
    product: SupplyProduct
    iiko_mapping: IikoProductMapping | None
    role: SupplyProductSourceRole | None
    mapping: SupplyProductSourceMapping | None
    source: IikoWarehouseMapping | None
    available_sources: list[IikoWarehouseMapping]


@dataclass
class _BootstrapCounts:
    created: int = 0
    already_mapped: int = 0
    conflicts: int = 0
    missing_source: int = 0
    ambiguous_source: int = 0
    unsupported_prefix: int = 0

    def add(self, other: "_BootstrapCounts") -> None:
        self.created += other.created
        self.already_mapped += other.already_mapped
        self.conflicts += other.conflicts
        self.missing_source += other.missing_source
        self.ambiguous_source += other.ambiguous_source
        self.unsupported_prefix += other.unsupported_prefix


def product_source_role(source_name: str) -> SupplyProductSourceRole | None:
    normalized = source_name.strip().casefold()
    for prefix, role in (
        ("тх ", SupplyProductSourceRole.HOUSEHOLD),
        ("ту ", SupplyProductSourceRole.PACKAGING),
        ("т ", SupplyProductSourceRole.MAIN),
    ):
        if normalized.startswith(prefix):
            return role
    return None


def _source_option(source: IikoWarehouseMapping) -> SupplyProductSourceOptionRead:
    return SupplyProductSourceOptionRead(
        mapping_id=source.id,
        iiko_warehouse_id=source.iiko_warehouse_id,
        name=source.source_name,
        role=SupplyProductSourceRole(source.role.value),
        legal_contour=source.legal_contour,
    )


def _valid_sources(
    session: Session,
    *,
    tenant_id: str,
    legal_contour: LegalContour,
    role: SupplyProductSourceRole,
) -> list[IikoWarehouseMapping]:
    return list(session.scalars(
        select(IikoWarehouseMapping)
        .where(
            IikoWarehouseMapping.tenant_id == tenant_id,
            IikoWarehouseMapping.destination_type
            == IikoWarehouseDestinationType.SOURCE,
            IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
            IikoWarehouseMapping.is_deleted.is_(False),
            IikoWarehouseMapping.legal_contour == legal_contour,
            IikoWarehouseMapping.role == IikoWarehouseRole(role.value),
        )
        .order_by(IikoWarehouseMapping.source_name, IikoWarehouseMapping.id)
    ).all())


def _confirmed_product_mapping(
    session: Session,
    *,
    tenant_id: str,
    product_id: UUID,
    for_update: bool = False,
) -> IikoProductMapping | None:
    statement = select(IikoProductMapping).where(
        IikoProductMapping.tenant_id == tenant_id,
        IikoProductMapping.eos_product_id == product_id,
        IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
        IikoProductMapping.is_deleted.is_(False),
    )
    if for_update:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    return session.scalar(statement)


def _locked_valid_source(
    session: Session,
    *,
    tenant_id: str,
    source_mapping_id: UUID,
    legal_contour: LegalContour,
    role: SupplyProductSourceRole,
) -> IikoWarehouseMapping | None:
    return session.scalar(
        select(IikoWarehouseMapping)
        .where(
            IikoWarehouseMapping.id == source_mapping_id,
            IikoWarehouseMapping.tenant_id == tenant_id,
            IikoWarehouseMapping.destination_type
            == IikoWarehouseDestinationType.SOURCE,
            IikoWarehouseMapping.status == IikoMappingStatus.CONFIRMED,
            IikoWarehouseMapping.is_deleted.is_(False),
            IikoWarehouseMapping.legal_contour == legal_contour,
            IikoWarehouseMapping.role == IikoWarehouseRole(role.value),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _bootstrap_product_source_mappings_for_product(
    session: Session,
    *,
    tenant_id: str,
    product_id: UUID,
    actor_user_id: int | None,
) -> _BootstrapCounts:
    counts = _BootstrapCounts()
    with session.begin():
        locked_product_mapping = _confirmed_product_mapping(
            session,
            tenant_id=tenant_id,
            product_id=product_id,
            for_update=True,
        )
        if locked_product_mapping is None:
            counts.conflicts += 1
            return counts
        role = product_source_role(locked_product_mapping.source_name)
        if role is None:
            counts.unsupported_prefix += 1
            return counts
        for contour in LegalContour:
            existing_mapping = session.scalar(
                select(SupplyProductSourceMapping)
                .where(
                    SupplyProductSourceMapping.tenant_id == tenant_id,
                    SupplyProductSourceMapping.eos_product_id == product_id,
                    SupplyProductSourceMapping.legal_contour == contour,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing_mapping is not None:
                counts.already_mapped += 1
                continue
            sources = _valid_sources(
                session,
                tenant_id=tenant_id,
                legal_contour=contour,
                role=role,
            )
            if not sources:
                counts.missing_source += 1
                continue
            if len(sources) != 1:
                counts.ambiguous_source += 1
                continue
            source = _locked_valid_source(
                session,
                tenant_id=tenant_id,
                source_mapping_id=sources[0].id,
                legal_contour=contour,
                role=role,
            )
            if source is None:
                counts.conflicts += 1
                continue
            try:
                with session.begin_nested():
                    mapping = SupplyProductSourceMapping(
                        tenant_id=tenant_id,
                        eos_product_id=product_id,
                        legal_contour=contour,
                        role=role,
                        source_warehouse_mapping_id=source.id,
                        assigned_by_user_id=actor_user_id,
                    )
                    session.add(mapping)
                    session.flush()
                    session.add(SupplyProductSourceMappingAuditEvent(
                        tenant_id=tenant_id,
                        mapping_id=mapping.id,
                        action=SupplyProductSourceAuditAction.BOOTSTRAPPED,
                        previous_source_warehouse_mapping_id=None,
                        source_warehouse_mapping_id=source.id,
                        actor_user_id=actor_user_id,
                        comment=None,
                    ))
                    session.flush()
            except IntegrityError as error:
                if not _is_product_source_unique_conflict(error):
                    raise
                counts.conflicts += 1
                continue
            counts.created += 1
    return counts


def bootstrap_product_source_mappings(
    session: Session, *, tenant_id: str, actor_user_id: int | None
) -> SupplyProductSourceBootstrapRead:
    product_ids = list(session.scalars(
        select(IikoProductMapping.eos_product_id)
        .join(SupplyProduct, SupplyProduct.id == IikoProductMapping.eos_product_id)
        .where(
            IikoProductMapping.tenant_id == tenant_id,
            IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
            IikoProductMapping.is_deleted.is_(False),
            IikoProductMapping.eos_product_id.is_not(None),
            SupplyProduct.tenant_id == tenant_id,
            SupplyProduct.is_active.is_(True),
        )
        .order_by(IikoProductMapping.eos_product_id)
    ).all())
    session.rollback()
    counts = _BootstrapCounts()
    for product_id in product_ids:
        try:
            item_counts = _bootstrap_product_source_mappings_for_product(
                session,
                tenant_id=tenant_id,
                product_id=product_id,
                actor_user_id=actor_user_id,
            )
        except SQLAlchemyError:
            session.rollback()
            counts.conflicts += 1
            continue
        counts.add(item_counts)
    return SupplyProductSourceBootstrapRead(
        created=counts.created,
        already_mapped=counts.already_mapped,
        conflicts=counts.conflicts,
        missing_source=counts.missing_source,
        ambiguous_source=counts.ambiguous_source,
        unsupported_prefix=counts.unsupported_prefix,
    )


def assign_product_source(
    session: Session,
    *,
    tenant_id: str,
    product_id: UUID,
    legal_contour: LegalContour,
    source_mapping_id: UUID,
    actor_user_id: int | None,
    expected_version: int | None,
    comment: str | None,
) -> SupplyProductSourceMappingRead:
    product = session.scalar(select(SupplyProduct).where(
        SupplyProduct.id == product_id,
        SupplyProduct.tenant_id == tenant_id,
        SupplyProduct.is_active.is_(True),
    ))
    product_mapping = _confirmed_product_mapping(
        session,
        tenant_id=tenant_id,
        product_id=product_id,
        for_update=True,
    )
    role = product_source_role(product_mapping.source_name) if product_mapping else None
    if product is None or product_mapping is None or role is None:
        raise SupplyProductSourceProductNotEligibleError
    mapping = session.scalar(
        select(SupplyProductSourceMapping)
        .where(
            SupplyProductSourceMapping.tenant_id == tenant_id,
            SupplyProductSourceMapping.eos_product_id == product_id,
            SupplyProductSourceMapping.legal_contour == legal_contour,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current_version = mapping.version if mapping is not None else None
    if mapping is None:
        if expected_version is not None:
            raise SupplyProductSourceVersionConflictError(
                current_version, expected_version
            )
    elif expected_version != mapping.version:
        raise SupplyProductSourceVersionConflictError(
            current_version, expected_version
        )
    source = _locked_valid_source(
        session,
        tenant_id=tenant_id,
        source_mapping_id=source_mapping_id,
        legal_contour=legal_contour,
        role=role,
    )
    if source is None:
        raise SupplyProductSourceNotAllowedError
    if mapping is not None and mapping.source_warehouse_mapping_id == source.id:
        return SupplyProductSourceMappingRead(
            id=mapping.id,
            product_id=product.id,
            product_name=product.name,
            legal_contour=legal_contour,
            role=role,
            source=_source_option(source),
            version=mapping.version,
            updated_at=mapping.updated_at,
        )
    normalized_comment = comment.strip() if comment else None
    if mapping is not None and not normalized_comment:
        raise SupplyProductSourceReplacementCommentRequiredError
    previous_source_id = mapping.source_warehouse_mapping_id if mapping else None
    action = (
        SupplyProductSourceAuditAction.REPLACED
        if mapping else SupplyProductSourceAuditAction.ASSIGNED
    )
    if mapping is None:
        try:
            with session.begin_nested():
                mapping = SupplyProductSourceMapping(
                    tenant_id=tenant_id,
                    eos_product_id=product_id,
                    legal_contour=legal_contour,
                    role=role,
                    source_warehouse_mapping_id=source.id,
                    assigned_by_user_id=actor_user_id,
                )
                session.add(mapping)
                session.flush()
                session.add(SupplyProductSourceMappingAuditEvent(
                    tenant_id=tenant_id,
                    mapping_id=mapping.id,
                    action=SupplyProductSourceAuditAction.ASSIGNED,
                    previous_source_warehouse_mapping_id=None,
                    source_warehouse_mapping_id=source.id,
                    actor_user_id=actor_user_id,
                    comment=None,
                ))
                session.flush()
        except IntegrityError as error:
            session.rollback()
            if not _is_product_source_unique_conflict(error):
                raise
            raise SupplyProductSourceConcurrentAssignmentError from error
    else:
        mapping.role = role
        mapping.source_warehouse_mapping_id = source.id
        mapping.assigned_by_user_id = actor_user_id
        mapping.version += 1
        session.add(SupplyProductSourceMappingAuditEvent(
            tenant_id=tenant_id,
            mapping_id=mapping.id,
            action=action,
            previous_source_warehouse_mapping_id=previous_source_id,
            source_warehouse_mapping_id=source.id,
            actor_user_id=actor_user_id,
            comment=normalized_comment,
        ))
    session.commit()
    session.refresh(mapping)
    return SupplyProductSourceMappingRead(
        id=mapping.id,
        product_id=product.id,
        product_name=product.name,
        legal_contour=legal_contour,
        role=role,
        source=_source_option(source),
        version=mapping.version,
        updated_at=mapping.updated_at,
    )


def _load_request(
    session: Session, *, tenant_id: str, request_id: UUID
) -> SupplyRequest:
    request = session.scalar(
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == tenant_id,
        )
        .options(
            joinedload(SupplyRequest.department),
            selectinload(SupplyRequest.lines).joinedload(SupplyRequestLine.product),
            selectinload(SupplyRequest.lines).joinedload(
                SupplyRequestLine.requested_unit
            ),
        )
    )
    if request is None:
        raise SupplyProductSourceRequestNotFoundError
    return request


def get_product_source_preview(
    session: Session, *, tenant_id: str, request_id: UUID
) -> SupplyProductSourcePreviewRead:
    request = _load_request(session, tenant_id=tenant_id, request_id=request_id)
    contour = request.department.legal_contour
    unique_products = {
        line.product_id: line.product
        for line in request.lines
        if line.product_id is not None and line.product is not None
    }
    product_ids = set(unique_products)
    iiko_mappings = {
        item.eos_product_id: item
        for item in session.scalars(select(IikoProductMapping).where(
            IikoProductMapping.tenant_id == tenant_id,
            IikoProductMapping.eos_product_id.in_(product_ids),
            IikoProductMapping.status == IikoMappingStatus.CONFIRMED,
            IikoProductMapping.is_deleted.is_(False),
        )).all()
    } if product_ids else {}
    stored_mappings = {
        item.eos_product_id: item
        for item in session.scalars(select(SupplyProductSourceMapping).where(
            SupplyProductSourceMapping.tenant_id == tenant_id,
            SupplyProductSourceMapping.eos_product_id.in_(product_ids),
            SupplyProductSourceMapping.legal_contour == contour,
        )).all()
    } if product_ids and contour is not None else {}
    source_ids = {item.source_warehouse_mapping_id for item in stored_mappings.values()}
    sources_by_id = {
        item.id: item
        for item in session.scalars(select(IikoWarehouseMapping).where(
            IikoWarehouseMapping.id.in_(source_ids)
        )).all()
    } if source_ids else {}

    routes: dict[UUID, _ProductRoute] = {}
    source_cache: dict[SupplyProductSourceRole, list[IikoWarehouseMapping]] = {}
    product_reads: list[SupplyProductSourceProductRead] = []
    assigned_products = 0
    blocking_reasons: list[str] = []
    if contour is None:
        blocking_reasons.append("У подразделения не указан legal contour")
    for product_id, product in sorted(unique_products.items(), key=lambda item: item[1].name):
        iiko_mapping = iiko_mappings.get(product_id)
        role = product_source_role(iiko_mapping.source_name) if iiko_mapping else None
        available = []
        if contour is not None and role is not None:
            if role not in source_cache:
                source_cache[role] = _valid_sources(
                    session,
                    tenant_id=tenant_id,
                    legal_contour=contour,
                    role=role,
                )
            available = source_cache[role]
        mapping = stored_mappings.get(product_id)
        source = sources_by_id.get(mapping.source_warehouse_mapping_id) if mapping else None
        valid_source_ids = {item.id for item in available}
        if source is None or source.id not in valid_source_ids or mapping.role != role:
            source = None
        if iiko_mapping is None:
            reason = "Нет подтверждённого IikoProductMapping"
        elif role is None:
            reason = "Исходный префикс iiko не определяет роль товара"
        elif source is None:
            reason = "SOURCE не назначен или больше не подтверждён"
        else:
            reason = None
            assigned_products += 1
        routes[product_id] = _ProductRoute(
            product=product,
            iiko_mapping=iiko_mapping,
            role=role,
            mapping=mapping,
            source=source,
            available_sources=available,
        )
        product_reads.append(SupplyProductSourceProductRead(
            product_id=product_id,
            product_name=product.name,
            role=role,
            iiko_mapping_confirmed=iiko_mapping is not None,
            assigned_source=_source_option(source) if source else None,
            mapping_version=mapping.version if mapping else None,
            available_sources=[_source_option(item) for item in available],
            blocking_reason=reason,
        ))

    unmatched_lines = [
        line for line in request.lines
        if line.match_status != "MATCHED" or line.product_id is None
    ]
    if unmatched_lines:
        blocking_reasons.append(
            f"Не сопоставлены строки заявки: {len(unmatched_lines)}"
        )
    unresolved_products = len(unique_products) - assigned_products
    if unresolved_products:
        blocking_reasons.append(
            f"Не назначен SOURCE для товаров: {unresolved_products}"
        )

    grouped_lines: dict[UUID, list[SupplyProductSourceLineRead]] = defaultdict(list)
    grouped_sources: dict[UUID, IikoWarehouseMapping] = {}
    for line in sorted(request.lines, key=lambda item: item.position):
        route = routes.get(line.product_id) if line.product_id else None
        if line.match_status != "MATCHED" or route is None or route.source is None:
            continue
        grouped_sources[route.source.id] = route.source
        grouped_lines[route.source.id].append(SupplyProductSourceLineRead(
            line_id=line.id,
            position=line.position,
            product_id=route.product.id,
            product_name=route.product.name,
            quantity=line.quantity,
            unit=line.requested_unit,
        ))
    groups = [
        SupplyProductSourceGroupRead(
            source=_source_option(grouped_sources[source_id]),
            lines=lines,
        )
        for source_id, lines in sorted(
            grouped_lines.items(), key=lambda item: grouped_sources[item[0]].source_name
        )
    ]
    return SupplyProductSourcePreviewRead(
        request_id=request.id,
        legal_contour=contour,
        assigned_products=assigned_products,
        total_products=len(unique_products),
        ready_for_shipment=not blocking_reasons,
        blocking_reasons=blocking_reasons,
        products=product_reads,
        groups=groups,
    )


def resolve_supply_request_sources(
    session: Session, *, tenant_id: str, request_id: UUID
) -> SupplyProductSourcePreviewRead:
    preview = get_product_source_preview(
        session, tenant_id=tenant_id, request_id=request_id
    )
    if not preview.ready_for_shipment:
        raise SupplyProductSourceResolutionBlockedError(preview)
    return preview
