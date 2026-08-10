import unittest
from uuid import UUID

from app.integrations.iiko.document_routing import (
    IikoDocumentRouteNotConfiguredError,
    resolve_internal_transfer_route,
    resolve_outgoing_invoice_route,
)
from app.models.supply import SupplyProductSourceRole


class IikoDocumentRoutingTests(unittest.TestCase):
    def test_resolves_all_outgoing_invoice_production_routes(self) -> None:
        expected = {
            ("М15", SupplyProductSourceRole.MAIN): (
                "24b90a5f-1a58-4f6b-9b55-368d7a92ec3e",
                "d8ac1fa7-73d3-4164-9651-fa2c0b806d0f",
                "47c6accc-4bc7-6be1-0194-ccf9367e20cd",
            ),
            ("М15", SupplyProductSourceRole.PACKAGING): (
                "bf44ec50-91d2-48b3-a927-2e3e2490f1d6",
                "d8ac1fa7-73d3-4164-9651-fa2c0b806d0f",
                "47c6accc-4bc7-6be1-0194-ccf9367e20cd",
            ),
            ("М15", SupplyProductSourceRole.HOUSEHOLD): (
                "9ea20084-9182-4633-8c52-a968a15e0b3b",
                "c3f43576-66fd-421d-a2c2-6ed3bf208ea1",
                "cbc5afd7-6e03-a56d-0197-0acc172e7633",
            ),
            ("М35", SupplyProductSourceRole.MAIN): (
                "24b90a5f-1a58-4f6b-9b55-368d7a92ec3e",
                "a6f406c7-de56-4021-b94b-3e8610f13960",
                "eac6f3d4-a2f2-0113-0195-53afd17de4dc",
            ),
            ("М35", SupplyProductSourceRole.PACKAGING): (
                "bf44ec50-91d2-48b3-a927-2e3e2490f1d6",
                "a6f406c7-de56-4021-b94b-3e8610f13960",
                "eac6f3d4-a2f2-0113-0195-53afd17de4dc",
            ),
            ("М35", SupplyProductSourceRole.HOUSEHOLD): (
                "9ea20084-9182-4633-8c52-a968a15e0b3b",
                "d9144d36-f4cb-47d4-afff-f6b3ad8a4ca7",
                "cbc5afd7-6e03-a56d-0197-0acc172e7647",
            ),
            ("М6А", SupplyProductSourceRole.MAIN): (
                "24b90a5f-1a58-4f6b-9b55-368d7a92ec3e",
                "10f8add8-163d-47a7-b4ce-7b766fe9d6f0",
                "47c6accc-4bc7-6be1-0194-ccf9367e20cb",
            ),
            ("М6А", SupplyProductSourceRole.PACKAGING): (
                "bf44ec50-91d2-48b3-a927-2e3e2490f1d6",
                "10f8add8-163d-47a7-b4ce-7b766fe9d6f0",
                "47c6accc-4bc7-6be1-0194-ccf9367e20cb",
            ),
            ("М6А", SupplyProductSourceRole.HOUSEHOLD): (
                "9ea20084-9182-4633-8c52-a968a15e0b3b",
                "1d5e0f78-5c64-4458-99da-51c643f21208",
                "cbc5afd7-6e03-a56d-0197-0acc172e765e",
            ),
        }

        for key, identifiers in expected.items():
            with self.subTest(department_code=key[0], flow=key[1]):
                route = resolve_outgoing_invoice_route(*key)
                self.assertEqual(route.source_store_id, UUID(identifiers[0]))
                self.assertEqual(
                    route.destination_store_id,
                    UUID(identifiers[1]),
                )
                self.assertEqual(route.counteragent_id, UUID(identifiers[2]))
                self.assertEqual(route.account_to_code, "21")
                self.assertEqual(route.revenue_account_code, "20")

    def test_resolves_all_internal_transfer_production_routes(self) -> None:
        expected = {
            ("ЦЕХ", SupplyProductSourceRole.MAIN): (
                "24b90a5f-1a58-4f6b-9b55-368d7a92ec3e",
                "1c22edc0-7ded-41c9-b781-0389462c7247",
            ),
            ("ЦЕХ", SupplyProductSourceRole.PACKAGING): (
                "bf44ec50-91d2-48b3-a927-2e3e2490f1d6",
                "1c22edc0-7ded-41c9-b781-0389462c7247",
            ),
            ("ЦЕХ", SupplyProductSourceRole.HOUSEHOLD): (
                "9ea20084-9182-4633-8c52-a968a15e0b3b",
                "db13589d-68fd-4140-b1de-550f3e07c88a",
            ),
        }

        for key, identifiers in expected.items():
            with self.subTest(department_code=key[0], flow=key[1]):
                route = resolve_internal_transfer_route(*key)
                self.assertEqual(route.from_store_id, UUID(identifiers[0]))
                self.assertEqual(route.to_store_id, UUID(identifiers[1]))

    def test_unknown_routes_fail_closed(self) -> None:
        unknown_routes = (
            (resolve_outgoing_invoice_route, "БАР", SupplyProductSourceRole.MAIN),
            (
                resolve_outgoing_invoice_route,
                "КУХНЯ",
                SupplyProductSourceRole.MAIN,
            ),
            (resolve_internal_transfer_route, "М15", SupplyProductSourceRole.MAIN),
            (resolve_internal_transfer_route, "ЦЕХ", "OTHER"),
        )
        for resolver, department_code, flow in unknown_routes:
            with self.subTest(
                resolver=resolver.__name__,
                department_code=department_code,
                flow=flow,
            ):
                with self.assertRaises(IikoDocumentRouteNotConfiguredError):
                    resolver(department_code, flow)


if __name__ == "__main__":
    unittest.main()
