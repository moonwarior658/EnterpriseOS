import json
import unittest
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError

from app.schemas.automation import (
    AutomationCallbackResult,
    AutomationCallbackStatus,
    AutomationCommand,
)


EXECUTION_ID = UUID("41644d7a-8875-4f35-a493-371b330fb154")


class AutomationCommandTests(unittest.TestCase):
    def test_serializes_versioned_command_to_json(self) -> None:
        command = AutomationCommand(
            execution_id=EXECUTION_ID,
            idempotency_key=EXECUTION_ID,
            automation_type="daily_sales_report",
            tenant_id="tenant-42",
            requested_at=datetime(
                2026,
                7,
                19,
                12,
                30,
                tzinfo=timezone.utc,
            ),
            payload={"location_ids": [10, 20]},
            callback_url=(
                "https://api.example.test/automation/callback"
            ),
        )

        serialized = json.loads(command.model_dump_json())

        self.assertEqual(serialized["contract_version"], "1.0")
        self.assertEqual(serialized["execution_id"], str(EXECUTION_ID))
        self.assertEqual(
            serialized["idempotency_key"],
            str(EXECUTION_ID),
        )
        self.assertEqual(
            serialized["automation_type"],
            "daily_sales_report",
        )
        self.assertEqual(serialized["tenant_id"], "tenant-42")
        self.assertEqual(
            serialized["requested_at"],
            "2026-07-19T12:30:00Z",
        )
        self.assertEqual(
            serialized["payload"],
            {"location_ids": [10, 20]},
        )
        self.assertEqual(
            serialized["callback_url"],
            "https://api.example.test/automation/callback",
        )

    def test_rejects_idempotency_key_for_another_execution(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            "idempotency_key must match execution_id",
        ):
            AutomationCommand(
                execution_id=EXECUTION_ID,
                idempotency_key=UUID(
                    "3cab29ad-d9b3-48b3-a481-2139f96e8ec5"
                ),
                automation_type="daily_sales_report",
                tenant_id="tenant-42",
                requested_at=datetime.now(timezone.utc),
                callback_url=(
                    "https://api.example.test/automation/callback"
                ),
            )


class AutomationCallbackResultTests(unittest.TestCase):
    def test_validates_callback_result(self) -> None:
        callback = AutomationCallbackResult.model_validate(
            {
                "contract_version": "1.0",
                "execution_id": str(EXECUTION_ID),
                "status": "succeeded",
                "started_at": "2026-07-19T12:30:01Z",
                "finished_at": "2026-07-19T12:31:00Z",
                "result": {"document_id": 123},
                "error_code": None,
                "error_message": None,
            }
        )

        self.assertEqual(
            callback.status,
            AutomationCallbackStatus.SUCCEEDED,
        )
        self.assertEqual(callback.result, {"document_id": 123})

    def test_rejects_callback_with_reversed_timestamps(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            "finished_at must not precede started_at",
        ):
            AutomationCallbackResult.model_validate(
                {
                    "contract_version": "1.0",
                    "execution_id": str(EXECUTION_ID),
                    "status": "failed",
                    "started_at": "2026-07-19T12:31:00Z",
                    "finished_at": "2026-07-19T12:30:01Z",
                    "result": None,
                    "error_code": "UPSTREAM_ERROR",
                    "error_message": "Upstream system failed",
                }
            )

    def test_rejects_unknown_contract_version(self) -> None:
        with self.assertRaises(ValidationError):
            AutomationCallbackResult.model_validate(
                {
                    "contract_version": "2.0",
                    "execution_id": str(EXECUTION_ID),
                    "status": "running",
                    "started_at": "2026-07-19T12:30:01Z",
                    "finished_at": None,
                    "result": None,
                    "error_code": None,
                    "error_message": None,
                }
            )
