import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  cancelSupplyDebt,
  closeSupplyDebt,
  getSupplyDebt,
  getSupplyDebts,
  SupplyApiError,
  type SupplyDebt,
} from '../services/supplyAdmin'

const SEVERITY_LABELS = {
  YELLOW: 'Новый',
  PURPLE: 'После следующего цикла',
  RED: 'После двух циклов',
  CRITICAL: 'Критический',
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

  const load = useCallback(async () => {
    const query = new URLSearchParams(searchParams)
    query.delete('open')
    if (!query.has('status')) query.set('status', 'ACTIVE')
    query.set('limit', '100')
    query.set('offset', '0')
    try {
      const page = await getSupplyDebts(query)
      setItems(page.items)
      const openId = searchParams.get('open')
      if (openId) setSelected(await getSupplyDebt(openId))
      setState('ready')
    } catch {
      setState('error')
    }
  }, [searchParams])

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timeout)
  }, [load])

  function updateFilter(name: string, value: string) {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(name, value)
    else next.delete(name)
    next.delete('open')
    setSearchParams(next)
  }

  async function closeDebt(debt: SupplyDebt) {
    const quantity = window.prompt(
      `Количество для закрытия (доступно ${debt.outstanding_quantity})`,
      debt.outstanding_quantity,
    )
    if (!quantity) return
    const comment = window.prompt('Комментарий к закрытию')
    if (!comment?.trim()) return
    setBusy(true)
    try {
      const updated = await closeSupplyDebt(
        debt.id, debt.version, quantity, comment.trim(),
      )
      setSelected(updated)
      setMessage('Долг обновлён')
      await load()
    } catch (error) {
      setMessage(
        error instanceof SupplyApiError
        && error.code === 'SUPPLY_DEBT_VERSION_CONFLICT'
          ? 'Долг уже изменился. Обновите страницу.'
          : 'Не удалось закрыть долг',
      )
    } finally {
      setBusy(false)
    }
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
      await load()
    } catch {
      setMessage('Не удалось отменить долг')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'loading') return <p className="page-state">Загружаем долги…</p>
  if (state === 'error') {
    return <p className="request-message request-message-error">Не удалось загрузить долги</p>
  }

  return (
    <section className="request-page supply-admin-page">
      <div className="request-panel">
        <div className="request-heading">
          <div><p className="eyebrow">СНАБЖЕНИЕ</p><h1>Долги подразделений</h1></div>
          <Link className="request-back-link" to="/supply/requests">К заявкам →</Link>
        </div>
        <div className="supply-filters">
          <label>
            <span>Поиск</span>
            <input
              value={searchParams.get('search') ?? ''}
              onChange={(event) => updateFilter('search', event.target.value)}
              placeholder="Товар или подразделение"
            />
          </label>
          <label>
            <span>Статус</span>
            <select
              value={searchParams.get('status') ?? 'ACTIVE'}
              onChange={(event) => updateFilter('status', event.target.value)}
            >
              <option value="">Все</option>
              <option value="ACTIVE">Активные</option>
              <option value="CLOSED">Закрытые</option>
              <option value="CANCELLED">Отменённые</option>
            </select>
          </label>
          <label>
            <span>Тревога</span>
            <select
              value={searchParams.get('severity') ?? ''}
              onChange={(event) => updateFilter('severity', event.target.value)}
            >
              <option value="">Все</option>
              {Object.entries(SEVERITY_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </div>
        {message && <p className="request-message">{message}</p>}
        {!items.length ? (
          <p className="page-state">Долгов по выбранным фильтрам нет</p>
        ) : (
          <div className="supply-debt-list">
            {items.map((debt) => (
              <button
                type="button"
                className={`supply-debt-row supply-debt-${debt.severity.toLowerCase()}`}
                key={debt.id}
                onClick={() => setSelected(debt)}
              >
                <strong>{debt.department.name} · {debt.product.name}</strong>
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
                <h2>{selected.department.name} · {selected.product.name}</h2>
              </div>
              <button type="button" onClick={() => setSelected(null)}>Закрыть карточку</button>
            </header>
            <dl className="request-facts">
              <div><dt>Осталось</dt><dd>{selected.outstanding_quantity} {selected.unit.short_name_ru}</dd></div>
              <div><dt>Исходно</dt><dd>{selected.original_quantity} {selected.unit.short_name_ru}</dd></div>
              <div><dt>Циклов</dt><dd>{selected.cycle_count}</dd></div>
              <div><dt>Статус</dt><dd>{STATUS_LABELS[selected.status]}</dd></div>
              <div><dt>Первая заявка</dt><dd><Link to={`/supply/requests/${selected.first_request_id}`}>Открыть</Link></dd></div>
              <div><dt>Последняя заявка</dt><dd><Link to={`/supply/requests/${selected.latest_request_id}`}>Открыть</Link></dd></div>
            </dl>
            {selected.status === 'ACTIVE' && (
              <div className="supply-card-actions">
                <button type="button" disabled={busy} onClick={() => void closeDebt(selected)}>
                  Закрыть частично или полностью
                </button>
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
