import unittest
from datetime import datetime, timezone

from app.automation.schedule_time import (
    InvalidScheduleConfigError,
    InvalidScheduleTimezoneError,
    calculate_next_run_at,
)


UTC = timezone.utc


class DailyScheduleTimeTests(unittest.TestCase):
    def test_uses_scheduled_time_today_when_still_ahead(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "08:30"},
            "UTC",
            now=datetime(2026, 7, 21, 8, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 21, 8, 30, tzinfo=UTC))

    def test_uses_next_day_when_time_has_passed(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "08:30"},
            "UTC",
            now=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 22, 8, 30, tzinfo=UTC))

    def test_exact_scheduled_time_uses_next_day(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "08:30"},
            "UTC",
            now=datetime(2026, 7, 21, 8, 30, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 22, 8, 30, tzinfo=UTC))

    def test_crosses_midnight(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "00:05"},
            "UTC",
            now=datetime(2026, 7, 21, 23, 59, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 22, 0, 5, tzinfo=UTC))

    def test_uses_schedule_timezone(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "09:00"},
            "Europe/Moscow",
            now=datetime(2026, 7, 21, 5, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 21, 6, 0, tzinfo=UTC))


class WeeklyScheduleTimeTests(unittest.TestCase):
    def test_finds_nearest_day_in_current_week(self) -> None:
        result = calculate_next_run_at(
            {"type": "weekly", "weekdays": [2], "time": "09:00"},
            "UTC",
            now=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 22, 9, 0, tzinfo=UTC))

    def test_uses_today_when_time_is_ahead(self) -> None:
        result = calculate_next_run_at(
            {"type": "weekly", "weekdays": [0], "time": "09:00"},
            "UTC",
            now=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 20, 9, 0, tzinfo=UTC))

    def test_skips_today_when_time_has_passed(self) -> None:
        result = calculate_next_run_at(
            {"type": "weekly", "weekdays": [0], "time": "09:00"},
            "UTC",
            now=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 27, 9, 0, tzinfo=UTC))

    def test_crosses_into_next_week(self) -> None:
        result = calculate_next_run_at(
            {"type": "weekly", "weekdays": [1], "time": "09:00"},
            "UTC",
            now=datetime(2026, 7, 22, 10, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 28, 9, 0, tzinfo=UTC))

    def test_selects_nearest_of_multiple_weekdays(self) -> None:
        result = calculate_next_run_at(
            {
                "type": "weekly",
                "weekdays": [0, 2, 4],
                "time": "09:00",
            },
            "UTC",
            now=datetime(2026, 7, 21, 10, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 22, 9, 0, tzinfo=UTC))

    def test_sunday_to_monday(self) -> None:
        result = calculate_next_run_at(
            {"type": "weekly", "weekdays": [0], "time": "09:00"},
            "UTC",
            now=datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 27, 9, 0, tzinfo=UTC))


class IntervalScheduleTimeTests(unittest.TestCase):
    def test_uses_now_without_previous_run(self) -> None:
        now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)

        result = calculate_next_run_at(
            {"type": "interval", "minutes": 30},
            "UTC",
            now=now,
        )

        self.assertEqual(result, datetime(2026, 7, 21, 8, 30, tzinfo=UTC))

    def test_uses_previous_run_as_base(self) -> None:
        result = calculate_next_run_at(
            {"type": "interval", "minutes": 30},
            "UTC",
            now=datetime(2026, 7, 21, 8, 0, tzinfo=UTC),
            previous_run_at=datetime(2026, 7, 21, 7, 45, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 21, 8, 15, tzinfo=UTC))

    def test_skips_one_missed_interval(self) -> None:
        result = calculate_next_run_at(
            {"type": "interval", "minutes": 30},
            "UTC",
            now=datetime(2026, 7, 21, 8, 20, tzinfo=UTC),
            previous_run_at=datetime(2026, 7, 21, 7, 30, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 21, 8, 30, tzinfo=UTC))

    def test_skips_many_intervals_arithmetically(self) -> None:
        result = calculate_next_run_at(
            {"type": "interval", "minutes": 15},
            "UTC",
            now=datetime(2026, 7, 21, 8, 7, tzinfo=UTC),
            previous_run_at=datetime(2025, 7, 21, 8, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 21, 8, 15, tzinfo=UTC))

    def test_exact_slot_advances_to_following_slot(self) -> None:
        result = calculate_next_run_at(
            {"type": "interval", "minutes": 30},
            "UTC",
            now=datetime(2026, 7, 21, 8, 0, tzinfo=UTC),
            previous_run_at=datetime(2026, 7, 21, 7, 30, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 21, 8, 30, tzinfo=UTC))

    def test_result_is_strictly_after_now(self) -> None:
        now = datetime(2026, 7, 21, 8, 0, tzinfo=UTC)

        result = calculate_next_run_at(
            {"type": "interval", "minutes": 1},
            "UTC",
            now=now,
            previous_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )

        self.assertGreater(result, now)

    def test_supports_largest_interval(self) -> None:
        result = calculate_next_run_at(
            {"type": "interval", "minutes": 10080},
            "UTC",
            now=datetime(2026, 7, 21, 8, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 7, 28, 8, 0, tzinfo=UTC))


class ScheduleTimezoneTests(unittest.TestCase):
    def test_rejects_invalid_timezone(self) -> None:
        with self.assertRaises(InvalidScheduleTimezoneError):
            calculate_next_run_at(
                {"type": "daily", "time": "08:30"},
                "Mars/Olympus_Mons",
                now=datetime(2026, 7, 21, tzinfo=UTC),
            )

    def test_rejects_naive_now(self) -> None:
        with self.assertRaisesRegex(ValueError, "now must include a timezone"):
            calculate_next_run_at(
                {"type": "daily", "time": "08:30"},
                "UTC",
                now=datetime(2026, 7, 21),
            )

    def test_rejects_naive_previous_run(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "previous_run_at must include a timezone",
        ):
            calculate_next_run_at(
                {"type": "interval", "minutes": 30},
                "UTC",
                now=datetime(2026, 7, 21, tzinfo=UTC),
                previous_run_at=datetime(2026, 7, 20),
            )

    def test_spring_gap_moves_to_first_existing_local_minute(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "02:30"},
            "Europe/Paris",
            now=datetime(2026, 3, 29, 0, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 3, 29, 1, 0, tzinfo=UTC))

    def test_autumn_ambiguity_uses_first_future_instant(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "02:30"},
            "Europe/Paris",
            now=datetime(2026, 10, 25, 0, 0, tzinfo=UTC),
        )

        self.assertEqual(result, datetime(2026, 10, 25, 0, 30, tzinfo=UTC))

    def test_result_is_timezone_aware_and_utc(self) -> None:
        result = calculate_next_run_at(
            {"type": "daily", "time": "08:30"},
            "Europe/Paris",
            now=datetime(2026, 7, 21, 5, 0, tzinfo=UTC),
        )

        self.assertIsNotNone(result.utcoffset())
        self.assertIs(result.tzinfo, UTC)

    def test_invalid_config_has_domain_error(self) -> None:
        with self.assertRaises(InvalidScheduleConfigError):
            calculate_next_run_at(
                {"type": "monthly"},
                "UTC",
                now=datetime(2026, 7, 21, tzinfo=UTC),
            )


if __name__ == "__main__":
    unittest.main()
