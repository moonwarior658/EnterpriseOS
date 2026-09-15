import logging
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.automation.dispatch import create_automation_execution
from app.models.supply import (
    SupplySupplierOrder,
    SupplySupplierOrderDeliveryAttempt,
)
from app.schemas.supplier_order import SupplySupplierOrderDeliveryAttemptRead
from app.supply.supplier_orders import _message_body, _message_subject


SUPPLIER_ORDER_EMAIL_SEND = "supply.supplier_order_email_send"
ACTIVE_DELIVERY_STATUSES = ("PENDING", "DISPATCHED", "SUCCEEDED")
logger = logging.getLogger(__name__)


class SupplierOrderDeliveryStateError(ValueError):
    pass


class SupplierOrderDeliveryPreparationError(ValueError):
    pass


class SupplierOrderDeliveryRetryError(ValueError):
    pass


def delivery_attempt_read(
    attempt: SupplySupplierOrderDeliveryAttempt,
) -> SupplySupplierOrderDeliveryAttemptRead:
    return SupplySupplierOrderDeliveryAttemptRead(
        id=attempt.id,
        attempt_number=attempt.attempt_number,
        status=attempt.status,
        recipient_email=attempt.recipient_email,
        provider_message_id=attempt.provider_message_id,
        error_code=attempt.error_code,
        error_message=attempt.error_message,
        created_at=attempt.created_at,
        dispatched_at=attempt.dispatched_at,
        completed_at=attempt.completed_at,
    )


def _event(name: str, attempt: SupplySupplierOrderDeliveryAttempt) -> None:
    logger.info(
        "supplier_order_email",
        extra={
            "event": name,
            "supplier_order_id": str(attempt.supplier_order_id),
            "delivery_attempt_id": str(attempt.id),
            "attempt_number": attempt.attempt_number,
            "automation_correlation_id": str(attempt.automation_execution_id),
        },
    )


def queue_supplier_order_email(
    session: Session,
    order_id: UUID,
    *,
    tenant_id: str,
    user_id: int,
    retry: bool = False,
) -> SupplySupplierOrderDeliveryAttemptRead:
    order = session.scalar(
        select(SupplySupplierOrder)
        .where(
            SupplySupplierOrder.id == order_id,
            SupplySupplierOrder.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if order is None:
        from app.supply.supplier_orders import SupplierOrderNotFoundError
        raise SupplierOrderNotFoundError
    if order.status != "READY":
        raise SupplierOrderDeliveryStateError
    if not order.lines or order.total_amount <= 0:
        raise SupplierOrderDeliveryPreparationError
    if not all((
        order.recipient_email_snapshot,
        order.recipient_name_snapshot,
        order.responsible_name_snapshot,
        order.responsible_phone_snapshot,
    )):
        raise SupplierOrderDeliveryPreparationError

    active = session.scalar(
        select(SupplySupplierOrderDeliveryAttempt)
        .where(
            SupplySupplierOrderDeliveryAttempt.tenant_id == tenant_id,
            SupplySupplierOrderDeliveryAttempt.supplier_order_id == order.id,
            SupplySupplierOrderDeliveryAttempt.status.in_(ACTIVE_DELIVERY_STATUSES),
        )
        .order_by(SupplySupplierOrderDeliveryAttempt.attempt_number.desc())
    )
    if active is not None:
        return delivery_attempt_read(active)

    latest = session.scalar(
        select(SupplySupplierOrderDeliveryAttempt)
        .where(
            SupplySupplierOrderDeliveryAttempt.tenant_id == tenant_id,
            SupplySupplierOrderDeliveryAttempt.supplier_order_id == order.id,
        )
        .order_by(SupplySupplierOrderDeliveryAttempt.attempt_number.desc())
        .limit(1)
    )
    if retry and (latest is None or latest.status != "FAILED"):
        raise SupplierOrderDeliveryRetryError
    if not retry and latest is not None:
        raise SupplierOrderDeliveryRetryError

    attempt_number = int(session.scalar(
        select(func.coalesce(func.max(SupplySupplierOrderDeliveryAttempt.attempt_number), 0))
        .where(
            SupplySupplierOrderDeliveryAttempt.tenant_id == tenant_id,
            SupplySupplierOrderDeliveryAttempt.supplier_order_id == order.id,
        )
    ) or 0) + 1
    attempt_id = uuid4()
    semantic_key = (
        f"supplier-order-email:{tenant_id}:{order.id}:attempt:{attempt_number}"
    )
    execution_id = uuid5(NAMESPACE_URL, semantic_key)
    payload = {
        "delivery_attempt_id": str(attempt_id),
        "recipient": order.recipient_email_snapshot,
        "subject": _message_subject(order),
        "body_text": _message_body(order),
    }

    try:
        create_automation_execution(
            session,
            automation_type=SUPPLIER_ORDER_EMAIL_SEND,
            tenant_id=tenant_id,
            scope_type="company",
            scope_id=None,
            recipients=[],
            payload=payload,
            execution_id=execution_id,
        )
        attempt = SupplySupplierOrderDeliveryAttempt(
            id=attempt_id,
            tenant_id=tenant_id,
            supplier_order_id=order.id,
            attempt_number=attempt_number,
            status="PENDING",
            recipient_email=order.recipient_email_snapshot,
            subject=payload["subject"],
            body_text=payload["body_text"],
            automation_execution_id=execution_id,
            idempotency_key=semantic_key,
            created_by_user_id=user_id,
        )
        session.add(attempt)
        session.flush()
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(SupplySupplierOrderDeliveryAttempt).where(
                SupplySupplierOrderDeliveryAttempt.tenant_id == tenant_id,
                SupplySupplierOrderDeliveryAttempt.supplier_order_id == order_id,
                SupplySupplierOrderDeliveryAttempt.status.in_(ACTIVE_DELIVERY_STATUSES),
            )
        )
        if existing is not None:
            return delivery_attempt_read(existing)
        raise
    except Exception:
        session.rollback()
        raise

    _event("queued", attempt)
    return delivery_attempt_read(attempt)


def mark_supplier_order_email_dispatched(
    session: Session, execution_id: UUID, *, dispatched_at: datetime,
) -> None:
    attempt = session.scalar(
        select(SupplySupplierOrderDeliveryAttempt)
        .where(SupplySupplierOrderDeliveryAttempt.automation_execution_id == execution_id)
        .with_for_update()
    )
    if attempt is None or attempt.status != "PENDING":
        return
    attempt.status = "DISPATCHED"
    attempt.dispatched_at = dispatched_at
    _event("dispatched", attempt)


def finalize_supplier_order_email(
    session: Session,
    execution_id: UUID,
    *,
    succeeded: bool,
    completed_at: datetime,
    started_at: datetime | None = None,
    provider_message_id: object = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    attempt = session.scalar(
        select(SupplySupplierOrderDeliveryAttempt)
        .where(SupplySupplierOrderDeliveryAttempt.automation_execution_id == execution_id)
        .with_for_update()
    )
    if attempt is None:
        return
    if attempt.status == "SUCCEEDED":
        return
    if attempt.status == "FAILED" and not succeeded:
        return

    order = session.scalar(
        select(SupplySupplierOrder)
        .where(
            SupplySupplierOrder.id == attempt.supplier_order_id,
            SupplySupplierOrder.tenant_id == attempt.tenant_id,
        )
        .with_for_update()
    )
    if order is None:
        return

    if succeeded:
        if order.status not in {"READY", "SENT"}:
            raise SupplierOrderDeliveryStateError
        attempt.status = "SUCCEEDED"
        attempt.dispatched_at = attempt.dispatched_at or started_at or completed_at
        attempt.completed_at = completed_at
        if isinstance(provider_message_id, str) and provider_message_id.strip():
            attempt.provider_message_id = provider_message_id.strip()[:255]
        attempt.error_code = None
        attempt.error_message = None
        if order.status == "READY":
            order.status = "SENT"
            order.sent_at = completed_at
        _event("succeeded", attempt)
        return

    attempt.status = "FAILED"
    attempt.completed_at = completed_at
    attempt.error_code = (error_code or "EMAIL_DELIVERY_FAILED")[:100]
    attempt.error_message = _safe_failure_message(error_message)
    _event("failed", attempt)


def _safe_failure_message(message: str | None) -> str:
    if not message:
        return "Почтовый transport не смог отправить письмо"
    normalized = " ".join(message.split())
    known_messages = {
        "Automation provider authentication failed": (
            "Почтовый transport не настроен или не авторизован"
        ),
        "Automation provider request timed out": (
            "Почтовый transport не ответил вовремя"
        ),
        "Automation provider is unavailable": (
            "Почтовый transport временно недоступен"
        ),
        "Automation provider communication failed": (
            "Не удалось связаться с почтовым transport"
        ),
        "Previous outbox worker claim expired": (
            "Отправка была прервана до подтверждения"
        ),
    }
    if normalized in known_messages:
        return known_messages[normalized]
    unsafe_markers = ("http://", "https://", "postgresql://", "token", "password", "traceback")
    if any(marker in normalized.lower() for marker in unsafe_markers):
        return "Почтовый transport не смог отправить письмо"
    return normalized[:500]
