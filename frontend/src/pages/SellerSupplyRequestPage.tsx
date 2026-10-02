import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { EosSelect } from '../components/EosFormControls'
import { formatDateTime } from '../utils/dateFormat'
import {
  BusinessActionError, confirmSellerRequest, getSellerWindow, saveSellerRequest,
  type SellerWindow,
} from '../services/actionContext'
import './SupplyPurchaseRequestsPage.css'

export default function SellerSupplyRequestPage() {
  const [windowInfo, setWindowInfo] = useState<SellerWindow | null>(null)
  const [allowedDepartments, setAllowedDepartments] = useState<SellerWindow['allowed_departments']>([])
  const [departmentId, setDepartmentId] = useState('')
  const [text, setText] = useState('')
  const [editing, setEditing] = useState(true)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    let active = true
    getSellerWindow(departmentId || undefined).then((result) => {
      if (!active) return
      setWindowInfo(result)
      if (result.allowed_departments.length) setAllowedDepartments(result.allowed_departments)
      setText(result.request?.raw_input ?? '')
      setEditing(result.request?.status !== 'SUBMITTED')
      setMessage('')
    }).catch(() => { if (active) setMessage('Не удалось загрузить окно заявок') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [departmentId])

  function errorMessage(error: unknown, fallback: string) {
    return error instanceof BusinessActionError ? error.message : fallback
  }

  async function save(event?: FormEvent) {
    event?.preventDefault()
    if (!windowInfo?.can_write || busy || !text.trim()) return
    setBusy(true); setMessage('')
    try {
      const request = await saveSellerRequest({
        department_id: departmentId || undefined,
        raw_input: text,
        expected_version: windowInfo.request?.version,
      })
      setWindowInfo({ ...windowInfo, request })
      setMessage('Черновик сохранён. Подтвердите заявку до закрытия приёма.')
    } catch (error) { setMessage(errorMessage(error, 'Не удалось сохранить заявку')) }
    finally { setBusy(false) }
  }

  async function confirm() {
    if (!windowInfo?.can_write || busy || !text.trim()) return
    setBusy(true); setMessage('')
    try {
      const current = windowInfo.request?.status === 'DRAFT' && windowInfo.request.raw_input === text.trim()
        ? windowInfo.request
        : await saveSellerRequest({
          department_id: departmentId || undefined,
          raw_input: text,
          expected_version: windowInfo.request?.version,
        })
      const confirmed = await confirmSellerRequest({
        department_id: departmentId || undefined,
        expected_version: current.version,
      })
      setWindowInfo({ ...windowInfo, request: confirmed })
      setEditing(false)
      setMessage('Заявка подтверждена. До закрытия приёма её можно изменить.')
    } catch (error) { setMessage(errorMessage(error, 'Не удалось подтвердить заявку')) }
    finally { setBusy(false) }
  }

  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ</p><h1>Заявка на товары</h1></div><Link className="request-back-link" to="/supply/requests">Назад</Link></div>
    {loading && <p className="page-state">Загружаем окно заявок…</p>}
    {!loading && windowInfo && <>
      {windowInfo.is_open ? <>
        {windowInfo.department && <p>Точка: <strong>{windowInfo.department.name}</strong></p>}
        {windowInfo.closes_at && <p>Приём заявок до: <strong>{formatDateTime(windowInfo.closes_at)}</strong></p>}
        {!windowInfo.department && allowedDepartments.length > 0 && <label className="eos-field"><span>Точка</span><EosSelect value={departmentId} disabled={busy} onChange={(event) => setDepartmentId(event.target.value)}><option value="">Выберите торговую точку</option>{allowedDepartments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</EosSelect></label>}
        <form onSubmit={(event) => void save(event)}>
          <label className="eos-field"><span>Что нужно</span><textarea value={text} disabled={!windowInfo.can_write || !editing || busy} rows={8} maxLength={10000} onChange={(event) => setText(event.target.value)} /></label>
          <p className="employee-help">Каждый товар укажите с новой строки.<br />Формат: Название — количество — фасовка.<br />Примеры:<br />Сливки 33% — 6 л<br />Молоко — 12 шт<br />Клубника — 5 кг<br />Стаканы 300 мл — 4 кор</p>
          {windowInfo.supported_units.length > 0 && <p className="employee-help">Поддерживаемые единицы и фасовки: {windowInfo.supported_units.join(', ')}</p>}
          {windowInfo.can_write && <div className="purchase-actions">
            {windowInfo.request?.status === 'SUBMITTED' && !editing
              ? <button className="secondary-action" type="button" onClick={() => setEditing(true)}>Изменить</button>
              : <><button className="secondary-action" type="submit" disabled={busy || !text.trim()}>{busy ? 'Сохраняем…' : 'Сохранить черновик'}</button><button className="primary-action" type="button" disabled={busy || !text.trim()} onClick={() => void confirm()}>Подтвердить</button></>}
          </div>}
        </form>
        {!windowInfo.can_write && <p className="request-message">{windowInfo.reason ?? 'Выберите торговую точку или откройте смену iiko'}</p>}
      </> : <p className="page-state">{windowInfo.reason ?? 'Приём заявок сейчас закрыт'}</p>}
      {windowInfo.request && <Link className="secondary-action" to={`/supply/requests/${windowInfo.request.id}`}>Открыть заявку</Link>}
    </>}
    {message && <p className="request-message" role="status">{message}</p>}
  </div></section>
}
