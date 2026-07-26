from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.work_request import WorkRequest
from app.schemas.work_request import WorkRequestCreate, WorkRequestStatusUpdate


class WorkRequestNotFoundError(LookupError):
    pass


def list_work_requests(session: Session) -> list[WorkRequest]:
    statement = (
        select(WorkRequest)
        .options(joinedload(WorkRequest.created_by))
        .order_by(WorkRequest.created_at.desc(), WorkRequest.id.desc())
    )
    return list(session.scalars(statement).all())


def create_work_request(
    session: Session,
    payload: WorkRequestCreate,
    *,
    created_by_user_id: int,
) -> WorkRequest:
    work_request = WorkRequest(
        request_type=payload.request_type.value,
        department=payload.department,
        description=payload.description,
        status="new",
        warehouse_category=(
            payload.warehouse_category.value
            if payload.warehouse_category is not None
            else None
        ),
        repair_category=payload.repair_category,
        priority=payload.priority.value if payload.priority is not None else None,
        created_by_user_id=created_by_user_id,
    )

    try:
        session.add(work_request)
        session.flush()
        session.refresh(work_request)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return work_request


def update_work_request_status(
    session: Session,
    request_id: int,
    payload: WorkRequestStatusUpdate,
) -> WorkRequest:
    work_request = session.get(WorkRequest, request_id)

    if work_request is None:
        raise WorkRequestNotFoundError

    try:
        work_request.status = payload.status.value
        session.flush()
        session.refresh(work_request)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return work_request
