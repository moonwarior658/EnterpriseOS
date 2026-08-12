import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.automation.dispatch import create_automation_execution
from app.integrations.iiko.provider import IikoProvider
from app.models.supply import (
    SupplyPrintJob,
    SupplyPrintJobStatus,
    SupplyPrintPurpose,
    SupplyRequest,
)
from app.schemas.supply import SupplyPrintCallback
from app.supply.iiko_document_pdf import (
    SupplyIikoDocumentPrintError,
    create_iiko_documents_pdf,
)
from app.supply.service import SupplyRequestNotFoundError


PRINT_AUTOMATION_TYPE = "supply.print_job"
PRINT_COPIES = 2
PRODUCTION_PRINTER = "HP LaserJet Pro MFP M125rnw"


class SupplyPrintError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pdf_fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def create_supply_print_job(
    session: Session,
    provider: IikoProvider,
    *,
    tenant_id: str,
    request_id: UUID,
    requested_by_user_id: int,
    printer_name: str,
    purpose: SupplyPrintPurpose = SupplyPrintPurpose.NORMAL,
) -> SupplyPrintJob:
    if printer_name != PRODUCTION_PRINTER:
        raise SupplyPrintError("SUPPLY_PRINT_PRINTER_NOT_ALLOWED")
    request_exists = session.scalar(select(SupplyRequest.id).where(
        SupplyRequest.id == request_id,
        SupplyRequest.tenant_id == tenant_id,
    ))
    if request_exists is None:
        raise SupplyRequestNotFoundError

    try:
        pdf = await create_iiko_documents_pdf(
            session,
            provider,
            tenant_id=tenant_id,
            request_id=request_id,
        )
    except SupplyIikoDocumentPrintError as error:
        raise SupplyPrintError("SUPPLY_PRINT_NO_PRINTABLE_DOCUMENTS") from error

    pdf_fingerprint = _pdf_fingerprint(pdf.content)
    if purpose == SupplyPrintPurpose.NORMAL:
        existing = session.scalar(select(SupplyPrintJob).where(
            SupplyPrintJob.tenant_id == tenant_id,
            SupplyPrintJob.supply_request_id == request_id,
            SupplyPrintJob.pdf_fingerprint == pdf_fingerprint,
            SupplyPrintJob.purpose == SupplyPrintPurpose.NORMAL,
        ))
        if existing is not None:
            existing_id = existing.id
            session.rollback()
            return session.get(SupplyPrintJob, existing_id)

    session.rollback()
    session.begin()
    job_id = uuid4()
    idempotency_key = uuid4()
    queued_at = _utcnow()
    retrieval_path = f"/supply/print-jobs/{job_id}/pdf"
    execution = create_automation_execution(
        session,
        execution_id=idempotency_key,
        automation_type=PRINT_AUTOMATION_TYPE,
        tenant_id=tenant_id,
        scope_type="company",
        scope_id=None,
        recipients=[],
        payload={
            "print_job_id": str(job_id),
            "tenant_id": tenant_id,
            "printer_name": printer_name,
            "copies": PRINT_COPIES,
            "idempotency_key": str(idempotency_key),
            "pdf_fingerprint": pdf_fingerprint,
            "pdf_retrieval": {"method": "GET", "path": retrieval_path},
            "result_callback": {
                "method": "POST",
                "path": f"/supply/print-jobs/{job_id}/callback",
            },
        },
    )
    job = SupplyPrintJob(
        id=job_id,
        tenant_id=tenant_id,
        supply_request_id=request_id,
        iiko_document_write_id=None,
        automation_execution_id=execution.execution_id,
        document_fingerprint=pdf.version_fingerprint,
        pdf_fingerprint=pdf_fingerprint,
        printer_name=printer_name,
        copies=PRINT_COPIES,
        idempotency_key=idempotency_key,
        purpose=purpose,
        status=SupplyPrintJobStatus.QUEUED_FOR_PRINT,
        attempt_count=0,
        requested_by_user_id=requested_by_user_id,
        queued_at=queued_at,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if purpose == SupplyPrintPurpose.NORMAL:
            existing = session.scalar(select(SupplyPrintJob).where(
                SupplyPrintJob.tenant_id == tenant_id,
                SupplyPrintJob.supply_request_id == request_id,
                SupplyPrintJob.pdf_fingerprint == pdf_fingerprint,
                SupplyPrintJob.purpose == SupplyPrintPurpose.NORMAL,
            ))
            if existing is not None:
                existing_id = existing.id
                session.rollback()
                return session.get(SupplyPrintJob, existing_id)
        raise
    session.refresh(job)
    return job


def list_supply_print_jobs(
    session: Session,
    *,
    tenant_id: str,
    request_id: UUID,
) -> list[SupplyPrintJob]:
    request_exists = session.scalar(select(SupplyRequest.id).where(
        SupplyRequest.id == request_id,
        SupplyRequest.tenant_id == tenant_id,
    ))
    if request_exists is None:
        raise SupplyRequestNotFoundError
    return list(session.scalars(
        select(SupplyPrintJob)
        .where(
            SupplyPrintJob.tenant_id == tenant_id,
            SupplyPrintJob.supply_request_id == request_id,
        )
        .order_by(SupplyPrintJob.created_at.desc(), SupplyPrintJob.id.desc())
    ).all())


async def retrieve_supply_print_job_pdf(
    session: Session,
    provider: IikoProvider,
    *,
    job_id: UUID,
) -> bytes:
    job = session.get(SupplyPrintJob, job_id)
    if job is None:
        raise SupplyRequestNotFoundError
    try:
        pdf = await create_iiko_documents_pdf(
            session,
            provider,
            tenant_id=job.tenant_id,
            request_id=job.supply_request_id,
        )
    except SupplyIikoDocumentPrintError as error:
        raise SupplyPrintError("SUPPLY_PRINT_PDF_CHANGED") from error
    if (
        pdf.version_fingerprint != job.document_fingerprint
        or _pdf_fingerprint(pdf.content) != job.pdf_fingerprint
    ):
        raise SupplyPrintError("SUPPLY_PRINT_PDF_CHANGED")
    return pdf.content


def apply_supply_print_callback(
    session: Session,
    *,
    job_id: UUID,
    callback: SupplyPrintCallback,
) -> SupplyPrintJob:
    job = session.scalar(
        select(SupplyPrintJob)
        .where(SupplyPrintJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        raise SupplyRequestNotFoundError
    if job.tenant_id != callback.tenant_id:
        raise SupplyRequestNotFoundError
    if job.status == SupplyPrintJobStatus.PRINTED:
        return job
    if (
        job.status == callback.status
        and job.attempt_count == callback.attempt_count
        and job.last_error_code == callback.error_code
        and job.started_at == callback.started_at
        and job.finished_at == callback.finished_at
    ):
        return job
    if job.status == SupplyPrintJobStatus.PRINT_FAILED:
        raise SupplyPrintError("SUPPLY_PRINT_JOB_ALREADY_FINALIZED")
    job.status = callback.status
    job.attempt_count = max(job.attempt_count, callback.attempt_count)
    job.last_error_code = callback.error_code
    job.started_at = callback.started_at or job.started_at
    job.finished_at = callback.finished_at
    if callback.status in {
        SupplyPrintJobStatus.PRINTED,
        SupplyPrintJobStatus.PRINT_FAILED,
    } and job.finished_at is None:
        job.finished_at = _utcnow()
    session.commit()
    session.refresh(job)
    return job
