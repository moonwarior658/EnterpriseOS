from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.api.routes.action_context import action_context_http_error
from app.audit.service import audit_query
from app.core.action_context import ActionContextError
from app.core.authorization import Capability, authorize
from app.db.session import get_db
from app.models.audit import AuditEvent
from app.models.user import User
from app.schemas.audit import AuditEventRead


router = APIRouter(prefix="/audit", tags=["audit"])
def require_audit_reader(db: Session, user: User) -> None:
    try:
        authorize(db, user, Capability.AUDIT_READ)
    except ActionContextError as error:
        raise action_context_http_error(error) from error


@router.get("/events", response_model=list[AuditEventRead])
def list_audit_events(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    entity_type: str | None = None,
    entity_id: str | None = None,
    employee_id: UUID | None = None,
    department_id: UUID | None = None,
    event_type: str | None = None,
    operation: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEvent]:
    require_audit_reader(db, current_user)
    query = audit_query(
        tenant_id=current_user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        employee_id=employee_id,
        department_id=department_id,
        event_type=event_type,
        operation=operation,
        date_from=date_from,
        date_to=date_to,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    response.headers["Cache-Control"] = "no-store"
    return list(db.scalars(
        query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .limit(limit)
        .offset(offset)
    ).all())
