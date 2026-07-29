import os
import unittest
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_admin
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.iiko import (
    IikoMappingAuditEvent,
    IikoProductMapping,
    IikoRawEntity,
    IikoSyncRun,
    IikoSyncStatus,
    IikoSyncType,
    IikoUnitMapping,
    IikoWarehouseMapping,
    IikoMappingStatus,
    IikoWarehouseDestinationType,
)
from app.models.supply import (
    Department,
    LegalContour,
    SupplyProduct,
    SupplyProductAlias,
    SupplyUnit,
)
from app.models.user import User


class IikoMappingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
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
        self.external_id = uuid4()
        with self.sessions.begin() as session:
            admin = User(
                id=1,
                username="admin",
                display_name="Администратор",
                hashed_password="unused",
                is_active=True,
                is_admin=True,
            )
            unit = SupplyUnit(
                tenant_id="tenant-a",
                code="PCS",
                name_ru="Штука",
                short_name_ru="шт",
            )
            product = SupplyProduct(
                tenant_id="tenant-a",
                name="Салфетки",
                normalized_name="салфетки",
                default_unit=unit,
            )
            department = Department(
                tenant_id="tenant-a",
                code="M15",
                name="М15",
                legal_contour=LegalContour.IP,
            )
            run = IikoSyncRun(
                tenant_id="tenant-a",
                sync_type=IikoSyncType.FULL_REFERENCE_SNAPSHOT,
                status=IikoSyncStatus.SUCCEEDED,
                source_api_type="iiko_server",
            )
            session.add_all([admin, unit, product, department, run])
            session.flush()
            session.add(
                IikoRawEntity(
                    tenant_id="tenant-a",
                    sync_run_id=run.id,
                    entity_type="product",
                    external_id=str(self.external_id),
                    payload={
                        "id": str(self.external_id),
                        "name": "т Салфетки",
                        "deleted": False,
                    },
                    payload_hash=uuid4().hex,
                    is_active=True,
                )
            )
            warehouse_mapping = IikoWarehouseMapping(
                tenant_id="tenant-a",
                iiko_warehouse_id=uuid4(),
                source_name="Центральный продуктовый склад",
                destination_type=IikoWarehouseDestinationType.DESTINATION,
                status=IikoMappingStatus.UNMAPPED,
                reasons=[],
            )
            session.add(warehouse_mapping)
            session.flush()
            self.product_id = product.id
            self.warehouse_mapping_id = warehouse_mapping.id

        def override_db():
            with self.sessions() as session:
                yield session

        def override_admin():
            with self.sessions() as session:
                return session.get(User, 1)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_admin] = override_admin
        self.previous_tenant = settings.default_tenant_id
        settings.default_tenant_id = "tenant-a"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        settings.default_tenant_id = self.previous_tenant
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_admin_can_generate_filter_confirm_ignore_unmap_and_read_audit(
        self,
    ) -> None:
        generation_id = uuid4()
        generated = self.client.post(
            "/integrations/iiko/mappings/generate",
            headers={"X-EOS-Generation-ID": str(generation_id)},
        )
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()["products_created"], 1)
        generation_status = self.client.get(
            "/integrations/iiko/mappings/generate/status",
            params={"generation_id": str(generation_id)},
        )
        self.assertEqual(generation_status.status_code, 200)
        self.assertEqual(generation_status.json()["status"], "SUCCEEDED")
        self.assertEqual(
            generation_status.json()["result"]["products_created"],
            1,
        )

        listing = self.client.get(
            "/integrations/iiko/mappings/products",
            params={"status": "SUGGESTED", "search": "Салф"},
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["total"], 1)
        mapping_id = listing.json()["items"][0]["id"]

        confirmed = self.client.post(
            f"/integrations/iiko/mappings/products/{mapping_id}/confirm",
            json={"eos_product_id": str(self.product_id)},
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["status"], "CONFIRMED")

        ignored = self.client.post(
            f"/integrations/iiko/mappings/products/{mapping_id}/ignore"
        )
        self.assertEqual(ignored.status_code, 200)
        self.assertEqual(ignored.json()["status"], "IGNORED")

        unmapped = self.client.post(
            f"/integrations/iiko/mappings/products/{mapping_id}/unmap"
        )
        self.assertEqual(unmapped.status_code, 200)
        self.assertEqual(unmapped.json()["status"], "UNMAPPED")

        audit = self.client.get(
            "/integrations/iiko/mappings/audit",
            params={"mapping_id": mapping_id},
        )
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.json()["total"], 4)

    def test_deleted_and_conflict_filters_are_available(self) -> None:
        self.client.post("/integrations/iiko/mappings/generate")
        default_queue = self.client.get(
            "/integrations/iiko/mappings/products"
        )
        self.assertEqual(default_queue.json()["total"], 1)
        conflicts = self.client.get(
            "/integrations/iiko/mappings/products",
            params={"conflicts_only": True, "include_deleted": True},
        )
        self.assertEqual(conflicts.status_code, 200)
        self.assertEqual(conflicts.json()["total"], 0)

    def test_non_admin_is_forbidden(self) -> None:
        def forbidden():
            raise HTTPException(status_code=403, detail="forbidden")

        app.dependency_overrides[get_current_admin] = forbidden
        response = self.client.get("/integrations/iiko/mappings/products")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_confirm_source_without_department(self) -> None:
        confirmed = self.client.post(
            "/integrations/iiko/mappings/warehouses/"
            f"{self.warehouse_mapping_id}/confirm",
            json={
                "destination_type": "SOURCE",
                "legal_contour": "IP",
                "role": "MAIN",
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        body = confirmed.json()
        self.assertEqual(body["destination_type"], "SOURCE")
        self.assertEqual(body["legal_contour"], "IP")
        self.assertEqual(body["role"], "MAIN")
        self.assertIsNone(body["eos_department_id"])

        invalid = self.client.post(
            "/integrations/iiko/mappings/warehouses/"
            f"{self.warehouse_mapping_id}/replace",
            json={
                "destination_type": "SOURCE",
            },
        )
        self.assertEqual(invalid.status_code, 422)
