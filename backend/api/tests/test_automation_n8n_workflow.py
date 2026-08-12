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

    def test_print_job_branch_preserves_eos_contract(self) -> None:
        workflows = json.loads(WORKFLOW_EXPORT.read_text(encoding="utf-8"))
        workflow = workflows[0]
        nodes = {node["name"]: node for node in workflow["nodes"]}
        condition = nodes["Require supply.print_job"]["parameters"][
            "conditions"
        ]["conditions"][0]
        self.assertEqual(condition["rightValue"], "supply.print_job")
        retrieval = nodes["Get verified PDF"]["parameters"]["url"]
        self.assertIn("pdf_retrieval.path", retrieval)
        agent = nodes["Print through local agent"]
        headers = agent["parameters"]["headerParameters"]["parameters"]
        names = {item["name"] for item in headers}
        self.assertEqual(names, {
            "Content-Type", "X-Print-Job-Id", "Idempotency-Key",
            "X-Printer-Name", "X-Copies",
        })
        serialized = json.dumps(workflow, ensure_ascii=False).lower()
        self.assertNotIn("192.168.0.14", serialized)
        self.assertNotIn("service_token", serialized)
        self.assertIn("supply_print_failed", serialized)


if __name__ == "__main__":
    unittest.main()
