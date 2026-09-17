import os
import unittest
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.integrations.iiko.schemas import IikoSupplierDto
from app.integrations.iiko.service import sync_reference_snapshot
from app.main import app
from app.models.iiko import (
    IikoRawEntity,
    IikoSupplierMapping,
    IikoSupplierMappingStatus,
    IikoSyncRun,
)
from app.models.supply import SupplySupplier
from app.models.user import User


class _ReferenceProvider:
    async def get_organizations(self): return []
    async def get_warehouses(self): return []
    async def get_product_groups(self): return []
    async def get_product_categories(self): return []
    async def get_products(self): return []
    async def get_units(self): return []
    async def get_packages(self): return []

    async def get_suppliers(self):
        return [
            IikoSupplierDto(
                external_id=str(SUPPLIER_EXTERNAL_ID),
                name="ООО Альфа",
                code="ALPHA",
                is_supplier=True,
            ),
            IikoSupplierDto(
                external_id=str(DELETED_EXTERNAL_ID),
                name="Удалённый",
                is_supplier=True,
                is_deleted=True,
            ),
        ]


SUPPLIER_EXTERNAL_ID = uuid4()
SECOND_EXTERNAL_ID = uuid4()
DELETED_EXTERNAL_ID = uuid4()


class IikoSupplierReferenceSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        User.__table__.create(self.engine)
        IikoSyncRun.__table__.create(self.engine)
        IikoRawEntity.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    async def test_reference_sync_preserves_supplier_fields_and_is_idempotent(self) -> None:
        with self.sessions() as session:
            first = await sync_reference_snapshot(
                session, _ReferenceProvider(), tenant_id="tenant-a",
                requested_by=None, source_api_type="test",
            )
            second = await sync_reference_snapshot(
                session, _ReferenceProvider(), tenant_id="tenant-a",
                requested_by=None, source_api_type="test",
            )
            rows = list(session.scalars(select(IikoRawEntity).where(
                IikoRawEntity.entity_type == "supplier",
            )))
        self.assertEqual(first.records_created, 2)
        self.assertEqual(second.records_unchanged, 2)
        self.assertEqual(len(rows), 2)
        active = next(row for row in rows if row.external_id == str(SUPPLIER_EXTERNAL_ID))
        deleted = next(row for row in rows if row.external_id == str(DELETED_EXTERNAL_ID))
        self.assertEqual(active.payload["name"], "ООО Альфа")
        self.assertEqual(active.payload["code"], "ALPHA")
        self.assertTrue(active.is_active)
        self.assertTrue(deleted.payload["deleted"])
        self.assertFalse(deleted.is_active)


class IikoSupplierMappingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        self.engine = create_engine(
            "sqlite://", poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        for table in (
            User.__table__, SupplySupplier.__table__, IikoSyncRun.__table__,
            IikoRawEntity.__table__, IikoSupplierMapping.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            session.add_all([
                User(
                    id=1, username="admin-a", display_name="Admin A",
                    hashed_password="unused", is_active=True, is_admin=True,
                    tenant_id="tenant-a",
                ),
                User(
                    id=2, username="admin-b", display_name="Admin B",
                    hashed_password="unused", is_active=True, is_admin=True,
                    tenant_id="tenant-b",
                ),
            ])
            supplier = SupplySupplier(
                tenant_id="tenant-a", display_name="Альфа EOS", inn="1234567890",
            )
            other = SupplySupplier(tenant_id="tenant-a", display_name="Бета EOS")
            foreign = SupplySupplier(tenant_id="tenant-b", display_name="Чужой")
            session.add_all([supplier, other, foreign])
            session.flush()
            self.supplier_id = supplier.id
            self.other_supplier_id = other.id
            self.foreign_supplier_id = foreign.id
            for tenant, external_id, name, deleted, inn in (
                ("tenant-a", SUPPLIER_EXTERNAL_ID, "ООО Альфа", False, "1234567890"),
                ("tenant-a", SECOND_EXTERNAL_ID, "ООО Бета", False, None),
                ("tenant-a", DELETED_EXTERNAL_ID, "Удалённый", True, None),
                ("tenant-b", uuid4(), "Чужой iiko", False, None),
            ):
                run = IikoSyncRun(
                    tenant_id=tenant, sync_type="FULL_REFERENCE_SNAPSHOT",
                    status="SUCCEEDED", source_api_type="test",
                )
                session.add(run)
                session.flush()
                session.add(IikoRawEntity(
                    tenant_id=tenant, sync_run_id=run.id,
                    entity_type="supplier", external_id=str(external_id),
                    payload={
                        "id": str(external_id), "name": name, "code": "CODE",
                        "inn": inn, "supplier": True, "employee": False,
                        "representsStore": False, "deleted": deleted,
                    },
                    payload_hash=uuid4().hex, is_active=not deleted,
                ))

        def override_db():
            with self.sessions() as session:
                yield session

        def override_admin():
            with self.sessions() as session:
                return session.get(User, 1)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_admin] = override_admin
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_create_readiness_remap_and_history(self) -> None:
        empty = self.client.get(f"/supply/suppliers/{self.supplier_id}/iiko-mapping")
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.json()["iiko_receipt_ready_supplier_mapping"])

        listing = self.client.get(
            "/supply/iiko/suppliers",
            params={"supplier_id": str(self.supplier_id), "search": "Альфа"},
        )
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(listing.json()["items"][0]["exact_inn_match"])

        created = self.client.post(
            f"/supply/suppliers/{self.supplier_id}/iiko-mapping",
            json={"iiko_supplier_id": str(SUPPLIER_EXTERNAL_ID)},
        )
        self.assertEqual(created.status_code, 200)
        self.assertTrue(created.json()["iiko_receipt_ready_supplier_mapping"])

        remapped = self.client.post(
            f"/supply/suppliers/{self.supplier_id}/iiko-mapping",
            json={"iiko_supplier_id": str(SECOND_EXTERNAL_ID)},
        )
        self.assertEqual(remapped.status_code, 200)
        self.assertEqual(len(remapped.json()["history"]), 2)
        self.assertEqual(remapped.json()["history"][1]["status"], "ARCHIVED")
        self.assertEqual(
            remapped.json()["history"][1]["superseded_by_id"],
            remapped.json()["mapping"]["id"],
        )

    def test_duplicate_external_deleted_and_cross_tenant_are_rejected(self) -> None:
        first = self.client.post(
            f"/supply/suppliers/{self.supplier_id}/iiko-mapping",
            json={"iiko_supplier_id": str(SUPPLIER_EXTERNAL_ID)},
        )
        self.assertEqual(first.status_code, 200)
        duplicate = self.client.post(
            f"/supply/suppliers/{self.other_supplier_id}/iiko-mapping",
            json={"iiko_supplier_id": str(SUPPLIER_EXTERNAL_ID)},
        )
        self.assertEqual(duplicate.status_code, 409)
        deleted = self.client.post(
            f"/supply/suppliers/{self.other_supplier_id}/iiko-mapping",
            json={"iiko_supplier_id": str(DELETED_EXTERNAL_ID)},
        )
        self.assertEqual(deleted.status_code, 409)
        cross_tenant = self.client.get(
            f"/supply/suppliers/{self.foreign_supplier_id}/iiko-mapping"
        )
        self.assertEqual(cross_tenant.status_code, 404)

    def test_archived_mapping_is_not_ready(self) -> None:
        created = self.client.post(
            f"/supply/suppliers/{self.supplier_id}/iiko-mapping",
            json={"iiko_supplier_id": str(SUPPLIER_EXTERNAL_ID)},
        )
        from uuid import UUID
        mapping_id = UUID(created.json()["mapping"]["id"])
        with self.sessions.begin() as session:
            mapping = session.get(IikoSupplierMapping, mapping_id)
            mapping.status = IikoSupplierMappingStatus.ARCHIVED
            from datetime import datetime, timezone
            mapping.archived_at = datetime.now(timezone.utc)
        state = self.client.get(f"/supply/suppliers/{self.supplier_id}/iiko-mapping")
        self.assertFalse(state.json()["iiko_receipt_ready_supplier_mapping"])
        self.assertIsNone(state.json()["mapping"])
