import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError

from app.schemas.automation import (
    AutomationScheduleCreate,
    AutomationScheduleRead,
    AutomationScheduleUpdate,
    DailyScheduleConfig,
    IntervalScheduleConfig,
    WeeklyScheduleConfig,
)


def valid_create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Daily report",
        "automation_type": "smoke_test",
        "scope_type": "company",
        "scope_id": None,
        "schedule_config": {"type": "daily", "time": "08:30"},
        "payload": {"report": "sales"},
        "recipients": [{"user_id": 1}],
        "timezone": "Asia/Yekaterinburg",
        "is_enabled": False,
    }
    payload.update(overrides)
    return payload


class AutomationScheduleCreateTests(unittest.TestCase):
    def test_valid_company_scope(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload()
        )

        self.assertEqual(schedule.scope_type, "company")
        self.assertIsNone(schedule.scope_id)

    def test_valid_department_scope(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                scope_type="department",
                scope_id="department-1",
            )
        )

        self.assertEqual(schedule.scope_id, "department-1")

    def test_valid_location_scope(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                scope_type="location",
                scope_id="location-1",
            )
        )

        self.assertEqual(schedule.scope_id, "location-1")

    def test_valid_user_scope(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                scope_type="user",
                scope_id="user-1",
            )
        )

        self.assertEqual(schedule.scope_id, "user-1")

    def test_strips_name(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(name="  Daily report  ")
        )

        self.assertEqual(schedule.name, "Daily report")

    def test_strips_automation_type(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(automation_type="  smoke_test  ")
        )

        self.assertEqual(schedule.automation_type, "smoke_test")

    def test_strips_scope_id(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                scope_type="department",
                scope_id="  department-1  ",
            )
        )

        self.assertEqual(schedule.scope_id, "department-1")

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(name="   ")
            )

    def test_rejects_empty_automation_type(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(automation_type="   ")
            )

    def test_rejects_invalid_scope_type(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(scope_type="branch")
            )

    def test_rejects_scope_id_for_company(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            "company scope requires scope_id to be null",
        ):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(scope_id="company-1")
            )

    def test_rejects_missing_scope_id_for_department(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    scope_type="department",
                    scope_id=None,
                )
            )

    def test_rejects_missing_scope_id_for_location(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    scope_type="location",
                    scope_id=None,
                )
            )

    def test_rejects_missing_scope_id_for_user(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    scope_type="user",
                    scope_id=None,
                )
            )

    def test_rejects_empty_scope_id(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    scope_type="department",
                    scope_id="   ",
                )
            )

    def test_accepts_and_normalizes_valid_timezone(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(timezone="  Asia/Yekaterinburg  ")
        )

        self.assertEqual(schedule.timezone, "Asia/Yekaterinburg")

    def test_rejects_invalid_timezone(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Unknown timezone"):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(timezone="Mars/Olympus_Mons")
            )

    def test_rejects_schedule_config_that_is_not_dict(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(schedule_config=[])
            )

    def test_rejects_payload_that_is_not_dict(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(payload=[])
            )

    def test_rejects_recipients_that_is_not_list(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(recipients={})
            )

    def test_rejects_unknown_extra_field(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(unknown_field="value")
            )


class ScheduleConfigTests(unittest.TestCase):
    def test_accepts_daily(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                schedule_config={"type": "daily", "time": "08:30"}
            )
        )

        self.assertIsInstance(schedule.schedule_config, DailyScheduleConfig)

    def test_accepts_and_sorts_weekly_weekdays(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                schedule_config={
                    "type": "weekly",
                    "weekdays": [4, 0, 2],
                    "time": "09:00",
                }
            )
        )

        self.assertIsInstance(schedule.schedule_config, WeeklyScheduleConfig)
        self.assertEqual(schedule.schedule_config.weekdays, [0, 2, 4])

    def test_accepts_interval(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                schedule_config={"type": "interval", "minutes": 30}
            )
        )

        self.assertIsInstance(
            schedule.schedule_config,
            IntervalScheduleConfig,
        )

    def test_rejects_unknown_type(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    schedule_config={"type": "monthly"}
                )
            )

    def test_rejects_invalid_daily_time(self) -> None:
        invalid_times = ("8:30", "24:00", "12:60", "08:30:00", 830)

        for value in invalid_times:
            with self.subTest(time=value):
                with self.assertRaises(ValidationError):
                    AutomationScheduleCreate.model_validate(
                        valid_create_payload(
                            schedule_config={
                                "type": "daily",
                                "time": value,
                            }
                        )
                    )

    def test_rejects_extra_fields_for_each_type(self) -> None:
        configs = (
            {"type": "daily", "time": "08:30", "minutes": 30},
            {
                "type": "weekly",
                "weekdays": [0],
                "time": "08:30",
                "extra": True,
            },
            {"type": "interval", "minutes": 30, "time": "08:30"},
        )

        for config in configs:
            with self.subTest(config=config):
                with self.assertRaises(ValidationError):
                    AutomationScheduleCreate.model_validate(
                        valid_create_payload(schedule_config=config)
                    )

    def test_rejects_empty_weekdays(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    schedule_config={
                        "type": "weekly",
                        "weekdays": [],
                        "time": "09:00",
                    }
                )
            )

    def test_rejects_weekday_outside_range(self) -> None:
        for weekday in (-1, 7):
            with self.subTest(weekday=weekday):
                with self.assertRaises(ValidationError):
                    AutomationScheduleCreate.model_validate(
                        valid_create_payload(
                            schedule_config={
                                "type": "weekly",
                                "weekdays": [weekday],
                                "time": "09:00",
                            }
                        )
                    )

    def test_rejects_duplicate_weekdays(self) -> None:
        with self.assertRaisesRegex(ValidationError, "duplicates"):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    schedule_config={
                        "type": "weekly",
                        "weekdays": [0, 0],
                        "time": "09:00",
                    }
                )
            )

    def test_rejects_interval_outside_range(self) -> None:
        for minutes in (0, 10081):
            with self.subTest(minutes=minutes):
                with self.assertRaises(ValidationError):
                    AutomationScheduleCreate.model_validate(
                        valid_create_payload(
                            schedule_config={
                                "type": "interval",
                                "minutes": minutes,
                            }
                        )
                    )

    def test_rejects_bool_interval_minutes(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationScheduleCreate.model_validate(
                valid_create_payload(
                    schedule_config={
                        "type": "interval",
                        "minutes": True,
                    }
                )
            )

    def test_serializes_to_json_compatible_dict(self) -> None:
        schedule = AutomationScheduleCreate.model_validate(
            valid_create_payload(
                schedule_config={
                    "type": "weekly",
                    "weekdays": [4, 0],
                    "time": "09:00",
                }
            )
        )

        self.assertEqual(
            schedule.model_dump(mode="json")["schedule_config"],
            {
                "type": "weekly",
                "weekdays": [0, 4],
                "time": "09:00",
            },
        )

    def test_update_uses_schedule_contract(self) -> None:
        update = AutomationScheduleUpdate(
            schedule_config={"type": "interval", "minutes": 45}
        )

        self.assertEqual(
            update.model_dump(exclude_unset=True),
            {"schedule_config": {"type": "interval", "minutes": 45}},
        )

    def test_update_without_schedule_config_remains_partial(self) -> None:
        update = AutomationScheduleUpdate(name="Updated")

        self.assertEqual(
            update.model_dump(exclude_unset=True),
            {"name": "Updated"},
        )


class AutomationScheduleServerFieldTests(unittest.TestCase):
    def assert_server_field_forbidden(
        self,
        field: str,
        value: object,
    ) -> None:
        with self.subTest(schema="create", field=field):
            with self.assertRaises(ValidationError):
                AutomationScheduleCreate.model_validate(
                    valid_create_payload(**{field: value})
                )

        with self.subTest(schema="update", field=field):
            with self.assertRaises(ValidationError):
                AutomationScheduleUpdate.model_validate({field: value})

    def test_rejects_id_in_create_and_update(self) -> None:
        self.assert_server_field_forbidden("id", 1)

    def test_rejects_contract_version_in_create_and_update(self) -> None:
        self.assert_server_field_forbidden("contract_version", "1.0")

    def test_rejects_tenant_id_in_create_and_update(self) -> None:
        self.assert_server_field_forbidden("tenant_id", "enterpriseos")

    def test_rejects_next_run_at_in_create_and_update(self) -> None:
        self.assert_server_field_forbidden(
            "next_run_at",
            "2026-07-21T12:00:00Z",
        )

    def test_rejects_created_by_user_id_in_create_and_update(self) -> None:
        self.assert_server_field_forbidden("created_by_user_id", 1)

    def test_rejects_created_at_and_updated_at_in_create_and_update(
        self,
    ) -> None:
        self.assert_server_field_forbidden(
            "created_at",
            "2026-07-21T12:00:00Z",
        )
        self.assert_server_field_forbidden(
            "updated_at",
            "2026-07-21T12:00:00Z",
        )


class AutomationScheduleUpdateTests(unittest.TestCase):
    def test_partial_update_with_name_only(self) -> None:
        update = AutomationScheduleUpdate(name="  New name  ")

        self.assertEqual(
            update.model_dump(exclude_unset=True),
            {"name": "New name"},
        )

    def test_partial_update_with_is_enabled_only(self) -> None:
        update = AutomationScheduleUpdate(is_enabled=True)

        self.assertEqual(
            update.model_dump(exclude_unset=True),
            {"is_enabled": True},
        )

    def test_distinguishes_missing_and_explicit_null_scope_id(self) -> None:
        missing = AutomationScheduleUpdate()
        explicit_null = AutomationScheduleUpdate(scope_id=None)

        self.assertEqual(missing.model_dump(exclude_unset=True), {})
        self.assertEqual(
            explicit_null.model_dump(exclude_unset=True),
            {"scope_id": None},
        )

    def test_rejects_explicit_null_for_not_null_fields(self) -> None:
        fields = (
            "name",
            "automation_type",
            "schedule_config",
            "payload",
            "recipients",
            "timezone",
            "is_enabled",
        )

        for field in fields:
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    AutomationScheduleUpdate.model_validate({field: None})

    def test_validates_scope_pair_when_both_fields_are_present(self) -> None:
        valid_company = AutomationScheduleUpdate(
            scope_type="company",
            scope_id=None,
        )
        valid_department = AutomationScheduleUpdate(
            scope_type="department",
            scope_id="department-1",
        )

        self.assertIsNone(valid_company.scope_id)
        self.assertEqual(valid_department.scope_id, "department-1")

        with self.assertRaises(ValidationError):
            AutomationScheduleUpdate(
                scope_type="company",
                scope_id="company-1",
            )

        with self.assertRaises(ValidationError):
            AutomationScheduleUpdate(
                scope_type="department",
                scope_id=None,
            )

    def test_accepts_scope_type_without_guessing_old_scope_id(self) -> None:
        update = AutomationScheduleUpdate(scope_type="department")

        self.assertEqual(
            update.model_dump(exclude_unset=True),
            {"scope_type": "department"},
        )

    def test_accepts_scope_id_without_guessing_old_scope_type(self) -> None:
        update = AutomationScheduleUpdate(scope_id="  department-1  ")

        self.assertEqual(
            update.model_dump(exclude_unset=True),
            {"scope_id": "department-1"},
        )


class AutomationScheduleReadTests(unittest.TestCase):
    def make_schedule_object(self) -> SimpleNamespace:
        created_at = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)
        updated_at = datetime(2026, 7, 21, 11, 0, tzinfo=timezone.utc)

        return SimpleNamespace(
            id=42,
            name="Daily report",
            automation_type="daily_report",
            contract_version="1.0",
            tenant_id="enterpriseos",
            scope_type="company",
            scope_id=None,
            schedule_config={"type": "daily", "time": "08:30"},
            payload={"report": "sales"},
            recipients=[{"user_id": 1}],
            timezone="Asia/Yekaterinburg",
            is_enabled=True,
            next_run_at=datetime(
                2026,
                7,
                22,
                5,
                0,
                tzinfo=timezone.utc,
            ),
            created_by_user_id=7,
            created_at=created_at,
            updated_at=updated_at,
        )

    def test_creates_read_schema_from_object_attributes(self) -> None:
        source = self.make_schedule_object()

        schedule = AutomationScheduleRead.model_validate(source)

        self.assertEqual(schedule.id, 42)
        self.assertEqual(schedule.name, "Daily report")
        self.assertEqual(schedule.scope_type, "company")

    def test_read_schema_contains_all_server_fields(self) -> None:
        schedule = AutomationScheduleRead.model_validate(
            self.make_schedule_object()
        )
        serialized = schedule.model_dump()

        expected_server_fields = {
            "id",
            "contract_version",
            "tenant_id",
            "next_run_at",
            "created_by_user_id",
            "created_at",
            "updated_at",
        }

        self.assertTrue(expected_server_fields.issubset(serialized))
        self.assertEqual(serialized["tenant_id"], "enterpriseos")


if __name__ == "__main__":
    unittest.main()
