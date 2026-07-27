import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getSupplyRequests,
  getSupplyDepartments,
  getSupplyDirections,
  getSupplyCycles,
  type SupplyCycle,
  type SupplyReference,
  type SupplyRequestSummary,
} from '../services/supplyAdmin'

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short', timeStyle: 'short',
  }).format(new Date(value))
}

function statusLabel(value: string): string {
  return ({
    SUBMITTED: 'Отправлена',
    IN_REVIEW: 'В обработке',
    PLANNED: 'Спланирована',
    CANCELLED: 'Отменена',
    DRAFT: 'Черновик',
  } as Record<string, string>)[value] ?? value
}

function SupplyRequestListPage() {
  const [items, setItems] = useState<SupplyRequestSummary[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [needsReview, setNeedsReview] = useState(false)
  const [duplicates, setDuplicates] = useState(false)
  const [departmentId, setDepartmentId] = useState('')
  const [directionId, setDirectionId] = useState('')
  const [cycleId, setCycleId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)
  const [departments, setDepartments] = useState<SupplyReference[]>([])
  const [directions, setDirections] = useState<SupplyReference[]>([])
  const [cycles, setCycles] = useState<SupplyCycle[]>([])
  const inFlight = useRef(false)
  const hasData = useRef(false)

  const load = useCallback(async (background = false) => {
    if (inFlight.current) return
    inFlight.current = true
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (search.trim()) query.set('search', search.trim())
    if (status) query.set('status', status)
    if (needsReview) query.set('has_needs_review', 'true')
    if (duplicates) query.set('has_duplicates', 'true')
    if (departmentId) query.set('department_id', departmentId)
    if (directionId) query.set('direction_id', directionId)
    if (cycleId) query.set('cycle_id', cycleId)
    if (dateFrom) query.set('date_from', dateFrom)
    if (dateTo) query.set('date_to', dateTo)
    try {
      const result = await getSupplyRequests(query)
      setItems(result)
      hasData.current = true
      setState('ready')
    } catch {
      if (!background || !hasData.current) setState('error')
    } finally {
      inFlight.current = false
    }
  }, [cycleId, dateFrom, dateTo, departmentId, directionId, duplicates, limit, needsReview, offset, search, status])

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    void Promise.all([
      getSupplyDepartments(), getSupplyDirections(), getSupplyCycles(),
    ]).then(([nextDepartments, nextDirections, nextCycles]) => {
      setDepartments(nextDepartments)
      setDirections(nextDirections)
      setCycles(nextCycles.items)
    }).catch(() => undefined)
    const interval = window.setInterval(() => void load(true), 10_000)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void load(true)
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [load])

  return (
    <section className="request-page request-list-page supply-admin-page">
      <div className="request-panel">
        <div className="request-heading">
          <div>
            <p className="eyebrow">СНАБЖЕНИЕ</p>
            <h1>Реестр заявок</h1>
            <p className="request-intro">Заявок в выборке: {items.length}</p>
          </div>
          <Link className="request-back-link" to="/dashboard">← На Dashboard</Link>
        </div>
        <div className="supply-filters">
          <input
            aria-label="Номер или текст"
            placeholder="Номер или текст"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select aria-label="Статус" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Все статусы</option>
            <option value="SUBMITTED">Отправлена</option>
            <option value="IN_REVIEW">В обработке</option>
            <option value="PLANNED">Спланирована</option>
            <option value="CANCELLED">Отменена</option>
          </select>
          <select aria-label="Подразделение" value={departmentId} onChange={(event) => { setDepartmentId(event.target.value); setOffset(0) }}>
            <option value="">Все подразделения</option>
            {departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <select aria-label="Направление" value={directionId} onChange={(event) => { setDirectionId(event.target.value); setOffset(0) }}>
            <option value="">Все направления</option>
            {directions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <select aria-label="Цикл" value={cycleId} onChange={(event) => { setCycleId(event.target.value); setOffset(0) }}>
            <option value="">Все циклы</option>
            {cycles.map((item) => <option key={item.id} value={item.id}>{item.cycle_date}</option>)}
          </select>
          <label>С <input type="date" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setOffset(0) }} /></label>
          <label>По <input type="date" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setOffset(0) }} /></label>
          <label><input type="checkbox" checked={needsReview} onChange={(event) => setNeedsReview(event.target.checked)} /> Требует сопоставления</label>
          <label><input type="checkbox" checked={duplicates} onChange={(event) => setDuplicates(event.target.checked)} /> Есть дубли</label>
          <button type="button" onClick={() => void load()}>Обновить</button>
        </div>
        {state === 'loading' && <p className="page-state">Загружаем заявки…</p>}
        {state === 'error' && <p className="request-message request-message-error">Не удалось загрузить заявки</p>}
        {state === 'ready' && items.length === 0 && <p className="page-state">Заявок по выбранным условиям нет</p>}
        {items.length > 0 && (
          <div className="supply-registry">
            {items.map((item) => (
              <Link to={`/supply/requests/${item.id}`} className="supply-registry-row" key={item.id}>
                <strong>{item.public_number}</strong>
                <span>{item.department.name} · {item.direction.name}</span>
                <span>{item.cycle?.cycle_date ?? 'Без цикла'}</span>
                <span>{item.public_author_name ?? 'Сотрудник EOS'}</span>
                <span>{formatDate(item.submitted_at ?? item.created_at)}</span>
                <span>Позиций: {item.lines_total}</span>
                <span>Сопоставлено: {item.lines_matched}</span>
                <span>Не сопоставлено: {item.lines_needs_review}</span>
                <span>Дубли: {item.duplicate_groups}</span>
                <span>{statusLabel(item.status)} · v{item.version}</span>
              </Link>
            ))}
          </div>
        )}
        <div className="supply-card-actions">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Назад</button>
          <span>Показано {items.length}, смещение {offset}</span>
          <button type="button" disabled={items.length < limit} onClick={() => setOffset(offset + limit)}>Далее</button>
          <select aria-label="Количество на странице" value={limit} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0) }}>
            <option value="25">25</option><option value="50">50</option><option value="100">100</option>
          </select>
        </div>
      </div>
    </section>
  )
}

export default SupplyRequestListPage
