import { useEffect, useState } from 'react'
import { EosDateField, EosSelect } from './EosFormControls'
import {
  cancelSupplySupplierConfirmation,
  createSupplySupplierConfirmation,
  getSupplySupplierConfirmations,
  recordSupplySupplierConfirmation,
  updateSupplySupplierConfirmation,
  updateSupplySupplierConfirmationLine,
  type SupplySupplierConfirmation,
  type SupplySupplierConfirmationLine,
  type SupplySupplierOrder,
  SupplyApiError,
} from '../services/supplyAdmin'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const responseLabels = {
  CONFIRMED: 'Подтверждено', PARTIALLY_CONFIRMED: 'Подтверждено частично', REJECTED: 'Отклонено',
} as const
const statusLabels = { DRAFT: 'Черновик', RECORDED: 'Зафиксировано', SUPERSEDED: 'Заменено новой ревизией', CANCELLED: 'Отменено' } as const

type Props = { order: SupplySupplierOrder; onOrderRefresh: () => void }

export default function SupplierConfirmationPanel({ order, onOrderRefresh }: Props) {
  const [history, setHistory] = useState<SupplySupplierConfirmation[]>([])
  const [draft, setDraft] = useState<SupplySupplierConfirmation | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function load() {
    const items = await getSupplySupplierConfirmations(order.id)
    setHistory(items)
    setDraft(items.find((item) => item.status === 'DRAFT') ?? null)
  }
  useEffect(() => {
    let active = true
    getSupplySupplierConfirmations(order.id).then((items) => {
      if (!active) return
      setHistory(items)
      setDraft(items.find((item) => item.status === 'DRAFT') ?? null)
    }).catch(() => { if (active) setMessage('Не удалось загрузить ответы поставщика') })
    return () => { active = false }
  }, [order.id])

  async function create() {
    setBusy(true); setMessage('')
    try { const value = await createSupplySupplierConfirmation(order.id); setDraft(value); await load(); onOrderRefresh() }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось создать черновик ответа') }
    finally { setBusy(false) }
  }
  async function saveHeader() {
    if (!draft) return null
    const value = await updateSupplySupplierConfirmation(draft.id, {
      supplier_reference: draft.supplier_reference,
      supplier_comment: draft.supplier_comment,
      confirmed_delivery_date: draft.confirmed_delivery_date,
      responded_at: draft.responded_at,
    })
    setDraft(value); return value
  }
  async function saveLine(line: SupplySupplierConfirmationLine, changes: Record<string, unknown>) {
    if (!draft) return
    setBusy(true); setMessage('')
    try {
      const value = await updateSupplySupplierConfirmationLine(draft.id, line.id, changes)
      setDraft(value)
    } catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось сохранить строку') }
    finally { setBusy(false) }
  }
  async function record() {
    if (!draft || !window.confirm(`Зафиксировать ответ поставщика, ревизия ${draft.revision_number}?`)) return
    setBusy(true); setMessage('')
    try { await saveHeader(); await recordSupplySupplierConfirmation(draft.id); setDraft(null); await load(); onOrderRefresh(); setMessage('Ответ поставщика зафиксирован') }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось зафиксировать ответ') }
    finally { setBusy(false) }
  }
  async function cancel() {
    if (!draft || !window.confirm('Отменить черновик ответа поставщика?')) return
    setBusy(true); setMessage('')
    try { await cancelSupplySupplierConfirmation(draft.id); setDraft(null); await load(); onOrderRefresh() }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось отменить черновик') }
    finally { setBusy(false) }
  }

  return <section className="supplier-message-panel supplier-confirmation-panel">
    <div className="supplier-message-heading"><div><span className="field-label">ОТВЕТ ПОСТАВЩИКА</span><h2>{draft ? `Ревизия ${draft.revision_number}` : 'Подтверждение заказа'}</h2></div><span>{order.supplier_display_name}</span></div>
    {message && <p className="request-message">{message}</p>}
    {!draft && <button type="button" className="primary-action" disabled={busy} onClick={create}>Зафиксировать ответ поставщика</button>}
    {draft && <>
      <div className="purchase-request-header">
        <EosDateField label="Подтверждённая дата поставки" value={draft.confirmed_delivery_date ?? ''} disabled={busy} onChange={(event) => setDraft({ ...draft, confirmed_delivery_date: event.target.value || null })} />
        <label className="eos-field"><span>Номер / ссылка поставщика</span><input disabled={busy} value={draft.supplier_reference ?? ''} onChange={(event) => setDraft({ ...draft, supplier_reference: event.target.value || null })} /></label>
        <label className="eos-field"><span>Когда поставщик ответил</span><input type="datetime-local" disabled={busy} value={draft.responded_at ? new Date(draft.responded_at).toISOString().slice(0, 16) : ''} onChange={(event) => setDraft({ ...draft, responded_at: event.target.value ? new Date(event.target.value).toISOString() : null })} /></label>
      </div>
      <label className="eos-field"><span>Комментарий поставщика</span><input disabled={busy} value={draft.supplier_comment ?? ''} onChange={(event) => setDraft({ ...draft, supplier_comment: event.target.value || null })} /></label>
      <div className="supplier-table-wrap"><table className="supplier-table confirmation-lines-table"><thead><tr><th>Товар</th><th>Заказано</th><th>Ответ</th><th>Подтверждено</th><th>Комментарий</th></tr></thead><tbody>{draft.lines.map((line) => <tr key={line.id}>
        <td><strong>{line.product_name_snapshot}</strong></td>
        <td>{line.ordered_packages_count} уп. · {line.ordered_quantity_base} {line.ordered_package_unit}<br />{money.format(Number(line.ordered_price_per_package))} / уп.</td>
        <td><EosSelect aria-label={`Ответ по ${line.product_name_snapshot}`} disabled={busy} value={line.response_status} onChange={(event) => saveLine(line, { response_status: event.target.value })}><option value="CONFIRMED">Подтверждено</option><option value="CHANGED">Изменено</option><option value="REJECTED">Отклонено</option></EosSelect></td>
        <td>{line.response_status === 'REJECTED' ? <span>Не подтверждено</span> : <div className="confirmation-values"><label>Упаковок<input type="number" min="1" disabled={busy} value={line.confirmed_packages_count ?? ''} onChange={(event) => setDraft({ ...draft, lines: draft.lines.map((item) => item.id === line.id ? { ...item, confirmed_packages_count: Number(event.target.value) } : item) })} onBlur={(event) => saveLine(line, { confirmed_packages_count: Number(event.target.value) })} /></label><label>Цена / уп.<input type="number" min="0.01" step="0.01" disabled={busy} value={line.confirmed_price_per_package ?? ''} onChange={(event) => setDraft({ ...draft, lines: draft.lines.map((item) => item.id === line.id ? { ...item, confirmed_price_per_package: event.target.value } : item) })} onBlur={(event) => saveLine(line, { confirmed_price_per_package: event.target.value })} /></label><small>{line.ordered_packages_count !== line.confirmed_packages_count ? `${line.ordered_packages_count} → ${line.confirmed_packages_count}` : ''} {line.ordered_price_per_package !== line.confirmed_price_per_package ? `${money.format(Number(line.ordered_price_per_package))} → ${money.format(Number(line.confirmed_price_per_package))}` : ''}</small></div>}</td>
        <td><input disabled={busy} value={line.supplier_line_comment ?? ''} onChange={(event) => setDraft({ ...draft, lines: draft.lines.map((item) => item.id === line.id ? { ...item, supplier_line_comment: event.target.value || null } : item) })} onBlur={(event) => saveLine(line, { supplier_line_comment: event.target.value || null })} /></td>
      </tr>)}</tbody></table></div>
      <div className="allocation-summary"><div><span>Заказано</span><strong>{money.format(Number(draft.ordered_total_amount))}</strong></div><div><span>Подтверждено</span><strong>{money.format(Number(draft.confirmed_total_amount))}</strong></div></div>
      <div className="purchase-actions"><button type="button" className="secondary-action" disabled={busy} onClick={() => saveHeader().then(() => setMessage('Черновик сохранён')).catch((error) => setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось сохранить черновик'))}>Сохранить</button><button type="button" className="primary-action" disabled={busy} onClick={record}>Зафиксировать ответ</button><button type="button" className="danger-action" disabled={busy} onClick={cancel}>Отменить черновик</button></div>
    </>}
    {history.length > 0 && <div className="supplier-table-wrap"><h3>История ответов</h3><table className="supplier-table"><thead><tr><th>Ревизия</th><th>Статус</th><th>Ответ</th><th>Дата поставки</th><th>Сумма</th><th>Зафиксировано</th></tr></thead><tbody>{history.map((item) => <tr key={item.id}><td>№{item.revision_number}</td><td>{statusLabels[item.status]}</td><td>{item.response_type ? responseLabels[item.response_type] : '—'}</td><td>{item.confirmed_delivery_date ?? '—'}</td><td>{money.format(Number(item.confirmed_total_amount))}</td><td>{item.recorded_at ? new Date(item.recorded_at).toLocaleString('ru-RU') : '—'}</td></tr>)}</tbody></table></div>}
  </section>
}
