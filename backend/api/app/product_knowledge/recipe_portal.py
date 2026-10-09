"""Protected, allowlisted K5B projections and transactional human commands.

Confirmation means Office review of an observed source recipe, not production
readiness. No new catalog, recipe mutation, scheduling or request-path iiko I/O.
"""
from decimal import Decimal, InvalidOperation
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select, func, and_
from app.audit.service import record_audit_event
from app.core.authorization import Capability, authorize
from app.core.action_context import ActionContextError
from app.models.audit import AuditEvent
from app.models.product_recipe import ProductRecipeObservation as Observation, ProductRecipeVersion as Version
from app.models.sales import SalesSyncState
from app.models.automation import AutomationExecution, ExecutionStatus
from app.models.employee import IikoDepartmentMapping
from app.models.supply import Department
from app.product_knowledge.management import find_product
from app.product_knowledge.bootstrap import digest
from app.product_knowledge.recipes import ACTION, RecipeRefreshPayload, enqueue_authorized

STATUS_LABELS = {'UNCONFIRMED': 'Требует проверки', 'INCOMPLETE': 'Неполные данные', 'CONFLICT': 'Конфликт'}
ACTIVE = {ExecutionStatus.PENDING, ExecutionStatus.DISPATCHING, ExecutionStatus.RUNNING, ExecutionStatus.RETRYING}
PROGRESS = {'dispatching': 'Начинаем обновление', 'pending': 'Ожидает обновления', 'running': 'Получаем данные из iiko',
    'retrying': 'Повторяем попытку обновления', 'succeeded': 'Обновление завершено',
    'failed': 'Не удалось обновить. Сохранённые рецептуры доступны',
    'timed_out': 'Превышено время ожидания. Сохранённые рецептуры доступны',
    'cancelled': 'Обновление отменено'}
ISSUES = {
    'OFFICE_ACCEPTANCE_PENDING': 'Нужна независимая сверка с iikoOffice',
    'PRODUCTION_STORE_UNCONFIRMED': 'Производственный склад не подтверждён',
    'INEFFECTIVE_CHART': 'Рецептура не действует на выбранную дату',
    'INVALID_BASE': 'Выход рецептуры отсутствует или некорректен',
    'INVALID_CHART': 'Исходная рецептура содержит некорректные данные',
    'INVALID_INTERVAL': 'Некорректный период действия',
    'INVALID_PREPARED': 'Проекция списания содержит некорректные данные',
    'INVALID_PREPARED_NORM': 'Норма списания отсутствует или некорректна',
    'INVALID_PREPARED_STORE_SCOPE': 'Некорректное ограничение склада в проекции списания',
    'INVALID_STORE_SCOPE': 'Некорректное ограничение склада',
    'MISSING_ITEMS': 'Строки исходной рецептуры отсутствуют',
    'MISSING_PREPARED_ITEMS': 'Строки проекции списания отсутствуют',
    'PREPARED_INTERVAL_INVALID': 'Проекция списания не действует на выбранную дату',
    'PREPARED_ROOT_MISMATCH': 'Проекция списания относится к другому изделию',
    'SOURCE_PRODUCT_DELETED': 'Ингредиент или изделие удалены в источнике',
    'UNKNOWN_ITEM_SCOPE': 'Ограничения строки не подтверждены',
    'UNKNOWN_PREPARED_SCOPE': 'Ограничения проекции списания не подтверждены',
    'UNKNOWN_PRODUCT_TYPE': 'Тип ингредиента не подтверждён',
    'UNKNOWN_STORE_SCOPE': 'Ограничения склада не подтверждены',
    'UNKNOWN_VALIDITY_END': 'Дата окончания действия не подтверждена',
    'UNKNOWN_WRITEOFF_STRATEGY': 'Способ списания не подтверждён',
    'UNREACHABLE_TREE_CHART': 'В дереве есть несвязанные рецептуры',
    'UNRESOLVED_PREPARED_INGREDIENT': 'Ингредиент списания не подтверждён',
    'UNRESOLVED_PRODUCT': 'Изделие или полуфабрикат не подтверждены',
    'MISSING_PROJECTION': 'Одна из проекций рецептуры отсутствует',
    'SIZE_REQUIRES_VERIFICATION': 'Размер изделия требует проверки',
    'PREPARED_SIZE_REQUIRES_VERIFICATION': 'Размер проекции списания требует проверки',
    'SIZE_REFERENCE_MISSING': 'Нет данных о размерах',
    'RECIPE_CYCLE': 'Обнаружен цикл вложенных рецептур',
    'MISSING_NESTED_RECIPE': 'Рецептура полуфабриката отсутствует',
    'UNRESOLVED_UNIT': 'Единица измерения не подтверждена',
    'UNRESOLVED_INGREDIENT': 'Ингредиент не подтверждён в источнике',
    'INVALID_NORM': 'Норма ингредиента отсутствует или некорректна',
    'ROOT_UNIT_MISMATCH': 'Единица изделия расходится с каталогом',
    'DEPENDENCY_NOT_UNIQUE': 'Несколько рецептур одного полуфабриката',
    'ROOT_NOT_UNIQUE': 'Исходная рецептура отсутствует или неоднозначна',
    'PREPARED_NOT_UNIQUE': 'Несколько проекций списания',
    'HISTORY_INTERVAL_AMBIGUOUS': 'Периоды версий пересекаются или отсутствуют',
    'HISTORY_CHANGED_DURING_COLLECTION': 'История изменилась во время обновления',
    'ROOT_CHANGED_DURING_COLLECTION': 'Рецептура изменилась во время обновления',
    'PREPARED_CHANGED_DURING_COLLECTION': 'Проекция списания изменилась во время обновления',
}


def permitted(db, actor, capability):
    try:
        authorize(db, actor, capability, write=False)
        return True
    except ActionContextError:
        return False


def context_scope(payload):
    raw = payload.get('scope', payload)
    return {k: raw.get(k) for k in ('department_id', 'warehouse_id', 'size_id')}


def context_key(payload):
    return digest(context_scope(payload))


def observations(db, actor, product):
    return select(Observation).where(Observation.tenant_id == actor.tenant_id,
        Observation.product_id == product.id, Observation.source_id == product.source_id)


def contexts(db, actor, product):
    # Only previously observed contexts of this exact tenant/source. This permits
    # single-product first loads without inferring department or warehouse IDs.
    fields = ('department_id', 'warehouse_id', 'size_id')
    rows = db.execute(select(*(Observation.payload['scope'][key].as_string() for key in fields)).where(
        Observation.tenant_id == actor.tenant_id, Observation.source_id == product.source_id).distinct()).all()
    result = {}
    for row in sorted(rows, key=lambda values: tuple(value or '' for value in values)):
        scope = dict(zip(fields, row))
        try:
            UUID(scope['department_id'])
            for k in ('warehouse_id', 'size_id'):
                if scope[k] is not None:
                    UUID(scope[k])
        except (TypeError, ValueError, AttributeError):
            continue
        result.setdefault(digest(scope), scope)
    return result


def context_options(db, actor, available):
    mappings = db.execute(select(IikoDepartmentMapping.olap_department_id, Department.name).join(
        Department, (Department.tenant_id == IikoDepartmentMapping.tenant_id) &
        (Department.id == IikoDepartmentMapping.eos_department_id)).where(
        IikoDepartmentMapping.tenant_id == actor.tenant_id)).all()
    names = {str(pid): name for pid, name in mappings if pid is not None}
    return [dict(key=key, label=f"{names.get(scope['department_id'], 'Подразделение iiko')} · контекст {i+1}",
        warehouse_label='Склад задан в источнике' if scope['warehouse_id'] else 'Склад не подтверждён',
        size_label='Размер задан в источнике' if scope['size_id'] else 'Размер не подтверждён')
        for i, (key, scope) in enumerate(available.items())]


def numeric(value):
    # Never round/convert through float. Missing/nonfinite values stay unknown.
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value))
        return format(number, 'f') if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def text(value):
    return value if isinstance(value, str) else None


def chart_projection(version, refs):
    chart = version.payload
    products, units = refs.get('products', {}), refs.get('units', {})
    def identity(pid):
        product = products.get(pid, {})
        return dict(name=text(product.get('name')) or 'Наименование не подтверждено',
            unit=text(units.get(product.get('mainUnit'), {}).get('name')))
    rows = []
    for item in chart.get('items', []) if isinstance(chart.get('items'), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(dict(product_id=text(item.get('productId')), **identity(item.get('productId')),
            gross=numeric(item.get('amountIn')), net=numeric(item.get('amountMiddle')),
            output=numeric(item.get('amountOut')), writeoff=numeric(item.get('amount')),
            scope_note='Ограничения строки требуют проверки' if item.get('storeSpecification') is not None or item.get('productSizeSpecification') is not None else None))
    return dict(version_id=str(version.id), chart_id=str(version.chart_id), product_id=str(version.source_product_id),
        kind=version.kind, **identity(str(version.source_product_id)),
        valid_from=text(chart.get('dateFrom')), valid_to=text(chart.get('dateTo')), valid_to_known='dateTo' in chart,
        base_amount=numeric(chart.get('assembledAmount')), technology=text(chart.get('technologyDescription')),
        writeoff_strategy={'ASSEMBLE': 'Через приготовление', 'DIRECT': 'Прямое списание'}.get(chart.get('productWriteoffStrategy'), 'Не подтверждена'),
        size_strategy={'COMMON': 'Общая рецептура', 'SPECIFIC': 'По размеру изделия'}.get(chart.get('productSizeAssemblyStrategy'), 'Не подтверждена'),
        store_note='Ограничения склада заданы в источнике' if chart.get('effectiveDirectWriteoffStoreSpecification') is not None else 'Производственный склад не подтверждён',
        items=rows)


def approval(db, actor, observation):
    return db.scalar(select(AuditEvent).where(AuditEvent.tenant_id == actor.tenant_id,
        AuditEvent.entity_type == 'ProductRecipeObservation', AuditEvent.entity_id == str(observation.id),
        AuditEvent.event_type == 'PRODUCT_RECIPE_CONFIRMED',
        AuditEvent.correlation_id == observation.payload.get('manifest_hash')).order_by(AuditEvent.occurred_at.desc()).limit(1))


def approval_projection(row):
    if not row:
        return None
    return dict(author=row.actor_name_snapshot, employee_id=row.actor_employee_id,
        confirmed_at=row.occurred_at, evidence=row.reason,
        version_ids=row.after.get('version_ids', []))


def scope_filter(column, recipe_scope, *, nested=True):
    column = column['scope'] if nested else column
    return and_(*(column[key].as_string().is_(None) if value is None else
        column[key].as_string() == value for key, value in recipe_scope.items()))


def attempts(db, actor, product, recipe_scope, *, active=False):
    # Exact UUID membership includes a product inside an existing K5B batch.
    stmt = select(AutomationExecution).where(AutomationExecution.tenant_id == actor.tenant_id,
        AutomationExecution.automation_type == ACTION,
        AutomationExecution.payload['source_id'].as_string() == product.source_id,
        scope_filter(AutomationExecution.payload, recipe_scope, nested=False))
    if db.get_bind().dialect.name == 'sqlite':
        members = func.json_each(AutomationExecution.payload['product_ids']).table_valued('value')
        stmt = stmt.where(select(1).select_from(members).where(members.c.value == str(product.iiko_product_id)).exists())
    else:
        stmt = stmt.where(AutomationExecution.payload['product_ids'].contains([str(product.iiko_product_id)]))
    if active:
        stmt = stmt.where(AutomationExecution.status.in_(ACTIVE))
    return db.scalar(stmt.order_by(AutomationExecution.requested_at.desc(), AutomationExecution.id.desc()).limit(1))


def progress(execution):
    if execution is None:
        return None
    state = str(execution.status)
    return dict(state=state, label=PROGRESS.get(state, 'Статус обновления уточняется'),
        active=execution.status in ACTIVE, requested_at=execution.requested_at,
        finished_at=execution.finished_at)


def detail(db, actor, product_id, *, selected_context=None, observation_id=None, offset=0, limit=20):
    authorize(db, actor, Capability.PRODUCT_RECIPE_READ, write=False)
    product = find_product(db, actor, product_id)
    available = contexts(db, actor, product)
    if selected_context is not None and selected_context not in available:
        raise HTTPException(404, 'Контекст рецептуры недоступен')
    base = observations(db, actor, product)
    selected = db.scalar(base.where(Observation.id == observation_id)) if observation_id else None
    if observation_id and (selected is None or selected_context and context_key(selected.payload) != selected_context):
        raise HTTPException(404, 'Наблюдение рецептуры недоступно')
    latest = db.scalar(base.order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1))
    key = selected_context or (context_key(selected.payload) if selected else context_key(latest.payload) if latest else next(iter(available), None))
    scoped = base.where(scope_filter(Observation.payload, available[key])) if key else base.where(False)
    ordered = scoped.order_by(Observation.observed_at.desc(), Observation.id.desc())
    current = db.scalar(ordered.limit(1))
    selected = selected or current
    history_rows = list(db.scalars(ordered.offset(offset).limit(limit)))
    total = db.scalar(select(func.count()).select_from(scoped.subquery()))
    last_attempt = (attempts(db, actor, product, available[key], active=True) or attempts(db, actor, product, available[key])) if key else None
    actions = []
    if product.deleted_at is None and permitted(db, actor, Capability.PRODUCT_RECIPE_REFRESH) and key:
        actions.append('REFRESH')
    versions = []
    confirmation = None
    if selected:
        ids = {UUID(entry['version_id']) for entry in selected.payload.get('manifest', [])}
        stored = list(db.scalars(select(Version).where(Version.tenant_id == actor.tenant_id,
            Version.source_id == product.source_id, Version.id.in_(ids))))
        roles = {}
        for entry in selected.payload.get('manifest', []):
            roles.setdefault(entry['version_id'], []).append(entry['role'])
        versions = [dict(**chart_projection(v, selected.payload.get('references', {})), roles=sorted(set(roles[str(v.id)]))) for v in stored]
        confirmation = approval_projection(approval(db, actor, selected))
        if selected == current and selected.status == 'UNCONFIRMED' and confirmation is None and product.deleted_at is None and not (last_attempt and last_attempt.status in ACTIVE) and permitted(db, actor, Capability.PRODUCT_RECIPE_CONFIRM):
            actions.append('CONFIRM')
    history = []
    for row in history_rows:
        history.append(dict(id=row.id, observed_at=row.observed_at, effective_on=row.effective_on,
            status_label=STATUS_LABELS[row.status], status=row.status,
            is_current=row == current, confirmation=approval_projection(approval(db, actor, row)),
            version_ids=sorted({e['version_id'] for e in row.payload.get('manifest', []) if e.get('role') == 'ASSEMBLED'})))
    return dict(contexts=context_options(db, actor, available), context_key=key,
        observation=None if selected is None else dict(id=selected.id, manifest_hash=selected.payload['manifest_hash'],
            effective_on=selected.effective_on, observed_at=selected.observed_at, status=selected.status,
            status_label=STATUS_LABELS[selected.status], is_current=selected == current,
            ready_for_production=False,
            issues=[ISSUES.get(code, 'Данные рецептуры требуют дополнительной проверки') for code in selected.payload.get('issues', []) if not (code == 'OFFICE_ACCEPTANCE_PENDING' and confirmation)],
            root_product_id=str(product.iiko_product_id), charts=versions, confirmation=confirmation),
        last_updated_at=current.observed_at if current else None, history=history, total=total,
        offset=offset, limit=limit, allowed_actions=actions, refresh=progress(last_attempt))


def lock_source(db, actor, product):
    if db.scalar(select(SalesSyncState).where(SalesSyncState.tenant_id == actor.tenant_id,
        SalesSyncState.source_id == product.source_id).with_for_update()) is None:
        raise HTTPException(409, 'Источник рецептуры недоступен')


def confirm(db, actor, product_id, command):
    context = authorize(db, actor, Capability.PRODUCT_RECIPE_CONFIRM, write=True)
    product = find_product(db, actor, product_id, lock=True)
    lock_source(db, actor, product)  # same lock as K5B publication, prevents stale approval
    row = db.scalar(observations(db, actor, product).where(Observation.id == command.observation_id))
    if row is None:
        raise HTTPException(404, 'Наблюдение рецептуры недоступно')
    if product.deleted_at is not None or row.status != 'UNCONFIRMED' or row.payload.get('manifest_hash') != command.manifest_hash:
        raise HTTPException(409, 'Подтверждение недоступно: проверьте качество и версию рецептуры')
    latest = db.scalar(observations(db, actor, product).where(scope_filter(Observation.payload, context_scope(row.payload)))
        .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1))
    if latest is None or latest.id != row.id:
        raise HTTPException(409, 'Рецептура обновлена. Сверьте последнюю версию')
    if attempts(db, actor, product, context_scope(row.payload), active=True):
        raise HTTPException(409, 'Дождитесь завершения обновления рецептуры')
    if approval(db, actor, row):
        return row  # immutable single confirmation for this exact observation
    record_audit_event(db, tenant_id=actor.tenant_id, entity_type='ProductRecipeObservation', entity_id=row.id,
        event_type='PRODUCT_RECIPE_CONFIRMED', operation='CONFIRM', context=context, actor_user=actor,
        after=dict(manifest_hash=command.manifest_hash, source_id=product.source_id,
            source_product_id=str(product.iiko_product_id), scope=row.payload['scope'],
            version_ids=sorted({e['version_id'] for e in row.payload['manifest']}),
            ready_for_production=False), reason=command.office_evidence, correlation_id=command.manifest_hash)
    db.flush()
    return row


def refresh(db, actor, product_id, command):
    context = authorize(db, actor, Capability.PRODUCT_RECIPE_REFRESH, write=True)
    product = find_product(db, actor, product_id, lock=True)
    if product.deleted_at is not None:
        raise HTTPException(409, 'Изделие удалено из EOS')
    lock_source(db, actor, product)
    available = contexts(db, actor, product)
    scope = available.get(command.context_key)
    if scope is None:
        raise HTTPException(409, 'Сначала подтвердите контекст рецептуры')
    fingerprint = digest(command.model_dump(mode='json'))
    prior = db.scalar(select(AuditEvent).where(AuditEvent.tenant_id == actor.tenant_id,
        AuditEvent.entity_type == 'ProductRecipeRefresh', AuditEvent.entity_id == str(product.id),
        AuditEvent.correlation_id == str(command.request_id)))
    if prior:
        if prior.after.get('command_hash') != fingerprint:
            raise HTTPException(409, 'Запрос обновления уже использован с другими параметрами')
        return progress(db.scalar(select(AutomationExecution).where(AutomationExecution.tenant_id == actor.tenant_id,
            AutomationExecution.execution_id == UUID(prior.after['execution_id']))))
    active = attempts(db, actor, product, scope, active=True)
    if active:
        if active.payload.get('effective_on') != command.effective_on.isoformat():
            raise HTTPException(409, 'Уже выполняется обновление на другую дату. Дождитесь результата')
        execution = active
    else:
        payload = RecipeRefreshPayload(source_id=product.source_id, product_ids=[product.iiko_product_id],
            **scope, effective_on=command.effective_on, scope_evidence='Ручное обновление подтверждённого контекста из карточки EOS')
        execution = enqueue_authorized(db, actor, payload, context)
    record_audit_event(db, tenant_id=actor.tenant_id, entity_type='ProductRecipeRefresh', entity_id=product.id,
        event_type='PRODUCT_RECIPE_REFRESH_REQUESTED', operation='REFRESH', context=context, actor_user=actor,
        after=dict(command_hash=fingerprint, execution_id=str(execution.execution_id)),
        reason='Ручное обновление ТТК из карточки изделия', correlation_id=str(command.request_id))
    db.flush()
    return progress(execution)
