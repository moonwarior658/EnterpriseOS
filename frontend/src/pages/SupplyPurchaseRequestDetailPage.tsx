import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EosDateField, EosSelect } from '../components/EosFormControls'
import { EosProductCombobox } from '../components/EosProductCombobox'
import SupplyPurchaseAllocationWorkspace from './SupplyPurchaseAllocationWorkspace'
import {
  addSupplyPurchaseRequestLine,
  cancelSupplyPurchaseRequest,
  collectSupplyPurchaseRequestNeeds,
  deleteSupplyPurchaseRequestLine,
  getSupplyPurchaseRequest,
  getSupplyUnits,
  readySupplyPurchaseRequest,
  updateSupplyPurchaseRequest,
  updateSupplyPurchaseRequestLine,
  type SupplyProduct,
  type SupplyPurchaseRequest,
  type SupplyPurchaseRequestLine,
  type SupplyUnit,
  SupplyApiError,
} from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'


const STATUS_LABELS = { DRAFT: 'Черновик', READY: 'Зафиксирован', CANCELLED: 'Отменён' } as const
const REASON_LABELS: Record<string, string> = {
  INTERNAL_STOCK_DEFICIT: 'Дефицит после расчёта остатков',
  DEBT_CARRY_FORWARD: 'Перенос долга подразделения',
  ACTUAL_SHORTFALL: 'Недопоставка',
}

type LineDraft = { product: SupplyProduct | null; quantity: string; unitId: string; comment: string }
const emptyDraft: LineDraft = { product: null, quantity: '', unitId: '', comment: '' }

export default function SupplyPurchaseRequestDetailPage() {
  const { requestId = '' } = useParams()
  const [request, setRequest] = useState<SupplyPurchaseRequest | null>(null)
  const [units, setUnits] = useState<SupplyUnit[]>([])
  const [needDate, setNeedDate] = useState('')
  const [comment, setComment] = useState('')
  const [draft, setDraft] = useState<LineDraft>(emptyDraft)
  const [editing, setEditing] = useState<SupplyPurchaseRequestLine | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [collected, setCollected] = useState(false)
  const [showAllocations, setShowAllocations] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      getSupplyPurchaseRequest(requestId, controller.signal),
      getSupplyUnits(controller.signal),
    ]).then(([loaded, loadedUnits]) => {
      setRequest(loaded); setNeedDate(loaded.need_date)
      setComment(loaded.comment ?? ''); setUnits(loadedUnits.filter((unit) => unit.is_active))
    }).catch(() => { if (!controller.signal.aborted) setMessage('Не удалось загрузить закупочный запрос') })
    return () => controller.abort()
  }, [requestId])

  const isDraft = request?.status === 'DRAFT'

  function beginEdit(line: SupplyPurchaseRequestLine) {
    setEditing(line)
    setDraft({ product: null, quantity: line.manual_future_quantity, unitId: line.unit_id, comment: line.comment ?? '' })
  }

  async function saveHeader() {
    setBusy(true); setMessage('')
    try {
      const updated = await updateSupplyPurchaseRequest(requestId, { need_date: needDate, comment: comment || null })
      setRequest(updated); setMessage('Изменения сохранены')
    } catch { setMessage('Не удалось сохранить изменения') } finally { setBusy(false) }
  }

  async function saveLine(event: React.FormEvent) {
    event.preventDefault()
    if ((!editing && !draft.product) || !draft.quantity || !draft.unitId) return
    setBusy(true); setMessage('')
    try {
      const updated = editing
        ? await updateSupplyPurchaseRequestLine(requestId, editing.id, { manual_future_quantity: draft.quantity, unit_id: draft.unitId, comment: draft.comment || null })
        : await addSupplyPurchaseRequestLine(requestId, { product_id: draft.product!.id, quantity: draft.quantity, unit_id: draft.unitId, comment: draft.comment || null })
      setRequest(updated); setDraft(emptyDraft); setEditing(null)
    } catch { setMessage('Не удалось сохранить строку. Проверьте количество и отсутствие дубля.') } finally { setBusy(false) }
  }

  async function removeLine(line: SupplyPurchaseRequestLine) {
    if (!window.confirm(`Удалить «${line.product.name}» из запроса?`)) return
    setBusy(true)
    try { setRequest(await deleteSupplyPurchaseRequestLine(requestId, line.id)) }
    catch { setMessage('Не удалось удалить строку') } finally { setBusy(false) }
  }

  async function changeStatus(action: 'ready' | 'cancel') {
    if (action === 'cancel' && !window.confirm('Отменить закупочный запрос?')) return
    setBusy(true); setMessage('')
    try {
      setRequest(action === 'ready' ? await readySupplyPurchaseRequest(requestId) : await cancelSupplyPurchaseRequest(requestId))
      setEditing(null); setDraft(emptyDraft)
    } catch (error) { setMessage(error instanceof SupplyApiError ? error.message : action === 'ready' ? 'Добавьте строку перед фиксацией потребности' : 'Не удалось отменить запрос') }
    finally { setBusy(false) }
  }

  async function collectNeeds() {
    setBusy(true); setMessage('')
    try {
      const updated = await collectSupplyPurchaseRequestNeeds(requestId)
      setRequest(updated); setCollected(true)
      const automaticCount = updated.lines?.flatMap((line) => line.sources).filter((source) => source.source_type === 'PROCUREMENT_NEED').length ?? 0
      setMessage(automaticCount ? 'Потребность собрана' : 'Открытых потребностей на выбранную дату нет')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось собрать потребность')
    } finally { setBusy(false) }
  }

  if (!request) return <section className="request-page"><div className="request-panel"><p className="page-state">{message || 'Загружаем запрос…'}</p></div></section>

  return (
    <section className="request-page supply-admin-page purchase-request-page">
      <div className="request-panel">
        <div className="request-heading">
          <div><p className="eyebrow">СНАБЖЕНИЕ · ЗАКУПОЧНЫЙ ЗАПРОС</p><h1>Закупочный запрос №{request.number}</h1></div>
          <Link className="request-back-link" to="/supply/purchase-requests">К списку →</Link>
        </div>
        <div className="purchase-request-header">
          <EosDateField label="Дата потребности" value={needDate} disabled={!isDraft || busy} onChange={(event) => setNeedDate(event.target.value)} />
          <label className="eos-field"><span>Комментарий</span><input value={comment} disabled={!isDraft || busy} onChange={(event) => setComment(event.target.value)} /></label>
          <div><span className="field-label">Статус</span><span className={`purchase-status purchase-status-${request.status.toLowerCase()}`}>{STATUS_LABELS[request.status]}</span></div>
        </div>
        {message && <p className="request-message">{message}</p>}
        {isDraft && <div className="purchase-actions"><button type="button" className="secondary-action" disabled={busy} onClick={saveHeader}>Сохранить</button><button type="button" className="secondary-action" disabled={busy} onClick={collectNeeds}>Собрать потребность</button><button type="button" className="primary-action" disabled={busy || !request.lines?.length} onClick={() => changeStatus('ready')}>Зафиксировать потребность</button><button type="button" className="danger-action" disabled={busy} onClick={() => changeStatus('cancel')}>Отменить запрос</button></div>}
        {request.status === 'READY' && <div className="purchase-actions"><button type="button" className="primary-action" onClick={() => setShowAllocations((value) => !value)}>{showAllocations ? 'Скрыть распределение' : 'Распределить по поставщикам'}</button></div>}

        {request.status === 'READY' && showAllocations && <SupplyPurchaseAllocationWorkspace requestId={requestId} />}

        {isDraft && (
          <form className="purchase-line-form" onSubmit={saveLine}>
            <label className="eos-field"><span>Товар</span>{editing ? <input value={editing.product.name} disabled /> : <EosProductCombobox id="purchase-product" value={draft.product?.id ?? ''} selectedLabel={draft.product?.name ?? ''} disabled={busy} onChange={(product) => setDraft({ ...draft, product, unitId: product.default_unit.id })} />}</label>
            <label className="eos-field"><span>Количество</span><input type="number" min="0.001" step="0.001" required value={draft.quantity} disabled={busy} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })} /></label>
            <label className="eos-field"><span>Единица</span><EosSelect required value={draft.unitId} disabled={busy} onChange={(event) => setDraft({ ...draft, unitId: event.target.value })}><option value="">Выберите</option>{units.map((unit) => <option key={unit.id} value={unit.id}>{unit.short_name_ru}</option>)}</EosSelect></label>
            <label className="eos-field"><span>Комментарий</span><input value={draft.comment} disabled={busy} onChange={(event) => setDraft({ ...draft, comment: event.target.value })} /></label>
            <div className="purchase-line-form-actions"><button className="primary-action" type="submit" disabled={busy}>{editing ? 'Сохранить строку' : 'Добавить товар'}</button>{editing && <button className="secondary-action" type="button" onClick={() => { setEditing(null); setDraft(emptyDraft) }}>Отмена</button>}</div>
          </form>
        )}

        {!request.lines?.length ? <p className="page-state">{collected ? 'Открытых потребностей на выбранную дату нет' : 'Строк пока нет'}</p> : (
          <div className="supplier-table-wrap"><table className="supplier-table purchase-lines-table"><thead><tr><th>Товар</th><th>Количество</th><th>Источник / разбивка</th><th>Комментарий</th>{isDraft && <th>Действия</th>}</tr></thead><tbody>{request.lines.map((line) => {
            const automatic = line.sources.filter((source) => source.source_type === 'PROCUREMENT_NEED')
            const hasManual = line.sources.some((source) => source.source_type === 'MANUAL_FUTURE')
            return <tr key={line.id}><td><strong>{line.product.name}</strong></td><td>{line.quantity} {line.unit.short_name_ru}</td><td>{automatic.length > 0 && <div className="purchase-source-group"><strong>Автоматическая потребность {automatic.reduce((sum, source) => sum + Number(source.quantity), 0)} {line.unit.short_name_ru}</strong>{automatic.map((source) => <div className="purchase-source-trace" key={source.id}><span>{source.procurement_need?.department ?? 'Подразделение не указано'} · {source.quantity} {source.unit.short_name_ru}</span><small>{source.procurement_need?.request_number ? `Заявка ${source.procurement_need.request_number}` : 'Долг подразделения'} · {REASON_LABELS[source.procurement_need?.reason ?? ''] ?? source.procurement_need?.reason}</small></div>)}</div>}{hasManual && <div className="purchase-source-group"><strong>Будущая потребность {line.manual_future_quantity} {line.unit.short_name_ru}</strong></div>}</td><td>{line.comment || '—'}</td>{isDraft && <td><div className="supplier-row-actions">{hasManual && <button type="button" className="secondary-action" disabled={busy} onClick={() => beginEdit(line)}>Изменить будущую</button>}{hasManual && <button type="button" className="danger-action" disabled={busy} onClick={() => removeLine(line)}>Удалить будущую</button>}</div></td>}</tr>
          })}</tbody></table></div>
        )}
      </div>
    </section>
  )
}
