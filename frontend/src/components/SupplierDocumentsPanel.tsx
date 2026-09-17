import { useEffect, useState } from 'react'
import { EosDateField, EosSelect } from './EosFormControls'
import {
  addSupplySupplierDocumentLine,
  cancelSupplySupplierDocument,
  createSupplySupplierDocument,
  deleteSupplySupplierDocumentLine,
  getSupplySupplierDocuments,
  recordSupplySupplierDocument,
  updateSupplySupplierDocument,
  updateSupplySupplierDocumentLine,
  type SupplySupplierDocument,
  type SupplySupplierDocumentLine,
  type SupplySupplierDocumentType,
  type SupplySupplierOrder,
  SupplyApiError,
} from '../services/supplyAdmin'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const typeLabels = { INVOICE: 'Счёт', DELIVERY_NOTE: 'Накладная', UPD: 'УПД' } as const
const statusLabels = { DRAFT: 'Черновик', RECORDED: 'Зафиксирован', CANCELLED: 'Отменён' } as const

type Props = { order: SupplySupplierOrder; onOrderRefresh: () => void }

export default function SupplierDocumentsPanel({ order, onOrderRefresh }: Props) {
  const [documents, setDocuments] = useState<SupplySupplierDocument[]>([])
  const [draft, setDraft] = useState<SupplySupplierDocument | null>(null)
  const [newType, setNewType] = useState<SupplySupplierDocumentType>('INVOICE')
  const [extraName, setExtraName] = useState('Доставка')
  const [extraAmount, setExtraAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function load() {
    const loaded = await getSupplySupplierDocuments(order.id)
    setDocuments(loaded)
    setDraft(loaded.find((item) => item.status === 'DRAFT') ?? null)
  }

  useEffect(() => {
    let active = true
    getSupplySupplierDocuments(order.id).then((loaded) => {
      if (!active) return
      setDocuments(loaded)
      setDraft(loaded.find((item) => item.status === 'DRAFT') ?? null)
    }).catch(() => { if (active) setMessage('Не удалось загрузить документы поставщика') })
    return () => { active = false }
  }, [order.id])

  async function run(action: () => Promise<SupplySupplierDocument>, success?: string) {
    setBusy(true); setMessage('')
    try {
      const value = await action()
      setDraft(value.status === 'DRAFT' ? value : null)
      await load(); onOrderRefresh()
      if (success) setMessage(success)
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось изменить документ')
    } finally { setBusy(false) }
  }

  async function create() {
    await run(() => createSupplySupplierDocument(order.id, { document_type: newType }))
  }

  async function saveHeader() {
    if (!draft) throw new Error('No draft')
    const value = await updateSupplySupplierDocument(draft.id, {
      document_type: draft.document_type,
      document_number: draft.document_number,
      document_date: draft.document_date,
      comment: draft.comment,
    })
    setDraft(value)
    return value
  }

  async function saveLine(line: SupplySupplierDocumentLine, changes: Partial<SupplySupplierDocumentLine>) {
    if (!draft) return
    const current = { ...line, ...changes }
    const input = current.pricing_basis === 'PACKAGE'
      ? { packages_count: current.packages_count, price_per_package: current.price_per_package }
      : line.pricing_basis === 'UNIT'
        ? { quantity_base: current.quantity_base, unit_price: current.unit_price }
        : { line_amount: current.line_amount }
    await run(() => updateSupplySupplierDocumentLine(draft.id, line.id, input))
  }

  async function addExtra() {
    if (!draft || !extraName.trim() || !extraAmount) return
    await run(() => addSupplySupplierDocumentLine(draft.id, {
      product_name_snapshot: extraName,
      pricing_basis: 'FIXED_AMOUNT',
      line_amount: extraAmount,
    }))
    setExtraAmount('')
  }

  async function record() {
    if (!draft || !window.confirm('Зафиксировать документ поставщика? После этого редактирование будет недоступно.')) return
    setBusy(true); setMessage('')
    try {
      await saveHeader()
      await recordSupplySupplierDocument(draft.id)
      setDraft(null); await load(); onOrderRefresh(); setMessage('Документ зафиксирован')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось зафиксировать документ')
    } finally { setBusy(false) }
  }

  async function cancel() {
    if (!draft || !window.confirm('Отменить черновик документа?')) return
    await run(() => cancelSupplySupplierDocument(draft.id))
  }

  function patchDraftLine(lineId: string, changes: Partial<SupplySupplierDocumentLine>) {
    if (!draft) return
    setDraft({ ...draft, lines: draft.lines.map((line) => line.id === lineId ? { ...line, ...changes } : line) })
  }

  return <section className="supplier-message-panel supplier-documents-panel">
    <div className="supplier-message-heading"><div><span className="field-label">ДОКУМЕНТЫ ПОСТАВЩИКА</span><h2>Счета, накладные и УПД</h2></div><span>Это документы поставщика, не факт приёмки товара</span></div>
    {message && <p className="request-message">{message}</p>}
    {!draft && <div className="supplier-document-create">
      <label className="eos-field"><span>Тип документа</span><EosSelect value={newType} disabled={busy} onChange={(event) => setNewType(event.target.value as SupplySupplierDocumentType)}><option value="INVOICE">Счёт</option><option value="DELIVERY_NOTE">Накладная</option><option value="UPD">УПД</option></EosSelect></label>
      <button type="button" className="primary-action" disabled={busy} onClick={create}>Добавить документ</button>
    </div>}
    {draft && <div className="supplier-document-editor">
      <div className="purchase-request-header">
        <label className="eos-field"><span>Тип</span><EosSelect value={draft.document_type} disabled={busy} onChange={(event) => setDraft({ ...draft, document_type: event.target.value as SupplySupplierDocumentType })}><option value="INVOICE">Счёт</option><option value="DELIVERY_NOTE">Накладная</option><option value="UPD">УПД</option></EosSelect></label>
        <label className="eos-field"><span>Номер</span><input value={draft.document_number ?? ''} disabled={busy} onChange={(event) => setDraft({ ...draft, document_number: event.target.value || null })} /></label>
        <EosDateField label="Дата" value={draft.document_date ?? ''} disabled={busy} onChange={(event) => setDraft({ ...draft, document_date: event.target.value || null })} />
      </div>
      {order.supplier_confirmation_review_state === 'REQUIRES_DECISION' && <p className="supplier-message-warning">Документ можно подготовить, но фиксация заблокирована до решений по обязательным отклонениям последнего ответа поставщика.</p>}
      <label className="eos-field"><span>Комментарий</span><input value={draft.comment ?? ''} disabled={busy} onChange={(event) => setDraft({ ...draft, comment: event.target.value || null })} /></label>
      <div className="supplier-table-wrap"><table className="supplier-table supplier-document-lines"><thead><tr><th>Позиция</th><th>Расчёт</th><th>Количество</th><th>Цена</th><th>Сумма</th><th></th></tr></thead><tbody>{draft.lines.map((line) => <tr key={line.id}>
        <td><strong>{line.product_name_snapshot}</strong>{line.is_extra_line && <small>Дополнительная строка документа</small>}</td>
        <td>{line.pricing_basis === 'PACKAGE' ? 'По упаковкам' : line.pricing_basis === 'UNIT' ? 'По количеству' : 'Фиксированная сумма'}</td>
        <td>{line.pricing_basis === 'PACKAGE' ? <input aria-label={`Упаковок ${line.product_name_snapshot}`} type="number" min="1" value={line.packages_count ?? ''} disabled={busy} onChange={(event) => patchDraftLine(line.id, { packages_count: Number(event.target.value) })} onBlur={(event) => saveLine(line, { packages_count: Number(event.target.value) })} /> : line.pricing_basis === 'UNIT' ? <input aria-label={`Количество ${line.product_name_snapshot}`} type="number" min="0.000001" step="0.000001" value={line.quantity_base ?? ''} disabled={busy} onChange={(event) => patchDraftLine(line.id, { quantity_base: event.target.value })} onBlur={(event) => saveLine(line, { quantity_base: event.target.value })} /> : '—'}{line.unit_name_snapshot && <small>{line.unit_name_snapshot}</small>}</td>
        <td>{line.pricing_basis === 'PACKAGE' ? <input aria-label={`Цена ${line.product_name_snapshot}`} type="number" min="0.01" step="0.01" value={line.price_per_package ?? ''} disabled={busy} onChange={(event) => patchDraftLine(line.id, { price_per_package: event.target.value })} onBlur={(event) => saveLine(line, { price_per_package: event.target.value })} /> : line.pricing_basis === 'UNIT' ? <input aria-label={`Цена единицы ${line.product_name_snapshot}`} type="number" min="0.000001" step="0.000001" value={line.unit_price ?? ''} disabled={busy} onChange={(event) => patchDraftLine(line.id, { unit_price: event.target.value })} onBlur={(event) => saveLine(line, { unit_price: event.target.value })} /> : '—'}</td>
        <td>{money.format(Number(line.line_amount))}</td>
        <td><button type="button" className="danger-action" disabled={busy} onClick={() => run(() => deleteSupplySupplierDocumentLine(draft.id, line.id))}>Удалить</button></td>
      </tr>)}</tbody></table></div>
      <div className="supplier-document-extra"><label className="eos-field"><span>Дополнительная строка</span><input value={extraName} disabled={busy} onChange={(event) => setExtraName(event.target.value)} /></label><label className="eos-field"><span>Сумма</span><input type="number" min="0.000001" step="0.000001" value={extraAmount} disabled={busy} onChange={(event) => setExtraAmount(event.target.value)} /></label><button type="button" className="secondary-action" disabled={busy || !extraName.trim() || !extraAmount} onClick={addExtra}>Добавить расход</button></div>
      <div className="allocation-summary"><div><span>Итого по документу</span><strong>{money.format(Number(draft.total_amount))}</strong></div>{draft.supplier_confirmation_revision && <div><span>Источник defaults</span><strong>Ответ поставщика, ревизия {draft.supplier_confirmation_revision}</strong></div>}</div>
      <div className="purchase-actions"><button type="button" className="secondary-action" disabled={busy} onClick={() => run(saveHeader, 'Черновик сохранён')}>Сохранить</button><button type="button" className="primary-action" disabled={busy} onClick={record}>Зафиксировать документ</button><button type="button" className="danger-action" disabled={busy} onClick={cancel}>Отменить черновик</button></div>
    </div>}
    {documents.length > 0 && <div className="supplier-table-wrap"><h3>История документов</h3><table className="supplier-table"><thead><tr><th>Тип</th><th>Номер</th><th>Дата</th><th>Сумма</th><th>Статус</th></tr></thead><tbody>{documents.map((document) => <tr key={document.id}><td>{typeLabels[document.document_type]}</td><td>{document.document_number ?? 'Не указан'}</td><td>{document.document_date ? new Date(`${document.document_date}T00:00:00`).toLocaleDateString('ru-RU') : 'Не указана'}</td><td>{money.format(Number(document.total_amount))}</td><td>{statusLabels[document.status]}</td></tr>)}</tbody></table></div>}
  </section>
}
