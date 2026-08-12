from dataclasses import dataclass
from pathlib import Path
from secrets import compare_digest
import hashlib
import os
import tempfile
from typing import Annotated
from uuid import UUID

from fastapi import Body, Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .backend import (
    PrintBackend,
    PrintBackendError,
    PrintBackendUncertainError,
    SumatraPdfWindowsBackend,
)
from .registry import DurablePrintRegistry, RegistryRecord


PRODUCTION_PRINTER = "HP LaserJet Pro MFP M125rnw"
PDF_MEDIA_TYPE = "application/pdf"


@dataclass(frozen=True, slots=True)
class PrintAgentSettings:
    service_token: str
    default_printer: str = PRODUCTION_PRINTER
    allowed_printers: tuple[str, ...] = (PRODUCTION_PRINTER,)
    default_copies: int = 2
    max_pdf_bytes: int = 20 * 1024 * 1024
    registry_path: Path = Path("print-agent-registry.sqlite3")
    sumatra_executable: Path = Path(
        r"C:\Program Files\SumatraPDF\SumatraPDF.exe"
    )

    @classmethod
    def from_environment(cls) -> "PrintAgentSettings":
        allowed = tuple(
            item.strip()
            for item in os.getenv(
                "PRINT_AGENT_ALLOWED_PRINTERS", PRODUCTION_PRINTER
            ).split(",")
            if item.strip()
        )
        return cls(
            service_token=os.getenv("PRINT_AGENT_SERVICE_TOKEN", ""),
            default_printer=os.getenv(
                "PRINT_AGENT_DEFAULT_PRINTER", PRODUCTION_PRINTER
            ),
            allowed_printers=allowed,
            default_copies=int(os.getenv("PRINT_AGENT_DEFAULT_COPIES", "2")),
            max_pdf_bytes=int(
                os.getenv("PRINT_AGENT_MAX_PDF_BYTES", str(20 * 1024 * 1024))
            ),
            registry_path=Path(os.getenv(
                "PRINT_AGENT_REGISTRY_PATH", "print-agent-registry.sqlite3"
            )),
            sumatra_executable=Path(os.getenv(
                "PRINT_AGENT_SUMATRA_PATH",
                r"C:\Program Files\SumatraPDF\SumatraPDF.exe",
            )),
        )


def _same_payload(record: RegistryRecord, **payload: object) -> bool:
    return all(getattr(record, key) == value for key, value in payload.items())


def create_app(
    settings: PrintAgentSettings | None = None,
    *,
    backend: PrintBackend | None = None,
) -> FastAPI:
    settings = settings or PrintAgentSettings.from_environment()
    if (
        settings.default_printer != PRODUCTION_PRINTER
        or settings.allowed_printers != (PRODUCTION_PRINTER,)
        or settings.default_copies != 2
    ):
        raise RuntimeError("Invalid production Print Agent configuration")
    registry: DurablePrintRegistry | None = None
    backend = backend or SumatraPdfWindowsBackend(settings.sumatra_executable)
    bearer = HTTPBearer(auto_error=False)
    app = FastAPI(title="EnterpriseOS Print Agent", version="1.0.0")

    def require_service_auth(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer)
        ],
    ) -> None:
        provided = credentials.credentials if credentials is not None else ""
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not settings.service_token
            or not compare_digest(provided.encode(), settings.service_token.encode())
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="PRINT_AGENT_UNAUTHORIZED",
            )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "eos-print-agent"}

    @app.post("/print")
    def print_pdf(
        pdf: Annotated[bytes, Body(media_type=PDF_MEDIA_TYPE)],
        _: Annotated[None, Depends(require_service_auth)],
        job_id: Annotated[UUID, Header(alias="X-Print-Job-Id")],
        idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
        printer_name: Annotated[str, Header(alias="X-Printer-Name")],
        copies: Annotated[int, Header(alias="X-Copies")],
        content_type: Annotated[str | None, Header(alias="Content-Type")] = None,
    ) -> dict[str, str]:
        nonlocal registry
        if content_type != PDF_MEDIA_TYPE:
            raise HTTPException(415, "PRINT_AGENT_INVALID_PDF")
        if printer_name not in settings.allowed_printers:
            raise HTTPException(409, "PRINT_AGENT_PRINTER_NOT_ALLOWED")
        if copies != 2:
            raise HTTPException(409, "PRINT_AGENT_INVALID_COPIES")
        if len(pdf) > settings.max_pdf_bytes:
            raise HTTPException(413, "PRINT_AGENT_PDF_TOO_LARGE")
        if not pdf.startswith(b"%PDF-"):
            raise HTTPException(422, "PRINT_AGENT_INVALID_PDF")
        fingerprint = hashlib.sha256(pdf).hexdigest()
        normalized_job_id = str(job_id)
        normalized_key = str(idempotency_key)
        if registry is None:
            registry = DurablePrintRegistry(settings.registry_path)
        record, is_new = registry.begin_once(
            idempotency_key=normalized_key,
            job_id=normalized_job_id,
            pdf_fingerprint=fingerprint,
            printer_name=printer_name,
            copies=copies,
        )
        if not _same_payload(
            record,
            job_id=normalized_job_id,
            pdf_fingerprint=fingerprint,
            printer_name=printer_name,
            copies=copies,
        ):
            raise HTTPException(409, "PRINT_AGENT_IDEMPOTENCY_CONFLICT")
        if not is_new:
            if record.state == "PRINTED":
                return {"status": "PRINTED", "result_code": "PRINTED"}
            if record.state == "PROCESSING":
                raise HTTPException(409, "PRINT_AGENT_IDEMPOTENCY_UNCERTAIN")
            raise HTTPException(502, record.result_code or "PRINT_AGENT_BACKEND_FAILED")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(pdf)
                temporary_path = Path(handle.name)
            backend.print_pdf(temporary_path, printer_name, copies)
        except PrintBackendUncertainError as error:
            # The process may already have submitted to the spooler. Keep the
            # durable PROCESSING marker so this key can never print again.
            raise HTTPException(502, "PRINT_AGENT_BACKEND_FAILED") from error
        except PrintBackendError as error:
            registry.finish(
                normalized_key,
                state="FAILED",
                result_code="PRINT_AGENT_BACKEND_FAILED",
            )
            raise HTTPException(502, "PRINT_AGENT_BACKEND_FAILED") from error
        except Exception as error:
            # PROCESSING is intentionally preserved: the backend outcome may
            # be unknown, so delivery of this key must not print again.
            raise HTTPException(502, "PRINT_AGENT_BACKEND_FAILED") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        registry.finish(normalized_key, state="PRINTED", result_code="PRINTED")
        return {"status": "PRINTED", "result_code": "PRINTED"}

    return app


app = create_app()
