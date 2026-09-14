import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { EosDateField } from '../components/EosFormControls'
import {
  createSupplyPurchaseRequest,
  getSupplyPurchaseRequests,
  type SupplyPurchaseRequest,
} from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'


const STATUS_LABELS = {
  DRAFT: 'Черновик', READY: 'Зафиксирован', CANCELLED: 'Отменён',
} as const

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU').format(new Date(`${value}T00:00:00`))
}

export default function SupplyPurchaseRequestsPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<SupplyPurchaseRequest[]>([])
  const [needDate, setNeedDate] = useState('')
  const [comment, setComment] = useState('')
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    getSupplyPurchaseRequests(controller.signal).then((page) => {
      setItems(page.items)
      setState('ready')
    }).catch(() => {
      if (!controller.signal.aborted) setState('error')
    })
    return () => controller.abort()
  }, [])

  async function createRequest(event: React.FormEvent) {
    event.preventDefault()
    if (!needDate) return
    setBusy(true)
    setMessage('')
    try {
      const created = await createSupplyPurchaseRequest({
        need_date: needDate, comment: comment || null,
      })
      navigate(`/supply/purchase-requests/${created.id}`)
    } catch {
      setMessage('Не удалось создать закупочный запрос')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="request-page supply-admin-page purchase-request-page">
      <div className="request-panel">
        <div className="request-heading">
          <div>
            <p className="eyebrow">СНАБЖЕНИЕ</p>
            <h1>Закупочные запросы</h1>
            <p className="subtitle">Внутренняя потребность компании на дату</p>
          </div>
          <Link className="request-back-link" to="/supply/requests">К заявкам →</Link>
        </div>

        <form className="purchase-request-create" onSubmit={createRequest}>
          <EosDateField
            label="Дата потребности" value={needDate} required
            disabled={busy} onChange={(event) => setNeedDate(event.target.value)}
          />
          <label className="eos-field">
            <span>Комментарий</span>
            <input
              value={comment} disabled={busy}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Необязательно"
            />
          </label>
          <button className="primary-action" type="submit" disabled={busy || !needDate}>
            {busy ? 'Создаём…' : 'Создать запрос'}
          </button>
        </form>
        {message && <p className="request-message request-message-error">{message}</p>}
        {state === 'loading' && <p className="page-state">Загружаем запросы…</p>}
        {state === 'error' && <p className="request-message request-message-error">Не удалось загрузить запросы</p>}
        {state === 'ready' && items.length === 0 && <p className="page-state">Закупочных запросов пока нет</p>}
        {items.length > 0 && (
          <div className="supplier-table-wrap">
            <table className="supplier-table purchase-request-table">
              <thead><tr><th>Номер</th><th>Дата потребности</th><th>Статус</th><th>Строк</th><th>Обновлён</th></tr></thead>
              <tbody>{items.map((item) => (
                <tr key={item.id}>
                  <td><Link to={`/supply/purchase-requests/${item.id}`}>{item.number}</Link></td>
                  <td>{formatDate(item.need_date)}</td>
                  <td><span className={`purchase-status purchase-status-${item.status.toLowerCase()}`}>{STATUS_LABELS[item.status]}</span></td>
                  <td>{item.line_count}</td>
                  <td>{new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(item.updated_at))}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
