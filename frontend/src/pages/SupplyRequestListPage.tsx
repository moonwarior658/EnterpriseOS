import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  EosCheckbox,
  EosDateField,
  EosPagination,
  EosSearchField,
  EosSelect,
} from '../components/EosFormControls'
import {
  getSupplyRequests,
  getSupplyDepartments,
  getSupplyDirections,
  getSupplyCycles,
  type SupplyCycle,
  type SupplyReference,
  type SupplyRequestSummary,
} from '../services/supplyAdmin'

export const SUPPLY_REQUEST_PAGE_SIZE = 25

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function statusLabel(value: string): string {
  return ({
    SUBMITTED: 'Создана',
    IN_REVIEW: 'Создана',
    PLANNED: 'Сопоставлена',
    PARTIALLY_FULFILLED: 'Исполнена частично',
    FULFILLED: 'Исполнена',
    CANCELLED: 'Отменена',
    DRAFT: 'Создана',
  } as Record<string, string>)[value] ?? value
}

function SupplyRequestListPage() {
  const [routeParams, setRouteParams] = useSearchParams()
  const [items, setItems] = useState<SupplyRequestSummary[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [search, setSearch] = useState(routeParams.get('search') ?? '')
  const [status, setStatus] = useState(routeParams.get('status') ?? '')
  const [needsReview, setNeedsReview] = useState(
    routeParams.get('has_needs_review') === 'true',
  )
  const [duplicates, setDuplicates] = useState(
    routeParams.get('has_duplicates') === 'true',
  )
  const [departmentId, setDepartmentId] = useState(
    routeParams.get('department_id') ?? '',
  )
  const [directionId, setDirectionId] = useState(
    routeParams.get('direction_id') ?? '',
  )
  const [cycleId, setCycleId] = useState(routeParams.get('cycle_id') ?? '')
  const [dateFrom, setDateFrom] = useState(routeParams.get('date_from') ?? '')
  const [dateTo, setDateTo] = useState(routeParams.get('date_to') ?? '')
  const [offset, setOffset] = useState(Number(routeParams.get('offset')) || 0)
  const [total, setTotal] = useState(0)
  const [departments, setDepartments] = useState<SupplyReference[]>([])
  const [directions, setDirections] = useState<SupplyReference[]>([])
  const [cycles, setCycles] = useState<SupplyCycle[]>([])
  const activeRequest = useRef<AbortController | null>(null)
  const requestSequence = useRef(0)
  const hasData = useRef(false)

  const load = useCallback(async (background = false) => {
    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    if (!background) setState('loading')
    const query = new URLSearchParams({
      limit: String(SUPPLY_REQUEST_PAGE_SIZE),
      offset: String(offset),
    })
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
      const result = await getSupplyRequests(query, controller.signal)
      if (
        controller.signal.aborted
        || sequence !== requestSequence.current
      ) return
      setItems(result.items)
      setTotal(result.total)
      hasData.current = true
      setState('ready')
    } catch {
      if (
        controller.signal.aborted
        || sequence !== requestSequence.current
      ) return
      if (!background || !hasData.current) setState('error')
    }
  }, [cycleId, dateFrom, dateTo, departmentId, directionId, duplicates, needsReview, offset, search, status])

  useEffect(() => {
    const next = new URLSearchParams()
    if (search.trim()) next.set('search', search.trim())
    if (status) next.set('status', status)
    if (departmentId) next.set('department_id', departmentId)
    if (directionId) next.set('direction_id', directionId)
    if (cycleId) next.set('cycle_id', cycleId)
    if (dateFrom) next.set('date_from', dateFrom)
    if (dateTo) next.set('date_to', dateTo)
    if (needsReview) next.set('has_needs_review', 'true')
    if (duplicates) next.set('has_duplicates', 'true')
    if (offset) next.set('offset', String(offset))
    setRouteParams(next, { replace: true })
  }, [
    cycleId, dateFrom, dateTo, departmentId, directionId, duplicates,
    needsReview, offset, search, setRouteParams, status,
  ])

  useEffect(() => {
    void Promise.all([
      getSupplyDepartments(), getSupplyDirections(), getSupplyCycles(),
    ]).then(([nextDepartments, nextDirections, nextCycles]) => {
      setDepartments(nextDepartments)
      setDirections(nextDirections)
      setCycles(nextCycles.items)
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    const interval = window.setInterval(() => void load(true), 10_000)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void load(true)
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
      activeRequest.current?.abort()
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
        <div className="supply-request-filters">
          <div className="supply-filter-row supply-filter-row-primary">
          <EosSearchField
            aria-label="Номер или текст"
            placeholder="Номер или текст"
            value={search}
            onChange={(event) => { setSearch(event.target.value); setOffset(0) }}
          />
          <EosSelect aria-label="Статус" value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0) }}>
            <option value="">Все статусы</option>
            <option value="SUBMITTED">Создана</option>
            <option value="IN_REVIEW">В обработке</option>
            <option value="PLANNED">Сопоставлена</option>
            <option value="PARTIALLY_FULFILLED">Исполнена частично</option>
            <option value="FULFILLED">Исполнена</option>
            <option value="CANCELLED">Отменена</option>
          </EosSelect>
          <EosSelect aria-label="Подразделение" value={departmentId} onChange={(event) => { setDepartmentId(event.target.value); setOffset(0) }}>
            <option value="">Все подразделения</option>
            {departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </EosSelect>
          <EosSelect aria-label="Направление" value={directionId} onChange={(event) => { setDirectionId(event.target.value); setOffset(0) }}>
            <option value="">Все направления</option>
            {directions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </EosSelect>
          </div>
          <div className="supply-filter-row supply-filter-row-secondary">
          <EosSelect aria-label="Цикл" value={cycleId} onChange={(event) => { setCycleId(event.target.value); setOffset(0) }}>
            <option value="">Все циклы</option>
            {cycles.map((item) => <option key={item.id} value={item.id}>{item.cycle_date}</option>)}
          </EosSelect>
          <EosDateField label="С" value={dateFrom} onChange={(event) => { setDateFrom(event.target.value); setOffset(0) }} />
          <EosDateField label="По" value={dateTo} onChange={(event) => { setDateTo(event.target.value); setOffset(0) }} />
          <button className="secondary-action" type="button" onClick={() => void load()}>Обновить</button>
          </div>
          <div className="supply-filter-checks">
            <EosCheckbox label="Требует сопоставления" checked={needsReview} onChange={(event) => { setNeedsReview(event.target.checked); setOffset(0) }} />
            <EosCheckbox label="Есть дубли" checked={duplicates} onChange={(event) => { setDuplicates(event.target.checked); setOffset(0) }} />
          </div>
        </div>
        {state === 'loading' && <p className="page-state">Загружаем заявки…</p>}
        {state === 'error' && <p className="request-message request-message-error">Не удалось загрузить заявки</p>}
        {state === 'ready' && items.length === 0 && <p className="page-state">Заявок по выбранным условиям нет</p>}
        {items.length > 0 && (
          <div className="supply-registry">
            {items.map((item) => (
              <Link
                to={`/supply/requests/${item.id}`}
                className="supply-registry-row"
                key={item.id}
                title={item.public_number}
                aria-label={`${item.department.name}, ${item.direction.name}, ${statusLabel(item.status)}, ${item.public_number}`}
              >
                <div className="supply-registry-heading">
                  <strong>{item.department.name}</strong>
                  <span>{item.direction.name}</span>
                  <time>{formatDate(item.submitted_at ?? item.created_at)}</time>
                </div>
                <span>Позиций: {item.lines_total}</span>
                <strong className="supply-status">{statusLabel(item.status)}</strong>
                {item.lines_needs_review > 0 && (
                  <span className="supply-registry-warning">
                    Требуется сопоставить {item.lines_needs_review} позиций
                  </span>
                )}
                {item.duplicate_groups > 0 && (
                  <span className="supply-registry-warning">
                    Есть возможные дубли
                  </span>
                )}
              </Link>
            ))}
          </div>
        )}
        <EosPagination
          offset={offset}
          total={total}
          pageSize={SUPPLY_REQUEST_PAGE_SIZE}
          itemCount={items.length}
          onPageChange={setOffset}
        />
      </div>
    </section>
  )
}

export default SupplyRequestListPage
