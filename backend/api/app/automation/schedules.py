from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automation.audit import (
    add_schedule_audit_event,
    schedule_audit_changes,
    schedule_audit_snapshot,
)
from app.automation.schedule_time import calculate_next_run_at
from app.automation.schedule_time import parse_schedule_config
from app.automation.supply_actions import (
    SupplyAutomationActionError,
    require_active_supply_direction,
)
from app.core.config import settings
from app.models.sales import SalesSyncState
from app.models.automation import (
    AutomationSchedule,
    ScheduleAuditEventType,
)
from app.schemas.automation import (
    SUPPLY_ENSURE_REQUEST_CYCLE,
    AutomationScheduleCreate,
    AutomationScheduleUpdate,
    validate_automation_schedule_contract,
)


SCHEDULE_MUTABLE_FIELDS = (
    "name",
    "automation_type",
    "scope_type",
    "scope_id",
    "schedule_config",
    "payload",
    "recipients",
    "timezone",
    "is_enabled",
)


class InvalidScheduleScopeError(ValueError):
    pass


class InvalidAutomationScheduleActionError(ValueError):
    pass


def _validated_action_payload(
    session: Session,
    *,
    automation_type: str,
    schedule_config: object,
    payload: dict[str, object],
    tenant_id: str,
) -> dict[str, object]:
    try:
        if automation_type == "sales.sync_iiko":
            sources = list(session.scalars(select(SalesSyncState.source_id).where(SalesSyncState.tenant_id == tenant_id)))
            if len(sources) != 1:
                raise InvalidAutomationScheduleActionError("Источник данных продаж не настроен однозначно. Обратитесь к администратору")
            if payload and payload.get('source_id') != sources[0]:
                raise InvalidAutomationScheduleActionError("Источник данных продаж не соответствует настройкам компании")
            payload = dict(payload, source_id=sources[0])
        normalized = validate_automation_schedule_contract(
            automation_type,
            parse_schedule_config(schedule_config),
            payload,
        )
        if automation_type == 'products.sync_iiko_costs':
            from app.product_knowledge.costs import CostRefreshPayload, require_verified_schedule
            require_verified_schedule(session,tenant_id,CostRefreshPayload.model_validate(normalized))
        if automation_type == 'products.sync_iiko_prices':
            from app.product_knowledge.price_refresh import PriceRefreshPayload, scope
            scope(session, tenant_id, PriceRefreshPayload.model_validate(normalized))
        if automation_type == SUPPLY_ENSURE_REQUEST_CYCLE:
            require_active_supply_direction(
                session,
                tenant_id=tenant_id,
                direction_code=str(normalized["direction_code"]),
            )
        return normalized
    except InvalidAutomationScheduleActionError:
        raise
    except (SupplyAutomationActionError, ValueError) as error:
        raise InvalidAutomationScheduleActionError(
            "Invalid automation action parameters"
        ) from error


def validate_schedule_scope(
    scope_type: object,
    scope_id: str | None,
) -> None:
    scope_type_value = getattr(scope_type, "value", scope_type)

    if scope_type_value == "company":
        if scope_id is not None:
            raise InvalidScheduleScopeError(
                "Invalid schedule scope: company requires scope_id to be null"
            )
        return

    if scope_type_value not in {"department", "location", "user"}:
        raise InvalidScheduleScopeError(
            f"Invalid schedule scope type: {scope_type_value}"
        )

    if scope_id is None or not scope_id.strip():
        raise InvalidScheduleScopeError(
            "Invalid schedule scope: "
            f"{scope_type_value} requires a non-empty scope_id"
        )


def list_schedules(session: Session) -> list[AutomationSchedule]:
    statement = select(AutomationSchedule).order_by(
        AutomationSchedule.id.asc()
    )
    return session.scalars(statement).all()


def get_schedule(
    session: Session,
    schedule_id: int,
) -> AutomationSchedule | None:
    return session.get(AutomationSchedule, schedule_id)


def product_price_configuration(session, tenant_id):
    from app.models.product_knowledge import ProductKnowledgePriceSnapshot
    from app.product_knowledge.price_refresh import PriceRefreshPayload, scope
    from app.models.supply import Department
    snapshot = session.scalar(select(ProductKnowledgePriceSnapshot).where(
        ProductKnowledgePriceSnapshot.tenant_id == tenant_id)
        .order_by(ProductKnowledgePriceSnapshot.observed_at.desc()).limit(1))
    if snapshot is None:
        raise InvalidAutomationScheduleActionError('Нет опубликованной подтверждённой конфигурации цен K3')
    try:
        policy = PriceRefreshPayload.model_validate({key: snapshot.payload[key] for key in
            ('source_id', 'confirmed_point_ids', 'currency', 'office_evidence')})
        _, links, _ = scope(session, tenant_id, policy)
    except (ValueError, KeyError):
        raise InvalidAutomationScheduleActionError('Подтверждённая конфигурация точек K3 изменилась: требуется проверка') from None
    if links != snapshot.payload['point_links']:
        raise InvalidAutomationScheduleActionError('Подтверждённая конфигурация точек K3 изменилась: требуется проверка')
    return dict(payload=policy.model_dump(mode='json'), points=[dict(id=str(p.id), name=p.name)
        for p in session.scalars(select(Department).where(Department.tenant_id == tenant_id,
            Department.id.in_(policy.confirmed_point_ids)).order_by(Department.name))])


def guard_price_schedule_duplicate(session, tenant_id, automation_type, payload, *, exclude_id=None):
    if automation_type != 'products.sync_iiko_prices':
        return
    # Serialize cooperating creates/updates on the same existing source row.
    session.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == tenant_id,
        SalesSyncState.source_id == payload['source_id']).with_for_update())
    query = select(AutomationSchedule.id).where(AutomationSchedule.tenant_id == tenant_id,
        AutomationSchedule.automation_type == automation_type,
        AutomationSchedule.payload['source_id'].as_string() == payload['source_id'])
    if exclude_id is not None:
        query = query.where(AutomationSchedule.id != exclude_id)
    if session.scalar(query.limit(1)) is not None:
        raise InvalidAutomationScheduleActionError('Регламент обновления цен этого источника уже существует. Откройте существующий регламент')


def create_schedule(
    session: Session,
    payload: AutomationScheduleCreate,
    *,
    created_by_user_id: int,
) -> AutomationSchedule:
    try:
        schedule_config = payload.schedule_config.model_dump(mode="json")
        action_payload = _validated_action_payload(
            session,
            automation_type=payload.automation_type,
            schedule_config=schedule_config,
            payload=payload.payload,
            tenant_id=settings.default_tenant_id,
        )
        guard_price_schedule_duplicate(session, settings.default_tenant_id, payload.automation_type, action_payload)
        next_run_at = (
            calculate_next_run_at(schedule_config, payload.timezone)
            if payload.is_enabled
            else None
        )
        schedule = AutomationSchedule(
            name=payload.name,
            automation_type=payload.automation_type,
            tenant_id=settings.default_tenant_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            schedule_config=schedule_config,
            payload=action_payload,
            recipients=payload.recipients,
            timezone=payload.timezone,
            is_enabled=payload.is_enabled,
            next_run_at=next_run_at,
            created_by_user_id=created_by_user_id,
        )
        session.add(schedule)
        session.flush()
        add_schedule_audit_event(
            session,
            event_type=ScheduleAuditEventType.CREATED,
            actor_user_id=created_by_user_id,
            schedule_id=schedule.id,
            metadata={"fields": schedule_audit_snapshot(schedule)},
        )
        session.flush()
        session.refresh(schedule)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return schedule


def update_schedule(
    session: Session,
    schedule: AutomationSchedule,
    payload: AutomationScheduleUpdate,
    *,
    actor_user_id: int,
) -> AutomationSchedule:
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        return schedule

    final_scope_type = updates.get("scope_type", schedule.scope_type)
    final_scope_id = (
        updates["scope_id"]
        if "scope_id" in updates
        else schedule.scope_id
    )
    validate_schedule_scope(final_scope_type, final_scope_id)
    if updates.get("automation_type", schedule.automation_type) in {"sales.sync_iiko", "sales.finalize_reports", 'products.sync_iiko_prices', 'products.sync_iiko_costs'} and getattr(final_scope_type, 'value', final_scope_type) != 'company':
        raise InvalidAutomationScheduleActionError("Обновление продаж доступно только для всей компании")

    before = schedule_audit_snapshot(schedule)

    try:
        final_is_enabled = updates.get(
            "is_enabled",
            schedule.is_enabled,
        )
        final_schedule_config = updates.get(
            "schedule_config",
            schedule.schedule_config,
        )
        final_automation_type = updates.get(
            "automation_type",
            schedule.automation_type,
        )
        final_payload = updates.get("payload", schedule.payload)
        updates["payload"] = _validated_action_payload(
            session,
            automation_type=final_automation_type,
            schedule_config=final_schedule_config,
            payload=final_payload,
            tenant_id=schedule.tenant_id,
        )
        guard_price_schedule_duplicate(session, schedule.tenant_id, final_automation_type, updates["payload"], exclude_id=schedule.id)
        final_timezone = updates.get("timezone", schedule.timezone)
        schedule_changed = (
            "schedule_config" in updates or "timezone" in updates
        )
        became_enabled = not schedule.is_enabled and final_is_enabled

        if not final_is_enabled:
            next_run_at = None
        elif became_enabled or schedule_changed:
            next_run_at = calculate_next_run_at(
                final_schedule_config,
                final_timezone,
            )
        else:
            next_run_at = schedule.next_run_at

        for field in SCHEDULE_MUTABLE_FIELDS:
            if field in updates:
                setattr(schedule, field, updates[field])

        schedule.next_run_at = next_run_at

        session.flush()
        changes = schedule_audit_changes(
            before,
            schedule_audit_snapshot(schedule),
        )
        enabled_change = changes.pop("is_enabled", None)

        if changes:
            add_schedule_audit_event(
                session,
                event_type=ScheduleAuditEventType.UPDATED,
                actor_user_id=actor_user_id,
                schedule_id=schedule.id,
                metadata={"changes": changes},
            )

        if enabled_change is not None:
            add_schedule_audit_event(
                session,
                event_type=(
                    ScheduleAuditEventType.ENABLED
                    if schedule.is_enabled
                    else ScheduleAuditEventType.DISABLED
                ),
                actor_user_id=actor_user_id,
                schedule_id=schedule.id,
                metadata={"changes": {"is_enabled": enabled_change}},
            )

        if changes or enabled_change is not None:
            session.flush()
        session.refresh(schedule)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return schedule


def delete_schedule(
    session: Session,
    schedule: AutomationSchedule,
) -> None:
    try:
        session.delete(schedule)
        session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
