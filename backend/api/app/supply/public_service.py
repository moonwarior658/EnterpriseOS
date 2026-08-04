from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, lazyload

from app.core.config import settings
from app.models.automation import AutomationSchedule
from app.models.supply import (
    Department,
    SupplyDepartmentProductMapping,
    SupplyProduct,
    SupplyRequest,
    SupplyRequestCycle,
    SupplyRequestDirection,
    SupplyRequestLine,
)
from app.schemas.supply import (
    PublicSupplyClarificationSelect,
    PublicSupplyRequestCreate,
    PublicSupplyLinesUpdate,
)
from app.supply.service import (
    DuplicateSupplyRequestError,
    PublicNumberGenerationError,
    SupplyRequestCycleUnavailableError,
    SupplyRequestDuplicatesPresentError,
    SupplyRequestNotFoundError,
    SupplyRequestStateError,
    SupplyRequestVersionConflictError,
    _apply_duplicate_detection,
    _as_aware_utc,
    _get_department,
    _next_public_number,
    _recognize_line,
    _request_options,
    _validate_cycle_for_new_request,
)
from app.supply.normalization import normalize_product_text


PUBLIC_TOKEN_TECHNICAL_GRACE = timedelta(hours=24)
PUBLIC_CREATE_RATE_WINDOW = timedelta(minutes=10)
PUBLIC_CREATE_RATE_LIMIT = 5


class PublicSupplyUnrecognizedLinesError(ValueError):
    def __init__(self, line_ids: list[UUID]):
        self.line_ids = line_ids
        super().__init__("Unrecognized supply lines require confirmation")


class PublicSupplyRateLimitError(ValueError):
    pass


class PublicSupplyCycleAmbiguousError(ValueError):
    pass


def hash_public_token(token: str) -> str:
    secret = settings.jwt_secret_key.encode("utf-8")
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_source_ip(client_host: str | None) -> str | None:
    if not client_host:
        return None
    secret = settings.jwt_secret_key.encode("utf-8")
    return hmac.new(
        secret,
        f"supply-ip:{client_host}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def list_public_departments(session: Session) -> list[Department]:
    return list(
        session.scalars(
            select(Department)
            .where(
                Department.tenant_id == settings.default_tenant_id,
                Department.is_active.is_(True),
            )
            .order_by(Department.display_order.asc(), Department.code.asc())
        ).all()
    )


def list_public_cycles(
    session: Session,
    *,
    department_id: UUID | None,
    direction_id: UUID | None,
    now: datetime,
) -> list[SupplyRequestCycle]:
    if department_id is not None:
        department = session.scalar(
            select(Department).where(
                Department.id == department_id,
                Department.tenant_id == settings.default_tenant_id,
                Department.is_active.is_(True),
            )
        )
        if department is None:
            return []
    filters = [
        SupplyRequestCycle.tenant_id == settings.default_tenant_id,
        SupplyRequestCycle.status == "OPEN",
        SupplyRequestCycle.opens_at <= now,
        SupplyRequestDirection.tenant_id == settings.default_tenant_id,
        SupplyRequestDirection.is_active.is_(True),
    ]
    if direction_id is not None:
        filters.append(SupplyRequestCycle.direction_id == direction_id)
    cycles = session.scalars(
        select(SupplyRequestCycle)
        .join(SupplyRequestDirection)
        .where(*filters)
        .options(joinedload(SupplyRequestCycle.direction))
        .order_by(
            SupplyRequestCycle.cycle_date.asc(),
            SupplyRequestDirection.display_order.asc(),
        )
    ).all()
    return [
        cycle
        for cycle in cycles
        if now <= _as_aware_utc(cycle.hard_closes_at or cycle.closes_at)
    ]


_WEEKDAY_NAMES = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def list_public_schedule_summaries(session: Session) -> list[str]:
    schedules = session.scalars(
        select(AutomationSchedule)
        .where(
            AutomationSchedule.tenant_id == settings.default_tenant_id,
            AutomationSchedule.automation_type
            == "supply.ensure_request_cycle",
            AutomationSchedule.is_enabled.is_(True),
        )
        .order_by(AutomationSchedule.id.asc())
    ).all()
    direction_codes = {
        str(schedule.payload.get("direction_code", "")).strip()
        for schedule in schedules
    }
    directions = session.scalars(
        select(SupplyRequestDirection).where(
            SupplyRequestDirection.tenant_id == settings.default_tenant_id,
            SupplyRequestDirection.code.in_(direction_codes),
        )
    ).all() if direction_codes else []
    direction_names = {item.code: item.name for item in directions}
    summaries: list[str] = []
    for schedule in schedules:
        config = schedule.schedule_config
        payload = schedule.payload
        if config.get("type") != "weekly":
            continue
        weekdays = [
            _WEEKDAY_NAMES[value]
            for value in config.get("weekdays", [])
            if isinstance(value, int) and 0 <= value < len(_WEEKDAY_NAMES)
        ]
        if not weekdays:
            continue
        direction_code = str(payload.get("direction_code", "")).strip()
        direction_name = direction_names.get(direction_code)
        if not direction_name:
            continue
        close_time = str(payload.get("closes_time", "")).strip()
        hard_close_time = str(payload.get("hard_closes_time", "")).strip()
        if not close_time or not hard_close_time:
            continue
        hard_suffix = (
            " следующего дня"
            if payload.get("hard_close_next_day") is True
            else ""
        )
        summaries.append(
            f"{direction_name} — {' и '.join(weekdays)}; "
            f"приём до {close_time}; окончательное закрытие до "
            f"{hard_close_time}{hard_suffix}."
        )
    return summaries


def _get_public_cycle_for_create(
    session: Session,
    cycle_id: UUID | None,
    *,
    department_id: UUID,
    now: datetime,
) -> SupplyRequestCycle:
    if cycle_id is None:
        cycles = list_public_cycles(
            session,
            department_id=department_id,
            direction_id=None,
            now=now,
        )
        if not cycles:
            raise SupplyRequestCycleUnavailableError
        if len(cycles) > 1:
            raise PublicSupplyCycleAmbiguousError
        return cycles[0]
    cycle = session.scalar(
        select(SupplyRequestCycle)
        .where(
            SupplyRequestCycle.id == cycle_id,
            SupplyRequestCycle.tenant_id == settings.default_tenant_id,
        )
        .options(joinedload(SupplyRequestCycle.direction))
    )
    if cycle is None or not cycle.direction.is_active:
        raise SupplyRequestCycleUnavailableError
    _validate_cycle_for_new_request(
        cycle,
        direction_id=cycle.direction_id,
        now=now,
    )
    return cycle


def _assert_draft_and_open(
    supply_request: SupplyRequest,
    *,
    now: datetime,
) -> None:
    if supply_request.status != "DRAFT" or supply_request.cycle is None:
        raise SupplyRequestStateError
    _validate_cycle_for_new_request(
        supply_request.cycle,
        direction_id=supply_request.direction_id,
        now=now,
    )


def _get_public_request_statement(token_hash: str):
    return (
        select(SupplyRequest)
        .where(
            SupplyRequest.tenant_id == settings.default_tenant_id,
            SupplyRequest.public_token_hash == token_hash,
        )
        .options(*_request_options())
    )


def get_public_request(
    session: Session,
    token: str,
    *,
    now: datetime | None = None,
) -> SupplyRequest:
    current_time = now or datetime.now(timezone.utc)
    supply_request = session.scalar(
        _get_public_request_statement(hash_public_token(token))
    )
    if (
        supply_request is None
        or supply_request.public_token_expires_at is None
        or _as_aware_utc(supply_request.public_token_expires_at) <= current_time
    ):
        raise SupplyRequestNotFoundError
    return supply_request


def _get_public_request_for_update(
    session: Session,
    token: str,
    *,
    expected_version: int,
    now: datetime,
) -> SupplyRequest:
    supply_request = session.scalar(
        select(SupplyRequest)
        .where(
            SupplyRequest.tenant_id == settings.default_tenant_id,
            SupplyRequest.public_token_hash == hash_public_token(token),
        )
        .options(lazyload("*"))
        .with_for_update(of=SupplyRequest)
    )
    if (
        supply_request is None
        or supply_request.public_token_expires_at is None
        or _as_aware_utc(supply_request.public_token_expires_at) <= now
    ):
        raise SupplyRequestNotFoundError
    if supply_request.version != expected_version:
        raise SupplyRequestVersionConflictError(
            supply_request.version,
            expected_version,
        )
    return session.scalar(
        select(SupplyRequest)
        .where(SupplyRequest.id == supply_request.id)
        .options(*_request_options())
        .execution_options(populate_existing=True)
    )


def create_public_request(
    session: Session,
    payload: PublicSupplyRequestCreate,
    *,
    source_ip_hash: str | None,
    now: datetime | None = None,
) -> tuple[SupplyRequest, str]:
    current_time = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    token_hash = hash_public_token(token)
    try:
        if source_ip_hash is not None:
            recent_count = session.scalar(
                select(func.count())
                .select_from(SupplyRequest)
                .where(
                    SupplyRequest.source_ip_hash == source_ip_hash,
                    SupplyRequest.public_created_at
                    >= current_time - PUBLIC_CREATE_RATE_WINDOW,
                )
            )
            if int(recent_count or 0) >= PUBLIC_CREATE_RATE_LIMIT:
                raise PublicSupplyRateLimitError
        department = _get_department(session, payload.department_id)
        cycle = _get_public_cycle_for_create(
            session,
            payload.cycle_id,
            department_id=department.id,
            now=current_time,
        )
        existing = session.scalar(
            select(SupplyRequest).where(
                SupplyRequest.tenant_id == settings.default_tenant_id,
                SupplyRequest.department_id == department.id,
                SupplyRequest.direction_id == cycle.direction_id,
                SupplyRequest.cycle_id == cycle.id,
            )
        )
        if existing is not None:
            raise DuplicateSupplyRequestError(
                existing.id,
                existing.public_number,
            )
        supply_request = SupplyRequest(
            tenant_id=settings.default_tenant_id,
            public_number=_next_public_number(
                session,
                department_code=department.code,
                direction_code=cycle.direction.code,
                now=current_time,
            ),
            department_id=department.id,
            direction_id=cycle.direction_id,
            cycle_id=cycle.id,
            status="DRAFT",
            source_type="PUBLIC_FORM",
            raw_input=payload.multiline_text,
            version=1,
            created_by_user_id=None,
            public_token_hash=token_hash,
            public_token_expires_at=_as_aware_utc(
                cycle.hard_closes_at or cycle.closes_at
            )
            + PUBLIC_TOKEN_TECHNICAL_GRACE,
            public_author_name=payload.author_name or None,
            public_author_phone=payload.author_phone,
            source_ip_hash=source_ip_hash,
            public_created_at=current_time,
            lines=[
                SupplyRequestLine(position=index, raw_text=line)
                for index, line in enumerate(
                    payload.multiline_text.splitlines(),
                    start=1,
                )
            ],
        )
        session.add(supply_request)
        session.flush()
        for line in supply_request.lines:
            _recognize_line(
                session,
                line,
                department_id=department.id,
                request_created_at=supply_request.created_at,
                now=current_time,
            )
        _apply_duplicate_detection(supply_request, supply_request.lines)
        session.flush()
        session.commit()
    except DuplicateSupplyRequestError:
        session.rollback()
        raise
    except IntegrityError as error:
        session.rollback()
        message = str(error.orig).lower()
        if "department" in message and "direction" in message and "cycle" in message:
            raise DuplicateSupplyRequestError(UUID(int=0), "") from error
        raise PublicNumberGenerationError from error
    except Exception:
        session.rollback()
        raise
    return get_public_request(session, token, now=current_time), token


def recognize_public_request(
    session: Session,
    token: str,
    *,
    expected_version: int,
    now: datetime | None = None,
) -> SupplyRequest:
    current_time = now or datetime.now(timezone.utc)
    supply_request = _get_public_request_for_update(
        session,
        token,
        expected_version=expected_version,
        now=current_time,
    )
    _assert_draft_and_open(supply_request, now=current_time)
    lines = list(supply_request.lines)
    before = [
        (
            line.parsed_name,
            line.parsed_quantity,
            line.parsed_unit_id,
            line.product_id,
            line.requested_unit_id,
            line.quantity,
            line.match_status,
            line.match_method,
            line.match_confidence,
            line.duplicate_group_id,
            line.duplicate_status,
        )
        for line in lines
    ]
    previous_matched_at = [line.matched_at for line in lines]
    for line in lines:
        if line.match_method != "MANUAL":
            _recognize_line(
                session,
                line,
                department_id=supply_request.department_id,
                request_created_at=supply_request.created_at,
                now=current_time,
            )
    _apply_duplicate_detection(supply_request, lines)
    after = [
        (
            line.parsed_name,
            line.parsed_quantity,
            line.parsed_unit_id,
            line.product_id,
            line.requested_unit_id,
            line.quantity,
            line.match_status,
            line.match_method,
            line.match_confidence,
            line.duplicate_group_id,
            line.duplicate_status,
        )
        for line in lines
    ]
    changed = before != after
    if changed:
        supply_request.version += 1
    else:
        for line, matched_at in zip(lines, previous_matched_at, strict=True):
            line.matched_at = matched_at
    try:
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_public_request(session, token, now=current_time)


def replace_public_request_lines(
    session: Session,
    token: str,
    payload: PublicSupplyLinesUpdate,
    *,
    now: datetime | None = None,
) -> SupplyRequest:
    current_time = now or datetime.now(timezone.utc)
    supply_request = _get_public_request_for_update(
        session,
        token,
        expected_version=payload.expected_version,
        now=current_time,
    )
    _assert_draft_and_open(supply_request, now=current_time)
    try:
        supply_request.lines.clear()
        session.flush()
        supply_request.raw_input = payload.multiline_text
        supply_request.lines = [
            SupplyRequestLine(position=index, raw_text=line)
            for index, line in enumerate(
                payload.multiline_text.splitlines(),
                start=1,
            )
        ]
        session.flush()
        for line in supply_request.lines:
            _recognize_line(
                session,
                line,
                department_id=supply_request.department_id,
                request_created_at=supply_request.created_at,
                now=current_time,
            )
        _apply_duplicate_detection(supply_request, supply_request.lines)
        supply_request.version += 1
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_public_request(session, token, now=current_time)


def list_public_clarification_options(
    session: Session,
    *,
    department_id: UUID,
    phrase: str | None,
) -> list[SupplyProduct]:
    if not phrase:
        return []
    normalized_phrase = normalize_product_text(phrase)
    current_mapping = session.scalar(
        select(SupplyDepartmentProductMapping.id).where(
            SupplyDepartmentProductMapping.tenant_id
            == settings.default_tenant_id,
            SupplyDepartmentProductMapping.department_id == department_id,
            SupplyDepartmentProductMapping.normalized_phrase
            == normalized_phrase,
        )
    )
    if current_mapping is not None:
        return []
    products = list(session.scalars(
        select(SupplyProduct)
        .join(
            SupplyDepartmentProductMapping,
            SupplyDepartmentProductMapping.product_id == SupplyProduct.id,
        )
        .where(
            SupplyDepartmentProductMapping.tenant_id
            == settings.default_tenant_id,
            SupplyDepartmentProductMapping.normalized_phrase
            == normalized_phrase,
            SupplyProduct.tenant_id == settings.default_tenant_id,
            SupplyProduct.is_active.is_(True),
        )
        .distinct()
        .order_by(SupplyProduct.name.asc(), SupplyProduct.id.asc())
    ).all())
    return products if len(products) > 1 else []


def select_public_line_clarification(
    session: Session,
    token: str,
    *,
    line_id: UUID,
    payload: PublicSupplyClarificationSelect,
    now: datetime | None = None,
) -> SupplyRequest:
    current_time = now or datetime.now(timezone.utc)
    supply_request = _get_public_request_for_update(
        session,
        token,
        expected_version=payload.expected_version,
        now=current_time,
    )
    _assert_draft_and_open(supply_request, now=current_time)
    line = next((item for item in supply_request.lines if item.id == line_id), None)
    if line is None:
        raise SupplyRequestNotFoundError
    options = list_public_clarification_options(
        session,
        department_id=supply_request.department_id,
        phrase=line.parsed_name,
    )
    product = next(
        (item for item in options if item.id == payload.product_id), None
    )
    if product is None or line.parsed_unit_id is None or line.parsed_quantity is None:
        raise SupplyRequestStateError
    line.product_id = product.id
    line.requested_unit_id = line.parsed_unit_id
    line.quantity = line.parsed_quantity
    line.match_status = "MATCHED"
    line.match_method = "MANUAL"
    line.match_confidence = 1
    line.matched_at = current_time
    line.matched_by_user_id = None
    line.match_notes = "Уточнено автором заявки"
    supply_request.version += 1
    session.commit()
    return get_public_request(session, token, now=current_time)


def submit_public_request(
    session: Session,
    token: str,
    *,
    expected_version: int,
    confirm_unrecognized: bool,
    now: datetime | None = None,
) -> SupplyRequest:
    current_time = now or datetime.now(timezone.utc)
    supply_request = _get_public_request_for_update(
        session,
        token,
        expected_version=expected_version,
        now=current_time,
    )
    _assert_draft_and_open(supply_request, now=current_time)
    lines = list(supply_request.lines)
    _apply_duplicate_detection(supply_request, lines)
    duplicate_groups = sorted(
        {
            line.duplicate_group_id
            for line in lines
            if line.duplicate_group_id is not None
            and line.duplicate_status in {"SUSPECTED", "CONFIRMED"}
        },
        key=str,
    )
    if duplicate_groups:
        session.rollback()
        raise SupplyRequestDuplicatesPresentError(duplicate_groups)
    unrecognized = [
        line.id
        for line in lines
        if line.match_status in {"NEEDS_REVIEW", "REJECTED", "UNPROCESSED"}
    ]
    if unrecognized and not confirm_unrecognized:
        session.rollback()
        raise PublicSupplyUnrecognizedLinesError(unrecognized)
    try:
        supply_request.status = "SUBMITTED"
        supply_request.submitted_at = current_time
        supply_request.version += 1
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return get_public_request(session, token, now=current_time)
