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
    IikoWarehouseRole,
)
from app.models.supply import (
    Department,
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
                            "name": "Молочко",
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
            self.assertIn("Совпадает подтверждённый алиас", product.reasons)
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
            confirm_warehouse_mapping(
                session,
                tenant_id="tenant-a",
                mapping_id=mappings[0].id,
                eos_department_id=department.id,
                role=IikoWarehouseRole.MAIN,
                actor_user_id=1,
            )
            confirm_warehouse_mapping(
                session,
                tenant_id="tenant-a",
                mapping_id=mappings[1].id,
                eos_department_id=department.id,
                role=IikoWarehouseRole.PACKAGING,
                actor_user_id=1,
            )
            with self.assertRaises(MappingError):
                confirm_warehouse_mapping(
                    session,
                    tenant_id="tenant-a",
                    mapping_id=mappings[1].id,
                    eos_department_id=department.id,
                    role=IikoWarehouseRole.MAIN,
                    actor_user_id=1,
                    replace=True,
                )
