from collections import OrderedDict, deque
from datetime import datetime, timezone
from ipaddress import ip_address
from threading import Lock
from time import monotonic
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.supply import SupplyRequest, SupplyRequestCycle
from app.schemas.supply import (
    PublicSupplyCycleRead,
    PublicSupplyDepartmentRead,
    PublicSupplyExpectedVersion,
    PublicSupplyLinesUpdate,
    PublicSupplyRequestCreate,
    PublicSupplyRequestCreated,
    PublicSupplyRequestRead,
    PublicSupplyScheduleRead,
    PublicSupplySubmit,
)
from app.supply.public_service import (
    PublicSupplyRateLimitError,
    PublicSupplyCycleAmbiguousError,
    PublicSupplyUnrecognizedLinesError,
    create_public_request,
    get_public_request,
    hash_public_token,
    hash_source_ip,
    list_public_cycles,
    list_public_departments,
    list_public_schedule_summaries,
    recognize_public_request,
    replace_public_request_lines,
    submit_public_request,
)
from app.supply.service import (
    DepartmentNotFoundError,
    DuplicateSupplyRequestError,
    InactiveDepartmentError,
    PublicNumberGenerationError,
    SupplyRequestCycleUnavailableError,
    SupplyRequestDuplicatesPresentError,
    SupplyRequestNotFoundError,
    SupplyRequestStateError,
    SupplyRequestVersionConflictError,
)


MAX_PUBLIC_BODY_BYTES = 24_000
TOKEN_RATE_LIMIT = 120
TOKEN_RATE_WINDOW_SECONDS = 300.0
TOKEN_RATE_MAX_KEYS = 10_000


class _PublicBodyLimitRoute(APIRoute):
    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def limited_handler(request: Request):
            raw_length = request.headers.get("content-length")
            if (
                request.method in {"POST", "PUT"}
                and (
                    (
                        raw_length
                        and raw_length.isdigit()
                        and int(raw_length) > MAX_PUBLIC_BODY_BYTES
                    )
                    or len(await request.body()) > MAX_PUBLIC_BODY_BYTES
                )
            ):
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "detail": {
                            "code": "SUPPLY_REQUEST_TOO_LARGE",
                            "message": "Заявка слишком большая",
                        }
                    },
                )
            return await original_handler(request)

        return limited_handler


router = APIRouter(
    prefix="/public/supply",
    tags=["public-supply"],
    route_class=_PublicBodyLimitRoute,
)


class _SingleInstanceTokenGuard:
    """Temporary guard for the current single API instance."""

    def __init__(self) -> None:
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, token_hash: str) -> None:
        now = monotonic()
        with self._lock:
            events = self._events.get(token_hash)
            if events is None:
                if len(self._events) >= TOKEN_RATE_MAX_KEYS:
                    self._events.popitem(last=False)
                events = deque()
                self._events[token_hash] = events
            else:
                self._events.move_to_end(token_hash)
            while events and events[0] <= now - TOKEN_RATE_WINDOW_SECONDS:
                events.popleft()
            if len(events) >= TOKEN_RATE_LIMIT:
                raise PublicSupplyRateLimitError
            events.append(now)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


token_rate_guard = _SingleInstanceTokenGuard()


def _check_token_rate(token: str) -> None:
    try:
        token_rate_guard.check(hash_public_token(token))
    except PublicSupplyRateLimitError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "SUPPLY_RATE_LIMITED",
                "message": "Слишком много запросов. Попробуйте немного позже",
            },
        ) from error


def _request_source_ip_hash(request: Request) -> str | None:
    if request.client is None:
        return None
    try:
        address = ip_address(request.client.host)
    except ValueError:
        return None
    if not (address.is_global or address.is_loopback):
        return None
    return hash_source_ip(address.compressed)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "SUPPLY_PUBLIC_REQUEST_NOT_FOUND",
            "message": "Заявка не найдена или срок доступа истёк",
        },
    )


def _cycle_payload(
    cycle: SupplyRequestCycle,
    *,
    now: datetime,
) -> dict:
    effective_close = cycle.hard_closes_at or cycle.closes_at
    if effective_close.tzinfo is None:
        effective_close = effective_close.replace(tzinfo=timezone.utc)
    return {
        "id": cycle.id,
        "direction": cycle.direction,
        "cycle_date": cycle.cycle_date,
        "opens_at": cycle.opens_at,
        "closes_at": cycle.closes_at,
        "hard_closes_at": cycle.hard_closes_at,
        "effective_closes_at": effective_close,
        "server_now": now,
        "seconds_until_close": max(
            0,
            int((effective_close - now).total_seconds()),
        ),
    }


def _line_message(match_status: str, duplicate_status: str) -> str:
    if duplicate_status in {"SUSPECTED", "CONFIRMED"}:
        return "Возможный дубль — измените заявку перед отправкой"
    if match_status == "MATCHED":
        return "Распознано"
    return "Требует проверки"


def _request_payload(
    supply_request: SupplyRequest,
    *,
    now: datetime,
    public_token: str | None = None,
) -> dict:
    result = {
        "request_number": supply_request.public_number,
        "department": supply_request.department,
        "direction": supply_request.direction,
        "cycle": _cycle_payload(supply_request.cycle, now=now),
        "status": supply_request.status,
        "version": supply_request.version,
        "author_name": supply_request.public_author_name,
        "submitted_at": supply_request.submitted_at,
        "expires_at": supply_request.public_token_expires_at,
        "lines": [
            {
                "id": line.id,
                "raw_text": line.raw_text,
                "parsed_name": line.parsed_name,
                "parsed_quantity": line.parsed_quantity,
                "parsed_unit": (
                    line.parsed_unit.short_name_ru if line.parsed_unit else None
                ),
                "matched_product_name": (
                    line.product.name if line.product else None
                ),
                "requested_quantity": line.quantity,
                "requested_unit": (
                    line.requested_unit.short_name_ru
                    if line.requested_unit
                    else None
                ),
                "confirmed_quantity": line.planned_total,
                "fulfilled_quantity": line.fulfilled_total,
                "unresolved_quantity": line.unresolved_quantity,
                "debt_quantity": (
                    line.debt_link.contributed_quantity
                    if line.debt_link else 0
                ),
                "match_status": line.match_status,
                "duplicate_status": line.duplicate_status,
                "public_message": _line_message(
                    line.match_status,
                    line.duplicate_status,
                ),
            }
            for line in supply_request.lines
        ],
    }
    if public_token is not None:
        result["public_token"] = public_token
    return result


def _mutating_error(error: Exception) -> HTTPException:
    if isinstance(error, SupplyRequestNotFoundError):
        return _not_found()
    if isinstance(error, SupplyRequestVersionConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_VERSION_CONFLICT",
                "message": "Заявка уже изменилась. Обновите страницу",
                "current_version": error.current_version,
            },
        )
    if isinstance(error, SupplyRequestCycleUnavailableError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_CYCLE_CLOSED",
                "message": "Приём заявок для этого цикла завершён",
            },
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "SUPPLY_REQUEST_NOT_EDITABLE",
            "message": "Эту заявку больше нельзя изменить",
        },
    )


@router.get(
    "/departments",
    response_model=list[PublicSupplyDepartmentRead],
)
def read_public_departments(
    db: Annotated[Session, Depends(get_db)],
):
    return list_public_departments(db)


@router.get(
    "/request-cycles",
    response_model=list[PublicSupplyCycleRead],
)
def read_public_cycles(
    db: Annotated[Session, Depends(get_db)],
    department_id: UUID | None = None,
    direction_id: UUID | None = None,
):
    now = datetime.now(timezone.utc)
    return [
        _cycle_payload(cycle, now=now)
        for cycle in list_public_cycles(
            db,
            department_id=department_id,
            direction_id=direction_id,
            now=now,
        )
    ]


@router.get(
    "/schedule",
    response_model=list[PublicSupplyScheduleRead],
)
def read_public_schedule(
    db: Annotated[Session, Depends(get_db)],
):
    return [
        {"summary": summary}
        for summary in list_public_schedule_summaries(db)
    ]


@router.post(
    "/requests",
    response_model=PublicSupplyRequestCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    request: Request,
    payload: PublicSupplyRequestCreate,
    db: Annotated[Session, Depends(get_db)],
):
    now = datetime.now(timezone.utc)
    try:
        supply_request, token = create_public_request(
            db,
            payload,
            source_ip_hash=_request_source_ip_hash(request),
            now=now,
        )
    except DuplicateSupplyRequestError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_ALREADY_EXISTS",
                "message": "Для этого подразделения заявка уже создана",
            },
        ) from error
    except PublicSupplyRateLimitError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "SUPPLY_RATE_LIMITED",
                "message": "Слишком много заявок. Попробуйте немного позже",
            },
        ) from error
    except (DepartmentNotFoundError, InactiveDepartmentError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "SUPPLY_DEPARTMENT_UNAVAILABLE",
                "message": "Выбранное подразделение недоступно",
            },
        ) from error
    except SupplyRequestCycleUnavailableError as error:
        raise _mutating_error(error) from error
    except PublicSupplyCycleAmbiguousError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_CYCLE_AMBIGUOUS",
                "message": (
                    "Сейчас доступно несколько направлений. "
                    "Обратитесь к снабжению"
                ),
            },
        ) from error
    except PublicNumberGenerationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_CREATE_CONFLICT",
                "message": "Не удалось создать заявку. Попробуйте ещё раз",
            },
        ) from error
    return _request_payload(supply_request, now=now, public_token=token)


@router.get(
    "/requests/{public_token}",
    response_model=PublicSupplyRequestRead,
)
def read_request(
    public_token: str,
    db: Annotated[Session, Depends(get_db)],
):
    _check_token_rate(public_token)
    now = datetime.now(timezone.utc)
    try:
        supply_request = get_public_request(db, public_token, now=now)
    except SupplyRequestNotFoundError as error:
        raise _not_found() from error
    return _request_payload(supply_request, now=now)


@router.post(
    "/requests/{public_token}/recognize",
    response_model=PublicSupplyRequestRead,
)
def recognize_request(
    public_token: str,
    payload: PublicSupplyExpectedVersion,
    db: Annotated[Session, Depends(get_db)],
):
    _check_token_rate(public_token)
    now = datetime.now(timezone.utc)
    try:
        supply_request = recognize_public_request(
            db,
            public_token,
            expected_version=payload.expected_version,
            now=now,
        )
    except (
        SupplyRequestNotFoundError,
        SupplyRequestVersionConflictError,
        SupplyRequestCycleUnavailableError,
        SupplyRequestStateError,
    ) as error:
        raise _mutating_error(error) from error
    return _request_payload(supply_request, now=now)


@router.put(
    "/requests/{public_token}/lines",
    response_model=PublicSupplyRequestRead,
)
def update_request_lines(
    public_token: str,
    payload: PublicSupplyLinesUpdate,
    db: Annotated[Session, Depends(get_db)],
):
    _check_token_rate(public_token)
    now = datetime.now(timezone.utc)
    try:
        supply_request = replace_public_request_lines(
            db,
            public_token,
            payload,
            now=now,
        )
    except (
        SupplyRequestNotFoundError,
        SupplyRequestVersionConflictError,
        SupplyRequestCycleUnavailableError,
        SupplyRequestStateError,
    ) as error:
        raise _mutating_error(error) from error
    return _request_payload(supply_request, now=now)


@router.post(
    "/requests/{public_token}/submit",
    response_model=PublicSupplyRequestRead,
)
def submit_request(
    public_token: str,
    payload: PublicSupplySubmit,
    db: Annotated[Session, Depends(get_db)],
):
    _check_token_rate(public_token)
    now = datetime.now(timezone.utc)
    try:
        supply_request = submit_public_request(
            db,
            public_token,
            expected_version=payload.expected_version,
            confirm_unrecognized=payload.confirm_unrecognized,
            now=now,
        )
    except PublicSupplyUnrecognizedLinesError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_UNRECOGNIZED_CONFIRMATION_REQUIRED",
                "message": "Подтвердите отправку нераспознанных строк",
                "unrecognized_line_ids": [
                    str(line_id) for line_id in error.line_ids
                ],
            },
        ) from error
    except SupplyRequestDuplicatesPresentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SUPPLY_REQUEST_DUPLICATES_PRESENT",
                "message": "Устраните возможные дубли перед отправкой",
            },
        ) from error
    except (
        SupplyRequestNotFoundError,
        SupplyRequestVersionConflictError,
        SupplyRequestCycleUnavailableError,
        SupplyRequestStateError,
    ) as error:
        raise _mutating_error(error) from error
    return _request_payload(supply_request, now=now)
