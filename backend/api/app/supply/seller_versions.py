"""Confirmed Seller payload stays on the request; pending edits never replace it."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.models.supply import SupplyRequest, SupplyRequestCycle


def confirmed_snapshot(item: SupplyRequest) -> dict:
    return {
        "version": item.version,
        "raw_input": item.raw_input,
        "submitted_at": item.submitted_at.isoformat(),
        "lines": [{"id": str(line.id), "position": line.position, "raw_text": line.raw_text}
                  for line in item.lines],
    }


def finalize_seller_requests(
    db: Session, cycle: SupplyRequestCycle, *, correlation_id: str | None = None,
) -> None:
    """Run inside the cycle-close transaction, after locking the cycle first."""
    requests = db.scalars(select(SupplyRequest).where(
        SupplyRequest.tenant_id == cycle.tenant_id,
        SupplyRequest.cycle_id == cycle.id,
        SupplyRequest.seller_confirmed_snapshot.is_not(None),
        SupplyRequest.seller_finalized_at.is_(None),
    ).order_by(SupplyRequest.id).with_for_update().execution_options(populate_existing=True)).all()
    for item in requests:
        snapshot = item.seller_confirmed_snapshot
        if snapshot is None:
            continue
        discarded = item.seller_draft_input is not None
        before = {"version": item.version, "draft_pending": discarded}
        item.seller_draft_input = None
        item.seller_finalized_at = datetime.now(timezone.utc)
        item.version += 1
        record_audit_event(
            db, tenant_id=cycle.tenant_id, event_type="SUPPLY_REQUEST_SELLER_FINALIZED",
            entity_type="SupplyRequest", entity_id=item.id, operation="FINALIZE",
            source="SYSTEM", correlation_id=correlation_id, before=before,
            after={"version": item.version, "confirmed_version": snapshot["version"],
                   "draft_pending": False, "draft_discarded": discarded,
                   "finalized_at": item.seller_finalized_at},
        )
