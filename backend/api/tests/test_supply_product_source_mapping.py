import os
import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.iiko import (
    IikoMappingStatus,
    IikoProductMapping,
    IikoWarehouseDestinationType,
    IikoWarehouseMapping,
    IikoWarehouseRole,
)
from app.models.supply import (
    Department,
    LegalContour,
    SupplyProduct,
    SupplyProductSourceMapping,
    SupplyProductSourceMappingAuditEvent,
    SupplyProductSourceRole,
    SupplyRequest,
    SupplyRequestDirection,
    SupplyRequestLine,
    SupplyUnit,
)
from app.models.user import User
from app.supply.source_mapping import (
    SupplyProductSourceConcurrentAssignmentError,
    SupplyProductSourceNotAllowedError,
    SupplyProductSourceProductNotEligibleError,
    SupplyProductSourceReplacementCommentRequiredError,
    SupplyProductSourceResolutionBlockedError,
    assign_product_source,
    bootstrap_product_source_mappings,
    get_product_source_preview,
    product_source_role,
    resolve_supply_request_sources,
)


class SupplyProductSourceMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        for table in (
            User.__table__,
            SupplyUnit.__table__,
            Department.__table__,
            SupplyRequestDirection.__table__,
            SupplyProduct.__table__,
            IikoProductMapping.__table__,
            IikoWarehouseMapping.__table__,
            SupplyProductSourceMapping.__table__,
            SupplyProductSourceMappingAuditEvent.__table__,
            SupplyRequest.__table__,
            SupplyRequestLine.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            session.add(User(
                id=1,
                username="supply",
                display_name="Снабжение",
                hashed_password="unused",
                is_active=True,
                is_admin=True,
            ))
            self.unit = SupplyUnit(
                tenant_id="tenant-a",
                code="KG",
                name_ru="Килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            )
            self.department = Department(
                tenant_id="tenant-a",
                code="M15",
                name="М15",
                legal_contour=LegalContour.IP,
            )
            self.direction = SupplyRequestDirection(
                tenant_id="tenant-a", code="MAIN", name="Продукты"
            )
            session.add_all([self.unit, self.department, self.direction])
            session.flush()

    def tearDown(self) -> None:
        self.engine.dispose()

    def _product(self, session, name: str, source_name: str) -> SupplyProduct:
        product = SupplyProduct(
            tenant_id="tenant-a",
            name=name,
            normalized_name=name.casefold(),
            default_unit_id=self.unit.id,
        )
        session.add(product)
        session.flush()
        session.add(IikoProductMapping(
            tenant_id="tenant-a",
            iiko_product_id=uuid4(),
            eos_product_id=product.id,
            status=IikoMappingStatus.CONFIRMED,
            source_name=source_name,
        ))
        session.flush()
        return product

    def _source(
        self,
        session,
        role: IikoWarehouseRole,
        contour: LegalContour = LegalContour.IP,
        name: str = "SOURCE",
    ) -> IikoWarehouseMapping:
        source = IikoWarehouseMapping(
            tenant_id="tenant-a",
            iiko_warehouse_id=uuid4(),
            destination_type=IikoWarehouseDestinationType.SOURCE,
            role=role,
            legal_contour=contour,
            status=IikoMappingStatus.CONFIRMED,
            source_name=name,
        )
        session.add(source)
        session.flush()
        return source

    def _request_with_products(
        self,
        session,
        products: list[SupplyProduct | None],
        *,
        legacy_source_id=None,
    ) -> SupplyRequest:
        request = SupplyRequest(
            tenant_id="tenant-a",
            public_number=f"REQ-{uuid4()}",
            department_id=self.department.id,
            direction_id=self.direction.id,
            iiko_source_warehouse_mapping_id=legacy_source_id,
            status="IN_REVIEW",
            source_type="INTERNAL",
            raw_input="Тестовая заявка",
        )
        session.add(request)
        session.flush()
        for position, product in enumerate(products, start=1):
            session.add(SupplyRequestLine(
                tenant_id="tenant-a",
                request_id=request.id,
                position=position,
                raw_text=f"Строка {position}",
                parsed_name=product.name if product else None,
                product_id=product.id if product else None,
                requested_unit_id=self.unit.id if product else None,
                quantity=Decimal("1") if product else None,
                match_status="MATCHED" if product else "NEEDS_REVIEW",
                match_method="MANUAL" if product else None,
            ))
        session.flush()
        return request

    def test_exact_product_prefix_recognition(self) -> None:
        self.assertEqual(product_source_role("т Молоко"), SupplyProductSourceRole.MAIN)
        self.assertEqual(
            product_source_role("ту Стакан"), SupplyProductSourceRole.PACKAGING
        )
        self.assertEqual(
            product_source_role("тх Перчатки"), SupplyProductSourceRole.HOUSEHOLD
        )
        self.assertIsNone(product_source_role("туалетная бумага"))
        self.assertIsNone(product_source_role("тхимия"))
        self.assertIsNone(product_source_role("ту\tСтакан"))

    def test_bootstrap_creates_mapping_for_single_confirmed_source(self) -> None:
        with self.sessions.begin() as session:
            product = self._product(session, "Молоко", "т Молоко")
            source = self._source(session, IikoWarehouseRole.MAIN)
        with self.sessions() as session:
            result = bootstrap_product_source_mappings(
                session, tenant_id="tenant-a", actor_user_id=1
            )
            mapping = session.scalar(select(SupplyProductSourceMapping).where(
                SupplyProductSourceMapping.eos_product_id == product.id
            ))
            self.assertEqual(result.created, 1)
            self.assertEqual(mapping.source_warehouse_mapping_id, source.id)
            self.assertEqual(mapping.role, SupplyProductSourceRole.MAIN)
            self.assertEqual(
                session.scalar(select(func.count(
                    SupplyProductSourceMappingAuditEvent.id
                ))),
                1,
            )

    def test_bootstrap_refuses_zero_or_multiple_sources(self) -> None:
        with self.sessions.begin() as session:
            self._product(session, "Стакан", "ту Стакан")
            self._product(session, "Молоко", "т Молоко")
            self._source(session, IikoWarehouseRole.MAIN, name="SOURCE 1")
            self._source(session, IikoWarehouseRole.MAIN, name="SOURCE 2")
        with self.sessions() as session:
            result = bootstrap_product_source_mappings(
                session, tenant_id="tenant-a", actor_user_id=1
            )
            self.assertEqual(result.created, 0)
            self.assertGreaterEqual(result.missing_source, 1)
            self.assertGreaterEqual(result.ambiguous_source, 1)
            self.assertEqual(
                session.scalar(select(func.count(SupplyProductSourceMapping.id))),
                0,
            )

    def test_replacement_requires_comment_and_appends_audit(self) -> None:
        with self.sessions.begin() as session:
            product = self._product(session, "Молоко", "т Молоко")
            first = self._source(session, IikoWarehouseRole.MAIN, name="SOURCE 1")
            second = self._source(session, IikoWarehouseRole.MAIN, name="SOURCE 2")
        with self.sessions() as session:
            assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=product.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=first.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            with self.assertRaises(
                SupplyProductSourceReplacementCommentRequiredError
            ):
                assign_product_source(
                    session,
                    tenant_id="tenant-a",
                    product_id=product.id,
                    legal_contour=LegalContour.IP,
                    source_mapping_id=second.id,
                    actor_user_id=1,
                    expected_version=1,
                    comment="  ",
                )
            assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=product.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=second.id,
                actor_user_id=1,
                expected_version=1,
                comment="Переносим постоянный маршрут",
            )
            events = session.scalars(
                select(SupplyProductSourceMappingAuditEvent).order_by(
                    SupplyProductSourceMappingAuditEvent.id
                )
            ).all()
            self.assertEqual([event.action for event in events], [
                "ASSIGNED", "REPLACED",
            ])
            self.assertEqual(events[-1].comment, "Переносим постоянный маршрут")

    def test_resolver_is_blocked_until_every_line_has_source(self) -> None:
        with self.sessions.begin() as session:
            milk = self._product(session, "Молоко", "т Молоко")
            cup = self._product(session, "Стакан", "ту Стакан")
            main = self._source(session, IikoWarehouseRole.MAIN, name="Продукты")
            packaging = self._source(
                session, IikoWarehouseRole.PACKAGING, name="Упаковка"
            )
            request = SupplyRequest(
                tenant_id="tenant-a",
                public_number="REQ-1",
                department_id=self.department.id,
                direction_id=self.direction.id,
                status="IN_REVIEW",
                source_type="INTERNAL",
                raw_input="Молоко; Стакан",
            )
            session.add(request)
            session.flush()
            session.add_all([
                SupplyRequestLine(
                    tenant_id="tenant-a",
                    request_id=request.id,
                    position=1,
                    raw_text="Молоко 1 кг",
                    parsed_name="Молоко",
                    product_id=milk.id,
                    requested_unit_id=self.unit.id,
                    quantity=Decimal("1"),
                    match_status="MATCHED",
                    match_method="MANUAL",
                ),
                SupplyRequestLine(
                    tenant_id="tenant-a",
                    request_id=request.id,
                    position=2,
                    raw_text="Стакан 1 кг",
                    parsed_name="Стакан",
                    product_id=cup.id,
                    requested_unit_id=self.unit.id,
                    quantity=Decimal("1"),
                    match_status="MATCHED",
                    match_method="MANUAL",
                ),
            ])
            request_id = request.id
        with self.sessions() as session:
            assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=milk.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=main.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            with self.assertRaises(SupplyProductSourceResolutionBlockedError):
                resolve_supply_request_sources(
                    session, tenant_id="tenant-a", request_id=request_id
                )
            assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=cup.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=packaging.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            preview = resolve_supply_request_sources(
                session, tenant_id="tenant-a", request_id=request_id
            )
            self.assertTrue(preview.ready_for_shipment)
            self.assertEqual(preview.assigned_products, 2)
            self.assertEqual(len(preview.groups), 2)

    def test_resolver_blocks_line_without_product_id(self) -> None:
        with self.sessions.begin() as session:
            request = self._request_with_products(session, [None])
            request_id = request.id
        with self.sessions() as session:
            with self.assertRaises(SupplyProductSourceResolutionBlockedError):
                resolve_supply_request_sources(
                    session, tenant_id="tenant-a", request_id=request_id
                )
            preview = get_product_source_preview(
                session, tenant_id="tenant-a", request_id=request_id
            )
            self.assertEqual(preview.total_products, 0)
            self.assertIn("Не сопоставлены строки заявки: 1", preview.blocking_reasons)

    def test_resolver_blocks_without_confirmed_iiko_product_mapping(self) -> None:
        with self.sessions.begin() as session:
            product = SupplyProduct(
                tenant_id="tenant-a",
                name="Без iiko",
                normalized_name="без iiko",
                default_unit_id=self.unit.id,
            )
            session.add(product)
            session.flush()
            source = self._source(session, IikoWarehouseRole.MAIN)
            request = self._request_with_products(session, [product])
            request_id = request.id
        with self.sessions() as session:
            preview = get_product_source_preview(
                session, tenant_id="tenant-a", request_id=request_id
            )
            self.assertFalse(preview.ready_for_shipment)
            self.assertEqual(
                preview.products[0].blocking_reason,
                "Нет подтверждённого IikoProductMapping",
            )
            with self.assertRaises(SupplyProductSourceResolutionBlockedError):
                resolve_supply_request_sources(
                    session, tenant_id="tenant-a", request_id=request_id
                )
            with self.assertRaises(SupplyProductSourceProductNotEligibleError):
                assign_product_source(
                    session,
                    tenant_id="tenant-a",
                    product_id=product.id,
                    legal_contour=LegalContour.IP,
                    source_mapping_id=source.id,
                    actor_user_id=1,
                    expected_version=None,
                    comment=None,
                )

    def test_disabled_source_makes_product_unresolved(self) -> None:
        with self.sessions.begin() as session:
            product = self._product(session, "Молоко", "т Молоко")
            source = self._source(session, IikoWarehouseRole.MAIN)
            request = self._request_with_products(session, [product])
            request_id = request.id
        with self.sessions() as session:
            assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=product.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=source.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            persisted_source = session.get(IikoWarehouseMapping, source.id)
            persisted_source.is_deleted = True
            session.commit()
            preview = get_product_source_preview(
                session, tenant_id="tenant-a", request_id=request_id
            )
            self.assertFalse(preview.ready_for_shipment)
            self.assertIsNone(preview.products[0].assigned_source)
            self.assertEqual(preview.products[0].mapping_version, 1)
            second_product = self._product(session, "Сыр", "т Сыр")
            with self.assertRaises(SupplyProductSourceNotAllowedError):
                assign_product_source(
                    session,
                    tenant_id="tenant-a",
                    product_id=second_product.id,
                    legal_contour=LegalContour.IP,
                    source_mapping_id=source.id,
                    actor_user_id=1,
                    expected_version=None,
                    comment=None,
                )

    def test_repeated_product_has_one_mapping_problem_and_multiple_lines(self) -> None:
        with self.sessions.begin() as session:
            product = self._product(session, "Молоко", "т Молоко")
            source = self._source(session, IikoWarehouseRole.MAIN)
            request = self._request_with_products(session, [product, product])
            request_id = request.id
        with self.sessions() as session:
            blocked = get_product_source_preview(
                session, tenant_id="tenant-a", request_id=request_id
            )
            self.assertEqual(blocked.total_products, 1)
            self.assertEqual(len(blocked.products), 1)
            self.assertIn("Не назначен SOURCE для товаров: 1", blocked.blocking_reasons)
            assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=product.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=source.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            resolved = resolve_supply_request_sources(
                session, tenant_id="tenant-a", request_id=request_id
            )
            self.assertEqual(resolved.assigned_products, 1)
            self.assertEqual(len(resolved.groups), 1)
            self.assertEqual(len(resolved.groups[0].lines), 2)

    def test_resolver_ignores_legacy_request_source_fk(self) -> None:
        with self.sessions.begin() as session:
            product = self._product(session, "Молоко", "т Молоко")
            legacy_source = self._source(
                session, IikoWarehouseRole.MAIN, name="Legacy 4A"
            )
            product_source = self._source(
                session, IikoWarehouseRole.MAIN, name="Товарный SOURCE"
            )
            request = self._request_with_products(
                session, [product], legacy_source_id=legacy_source.id
            )
            request_id = request.id
        with self.sessions() as session:
            assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=product.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=product_source.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            preview = resolve_supply_request_sources(
                session, tenant_id="tenant-a", request_id=request_id
            )
            self.assertEqual(
                preview.groups[0].source.mapping_id,
                product_source.id,
            )
            self.assertNotEqual(
                preview.groups[0].source.mapping_id,
                legacy_source.id,
            )

    def test_concurrent_first_assignment_unique_conflict_is_safe(self) -> None:
        with self.sessions.begin() as session:
            product = self._product(session, "Молоко", "т Молоко")
            source = self._source(session, IikoWarehouseRole.MAIN)
        with self.sessions() as session:
            original_flush = session.flush
            conflict_raised = False

            def racing_flush(*args, **kwargs):
                nonlocal conflict_raised
                has_new_mapping = any(
                    isinstance(item, SupplyProductSourceMapping)
                    for item in session.new
                )
                if has_new_mapping and not conflict_raised:
                    conflict_raised = True
                    raise IntegrityError(
                        "INSERT",
                        {},
                        Exception(
                            "UNIQUE constraint failed: "
                            "supply_product_source_mappings.tenant_id"
                        ),
                    )
                return original_flush(*args, **kwargs)

            with patch.object(session, "flush", side_effect=racing_flush):
                with self.assertRaises(
                    SupplyProductSourceConcurrentAssignmentError
                ):
                    assign_product_source(
                        session,
                        tenant_id="tenant-a",
                        product_id=product.id,
                        legal_contour=LegalContour.IP,
                        source_mapping_id=source.id,
                        actor_user_id=1,
                        expected_version=None,
                        comment=None,
                    )
            self.assertEqual(
                session.scalar(select(func.count(SupplyProductSourceMapping.id))),
                0,
            )
            self.assertEqual(
                session.scalar(select(func.count(
                    SupplyProductSourceMappingAuditEvent.id
                ))),
                0,
            )

    def test_stale_replacement_expected_version_is_rejected(self) -> None:
        with self.sessions.begin() as session:
            product = self._product(session, "Молоко", "т Молоко")
            first = self._source(session, IikoWarehouseRole.MAIN, name="SOURCE 1")
            second = self._source(session, IikoWarehouseRole.MAIN, name="SOURCE 2")
        with self.sessions() as session:
            assigned = assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=product.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=first.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            replaced = assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=product.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=second.id,
                actor_user_id=1,
                expected_version=assigned.version,
                comment="Меняем маршрут",
            )
            self.assertEqual(replaced.version, 2)
        previous_tenant_id = settings.default_tenant_id
        settings.default_tenant_id = "tenant-a"

        def override_db():
            with self.sessions() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_admin] = lambda: User(
            id=1,
            username="supply",
            display_name="Снабжение",
            hashed_password="unused",
            is_active=True,
            is_admin=True,
        )
        try:
            with TestClient(app) as client:
                response = client.put(
                    f"/supply/products/{product.id}/source-mapping",
                    json={
                        "legal_contour": "IP",
                        "source_mapping_id": str(first.id),
                        "expected_version": 1,
                        "comment": "Устаревшая замена",
                    },
                )
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(response.json()["detail"], {
                "code": "VERSION_CONFLICT",
                "current_version": 2,
                "expected_version": 1,
            })
        finally:
            app.dependency_overrides.clear()
            settings.default_tenant_id = previous_tenant_id
        with self.sessions() as session:
            mapping = session.scalar(select(SupplyProductSourceMapping))
            self.assertEqual(mapping.source_warehouse_mapping_id, second.id)
            self.assertEqual(mapping.version, 2)
            self.assertEqual(
                session.scalar(select(func.count(
                    SupplyProductSourceMappingAuditEvent.id
                ))),
                2,
            )

    def test_bootstrap_unique_conflict_continues_remaining_items(self) -> None:
        with self.sessions.begin() as session:
            self._product(session, "Молоко", "т Молоко")
            self._product(session, "Сыр", "т Сыр")
            manual = self._product(session, "Масло", "т Масло")
            ip_source = self._source(
                session, IikoWarehouseRole.MAIN, LegalContour.IP, "IP SOURCE"
            )
            self._source(
                session, IikoWarehouseRole.MAIN, LegalContour.OOO, "OOO SOURCE"
            )
        with self.sessions() as session:
            manual_mapping = assign_product_source(
                session,
                tenant_id="tenant-a",
                product_id=manual.id,
                legal_contour=LegalContour.IP,
                source_mapping_id=ip_source.id,
                actor_user_id=1,
                expected_version=None,
                comment=None,
            )
            original_flush = session.flush
            conflict_raised = False

            def racing_flush(*args, **kwargs):
                nonlocal conflict_raised
                pending_bootstrap = any(
                    isinstance(item, SupplyProductSourceMapping)
                    and item.eos_product_id != manual.id
                    for item in session.new
                )
                if pending_bootstrap and not conflict_raised:
                    conflict_raised = True
                    raise IntegrityError(
                        "INSERT",
                        {},
                        Exception(
                            "UNIQUE constraint failed: "
                            "supply_product_source_mappings.tenant_id"
                        ),
                    )
                return original_flush(*args, **kwargs)

            with patch.object(session, "flush", side_effect=racing_flush):
                result = bootstrap_product_source_mappings(
                    session, tenant_id="tenant-a", actor_user_id=1
                )
            self.assertEqual(result.conflicts, 1)
            self.assertEqual(result.already_mapped, 1)
            self.assertEqual(result.created, 4)
            persisted_manual = session.get(
                SupplyProductSourceMapping, manual_mapping.id
            )
            self.assertEqual(
                persisted_manual.source_warehouse_mapping_id,
                ip_source.id,
            )
            self.assertEqual(persisted_manual.version, 1)
            self.assertEqual(
                session.scalar(select(func.count(SupplyProductSourceMapping.id))),
                5,
            )
            self.assertEqual(
                session.scalar(select(func.count(
                    SupplyProductSourceMappingAuditEvent.id
                ))),
                5,
            )
