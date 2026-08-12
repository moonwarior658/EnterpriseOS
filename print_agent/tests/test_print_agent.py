from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from print_agent.backend import PrintBackendError, PrintBackendUncertainError
from print_agent.main import PRODUCTION_PRINTER, PrintAgentSettings, create_app


class RecordingBackend:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    def print_pdf(self, pdf_path: Path, printer_name: str, copies: int) -> None:
        self.calls.append((pdf_path.read_bytes(), printer_name, copies))
        if self.fail:
            raise PrintBackendError("PRINT_AGENT_BACKEND_FAILED")


class UncertainBackend(RecordingBackend):
    def print_pdf(self, pdf_path: Path, printer_name: str, copies: int) -> None:
        self.calls.append((pdf_path.read_bytes(), printer_name, copies))
        raise PrintBackendUncertainError("PRINT_AGENT_BACKEND_FAILED")


class PrintAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.registry_path = Path(self.temporary.name) / "registry.sqlite3"
        self.backend = RecordingBackend()
        self.settings = PrintAgentSettings(
            service_token="secret",
            registry_path=self.registry_path,
            max_pdf_bytes=32,
        )
        self.client = TestClient(create_app(self.settings, backend=self.backend))
        self.pdf = b"%PDF-1.4\nvalid"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def headers(self, **changes: str) -> dict[str, str]:
        values = {
            "Authorization": "Bearer secret",
            "Content-Type": "application/pdf",
            "X-Print-Job-Id": str(uuid4()),
            "Idempotency-Key": str(uuid4()),
            "X-Printer-Name": PRODUCTION_PRINTER,
            "X-Copies": "2",
        }
        values.update(changes)
        return values

    def test_health(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_auth_required(self) -> None:
        headers = self.headers()
        headers.pop("Authorization")
        response = self.client.post("/print", headers=headers, content=self.pdf)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "PRINT_AGENT_UNAUTHORIZED")

    def test_exact_printer_and_two_copies_print_once(self) -> None:
        response = self.client.post(
            "/print", headers=self.headers(), content=self.pdf
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(self.backend.calls[0][1:], (PRODUCTION_PRINTER, 2))

    def test_other_printer_is_blocked(self) -> None:
        response = self.client.post(
            "/print",
            headers=self.headers(**{"X-Printer-Name": "Other"}),
            content=self.pdf,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "PRINT_AGENT_PRINTER_NOT_ALLOWED")

    def test_invalid_copies_are_blocked(self) -> None:
        response = self.client.post(
            "/print", headers=self.headers(**{"X-Copies": "1"}), content=self.pdf
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "PRINT_AGENT_INVALID_COPIES")

    def test_invalid_content_type_and_pdf_are_blocked(self) -> None:
        response = self.client.post(
            "/print",
            headers=self.headers(**{"Content-Type": "text/plain"}),
            content=self.pdf,
        )
        self.assertEqual(response.status_code, 415)
        response = self.client.post(
            "/print", headers=self.headers(), content=b"not pdf"
        )
        self.assertEqual(response.status_code, 422)

    def test_oversized_pdf_is_blocked(self) -> None:
        response = self.client.post(
            "/print", headers=self.headers(), content=b"%PDF-" + b"x" * 32
        )
        self.assertEqual(response.status_code, 413)

    def test_repeated_success_is_returned_without_second_print(self) -> None:
        headers = self.headers()
        first = self.client.post("/print", headers=headers, content=self.pdf)
        second = self.client.post("/print", headers=headers, content=self.pdf)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(len(self.backend.calls), 1)

    def test_same_key_with_different_pdf_conflicts(self) -> None:
        headers = self.headers()
        self.client.post("/print", headers=headers, content=self.pdf)
        response = self.client.post(
            "/print", headers=headers, content=b"%PDF-1.4\nchanged"
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "PRINT_AGENT_IDEMPOTENCY_CONFLICT")

    def test_registry_survives_agent_restart(self) -> None:
        headers = self.headers()
        self.client.post("/print", headers=headers, content=self.pdf)
        restarted_backend = RecordingBackend()
        restarted = TestClient(create_app(self.settings, backend=restarted_backend))
        response = restarted.post("/print", headers=headers, content=self.pdf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(restarted_backend.calls, [])

    def test_backend_failure_is_safe_and_not_retried(self) -> None:
        backend = RecordingBackend(fail=True)
        client = TestClient(create_app(self.settings, backend=backend))
        headers = self.headers()
        first = client.post("/print", headers=headers, content=self.pdf)
        second = client.post("/print", headers=headers, content=self.pdf)
        self.assertEqual((first.status_code, second.status_code), (502, 502))
        self.assertEqual(first.json()["detail"], "PRINT_AGENT_BACKEND_FAILED")
        self.assertEqual(len(backend.calls), 1)

    def test_uncertain_backend_state_is_never_blindly_retried(self) -> None:
        backend = UncertainBackend()
        client = TestClient(create_app(self.settings, backend=backend))
        headers = self.headers()
        first = client.post("/print", headers=headers, content=self.pdf)
        second = client.post("/print", headers=headers, content=self.pdf)
        self.assertEqual(first.status_code, 502)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            second.json()["detail"], "PRINT_AGENT_IDEMPOTENCY_UNCERTAIN"
        )
        self.assertEqual(len(backend.calls), 1)


if __name__ == "__main__":
    unittest.main()
