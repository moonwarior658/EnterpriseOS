import os
import unittest
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.integrations.iiko.mapping_service import (
    MappingError,
    bootstrap_product_catalog,
    confirm_product_mapping,
    confirm_warehouse_mapping,
    generate_mapping_candidates,
    set_mapping_ignored,
    unmap_mapping,
)
from app.models.iiko import (
    IikoMappingAuditEvent,
    IikoMappingStatus,
    IikoProductMapping,
    IikoRawEntity,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
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
from app.models.user import User


class IikoMappingServiceTests(unittest.TestCase):
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
            SupplyProduct.__table__,
            SupplyProductAlias.__table__,
            IikoSyncRun.__table__,
            IikoRawEntity.__table__,
            IikoProductMapping.__table__,
            IikoUnitMapping.__table__,
            IikoWarehouseMapping.__table__,
            IikoMappingAuditEvent.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.product_external_id = uuid4()
        self.unit_external_id = uuid4()
        self.warehouse_external_id = uuid4()
        with self.sessions.begin() as session:
            session.add(
                User(
                    id=1,
                    username="admin",
                    display_name="Администратор",
                    hashed_password="unused",
                    is_active=True,
                    is_admin=True,
                )
            )
            unit = SupplyUnit(
                tenant_id="tenant-a",
                code="KG",
                name_ru="Килограмм",
                short_name_ru="кг",
                allows_fraction=True,
            )
            department = Department(
                tenant_id="tenant-a",
                code="M15",
                name="М15",
                legal_contour=LegalContour.IP,
            )
            product = SupplyProduct(
                tenant_id="tenant-a",
                name="Молоко",
                normalized_name="молоко",
                default_unit=unit,
            )
            session.add_all([unit, department, product])
            session.flush()
            session.add(
                SupplyProductAlias(
                    tenant_id="tenant-a",
                    product_id=product.id,
                    alias="Молочко",
                    normalized_alias="молочко",
                    status="APPROVED",
                )
            )
            run = IikoSyncRun(
                tenant_id="tenant-a",
                sync_type=IikoSyncType.FULL_REFERENCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
            )
            session.add(run)
            session.flush()
            session.add_all(
                [
                    self.raw(
                        run,
                        "product",
                        self.product_external_id,
                        {
                            "id": str(self.product_external_id),
                            "name": "т Молочко",
                            "code": "MILK",
                            "num": "100",
                            "mainUnit": str(self.unit_external_id),
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "unit",
                        self.unit_external_id,
                        {
                            "id": str(self.unit_external_id),
                            "name": "Килограмм",
                            "code": "кг",
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "warehouse",
                        self.warehouse_external_id,
                        {
                            "id": str(self.warehouse_external_id),
                            "name": "М15 Основной склад",
                            "code": "M15",
                            "deleted": False,
                        },
                    ),
                ]
            )

    @staticmethod
    def raw(run, entity_type, external_id, payload):
        return IikoRawEntity(
            tenant_id=run.tenant_id,
            sync_run_id=run.id,
            entity_type=entity_type,
            external_id=str(external_id),
            payload=payload,
            payload_hash=uuid4().hex,
            is_active=not payload.get("deleted", False),
        )

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_generation_is_idempotent_and_uses_alias_code_and_unit(self) -> None:
        with self.sessions() as session:
            first = generate_mapping_candidates(session, tenant_id="tenant-a")
            second = generate_mapping_candidates(session, tenant_id="tenant-a")
            self.assertEqual(first.products_created, 1)
            self.assertEqual(first.units_created, 1)
            self.assertEqual(first.warehouses_created, 1)
            self.assertEqual(second.products_created, 0)
            self.assertEqual(second.products_updated, 0)
            self.assertEqual(
                session.scalar(select(func.count(IikoProductMapping.id))),
                1,
            )
            product = session.scalar(select(IikoProductMapping))
            unit = session.scalar(select(IikoUnitMapping))
            warehouse = session.scalar(select(IikoWarehouseMapping))
            self.assertEqual(product.status, IikoMappingStatus.SUGGESTED)
            self.assertEqual(product.source_name, "т Молочко")
            self.assertIn("Совпадает подтверждённый алиас", product.reasons)
            self.assertIn("Тип iiko: PRODUCT", product.reasons)
            self.assertEqual(unit.status, IikoMappingStatus.SUGGESTED)
            self.assertEqual(warehouse.status, IikoMappingStatus.SUGGESTED)
            self.assertEqual(warehouse.role, IikoWarehouseRole.MAIN)
            self.assertEqual(
                session.scalar(select(func.count(IikoMappingAuditEvent.id))),
                3,
            )

    def test_confirmed_mapping_survives_new_snapshot_and_deleted_source(self) -> None:
        with self.sessions() as session:
            generate_mapping_candidates(session, tenant_id="tenant-a")
            mapping = session.scalar(select(IikoProductMapping))
            product = session.scalar(select(SupplyProduct))
            confirm_product_mapping(
                session,
                tenant_id="tenant-a",
                mapping_id=mapping.id,
                eos_product_id=product.id,
                actor_user_id=1,
            )
            run = IikoSyncRun(
                tenant_id="tenant-a",
                sync_type=IikoSyncType.PRODUCTS,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
            )
            session.add(run)
            session.flush()
            session.add(
                self.raw(
                    run,
                    "product",
                    self.product_external_id,
                    {
                        "id": str(self.product_external_id),
                        "name": "Новое название",
                        "deleted": True,
                    },
                )
            )
            session.commit()
            generate_mapping_candidates(session, tenant_id="tenant-a")
            session.refresh(mapping)
            self.assertEqual(mapping.status, IikoMappingStatus.CONFIRMED)
            self.assertEqual(mapping.eos_product_id, product.id)
            self.assertTrue(mapping.is_deleted)

    def test_ignored_mapping_survives_source_without_prefix(self) -> None:
        with self.sessions() as session:
            generate_mapping_candidates(session, tenant_id="tenant-a")
            mapping = session.scalar(select(IikoProductMapping))
            set_mapping_ignored(
                session,
                IikoProductMapping,
                tenant_id="tenant-a",
                mapping_id=mapping.id,
                actor_user_id=1,
            )
            run = IikoSyncRun(
                tenant_id="tenant-a",
                sync_type=IikoSyncType.PRODUCTS,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
            )
            session.add(run)
            session.flush()
            session.add(
                self.raw(
                    run,
                    "product",
                    self.product_external_id,
                    {
                        "id": str(self.product_external_id),
                        "name": "Название без префикса",
                        "deleted": False,
                    },
                )
            )
            session.commit()
            generate_mapping_candidates(session, tenant_id="tenant-a")
            session.refresh(mapping)
            self.assertEqual(mapping.status, IikoMappingStatus.IGNORED)
            self.assertEqual(mapping.source_name, "Название без префикса")

    def test_product_prefixes_and_exclusions(self) -> None:
        packaging_id = uuid4()
        household_id = uuid4()
        excluded_ids = [uuid4() for _ in range(4)]
        with self.sessions.begin() as session:
            run = session.scalar(select(IikoSyncRun))
            session.add_all(
                [
                    self.raw(
                        run,
                        "product",
                        packaging_id,
                        {
                            "id": str(packaging_id),
                            "name": "ТУ Коробка",
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "product",
                        household_id,
                        {
                            "id": str(household_id),
                            "name": "тХ Чистящее средство",
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "product",
                        excluded_ids[0],
                        {
                            "id": str(excluded_ids[0]),
                            "name": "- Скрытая позиция",
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "product",
                        excluded_ids[1],
                        {
                            "id": str(excluded_ids[1]),
                            "name": "Без префикса",
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "product",
                        excluded_ids[2],
                        {
                            "id": str(excluded_ids[2]),
                            "name": "т Неактивная позиция",
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "product",
                        excluded_ids[3],
                        {
                            "id": str(excluded_ids[3]),
                            "name": "т Удалённая позиция",
                            "deleted": True,
                        },
                    ),
                ]
            )
            inactive = session.scalar(
                select(IikoRawEntity).where(
                    IikoRawEntity.external_id == str(excluded_ids[2])
                )
            )
            inactive.is_active = False
        with self.sessions() as session:
            result = generate_mapping_candidates(
                session,
                tenant_id="tenant-a",
            )
            self.assertEqual(result.products_created, 3)
            mappings = {
                mapping.iiko_product_id: mapping
                for mapping in session.scalars(
                    select(IikoProductMapping)
                ).all()
            }
            self.assertEqual(
                mappings[packaging_id].source_name,
                "ТУ Коробка",
            )
            self.assertIn(
                "Тип iiko: PACKAGING",
                mappings[packaging_id].reasons,
            )
            self.assertEqual(
                mappings[household_id].source_name,
                "тХ Чистящее средство",
            )
            self.assertIn(
                "Тип iiko: HOUSEHOLD",
                mappings[household_id].reasons,
            )
            for excluded_id in excluded_ids:
                self.assertNotIn(excluded_id, mappings)

    def test_catalog_bootstrap_creates_links_and_is_idempotent(self) -> None:
        packaging_id = uuid4()
        ignored_id = uuid4()
        deleted_id = uuid4()
        with self.sessions.begin() as session:
            unit = session.scalar(select(SupplyUnit))
            run = session.scalar(select(IikoSyncRun))
            session.add(
                IikoUnitMapping(
                    tenant_id="tenant-a",
                    iiko_unit_id=self.unit_external_id,
                    eos_unit_id=unit.id,
                    source_name="Килограмм",
                    status=IikoMappingStatus.CONFIRMED,
                    reasons=["Подтверждено администратором"],
                )
            )
            session.add_all(
                [
                    self.raw(
                    run,
                    "product",
                    packaging_id,
                    {
                        "id": str(packaging_id),
                        "name": "ТУ Коробка",
                        "mainUnit": str(self.unit_external_id),
                        "deleted": False,
                    },
                    ),
                    self.raw(
                        run,
                        "product",
                        ignored_id,
                        {
                            "id": str(ignored_id),
                            "name": "т Игнорируемый товар",
                            "mainUnit": str(self.unit_external_id),
                            "deleted": False,
                        },
                    ),
                    self.raw(
                        run,
                        "product",
                        deleted_id,
                        {
                            "id": str(deleted_id),
                            "name": "т Удалённый товар",
                            "mainUnit": str(self.unit_external_id),
                            "deleted": True,
                        },
                    ),
                    IikoProductMapping(
                        tenant_id="tenant-a",
                        iiko_product_id=ignored_id,
                        source_name="т Игнорируемый товар",
                        status=IikoMappingStatus.IGNORED,
                        reasons=["Игнорировано администратором"],
                    ),
                ]
            )

        with self.sessions() as session:
            first = bootstrap_product_catalog(
                session,
                tenant_id="tenant-a",
                actor_user_id=1,
            )
            self.assertEqual(first.created, 1)
            self.assertEqual(first.linked, 1)
            self.assertEqual(first.existing, 1)
            self.assertEqual(first.conflicts, 0)
            self.assertEqual(first.skipped, 2)
            product = session.scalar(
                select(SupplyProduct).where(
                    SupplyProduct.normalized_name == "коробка"
                )
            )
            self.assertEqual(product.name, "Коробка")
            self.assertEqual(product.iiko_id, str(packaging_id))
            mappings = {
                mapping.iiko_product_id: mapping
                for mapping in session.scalars(
                    select(IikoProductMapping)
                ).all()
            }
            self.assertEqual(
                mappings[packaging_id].status,
                IikoMappingStatus.CONFIRMED,
            )
            self.assertIn(
                "Тип iiko: PACKAGING",
                mappings[packaging_id].reasons,
            )
            self.assertEqual(
                mappings[self.product_external_id].status,
                IikoMappingStatus.SUGGESTED,
            )
            self.assertEqual(
                mappings[ignored_id].status,
                IikoMappingStatus.IGNORED,
            )

            second = bootstrap_product_catalog(
                session,
                tenant_id="tenant-a",
                actor_user_id=1,
            )
            self.assertEqual(second.created, 0)
            self.assertEqual(second.linked, 0)
            self.assertEqual(second.existing, 2)
            self.assertEqual(second.conflicts, 0)
            self.assertEqual(second.skipped, 2)

    def test_catalog_bootstrap_conflicts_on_different_unit(self) -> None:
        other_unit_external_id = uuid4()
        other_product_external_id = uuid4()
        with self.sessions.begin() as session:
            unit = session.scalar(select(SupplyUnit))
            other_unit = SupplyUnit(
                tenant_id="tenant-a",
                code="PCS",
                name_ru="Штука",
                short_name_ru="шт",
            )
            session.add(other_unit)
            session.flush()
            session.add_all(
                [
                    IikoUnitMapping(
                        tenant_id="tenant-a",
                        iiko_unit_id=self.unit_external_id,
                        eos_unit_id=unit.id,
                        source_name="Килограмм",
                        status=IikoMappingStatus.CONFIRMED,
                        reasons=["Подтверждено администратором"],
                    ),
                    IikoUnitMapping(
                        tenant_id="tenant-a",
                        iiko_unit_id=other_unit_external_id,
                        eos_unit_id=other_unit.id,
                        source_name="Штука",
                        status=IikoMappingStatus.CONFIRMED,
                        reasons=["Подтверждено администратором"],
                    ),
                ]
            )
            run = session.scalar(select(IikoSyncRun))
            session.add(
                self.raw(
                    run,
                    "product",
                    other_product_external_id,
                    {
                        "id": str(other_product_external_id),
                        "name": "т Молоко",
                        "mainUnit": str(other_unit_external_id),
                        "deleted": False,
                    },
                )
            )

        with self.sessions() as session:
            result = bootstrap_product_catalog(
                session,
                tenant_id="tenant-a",
                actor_user_id=1,
            )
            self.assertEqual(result.created, 0)
            self.assertEqual(result.conflicts, 1)
            mapping = session.scalar(
                select(IikoProductMapping).where(
                    IikoProductMapping.iiko_product_id
                    == other_product_external_id
                )
            )
            self.assertEqual(mapping.status, IikoMappingStatus.CONFLICT)
            self.assertIn("единица товара отличается", mapping.reasons[0])

    def test_candidate_for_already_confirmed_target_becomes_conflict(self) -> None:
        other_external_id = uuid4()
        with self.sessions.begin() as session:
            product = session.scalar(select(SupplyProduct))
            session.add(
                IikoProductMapping(
                    tenant_id="tenant-a",
                    iiko_product_id=other_external_id,
                    eos_product_id=product.id,
                    source_name="Старый товар iiko",
                    status=IikoMappingStatus.CONFIRMED,
                    reasons=["Подтверждено администратором"],
                )
            )
        with self.sessions() as session:
            generate_mapping_candidates(session, tenant_id="tenant-a")
            mapping = session.scalar(
                select(IikoProductMapping).where(
                    IikoProductMapping.iiko_product_id
                    == self.product_external_id
                )
            )
            self.assertEqual(mapping.status, IikoMappingStatus.CONFLICT)

    def test_tenant_isolation_and_history_preserved_on_ignore_and_unmap(self) -> None:
        with self.sessions() as session:
            generate_mapping_candidates(session, tenant_id="tenant-a")
            mapping = session.scalar(select(IikoProductMapping))
            with self.assertRaises(MappingError):
                set_mapping_ignored(
                    session,
                    IikoProductMapping,
                    tenant_id="tenant-b",
                    mapping_id=mapping.id,
                    actor_user_id=1,
                )
            set_mapping_ignored(
                session,
                IikoProductMapping,
                tenant_id="tenant-a",
                mapping_id=mapping.id,
                actor_user_id=1,
            )
            unmap_mapping(
                session,
                IikoProductMapping,
                tenant_id="tenant-a",
                mapping_id=mapping.id,
                actor_user_id=1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(IikoMappingAuditEvent.id)).where(
                        IikoMappingAuditEvent.mapping_id == mapping.id
                    )
                ),
                3,
            )
            self.assertIsNotNone(session.get(IikoProductMapping, mapping.id))

    def test_department_supports_multiple_roles_but_not_same_active_role(self) -> None:
        second_warehouse = uuid4()
        with self.sessions.begin() as session:
            run = session.scalar(select(IikoSyncRun))
            session.add(
                self.raw(
                    run,
                    "warehouse",
                    second_warehouse,
                    {
                        "id": str(second_warehouse),
                        "name": "М15 Упаковка",
                        "code": "M15",
                        "deleted": False,
                    },
                )
            )
        with self.sessions() as session:
            generate_mapping_candidates(session, tenant_id="tenant-a")
            mappings = session.scalars(
                select(IikoWarehouseMapping).order_by(
                    IikoWarehouseMapping.source_name
                )
            ).all()
            department = session.scalar(select(Department))
            first = confirm_warehouse_mapping(
                session,
                tenant_id="tenant-a",
                mapping_id=mappings[0].id,
                destination_type=IikoWarehouseDestinationType.DESTINATION,
                eos_department_id=department.id,
                role=IikoWarehouseRole.MAIN,
                legal_contour=None,
                actor_user_id=1,
            )
            audit = session.scalars(
                select(IikoMappingAuditEvent).where(
                    IikoMappingAuditEvent.mapping_id == first.id
                )
            ).all()
            self.assertEqual(audit[-1].after["legal_contour"], "IP")
            confirm_warehouse_mapping(
                session,
                tenant_id="tenant-a",
                mapping_id=mappings[1].id,
                destination_type=IikoWarehouseDestinationType.DESTINATION,
                eos_department_id=department.id,
                role=IikoWarehouseRole.PACKAGING,
                legal_contour=None,
                actor_user_id=1,
            )
            with self.assertRaises(MappingError):
                confirm_warehouse_mapping(
                    session,
                    tenant_id="tenant-a",
                    mapping_id=mappings[1].id,
                    destination_type=IikoWarehouseDestinationType.DESTINATION,
                    eos_department_id=department.id,
                    role=IikoWarehouseRole.MAIN,
                    legal_contour=None,
                    actor_user_id=1,
                    replace=True,
                )

    def test_sources_allow_multiple_per_contour_and_role_without_department(
        self,
    ) -> None:
        source_ids = [uuid4(), uuid4()]
        with self.sessions.begin() as session:
            session.add_all(
                [
                    IikoWarehouseMapping(
                        tenant_id="tenant-a",
                        iiko_warehouse_id=source_id,
                        source_name=f"Центральный склад {index}",
                        destination_type=IikoWarehouseDestinationType.DESTINATION,
                        status=IikoMappingStatus.UNMAPPED,
                        reasons=[],
                    )
                    for index, source_id in enumerate(source_ids, start=1)
                ]
            )
        with self.sessions() as session:
            mappings = session.scalars(
                select(IikoWarehouseMapping).where(
                    IikoWarehouseMapping.iiko_warehouse_id.in_(source_ids)
                )
            ).all()
            first = confirm_warehouse_mapping(
                session,
                tenant_id="tenant-a",
                mapping_id=mappings[0].id,
                destination_type=IikoWarehouseDestinationType.SOURCE,
                eos_department_id=None,
                role=IikoWarehouseRole.PACKAGING,
                legal_contour=LegalContour.IP,
                actor_user_id=1,
            )
            second = confirm_warehouse_mapping(
                session,
                tenant_id="tenant-a",
                mapping_id=mappings[1].id,
                destination_type=IikoWarehouseDestinationType.SOURCE,
                eos_department_id=None,
                role=IikoWarehouseRole.PACKAGING,
                legal_contour=LegalContour.IP,
                actor_user_id=1,
            )
            self.assertIsNone(first.eos_department_id)
            self.assertEqual(first.legal_contour, LegalContour.IP)
            self.assertEqual(second.legal_contour, LegalContour.IP)
            self.assertEqual(first.role, IikoWarehouseRole.PACKAGING)
            self.assertEqual(second.role, IikoWarehouseRole.PACKAGING)
            self.assertEqual(first.status, IikoMappingStatus.CONFIRMED)
            self.assertEqual(second.status, IikoMappingStatus.CONFIRMED)
            with self.assertRaises(MappingError):
                confirm_warehouse_mapping(
                    session,
                    tenant_id="tenant-b",
                    mapping_id=mappings[0].id,
                    destination_type=IikoWarehouseDestinationType.SOURCE,
                    eos_department_id=None,
                    role=IikoWarehouseRole.MAIN,
                    legal_contour=LegalContour.OOO,
                    actor_user_id=1,
                )
            audit = session.scalars(
                select(IikoMappingAuditEvent).where(
                    IikoMappingAuditEvent.mapping_id == first.id
                )
            ).all()
            self.assertEqual(audit[-1].after["destination_type"], "SOURCE")
            self.assertEqual(audit[-1].after["legal_contour"], "IP")
