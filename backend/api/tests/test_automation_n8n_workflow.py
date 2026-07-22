import json
import unittest
from pathlib import Path


WORKFLOW_EXPORT = (
    Path(__file__).resolve().parents[3]
    / "n8n"
    / "workflows"
    / "eos-workflows.json"
)


class AutomationN8nWorkflowTests(unittest.TestCase):
    def test_smoke_workflow_checks_type_and_returns_versioned_callback(
        self,
    ) -> None:
        workflows = json.loads(WORKFLOW_EXPORT.read_text(encoding="utf-8"))
        workflow = workflows[0]
        nodes = {node["name"]: node for node in workflow["nodes"]}

        type_check = nodes["Require smoke_test"]
        condition = type_check["parameters"]["conditions"]["conditions"][0]
        self.assertIn("automation_type", condition["leftValue"])
        self.assertEqual(condition["rightValue"], "smoke_test")
        self.assertEqual(
            workflow["connections"]["Require smoke_test"]["main"][0][0][
                "node"
            ],
            "HTTP Request",
        )

        callback_body = nodes["HTTP Request"]["parameters"]["jsonBody"]
        self.assertIn('"status": "succeeded"', callback_body)
        self.assertIn("contract_version", callback_body)
        self.assertIn("execution_id", callback_body)
        self.assertNotIn("recipients", callback_body)
        self.assertNotIn("service_token", callback_body.lower())

    def test_workflow_does_not_store_execution_data(self) -> None:
        workflows = json.loads(WORKFLOW_EXPORT.read_text(encoding="utf-8"))
        settings = workflows[0]["settings"]

        self.assertEqual(settings["saveDataErrorExecution"], "none")
        self.assertEqual(settings["saveDataSuccessExecution"], "none")
        self.assertFalse(settings["saveManualExecutions"])


if __name__ == "__main__":
    unittest.main()
