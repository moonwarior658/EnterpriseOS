import unittest
from datetime import datetime
from decimal import Decimal

from app.integrations.iiko.exceptions import IikoContractError
from app.integrations.iiko.mapper import (
    map_collection,
    map_packages,
    map_product,
    map_stock_balance,
    map_unit,
    map_warehouse,
)


class IikoMapperTests(unittest.TestCase):
    def test_product_normalizes_ids_nullable_and_deleted(self) -> None:
        record = map_product(
            {
                "id": " product-id ",
                "name": " Молоко ",
                "code": None,
                "num": " 001 ",
                "parent": None,
                "mainUnit": "unit-id",
                "deleted": True,
                "type": "GOODS",
                "unknown": "ignored",
            }
        )
        self.assertEqual(record.dto.external_id, "product-id")
        self.assertEqual(record.dto.name, "Молоко")
        self.assertEqual(record.dto.sku, "001")
        self.assertIsNone(record.dto.code)
        self.assertTrue(record.dto.is_deleted)
        self.assertFalse(record.dto.is_active)

    def test_packages_use_decimal_and_product_unit(self) -> None:
        records = map_packages(
            {
                "id": "product-id",
                "mainUnit": "unit-id",
                "containers": [
                    {
                        "id": "package-id",
                        "name": "Короб",
                        "count": "2.500",
                        "deleted": False,
                        "extra": "ignored",
                    }
                ],
            }
        )
        package = records[0].dto
        self.assertEqual(package.coefficient, Decimal("2.500"))
        self.assertEqual(package.product_external_id, "product-id")
        self.assertEqual(package.unit_external_id, "unit-id")
        self.assertTrue(package.is_default)

    def test_invalid_contract_and_duplicate_ids_are_rejected(self) -> None:
        with self.assertRaises(IikoContractError):
            map_product({"id": "id", "name": ""})
        with self.assertRaises(IikoContractError):
            map_packages(
                {
                    "id": "product",
                    "containers": [
                        {"id": "package", "name": "Короб", "count": "bad"}
                    ],
                }
            )
        payload = {
            "id": "unit-id",
            "name": "Штука",
            "code": "шт",
            "deleted": False,
        }
        with self.assertRaises(IikoContractError):
            map_collection([payload, payload], map_unit)

    def test_warehouse_allows_nullable_enterprise_and_deleted(self) -> None:
        record = map_warehouse(
            {
                "id": "warehouse-1",
                "name": "Основной склад",
                "code": "01",
                "type": "INVENTORY_ASSETS",
                "accountParentId": None,
                "parentCorporateId": None,
                "deleted": True,
            }
        )
        self.assertIsNone(record.dto.enterprise_external_id)
        self.assertEqual(record.dto.warehouse_type, "INVENTORY_ASSETS")
        self.assertTrue(record.dto.is_deleted)
        self.assertFalse(record.dto.is_active)
        with self.assertRaises(IikoContractError):
            map_warehouse({})
        with self.assertRaises(IikoContractError):
            map_warehouse({"id": "warehouse-2", "name": ""})

    def test_stock_balance_preserves_decimal_negative_and_context(
        self,
    ) -> None:
        product = map_product(
            {
                "id": "product-1",
                "name": "Молоко",
                "mainUnit": "unit-1",
                "deleted": False,
            }
        ).dto
        warehouse = map_warehouse(
            {
                "id": "warehouse-1",
                "name": "Основной склад",
                "type": "INVENTORY_ASSETS",
                "deleted": False,
            }
        ).dto
        record = map_stock_balance(
            {
                "store": "warehouse-1",
                "product": "product-1",
                "amount": "-1.250",
                "sum": -10,
            },
            calculated_at=datetime(2026, 7, 29, 23, 59, 59),
            product=product,
            warehouse=warehouse,
        )
        self.assertEqual(record.dto.quantity, Decimal("-1.250"))
        self.assertEqual(record.dto.unit_external_id, "unit-1")
        self.assertEqual(record.dto.product_name, "Молоко")
        self.assertEqual(record.dto.warehouse_name, "Основной склад")
        self.assertEqual(
            record.external_id,
            "warehouse-1:product-1:2026-07-29",
        )
        zero_without_catalog_context = map_stock_balance(
            {
                "store": "warehouse-1",
                "product": "unknown-product",
                "amount": 0,
            },
            calculated_at=datetime(2026, 7, 29, 23, 59, 59),
        )
        self.assertEqual(
            zero_without_catalog_context.dto.quantity,
            Decimal("0"),
        )
        self.assertIsNone(zero_without_catalog_context.dto.unit_external_id)
