from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from threading import Lock


@dataclass(frozen=True, slots=True)
class RegistryRecord:
    idempotency_key: str
    job_id: str
    pdf_fingerprint: str
    printer_name: str
    copies: int
    state: str
    result_code: str | None


class DurablePrintRegistry:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._database_path = database_path
        self._lock = Lock()
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS print_registry (
                    idempotency_key TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    pdf_fingerprint TEXT NOT NULL,
                    printer_name TEXT NOT NULL,
                    copies INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    result_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> RegistryRecord:
        return RegistryRecord(
            idempotency_key=row["idempotency_key"],
            job_id=row["job_id"],
            pdf_fingerprint=row["pdf_fingerprint"],
            printer_name=row["printer_name"],
            copies=row["copies"],
            state=row["state"],
            result_code=row["result_code"],
        )

    def begin_once(
        self,
        *,
        idempotency_key: str,
        job_id: str,
        pdf_fingerprint: str,
        printer_name: str,
        copies: int,
    ) -> tuple[RegistryRecord, bool]:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM print_registry WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is not None:
                return self._record(row), False
            connection.execute(
                """
                INSERT INTO print_registry (
                    idempotency_key, job_id, pdf_fingerprint, printer_name,
                    copies, state, result_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'PROCESSING', NULL, ?, ?)
                """,
                (
                    idempotency_key, job_id, pdf_fingerprint, printer_name,
                    copies, now, now,
                ),
            )
            return RegistryRecord(
                idempotency_key=idempotency_key,
                job_id=job_id,
                pdf_fingerprint=pdf_fingerprint,
                printer_name=printer_name,
                copies=copies,
                state="PROCESSING",
                result_code=None,
            ), True

    def finish(self, idempotency_key: str, *, state: str, result_code: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE print_registry
                SET state = ?, result_code = ?, updated_at = ?
                WHERE idempotency_key = ?
                """,
                (state, result_code, now, idempotency_key),
            )
