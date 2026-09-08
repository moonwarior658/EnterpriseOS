import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.supply import SupplyProductSupplierPriceHistory
from app.models.user import User


TEST_DATABASE_URL = os.getenv("SUPPLY_TEST_DATABASE_URL")
EXPECTED_DATABASE_NAME = "eos_supply_migration_test"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}


@unittest.skipUnless(TEST_DATABASE_URL, "SUPPLY_TEST_DATABASE_URL is not configured")
class SupplyProductSuppliersPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        url = make_url(TEST_DATABASE_URL or "")
        if not url.drivername.startswith("postgresql") or url.host not in ALLOWED_HOSTS or url.database != EXPECTED_DATABASE_NAME:
            raise RuntimeError("Test requires the dedicated local PostgreSQL database")
        cls.previous = (settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port)
        settings.postgres_db = url.database
        settings.postgres_user = url.username or ""
        settings.postgres_password = url.password or ""
        settings.postgres_host = url.host or ""
        settings.postgres_port = url.port or 5432
        cls.engine = create_engine(TEST_DATABASE_URL)
        if inspect(cls.engine).get_table_names():
            raise RuntimeError("Migration test database must be empty")
        cls.sessions = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    @classmethod
    def tearDownClass(cls) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        if hasattr(cls, "engine"):
            cls.engine.dispose()
        if hasattr(cls, "previous"):
            (settings.postgres_db, settings.postgres_user, settings.postgres_password, settings.postgres_host, settings.postgres_port) = cls.previous

    def revision(self):
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def test_cycle_partial_indexes_tenant_fk_and_api_conflicts(self) -> None:
        command.upgrade(self.config, "20260907_0035")
        self.assertEqual(self.revision(), "20260907_0035")
        command.upgrade(self.config, "20260907_0037")
        self.assertEqual(self.revision(), "20260907_0037")
        command.downgrade(self.config, "20260907_0036")
        self.assertEqual(self.revision(), "20260907_0036")
        command.upgrade(self.config, "20260907_0037")
        self.assertEqual(self.revision(), "20260907_0037")

        with self.engine.connect() as connection:
            definitions = dict(connection.execute(text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = current_schema() "
                "AND indexname IN ('uq_supply_product_suppliers_active_pair', 'uq_supply_product_suppliers_active_primary')"
            )).all())
        self.assertIn("WHERE (is_active = true)", definitions["uq_supply_product_suppliers_active_pair"])
        self.assertIn("role", definitions["uq_supply_product_suppliers_active_primary"])

        unit_id, product_id, other_product_id = uuid4(), uuid4(), uuid4()
        supplier_one, supplier_two, other_supplier = uuid4(), uuid4(), uuid4()
        with self.sessions.begin() as session:
            session.add(User(id=92001, username="product-supplier-admin", display_name="Admin", hashed_password="x", tenant_id="eclair", is_active=True, is_admin=True))
            session.execute(text("INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) VALUES (:id, 'eclair', 'PS_BOX', 'Коробка', 'кор.', false, true)"), {"id": unit_id})
            session.execute(text("INSERT INTO supply_units (id, tenant_id, code, name_ru, short_name_ru, allows_fraction, is_active) VALUES (:id, 'other', 'PS_BOX', 'Коробка', 'кор.', false, true)"), {"id": uuid4()})
            session.execute(text("INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) VALUES (:id, 'eclair', 'PG Product', 'pg product', :unit, true)"), {"id": product_id, "unit": unit_id})
            other_unit = session.execute(text("SELECT id FROM supply_units WHERE tenant_id='other' AND code='PS_BOX'")).scalar_one()
            session.execute(text("INSERT INTO supply_products (id, tenant_id, name, normalized_name, default_unit_id, is_active) VALUES (:id, 'other', 'PG Product', 'pg product', :unit, true)"), {"id": other_product_id, "unit": other_unit})
            for supplier_id, tenant, name in ((supplier_one, "eclair", "One"), (supplier_two, "eclair", "Two"), (other_supplier, "other", "Other")):
                session.execute(text("INSERT INTO supply_suppliers (id, tenant_id, display_name, is_active) VALUES (:id, :tenant, :name, true)"), {"id": supplier_id, "tenant": tenant, "name": name})

        def override_db():
            with self.sessions() as session:
                yield session

        def override_user():
            with self.sessions() as session:
                return session.get(User, 92001)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        client = TestClient(app)
        payload = {"supplier_id": str(supplier_one), "role": "PRIMARY", "priority": 10, "package_quantity": "12", "package_unit_id": str(unit_id), "price_per_package": "4956", "currency": "RUB", "is_available": True}
        first = client.post(f"/supply/products/{product_id}/suppliers", json=payload)
        self.assertEqual(first.status_code, 201, first.text)
        history_url = f"/supply/products/{product_id}/suppliers/{first.json()['id']}/price-history"
        history = client.get(history_url)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()[0]["base_unit_price_snapshot"], "413.000000")

        def reject_history(*_args):
            raise RuntimeError("forced history failure")

        event.listen(SupplyProductSupplierPriceHistory, "before_insert", reject_history)
        try:
            with self.assertRaises(RuntimeError):
                client.patch(
                    f"/supply/products/{product_id}/suppliers/{first.json()['id']}",
                    json={"price_per_package": "6000.00"},
                )
        finally:
            event.remove(SupplyProductSupplierPriceHistory, "before_insert", reject_history)
        current = client.get(f"/supply/products/{product_id}/suppliers").json()[0]
        self.assertEqual(current["price_per_package"], "4956.00")
        self.assertEqual(len(client.get(history_url).json()), 1)
        with patch("app.supply.service._active_product_supplier_exists", return_value=False):
            duplicate = client.post(f"/supply/products/{product_id}/suppliers", json={**payload, "role": "BACKUP"})
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        second_payload = {**payload, "supplier_id": str(supplier_two), "role": "PRIMARY"}
        with patch("app.supply.service._active_primary_product_supplier_exists", return_value=False):
            second_primary = client.post(f"/supply/products/{product_id}/suppliers", json=second_payload)
        self.assertEqual(second_primary.status_code, 409, second_primary.text)

        archived = client.post(f"/supply/products/{product_id}/suppliers/{first.json()['id']}/archive")
        self.assertEqual(archived.status_code, 200)
        replacement = client.post(f"/supply/products/{product_id}/suppliers", json=second_payload)
        self.assertEqual(replacement.status_code, 201, replacement.text)
        with patch("app.supply.service._active_primary_product_supplier_exists", return_value=False):
            restore = client.post(f"/supply/products/{product_id}/suppliers/{first.json()['id']}/restore")
        self.assertEqual(restore.status_code, 409, restore.text)

        backup_payload = {**payload, "supplier_id": str(supplier_one), "role": "BACKUP"}
        backup = client.post(f"/supply/products/{product_id}/suppliers", json=backup_payload)
        self.assertEqual(backup.status_code, 201, backup.text)
        promoted = client.post(f"/supply/products/{product_id}/suppliers/{backup.json()['id']}/make-primary")
        self.assertEqual(promoted.status_code, 200, promoted.text)
        with self.sessions() as session:
            primary_count = session.execute(text("SELECT count(*) FROM supply_product_suppliers WHERE tenant_id='eclair' AND product_id=:product AND is_active=true AND role='PRIMARY'"), {"product": product_id}).scalar_one()
        self.assertEqual(primary_count, 1)

        with self.sessions() as session:
            with self.assertRaises(IntegrityError):
                session.execute(text("INSERT INTO supply_product_suppliers (id, tenant_id, product_id, supplier_id, package_quantity, package_unit_id) VALUES (:id, 'eclair', :product, :supplier, 1, :unit)"), {"id": uuid4(), "product": other_product_id, "supplier": supplier_one, "unit": unit_id})
                session.commit()


if __name__ == "__main__":
    unittest.main()
