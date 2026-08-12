from pathlib import Path
from typing import Protocol
import subprocess


class PrintBackendError(RuntimeError):
    pass


class PrintBackendUncertainError(PrintBackendError):
    pass


class PrintBackend(Protocol):
    def print_pdf(self, pdf_path: Path, printer_name: str, copies: int) -> None:
        """Submit a PDF to the operating-system print subsystem."""


class SumatraPdfWindowsBackend:
    """Silent Windows queue backend using pinned SumatraPDF 3.5.2."""

    def __init__(self, executable: Path, *, timeout_seconds: float = 60) -> None:
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def print_pdf(self, pdf_path: Path, printer_name: str, copies: int) -> None:
        if not self._executable.is_file():
            raise PrintBackendError("PRINT_AGENT_BACKEND_FAILED")
        command = [
            str(self._executable),
            "-print-to",
            printer_name,
            "-print-settings",
            f"{copies}x",
            "-silent",
            str(pdf_path),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=self._timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            raise PrintBackendUncertainError(
                "PRINT_AGENT_BACKEND_FAILED"
            ) from error
        except (OSError, subprocess.SubprocessError) as error:
            raise PrintBackendError("PRINT_AGENT_BACKEND_FAILED") from error
        if completed.returncode != 0:
            raise PrintBackendError("PRINT_AGENT_BACKEND_FAILED")
