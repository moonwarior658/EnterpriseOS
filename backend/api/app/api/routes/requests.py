from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_admin, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.work_request import WorkRequest
from app.requests.service import (
    WorkRequestNotFoundError,
    create_work_request,
    list_work_requests,
    update_work_request_status,
)
from app.schemas.work_request import (
    WorkRequestCreate,
    WorkRequestRead,
    WorkRequestStatusUpdate,
)


router = APIRouter(prefix="/requests", tags=["requests"])


@router.post(
    "",
    response_model=WorkRequestRead,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: WorkRequestCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> WorkRequest:
    return create_work_request(
        db,
        payload,
        created_by_user_id=current_user.id,
    )


@router.get("", response_model=list[WorkRequestRead])
def read_requests(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[WorkRequest]:
    return list_work_requests(db)


@router.patch("/{request_id}/status", response_model=WorkRequestRead)
def change_request_status(
    request_id: int,
    payload: WorkRequestStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_admin)],
) -> WorkRequest:
    try:
        return update_work_request_status(db, request_id, payload)
    except WorkRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found",
        ) from error
