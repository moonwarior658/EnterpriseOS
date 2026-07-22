import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.automation.catalog import (
    AUTOMATION_TYPES,
    AutomationTypeDefinition,
    get_automation_type,
    list_available_automation_types,
)
from app.schemas.automation import (
    AutomationScheduleCreate,
    AutomationScheduleUpdate,
)


def schedule_body(automation_type: str = "smoke_test") -> dict[str, object]:
    return {
        "name": "Automation Core check",
        "automation_type": automation_type,
        "scope_type": "company",
        "scope_id": None,
        "schedule_config": {"type": "interval", "minutes": 60},
        "payload": {},
        "recipients": [],
        "timezone": "UTC",
        "is_enabled": True,
    }


class AutomationCatalogTests(unittest.TestCase):
    def test_catalog_contains_safe_smoke_test(self) -> None:
        definition = get_automation_type("smoke_test")

        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertEqual(definition.display_name, "Проверка Automation Core")
        self.assertEqual(definition.category, "technical")
        self.assertTrue(definition.is_system)
        self.assertTrue(definition.is_available)
        self.assertTrue(definition.supports_manual_run)

    def test_catalog_keys_are_unique(self) -> None:
        keys = [item.key for item in AUTOMATION_TYPES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_available_catalog_order_is_deterministic(self) -> None:
        first = list_available_automation_types()
        second = list_available_automation_types()

        self.assertEqual(first, second)
        self.assertEqual([item.key for item in first], ["smoke_test"])

    def test_unavailable_catalog_entries_are_not_listed(self) -> None:
        unavailable = AutomationTypeDefinition(
            key="unavailable_fixture",
            display_name="Unavailable fixture",
            description="Test-only unavailable type",
            category="technical",
            is_system=True,
            is_available=False,
            supports_manual_run=False,
        )

        with patch(
            "app.automation.catalog.AUTOMATION_TYPES",
            AUTOMATION_TYPES + (unavailable,),
        ):
            listed = list_available_automation_types()

        self.assertNotIn("unavailable_fixture", {item.key for item in listed})

    def test_create_and_update_accept_smoke_test_without_recipients(self) -> None:
        created = AutomationScheduleCreate.model_validate(schedule_body())
        updated = AutomationScheduleUpdate(automation_type="smoke_test")

        self.assertEqual(created.recipients, [])
        self.assertEqual(updated.automation_type, "smoke_test")

    def test_unknown_type_is_rejected_on_create_and_update(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Unsupported automation type"):
            AutomationScheduleCreate.model_validate(schedule_body("unknown"))

        with self.assertRaisesRegex(ValidationError, "Unsupported automation type"):
            AutomationScheduleUpdate(automation_type="unknown")

    def test_unavailable_type_is_rejected(self) -> None:
        unavailable = AutomationTypeDefinition(
            key="unavailable_fixture",
            display_name="Unavailable fixture",
            description="Test-only unavailable type",
            category="technical",
            is_system=True,
            is_available=False,
            supports_manual_run=False,
        )

        with patch(
            "app.automation.catalog.AUTOMATION_TYPES",
            AUTOMATION_TYPES + (unavailable,),
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "Unsupported automation type",
            ):
                AutomationScheduleCreate.model_validate(
                    schedule_body("unavailable_fixture")
                )


if __name__ == "__main__":
    unittest.main()
