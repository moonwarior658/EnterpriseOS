import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  EosSearchField,
  EosSelect,
} from '../components/EosFormControls'
import {
  cancelSupplyDebt,
  getSupplyDebt,
  getSupplyDebts,
  SupplyApiError,
  type SupplyDebt,
} from '../services/supplyAdmin'

const SEVERITY_LABELS = {
  NONE: 'Первый недовоз',
  YELLOW: 'Второй недовоз',
  RED: 'Третий недовоз и далее',
} as const

const STATUS_LABELS = {
  ACTIVE: 'Активный',
  CLOSED: 'Закрыт',
  CANCELLED: 'Отменён',
} as const

const EVENT_LABELS: Record<string, string> = {
  CREATED: 'Долг создан',
  INCREASED: 'Долг увеличен',
  INCLUDED_IN_REQUEST: 'Учтён в новой заявке',
  PARTIALLY_CLOSED: 'Частично закрыт',
  CLOSED: 'Закрыт',
  CANCELLED: 'Отменён',
  REOPENED: 'Возобновлён',
  ADJUSTED: 'Скорректирован',
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short', timeStyle: 'short',
  }).format(new Date(value))
}

function SupplyDebtListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [items, setItems] = useState<SupplyDebt[]>([])
  const [selected, setSelected] = useState<SupplyDebt | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const activeRequest = useRef<AbortController | null>(null)
  const requestSequence = useRef(0)
  const searchKey = searchParams.toString()

  const load = useCallback(async (background = false) => {
    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    const sequence = requestSequence.current + 1
    requestSequence.current = sequence
    const routeParams = new URLSearchParams(searchKey)
    const query = new URLSearchParams(routeParams)
    query.delete('open')
    query.set('limit', '100')
    query.set('offset', '0')
    if (!background) setState('loading')
    try {
      const openId = routeParams.get('open')
      const [page, openedDebt] = await Promise.all([
        getSupplyDebts(query, controller.signal),
        openId
          ? getSupplyDebt(openId, controller.signal)
          : Promise.resolve(null),
      ])
      if (
        controller.signal.aborted
        || sequence !== requestSequence.current
      ) return
      setItems(page.items)
      setSelected(openedDebt)
      setState('ready')
    } catch {
      if (
        controller.signal.aborted
        || sequence !== requestSequence.current
      ) return
      if (!background) setState('error')
    }
  }, [searchKey])

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0)
    const interval = window.setInterval(() => void load(true), 10_000)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void load(true)
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.clearTimeout(timeout)
      window.clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisibility)
      activeRequest.current?.abort()
    }
  }, [load])

  function updateFilter(name: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(name, value)
    else next.delete(name)
    next.delete('open')
    setSearchParams(next)
  }

  function openDebt(debtId: string) {
    const next = new URLSearchParams(searchParams)
    next.set('open', debtId)
    setSearchParams(next)
  }

  function closeDebtCard() {
    const next = new URLSearchParams(searchParams)
    next.delete('open')
    setSearchParams(next)
  }

  async function cancelDebt(debt: SupplyDebt) {
    const comment = window.prompt('Укажите причину отмены долга')
    if (!comment?.trim()) return
    setBusy(true)
    try {
      const updated = await cancelSupplyDebt(
        debt.id, debt.version, comment.trim(),
      )
      setSelected(updated)
      setMessage('Долг отменён')
      await load(true)
    } catch (error) {
      setMessage(
        error instanceof SupplyApiError
        && error.code === 'SUPPLY_DEBT_VERSION_CONFLICT'
          ? 'Долг уже изменился. Список обновлён — повторите действие.'
          : 'Не удалось отменить долг',
      )
      if (
        error instanceof SupplyApiError
        && error.code === 'SUPPLY_DEBT_VERSION_CONFLICT'
      ) await load(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="request-page supply-admin-page">
      <div className="request-panel">
        <div className="request-heading">
          <div><p className="eyebrow">СНАБЖЕНИЕ</p><h1>Долги подразделений</h1></div>
          <Link className="request-back-link" to="/supply/requests">К заявкам →</Link>
        </div>
        <div className="supply-debt-filters">
          <EosSearchField
              label="Поиск"
              value={searchParams.get('search') ?? ''}
              onChange={(event) => updateFilter('search', event.target.value)}
              placeholder="Товар или подразделение"
            />
          <label className="eos-field">
            <span>Статус</span>
            <EosSelect
              value={searchParams.get('status') ?? ''}
              onChange={(event) => updateFilter('status', event.target.value)}
            >
              <option value="">Все</option>
              <option value="ACTIVE">Активные</option>
              <option value="CLOSED">Закрытые</option>
              <option value="CANCELLED">Отменённые</option>
            </EosSelect>
          </label>
          <label className="eos-field">
            <span>Тревога</span>
            <EosSelect
              value={searchParams.get('severity') ?? ''}
              onChange={(event) => updateFilter('severity', event.target.value)}
            >
              <option value="">Все</option>
              {Object.entries(SEVERITY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </EosSelect>
          </label>
        </div>
        {message && <p className="request-message">{message}</p>}
        {state === 'loading' && (
          <p className="page-state">Загружаем долги…</p>
        )}
        {state === 'error' && (
          <p className="request-message request-message-error">
            Не удалось загрузить долги
          </p>
        )}
        {state === 'ready' && !items.length ? (
          <p className="page-state">Долгов по выбранным фильтрам нет</p>
        ) : items.length > 0 && (
          <div className="supply-debt-list">
            {items.map((debt) => (
              <button
                type="button"
                className={`supply-debt-row supply-debt-${debt.severity.toLowerCase()}`}
                key={debt.id}
                onClick={() => openDebt(debt.id)}
              >
                <strong>{debt.department.name} · {debt.working_name}</strong>
                <span>{debt.outstanding_quantity} {debt.unit.short_name_ru}</span>
                <span>{SEVERITY_LABELS[debt.severity]}</span>
                <span>{formatDate(debt.opened_at)}</span>
                <span>{STATUS_LABELS[debt.status]}</span>
              </button>
            ))}
          </div>
        )}
        {selected && (
          <article className="supply-debt-detail">
            <header>
              <div>
                <p className="eyebrow">{SEVERITY_LABELS[selected.severity]}</p>
                <h2>{selected.department.name} · {selected.working_name}</h2>
              </div>
              <button type="button" onClick={closeDebtCard}>Закрыть карточку</button>
            </header>
            <dl className="request-facts">
              <div><dt>Осталось</dt><dd>{selected.outstanding_quantity} {selected.unit.short_name_ru}</dd></div>
              <div><dt>Исходно</dt><dd>{selected.original_quantity} {selected.unit.short_name_ru}</dd></div>
              <div><dt>Недовозов подряд</dt><dd>{selected.cycle_count}</dd></div>
              <div><dt>Статус</dt><dd>{STATUS_LABELS[selected.status]}</dd></div>
              <div><dt>Первая заявка</dt><dd><Link to={`/supply/requests/${selected.first_request_id}`}>Открыть</Link></dd></div>
              <div><dt>Последняя заявка</dt><dd><Link to={`/supply/requests/${selected.latest_request_id}`}>Открыть</Link></dd></div>
            </dl>
            {!selected.product && (
              <p className="request-message request-message-warning">
                Требуется ручное сопоставление товара EOS. Откройте первую
                заявку и сопоставьте строку долга.
              </p>
            )}
            {selected.status === 'ACTIVE' && (
              <div className="supply-card-actions">
                <button type="button" disabled={busy} onClick={() => void cancelDebt(selected)}>
                  Отменить долг
                </button>
              </div>
            )}
            <h3>История</h3>
            <ol className="supply-debt-events">
              {selected.events.map((item) => (
                <li key={item.id}>
                  <strong>{EVENT_LABELS[item.event_type] ?? 'Изменение долга'}</strong>
                  <span>{item.quantity_before} → {item.quantity_after}</span>
                  <span>{item.comment ?? 'Без комментария'}</span>
                  <time>{formatDate(item.created_at)}</time>
                </li>
              ))}
            </ol>
          </article>
        )}
      </div>
    </section>
  )
}

export default SupplyDebtListPage
