from datetime import datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
from app.models.supply import (
    Department,
    SupplyRequest,
    SupplyRequestDirection,
    SupplyRequestLine,
)
from app.schemas.supply import SupplyRequestCreate


PUBLIC_NUMBER_RETRY_LIMIT = 5


class SupplyRequestNotFoundError(LookupError):
    pass


class DepartmentNotFoundError(LookupError):
    pass


class DirectionNotFoundError(LookupError):
    pass


class InactiveDepartmentError(ValueError):
    pass


class InactiveDirectionError(ValueError):
    pass


class SupplyRequestStateError(ValueError):
    pass


class PublicNumberGenerationError(RuntimeError):
    pass


def list_departments(session: Session) -> list[Department]:
    statement = (
        select(Department)
        .where(Department.tenant_id == settings.default_tenant_id)
        .order_by(Department.display_order.asc(), Department.code.asc())
    )
    return list(session.scalars(statement).all())


def list_request_directions(
    session: Session,
) -> list[SupplyRequestDirection]:
    statement = (
        select(SupplyRequestDirection)
        .where(
            SupplyRequestDirection.tenant_id == settings.default_tenant_id
        )
        .order_by(
            SupplyRequestDirection.display_order.asc(),
            SupplyRequestDirection.code.asc(),
        )
    )
    return list(session.scalars(statement).all())


def _request_options():
    return (
        joinedload(SupplyRequest.department),
        joinedload(SupplyRequest.direction),
        selectinload(SupplyRequest.lines),
    )


def get_supply_request(
    session: Session,
    request_id: UUID,
) -> SupplyRequest:
    statement = (
        select(SupplyRequest)
        .where(
            SupplyRequest.id == request_id,
            SupplyRequest.tenant_id == settings.default_tenant_id,
        )
        .options(*_request_options())
    )
    supply_request = session.scalar(statement)
    if supply_request is None:
        raise SupplyRequestNotFoundError
    return supply_request


def list_supply_requests(session: Session) -> list[SupplyRequest]:
    statement = (
        select(SupplyRequest)
        .where(SupplyRequest.tenant_id == settings.default_tenant_id)
        .options(*_request_options())
        .order_by(SupplyRequest.created_at.desc(), SupplyRequest.id.desc())
    )
    return list(session.scalars(statement).all())


def _get_department(session: Session, department_id: UUID) -> Department:
    department = session.scalar(
        select(Department).where(
            Department.id == department_id,
            Department.tenant_id == settings.default_tenant_id,
        )
    )
    if department is None:
        raise DepartmentNotFoundError
    if not department.is_active:
        raise InactiveDepartmentError
    return department


def _get_direction(
    session: Session,
    direction_id: UUID,
) -> SupplyRequestDirection:
    direction = session.scalar(
        select(SupplyRequestDirection).where(
            SupplyRequestDirection.id == direction_id,
            SupplyRequestDirection.tenant_id == settings.default_tenant_id,
        )
    )
    if direction is None:
        raise DirectionNotFoundError
    if not direction.is_active:
        raise InactiveDirectionError
    return direction


def _next_public_number(
    session: Session,
    *,
    department_code: str,
    direction_code: str,
    now: datetime,
) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    business_date = now.astimezone(ZoneInfo(settings.business_timezone))
    prefix = (
        f"ЗАЯВКА-{business_date:%Y%m%d}-"
        f"{department_code}-{direction_code}-"
    )
    existing_numbers = session.scalars(
        select(SupplyRequest.public_number)
        .where(
            SupplyRequest.tenant_id == settings.default_tenant_id,
            SupplyRequest.public_number.like(f"{prefix}%"),
        )
    ).all()
    sequences = [
        int(number.removeprefix(prefix))
        for number in existing_numbers
        if number.removeprefix(prefix).isdigit()
    ]
    sequence = max(sequences, default=0) + 1
    return f"{prefix}{sequence:03d}"


def _is_public_number_conflict(error: IntegrityError) -> bool:
    constraint_name = getattr(
        getattr(error.orig, "diag", None),
        "constraint_name",
        None,
    )
    if constraint_name == "uq_supply_requests_tenant_public_number":
        return True
    message = str(error.orig).lower()
    return (
        "supply_requests.tenant_id" in message
        and "supply_requests.public_number" in message
    )


def create_supply_request(
    session: Session,
    payload: SupplyRequestCreate,
    *,
    created_by_user_id: int | None,
    source_work_request_id: int | None = None,
    now: datetime | None = None,
) -> SupplyRequest:
    number_time = now or datetime.now(timezone.utc)
    for attempt in range(PUBLIC_NUMBER_RETRY_LIMIT):
        try:
            department = _get_department(session, payload.department_id)
            direction = _get_direction(session, payload.direction_id)
            public_number = _next_public_number(
                session,
                department_code=department.code,
                direction_code=direction.code,
                now=number_time,
            )
            supply_request = SupplyRequest(
                tenant_id=settings.default_tenant_id,
                public_number=public_number,
                department_id=department.id,
                direction_id=direction.id,
                status="DRAFT",
                source_type="INTERNAL",
                source_work_request_id=source_work_request_id,
                raw_input=payload.raw_input,
                version=1,
                created_by_user_id=created_by_user_id,
            )
            supply_request.lines = [
                SupplyRequestLine(
                    position=position,
                    raw_text=line.raw_text,
                )
                for position, line in enumerate(payload.lines, start=1)
            ]
            session.add(supply_request)
            session.flush()
            session.commit()
            return get_supply_request(session, supply_request.id)
        except IntegrityError as error:
            session.rollback()
            if (
                _is_public_number_conflict(error)
                and attempt + 1 < PUBLIC_NUMBER_RETRY_LIMIT
            ):
                continue
            raise
        except Exception:
            session.rollback()
            raise

    raise PublicNumberGenerationError


def submit_supply_request(
    session: Session,
    request_id: UUID,
) -> SupplyRequest:
    supply_request = get_supply_request(session, request_id)
    if supply_request.status != "DRAFT":
        raise SupplyRequestStateError
    if not supply_request.lines:
        raise SupplyRequestStateError

    try:
        supply_request.status = "SUBMITTED"
        supply_request.submitted_at = datetime.now(timezone.utc)
        supply_request.version += 1
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise

    return get_supply_request(session, request_id)
