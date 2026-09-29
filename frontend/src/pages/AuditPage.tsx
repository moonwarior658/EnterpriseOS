import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { getAuditEvents, type AuditEvent, type AuditFilters } from '../services/audit'

const valueText = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function eventDiff(event: AuditEvent) {
  return Array.from(new Set([
    ...Object.keys(event.before),
    ...Object.keys(event.after),
  ])).sort().map((key) => ({
    key,
    before: valueText(event.before[key]),
    after: valueText(event.after[key]),
  }))
}

function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [filters, setFilters] = useState<AuditFilters>({})
  const [draft, setDraft] = useState<AuditFilters>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    getAuditEvents(filters)
      .then((items) => { if (active) setEvents(items) })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : 'Не удалось загрузить аудит')
      })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [filters])

  const employees = useMemo(() => Array.from(new Map(
    events
      .filter((item) => item.actor_employee_id && item.actor_name_snapshot)
      .map((item) => [item.actor_employee_id!, item.actor_name_snapshot!]),
  ).entries()), [events])
  const departments = useMemo(() => Array.from(new Map(
    events
      .filter((item) => item.actual_department_id && item.actual_department_name_snapshot)
      .map((item) => [item.actual_department_id!, item.actual_department_name_snapshot!]),
  ).entries()), [events])

  function applyFilters(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError('')
    setFilters({ ...draft })
  }

  return (
    <section className="audit-page">
      <div className="page-heading">
        <div><p className="eyebrow">АДМИНИСТРИРОВАНИЕ</p><h1>Аудит</h1></div>
      </div>
      <form className="audit-filters" onSubmit={applyFilters}>
        <label><span>С даты</span><input type="date" value={draft.dateFrom ?? ''} onChange={(e) => setDraft({ ...draft, dateFrom: e.target.value })} /></label>
        <label><span>По дату</span><input type="date" value={draft.dateTo ?? ''} onChange={(e) => setDraft({ ...draft, dateTo: e.target.value })} /></label>
        <label><span>Сотрудник</span><select value={draft.employeeId ?? ''} onChange={(e) => setDraft({ ...draft, employeeId: e.target.value })}><option value="">Все</option>{employees.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label><span>Подразделение</span><select value={draft.departmentId ?? ''} onChange={(e) => setDraft({ ...draft, departmentId: e.target.value })}><option value="">Все</option>{departments.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
        <label><span>Тип сущности</span><input value={draft.entityType ?? ''} onChange={(e) => setDraft({ ...draft, entityType: e.target.value })} /></label>
        <label><span>Операция</span><input value={draft.operation ?? ''} onChange={(e) => setDraft({ ...draft, operation: e.target.value })} /></label>
        <label><span>Тип события</span><input value={draft.eventType ?? ''} onChange={(e) => setDraft({ ...draft, eventType: e.target.value })} /></label>
        <button className="primary-action" type="submit">Применить</button>
      </form>
      {loading && <p className="page-state">Загружаем события…</p>}
      {error && <p className="request-message request-message-error">{error}</p>}
      {!loading && !error && events.length === 0 && <p className="page-state">Событий по выбранным фильтрам нет.</p>}
      <div className="audit-event-list">
        {events.map((item) => {
          const diff = eventDiff(item)
          return (
            <article className="audit-event-card" key={item.id}>
              <header>
                <div><strong>{item.event_type}</strong><span>{new Date(item.occurred_at).toLocaleString('ru-RU')}</span></div>
                <span>{item.entity_type} · {item.operation}</span>
              </header>
              <dl>
                <div><dt>Actor</dt><dd>{item.actor_name_snapshot ?? 'Система'}</dd></div>
                <div><dt>Авторизован как</dt><dd>{item.authorized_as ?? 'SYSTEM'}</dd></div>
                <div><dt>Основное подразделение</dt><dd>{item.primary_department_name_snapshot ?? '—'}</dd></div>
                <div><dt>Фактическое подразделение</dt><dd>{item.actual_department_name_snapshot ?? '—'}</dd></div>
                <div><dt>Причина</dt><dd>{item.reason ?? '—'}</dd></div>
              </dl>
              {diff.length > 0 && <div className="audit-diff">{diff.map((row) => <p key={row.key}><strong>{row.key}</strong>: {row.before} → {row.after}</p>)}</div>}
            </article>
          )
        })}
      </div>
    </section>
  )
}

export default AuditPage
