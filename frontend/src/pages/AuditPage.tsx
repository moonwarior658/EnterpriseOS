import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { EosDateField, EosSelect } from '../components/EosFormControls'
import { getActionContext } from '../services/actionContext'
import { getAuditEvents, type AuditEvent, type AuditFilters } from '../services/audit'
import { formatDateOnly, formatDateTime } from '../utils/dateFormat'

const EVENT_LABELS: Record<string, string> = {
  REPAIR_CREATED: 'Создана заявка на ремонт', REPAIR_DETAILS_UPDATED: 'Изменены данные ремонта',
  REPAIR_TAKE: 'Ремонт принят в работу', REPAIR_ASSIGN_CONTRACTOR: 'Назначен внешний подрядчик',
  REPAIR_SCHEDULE_EXTERNAL_VISIT: 'Назначен визит внешнего мастера',
  REPAIR_ESCALATE_TO_SUPPLY: 'Ремонт передан руководителю', REPAIR_CLOSE: 'Ремонт закрыт',
  REPAIR_REOPEN: 'Ремонт переоткрыт', REPAIR_COMMENTED: 'Добавлен комментарий к ремонту',
  REPAIR_PHOTO_ADDED: 'Добавлена фотография ремонта',
  REPAIR_EXTERNAL_COST_UPDATED: 'Изменена стоимость внешнего ремонта',
  REPAIR_EXTERNAL_DOCUMENT_ADDED: 'Добавлен документ внешнего ремонта',
  CONTRACTOR_CREATED: 'Добавлен внешний подрядчик', CONTRACTOR_UPDATED: 'Изменён внешний подрядчик',
  CONTRACTOR_SPECIALIZATION_CREATED: 'Добавлена специализация', CONTRACTOR_SPECIALIZATION_UPDATED: 'Изменена специализация',
  EMPLOYEE_CREATED: 'Создан сотрудник', EMPLOYEE_UPDATED: 'Изменены данные сотрудника',
  EMPLOYEE_DISMISSED: 'Сотрудник уволен', EMPLOYEE_REACTIVATED: 'Сотрудник восстановлен',
  EMPLOYEE_ROLE_ASSIGNED: 'Назначена роль сотрудника', EMPLOYEE_DEPARTMENT_ASSIGNED: 'Назначено подразделение сотрудника',
  EMPLOYEE_USER_LINKED: 'Учётная запись связана с сотрудником', EMPLOYEE_USER_UNLINKED: 'Учётная запись отвязана',
  EMPLOYEE_AVATAR_UPDATED: 'Изменена фотография сотрудника', EMPLOYEE_AVATAR_REMOVED: 'Удалена фотография сотрудника',
  IIKO_EMPLOYEE_LINK_CREATED: 'Создана связь с iiko', IIKO_EMPLOYEE_LINK_CORRECTED: 'Исправлена связь с iiko',
  SHIFT_SUBSTITUTION_CONFIRMED: 'Подтверждена замена смены',
  USER_CREATED: 'Создана учётная запись', USER_UPDATED: 'Изменена учётная запись',
  USER_PASSWORD_CHANGED: 'Сотрудник сменил пароль', USER_PASSWORD_RESET: 'Пароль сотрудника сброшен',
  SUPPLY_REQUEST_CREATED: 'Создана заявка на товары', SUPPLY_REQUEST_DETAILS_UPDATED: 'Изменена заявка на товары',
  SUPPLY_REQUEST_SUBMITTED: 'Заявка на товары подтверждена', SUPPLY_REQUEST_CANCELLED: 'Заявка на товары отменена',
  SUPPLIER_CREATED: 'Добавлен поставщик', SUPPLIER_UPDATED: 'Изменён поставщик',
  SUPPLIER_ARCHIVED: 'Поставщик архивирован', SUPPLIER_RESTORED: 'Поставщик восстановлен',
  SUPPLIER_ORDER_CREATED: 'Создан заказ поставщику', SUPPLIER_ORDER_UPDATED: 'Изменён заказ поставщику',
  SUPPLIER_ORDER_READY: 'Заказ готов к отправке', SUPPLIER_ORDER_CANCELLED: 'Заказ поставщику отменён',
  SUPPLIER_PAYMENT_CREATED: 'Создана оплата поставщику', SUPPLIER_PAYMENT_UPDATED: 'Изменена оплата поставщику',
  SUPPLIER_PAYMENT_RECORDED: 'Оплата поставщику зафиксирована', SUPPLIER_PAYMENT_CANCELLED: 'Оплата поставщику отменена',
  SUPPLIER_PAYMENT_PHOTO_ADDED: 'Прикреплено фото оплаты',
  AUTOMATION_SCHEDULE_DELETED: 'Удалена регламентная задача',
  FIRST_ADMIN_BOOTSTRAPPED: 'Создан первый администратор',
  SUPPLY_REQUEST_SELLER_EDITED: 'Сохранён черновик заявки продавца',
  SUPPLY_REQUEST_SELLER_CONFIRMED: 'Подтверждена новая версия заявки продавца',
  SUPPLY_REQUEST_SELLER_FINALIZED: 'Окно закрыто: подтверждённая заявка зафиксирована',
}
const ENTITY_LABELS: Record<string, string> = {
  WorkRequest: 'Ремонт', ExternalContractor: 'Подрядчик', ContractorSpecialization: 'Специализация',
  Employee: 'Сотрудник', User: 'Учётная запись', IikoEmployeeLink: 'Связь с iiko',
  SupplyRequest: 'Заявка на товары', SupplySupplier: 'Поставщик', SupplySupplierOrder: 'Заказ поставщику',
  SupplySupplierPayment: 'Оплата поставщику', AutomationSchedule: 'Регламентная задача',
}
const FIELD_LABELS: Record<string, string> = {
  status: 'Статус', responsible_role: 'Ответственная роль', responsible_employee_id: 'Ответственный',
  contractor_id: 'Подрядчик', contractor_name_snapshot: 'Подрядчик', specialization_id: 'Специализация',
  specialization_name_snapshot: 'Специализация', visit_at: 'Время визита', closed_at: 'Дата закрытия',
  description: 'Описание', repair_category: 'Категория', priority: 'Приоритет', repair_cost: 'Сумма ремонта',
  name: 'Название', full_name: 'Имя', phone: 'Телефон', birth_date: 'Дата рождения',
  dismissal_date: 'Дата увольнения', dismissal_reason: 'Причина увольнения', is_active: 'Активность',
  department_id: 'Подразделение', department_name: 'Подразделение', role: 'Роль',
  amount: 'Сумма', payment_date: 'Дата оплаты', need_date: 'Дата потребности',
  is_enabled: 'Активность', number: 'Номер', comment: 'Комментарий',
  account_type: 'Тип учётной записи', employee_id: 'Сотрудник', linked_user_id: 'Учётная запись',
  iiko_display_name: 'Имя в iiko', iiko_user_id: 'Сотрудник iiko', is_primary: 'Основная связь',
  notes: 'Примечание', photo_url: 'Фотография', primary_department_id: 'Основное подразделение',
  responsibility_started_at: 'Дата назначения', specialization_ids: 'Специализации',
  valid_from: 'Дата начала', created_at: 'Дата создания', photo_original_name: 'Фото оплаты',
  raw_input: 'Содержание заявки', confirmed_version: 'Подтверждённая версия',
  draft_pending: 'Есть незавершённый черновик', draft_discarded: 'Незавершённые правки отброшены',
  finalized_at: 'Дата фиксации',
}
const VALUE_LABELS: Record<string, string> = {
  new: 'Новая', in_progress: 'В работе', waiting_external: 'Ожидается внешний мастер',
  escalated: 'Передано руководителю', completed: 'Завершена', reopened: 'Переоткрыта', cancelled: 'Отменена',
  DRAFT: 'Черновик', READY: 'Готово', SENT: 'Отправлено', RECORDED: 'Зафиксировано',
  SUBMITTED: 'Подтверждено', OPEN: 'Открыто', CLOSED: 'Закрыто',
  HANDYMAN: 'Мастер по ремонту', SUPPLY_MANAGER: 'Руководитель снабжения',
  ADMIN: 'Администратор', DIRECTOR: 'Директор', DEPUTY_DIRECTOR: 'Заместитель директора',
  NETWORK_MANAGER: 'Управляющий сетью', HEAD_OF_PRODUCTION: 'Заведующий производством',
  CHEF_CONFECTIONER: 'Шеф-кондитер', CONFECTIONER: 'Кондитер', BAKER: 'Пекарь',
  DRIVER: 'Водитель', SELLER: 'Продавец', ACCOUNTANT: 'Бухгалтер',
  HUMAN: 'Сотрудник', SERVICE: 'Сервисная запись', ACTIVE: 'Активен', DISMISSED: 'Уволен',
  routine: 'Обычный', important: 'Важный', urgent: 'Срочный',
  true: 'Да', false: 'Нет',
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const technicalKeys = new Set(['id', 'tenant_id', 'shift_id', 'created_by_user_id', 'actor_user_id'])
function labelEvent(value: string) { return EVENT_LABELS[value] ?? 'Действие в системе' }
function valueText(value: unknown, key: string): string {
  if (value === null || value === undefined || value === '') return '—'
  if (key === 'photo_url') return 'Есть фото'
  if (key === 'specialization_ids' && Array.isArray(value)) return `${value.length} специализаций`
  if (key.endsWith('_id')) return 'Связано'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  if (typeof value === 'string') {
    if (VALUE_LABELS[value]) return VALUE_LABELS[value]
    if (UUID.test(value)) return 'Установлено'
    if (key.endsWith('_at')) return formatDateTime(value)
    if (key.endsWith('_date')) return formatDateOnly(value)
    return value
  }
  if (typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map((item) => valueText(item, key)).join(', ')
  return 'Данные изменены'
}
function eventDiff(event: AuditEvent) {
  return Array.from(new Set([...Object.keys(event.before), ...Object.keys(event.after)]))
    .sort().filter((key) => !technicalKeys.has(key) && JSON.stringify(event.before[key] ?? null) !== JSON.stringify(event.after[key] ?? null))
    .filter((key) => key in FIELD_LABELS)
    .filter((key) => !(key.endsWith('_id') && (`${key.slice(0, -3)}_name_snapshot` in event.after || `${key.slice(0, -3)}_name_snapshot` in event.before)))
    .map((key) => ({ key, label: FIELD_LABELS[key] ?? key.replaceAll('_', ' '), before: valueText(event.before[key], key), after: valueText(event.after[key], key) }))
}

function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [filters, setFilters] = useState<AuditFilters>({})
  const [draft, setDraft] = useState<AuditFilters>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [technicalAdmin, setTechnicalAdmin] = useState(false)
  useEffect(() => { getActionContext().then((context) => setTechnicalAdmin(context.roles.includes('ADMIN'))).catch(() => setTechnicalAdmin(false)) }, [])
  useEffect(() => {
    let active = true
    getAuditEvents(filters).then((items) => { if (active) setEvents(items) })
      .catch(() => { if (active) setError('Не удалось загрузить аудит') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [filters])
  const employees = useMemo(() => Array.from(new Map(events.filter((item) => item.actor_employee_id && item.actor_name_snapshot).map((item) => [item.actor_employee_id!, item.actor_name_snapshot!])).entries()), [events])
  const departments = useMemo(() => Array.from(new Map(events.filter((item) => item.actual_department_id && item.actual_department_name_snapshot).map((item) => [item.actual_department_id!, item.actual_department_name_snapshot!])).entries()), [events])
  const entities = useMemo(() => [...new Set(events.map((item) => item.entity_type))], [events])
  const eventTypes = useMemo(() => [...new Set(events.map((item) => item.event_type))], [events])
  function applyFilters(event: FormEvent) { event.preventDefault(); setLoading(true); setError(''); setFilters({ ...draft }) }

  return <main className="app-page"><div className="page-shell audit-page">
    <div className="page-heading"><div><p className="eyebrow">АДМИНИСТРИРОВАНИЕ</p><h1>Аудит</h1></div></div>
    <form className="audit-filters" onSubmit={applyFilters}>
      <EosDateField label="С даты" value={draft.dateFrom ?? ''} onChange={(e) => setDraft({ ...draft, dateFrom: e.target.value })} />
      <EosDateField label="По дату" value={draft.dateTo ?? ''} onChange={(e) => setDraft({ ...draft, dateTo: e.target.value })} />
      <label><span>Сотрудник</span><EosSelect value={draft.employeeId ?? ''} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}><option value="">Все</option>{employees.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</EosSelect></label>
      <label><span>Подразделение</span><EosSelect value={draft.departmentId ?? ''} onChange={(e) => setDraft({ ...draft, departmentId: e.target.value })}><option value="">Все</option>{departments.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</EosSelect></label>
      <label><span>Объект</span><EosSelect value={draft.entityType ?? ''} onChange={(e) => setDraft({ ...draft, entityType: e.target.value })}><option value="">Все</option>{entities.map((item) => <option key={item} value={item}>{ENTITY_LABELS[item] ?? 'Другое'}</option>)}</EosSelect></label>
      <label><span>Событие</span><EosSelect value={draft.eventType ?? ''} onChange={(e) => setDraft({ ...draft, eventType: e.target.value })}><option value="">Все</option>{eventTypes.map((item) => <option key={item} value={item}>{labelEvent(item)}</option>)}</EosSelect></label>
      <button className="primary-action" type="submit">Применить</button>
    </form>
    {loading && <p className="page-state">Загружаем события…</p>}
    {error && <p className="request-message request-message-error">{error}</p>}
    {!loading && !error && events.length === 0 && <p className="page-state">Событий по выбранным фильтрам нет.</p>}
    <div className="audit-event-list">{events.map((item) => <article className="audit-event-card" key={item.id}>
      <header><div><strong>{labelEvent(item.event_type)}</strong><span>{formatDateTime(item.occurred_at)}</span></div><span>{ENTITY_LABELS[item.entity_type] ?? 'Объект системы'}</span></header>
      <dl><div><dt>Сотрудник</dt><dd>{item.actor_name_snapshot ?? 'Система'}</dd></div><div><dt>Роль</dt><dd>{item.authorized_as ? (VALUE_LABELS[item.authorized_as] ?? 'Рабочая роль') : 'Система'}</dd></div><div><dt>Основное подразделение</dt><dd>{item.primary_department_name_snapshot ?? '—'}</dd></div><div><dt>Фактическое подразделение</dt><dd>{item.actual_department_name_snapshot ?? '—'}</dd></div>{item.reason && <div><dt>Причина</dt><dd>{item.reason}</dd></div>}</dl>
      {eventDiff(item).length > 0 && <div className="audit-diff">{eventDiff(item).map((row) => <p key={row.key}><strong>{row.label}</strong>: {row.before} → {row.after}</p>)}</div>}
      {technicalAdmin && <details><summary>Технические данные</summary><pre>{JSON.stringify({ event_type: item.event_type, entity_type: item.entity_type, entity_id: item.entity_id, operation: item.operation, before: item.before, after: item.after }, null, 2)}</pre></details>}
    </article>)}</div>
  </div></main>
}
export default AuditPage
