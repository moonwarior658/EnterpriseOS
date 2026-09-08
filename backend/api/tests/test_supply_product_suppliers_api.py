import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.supply import (
    SupplyProduct,
    SupplyProductCategory,
    SupplyProductSupplier,
    SupplyProductSupplierPriceHistory,
    SupplyRequestDirection,
    SupplyStorageZone,
    SupplySupplier,
    SupplyUnit,
)
from app.models.user import User


class SupplyProductSuppliersApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        for table in (
            User.__table__, SupplyUnit.__table__, SupplyRequestDirection.__table__,
            SupplyProductCategory.__table__, SupplyStorageZone.__table__,
            SupplyProduct.__table__,
            SupplySupplier.__table__, SupplyProductSupplier.__table__,
            SupplyProductSupplierPriceHistory.__table__,
        ):
            table.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            session.add_all([
                User(id=1, username="employee", display_name="Employee", hashed_password="x", tenant_id="eclair", is_active=True, is_admin=False),
                User(id=2, username="admin", display_name="Admin", hashed_password="x", tenant_id="eclair", is_active=True, is_admin=True),
                User(id=3, username="other-admin", display_name="Other", hashed_password="x", tenant_id="other", is_active=True, is_admin=True),
            ])
            self.unit = SupplyUnit(tenant_id="eclair", code="L", name_ru="Литр", short_name_ru="л", allows_fraction=True, is_active=True)
            self.box = SupplyUnit(tenant_id="eclair", code="BOX", name_ru="Коробка", short_name_ru="кор.", allows_fraction=False, is_active=True)
            self.other_box = SupplyUnit(tenant_id="other", code="BOX", name_ru="Коробка", short_name_ru="кор.", allows_fraction=False, is_active=True)
            session.add_all([self.unit, self.box, self.other_box])
            session.flush()
            self.product = SupplyProduct(tenant_id="eclair", name="Сливки", normalized_name="сливки", default_unit_id=self.unit.id, is_active=True)
            self.product_two = SupplyProduct(tenant_id="eclair", name="Молоко", normalized_name="молоко", default_unit_id=self.unit.id, is_active=True)
            self.other_product = SupplyProduct(tenant_id="other", name="Сливки", normalized_name="сливки", default_unit_id=self.other_box.id, is_active=True)
            self.supplier = SupplySupplier(tenant_id="eclair", display_name="Поставщик 1", is_active=True)
            self.supplier_two = SupplySupplier(tenant_id="eclair", display_name="Поставщик 2", is_active=True)
            self.other_supplier = SupplySupplier(tenant_id="other", display_name="Чужой", is_active=True)
            session.add_all([self.product, self.product_two, self.other_product, self.supplier, self.supplier_two, self.other_supplier])
        self.current_user_id = 2

        def override_db():
            with self.sessions() as session:
                yield session

        def override_user():
            with self.sessions() as session:
                return session.get(User, self.current_user_id)

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = override_user
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        app.openapi_schema = None
        self.engine.dispose()

    def payload(self, supplier_id=None, **changes):
        result = {
            "supplier_id": str(supplier_id or self.supplier.id),
            "supplier_product_name": "Сливки 33%",
            "supplier_sku": "CREAM-33",
            "role": "BACKUP",
            "priority": 100,
            "package_quantity": "12.000",
            "package_unit_id": str(self.box.id),
            "price_per_package": "4956.00",
            "currency": "RUB",
            "is_available": True,
            "unavailable_until": None,
        }
        result.update(changes)
        return result

    def create(self, product_id=None, supplier_id=None, **changes):
        return self.client.post(
            f"/supply/products/{product_id or self.product.id}/suppliers",
            json=self.payload(supplier_id, **changes),
        )

    def test_create_list_update_archive_restore_and_calculated_price(self) -> None:
        created = self.create(role="PRIMARY")
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["supplier"]["display_name"], "Поставщик 1")
        self.assertEqual(body["price_per_base_unit"], "413.00")

        listed = self.client.get(f"/supply/products/{self.product.id}/suppliers")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        relation_id = body["id"]
        updated = self.client.patch(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}",
            json={"price_per_package": "5280.00", "priority": 20, "is_available": False, "unavailable_until": (date.today() + timedelta(days=2)).isoformat()},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["price_per_base_unit"], "440.00")
        self.assertFalse(updated.json()["is_available"])

        archived = self.client.post(f"/supply/products/{self.product.id}/suppliers/{relation_id}/archive")
        self.assertEqual(archived.status_code, 200)
        self.assertFalse(archived.json()["is_active"])
        self.assertEqual(self.client.get(f"/supply/products/{self.product.id}/suppliers").json(), [])
        restored = self.client.post(f"/supply/products/{self.product.id}/suppliers/{relation_id}/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertTrue(restored.json()["is_active"])

    def test_duplicates_multiplicity_and_atomic_primary_change(self) -> None:
        first = self.create(role="PRIMARY")
        self.assertEqual(first.status_code, 201)
        duplicate = self.create()
        self.assertEqual(duplicate.status_code, 409)
        second = self.create(supplier_id=self.supplier_two.id, priority=10)
        self.assertEqual(second.status_code, 201, second.text)
        second_id = second.json()["id"]
        direct_primary = self.create(product_id=self.product_two.id, supplier_id=self.supplier_two.id, role="PRIMARY")
        self.assertEqual(direct_primary.status_code, 201)
        same_supplier_other_product = self.create(product_id=self.product_two.id, supplier_id=self.supplier.id)
        self.assertEqual(same_supplier_other_product.status_code, 201)

        changed = self.client.post(f"/supply/products/{self.product.id}/suppliers/{second_id}/make-primary")
        self.assertEqual(changed.status_code, 200, changed.text)
        relations = self.client.get(f"/supply/products/{self.product.id}/suppliers").json()
        self.assertEqual([item["role"] for item in relations], ["PRIMARY", "BACKUP"])
        self.assertEqual(relations[0]["id"], second_id)

    def test_tenant_isolation_and_cross_tenant_references(self) -> None:
        self.assertEqual(self.create(supplier_id=self.other_supplier.id).status_code, 404)
        wrong_unit = self.create(package_unit_id=str(self.other_box.id))
        self.assertEqual(wrong_unit.status_code, 422)
        self.current_user_id = 3
        self.assertEqual(self.client.get(f"/supply/products/{self.product.id}/suppliers").status_code, 404)
        own = self.create(product_id=self.other_product.id, supplier_id=self.other_supplier.id, package_unit_id=str(self.other_box.id))
        self.assertEqual(own.status_code, 201, own.text)

    def test_archived_entities_validation_and_permissions(self) -> None:
        with self.sessions.begin() as session:
            session.get(SupplySupplier, self.supplier.id).is_active = False
            supplier = session.get(SupplySupplier, self.supplier.id)
            supplier.archived_at = datetime.now(timezone.utc)
            supplier.archived_by_user_id = 2
        self.assertEqual(self.create().status_code, 409)
        with self.sessions.begin() as session:
            product = session.get(SupplyProduct, self.product.id)
            product.is_active = False
            product.archived_at = datetime.now(timezone.utc)
            product.archived_by_user_id = 2
        self.assertEqual(self.create(supplier_id=self.supplier_two.id).status_code, 409)
        self.current_user_id = 1
        self.assertEqual(self.client.get(f"/supply/products/{self.product.id}/suppliers").status_code, 403)

    def test_package_price_and_availability_validation(self) -> None:
        self.assertEqual(self.create(package_quantity="0").status_code, 422)
        self.assertEqual(self.create(price_per_package="0").status_code, 422)
        self.assertEqual(self.create(currency="USD").status_code, 422)
        invalid = self.create(is_available=True, unavailable_until=date.today().isoformat())
        self.assertEqual(invalid.status_code, 422)
        created = self.create()
        self.assertEqual(created.status_code, 201)
        relation_id = created.json()["id"]
        invalid_update = self.client.patch(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}",
            json={"unavailable_until": date.today().isoformat()},
        )
        self.assertEqual(invalid_update.status_code, 422)

    def test_restore_conflicts_are_409_and_primary_archive_has_no_promotion(self) -> None:
        first = self.create(role="PRIMARY")
        second = self.create(supplier_id=self.supplier_two.id)
        first_id = first.json()["id"]
        second_id = second.json()["id"]
        self.client.post(f"/supply/products/{self.product.id}/suppliers/{first_id}/archive")
        active = self.client.get(f"/supply/products/{self.product.id}/suppliers").json()
        self.assertEqual(active[0]["role"], "BACKUP")
        self.client.post(f"/supply/products/{self.product.id}/suppliers/{second_id}/make-primary")
        restored = self.client.post(f"/supply/products/{self.product.id}/suppliers/{first_id}/restore")
        self.assertEqual(restored.status_code, 409, restored.text)

    def test_price_history_tracks_only_changed_complete_price_context(self) -> None:
        created = self.create(role="PRIMARY")
        self.assertEqual(created.status_code, 201, created.text)
        relation_id = created.json()["id"]

        initial = self.client.get(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}/price-history"
        )
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(len(initial.json()), 1)
        self.assertEqual(initial.json()[0]["price_per_package"], "4956.00")
        self.assertEqual(initial.json()[0]["package_quantity"], "12.000")
        self.assertEqual(initial.json()[0]["base_unit_price_snapshot"], "413.000000")
        self.assertEqual(initial.json()[0]["source"], "MANUAL")
        self.assertEqual(initial.json()[0]["package_unit"]["id"], str(self.box.id))
        self.assertEqual(initial.json()[0]["base_unit"]["id"], str(self.unit.id))

        for payload in (
            {"price_per_package": "5000.00"},
            {"package_quantity": "10.000"},
            {"package_unit_id": str(self.unit.id)},
        ):
            response = self.client.patch(
                f"/supply/products/{self.product.id}/suppliers/{relation_id}",
                json=payload,
            )
            self.assertEqual(response.status_code, 200, response.text)

        unchanged = self.client.patch(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}",
            json={"price_per_package": "5000.00"},
        )
        availability = self.client.patch(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}",
            json={"is_available": False},
        )
        renamed = self.client.patch(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}",
            json={"supplier_product_name": "Новое имя"},
        )
        self.assertEqual(unchanged.status_code, 200, unchanged.text)
        self.assertEqual(availability.status_code, 200, availability.text)
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(
            self.client.post(
                f"/supply/products/{self.product.id}/suppliers/{relation_id}/make-primary"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/supply/products/{self.product.id}/suppliers/{relation_id}/archive"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/supply/products/{self.product.id}/suppliers/{relation_id}/restore"
            ).status_code,
            200,
        )

        history = self.client.get(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}/price-history"
        ).json()
        self.assertEqual(len(history), 4)
        self.assertEqual(history[0]["base_unit_price_snapshot"], "500.000000")
        self.assertEqual(history[-1]["price_per_package"], "4956.00")

    def test_price_history_decimal_precision_order_and_old_rows_are_immutable(self) -> None:
        created = self.create(price_per_package="10.00", package_quantity="3.000")
        relation_id = created.json()["id"]
        initial = self.client.get(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}/price-history"
        ).json()[0]
        self.assertEqual(initial["base_unit_price_snapshot"], "3.333333")

        updated = self.client.patch(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}",
            json={"price_per_package": "11.00"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        history = self.client.get(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}/price-history"
        ).json()
        self.assertEqual([row["price_per_package"] for row in history], ["11.00", "10.00"])
        self.assertEqual(history[1], initial)
        with self.sessions() as session:
            rows = list(session.query(SupplyProductSupplierPriceHistory).all())
            self.assertEqual(rows[0].base_unit_price_snapshot, Decimal("3.333333"))

    def test_price_history_is_admin_only_tenant_safe_and_product_scoped(self) -> None:
        created = self.create()
        relation_id = created.json()["id"]
        mismatch = self.client.get(
            f"/supply/products/{self.product_two.id}/suppliers/{relation_id}/price-history"
        )
        self.assertEqual(mismatch.status_code, 404, mismatch.text)
        self.current_user_id = 3
        hidden = self.client.get(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}/price-history"
        )
        self.assertEqual(hidden.status_code, 404, hidden.text)
        self.current_user_id = 1
        forbidden = self.client.get(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}/price-history"
        )
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

    def test_price_update_rolls_back_when_history_insert_fails(self) -> None:
        created = self.create()
        relation_id = created.json()["id"]

        def reject_history(*_args):
            raise RuntimeError("forced history failure")

        event.listen(SupplyProductSupplierPriceHistory, "before_insert", reject_history)
        try:
            with self.assertRaises(RuntimeError):
                self.client.patch(
                    f"/supply/products/{self.product.id}/suppliers/{relation_id}",
                    json={"price_per_package": "6000.00"},
                )
        finally:
            event.remove(SupplyProductSupplierPriceHistory, "before_insert", reject_history)

        relation = self.client.get(
            f"/supply/products/{self.product.id}/suppliers"
        ).json()[0]
        self.assertEqual(relation["price_per_package"], "4956.00")
        history = self.client.get(
            f"/supply/products/{self.product.id}/suppliers/{relation_id}/price-history"
        ).json()
        self.assertEqual(len(history), 1)


if __name__ == "__main__":
    unittest.main()
