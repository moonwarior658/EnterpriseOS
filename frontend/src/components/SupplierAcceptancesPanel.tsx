import { useCallback, useEffect, useState } from 'react'
import { EosSelect } from './EosFormControls'
import {
  getConfirmedDestinationWarehouseMappings,
  type IikoWarehouseMapping,
} from '../services/iikoMapping'
import {
  addSupplySupplierAcceptanceLine, cancelSupplySupplierAcceptance, createSupplySupplierAcceptance, getSupplySupplierAcceptances,
  getSupplySupplierDocuments, recordSupplySupplierAcceptance, updateSupplySupplierAcceptance,
  getSupplyIikoIncomingReceiptForAcceptance, prepareSupplyIikoIncomingReceipt,
  resolveSupplyAcceptanceResolution, updateSupplySupplierAcceptanceLine, SupplyApiError,
  transitionSupplyIikoIncomingReceipt,
  updateSupplySupplierAcceptanceLineSources,
  type SupplyAcceptanceResolution, type SupplyAcceptanceResolutionType,
  type SupplySupplierAcceptance, type SupplySupplierAcceptanceLine,
  type SupplyIikoIncomingReceipt,
  type SupplySupplierAcceptanceRejectionReason, type SupplySupplierDocument, type SupplySupplierOrder,
} from '../services/supplyAdmin'

const reasons: Record<SupplySupplierAcceptanceRejectionReason, string> = { DAMAGED: 'Повреждение', QUALITY_MISMATCH: 'Несоответствие качества', WRONG_PRODUCT: 'Другой товар', WRONG_PACKAGE: 'Другая упаковка', EXPIRED: 'Истёк срок годности', OTHER: 'Другое' }
const results = { FULLY_ACCEPTED: 'Принято полностью', PARTIALLY_ACCEPTED: 'Принято частично', REJECTED: 'Отклонено', OVER_DELIVERED: 'Поставка сверх документа', MIXED: 'Смешанный результат' } as const
const roles: Record<string, string> = { MAIN: 'Основной', PACKAGING: 'Упаковка', HOUSEHOLD: 'Хозяйственный', FIXED_ASSETS: 'Основные средства', OTHER: 'Другой' }
const issueLabels = { SHORTAGE: 'Недопоставка', REJECTED: 'Брак / отклонено', EXCESS: 'Принятый излишек' } as const
const resolutionLabels: Record<SupplyAcceptanceResolutionType, string> = {
  WAIT_FOR_DELIVERY: 'Ожидается довоз', CLOSE_SHORTAGE: 'Недопоставка закрыта', RETURN_TO_PROCUREMENT: 'Возвращено в закупку',
  WAIT_FOR_REPLACEMENT: 'Ожидается замена', CLOSE_REJECTION: 'Отклонение закрыто', ACCEPT_EXCESS: 'Излишек принят', REJECT_EXCESS: 'Излишек исключён',
}
const receiptReasonLabels: Record<string, string> = {
  HISTORICAL_PRICE_MISSING: 'Для прихода в iiko не хватает цены из документа поставщика. Добавьте УПД и свяжите его строки с принятыми товарами.',
  FIXED_AMOUNT_NOT_PHYSICAL: 'Дополнительная услуга не является товарной строкой и не передаётся в приход iiko.',
  SUPPLIER_MAPPING_MISSING: 'Не подтверждено сопоставление поставщика с iiko.',
  SUPPLIER_MAPPING_STALE: 'Сопоставление поставщика с iiko устарело.',
  STORE_MAPPING_MISSING: 'Не подтверждено сопоставление склада приёмки с iiko.',
  PRODUCT_MAPPING_MISSING: 'Не все принятые товары сопоставлены с iiko.',
  UNIT_MAPPING_MISSING: 'Не все единицы измерения сопоставлены с iiko.',
  PRODUCT_MAIN_UNIT_MISSING: 'В iiko не определена основная единица товара.',
  UNIT_NOT_MAIN: 'Единица документа не совпадает с основной единицей товара в iiko.',
  UNRESOLVED_EXCESS: 'Сначала примите решение по излишку.',
  NO_RECEIPT_ELIGIBLE_QUANTITY: 'Нет принятого количества, доступного для прихода.',
}

function destinationLabel(mapping: IikoWarehouseMapping) {
  const code = mapping.source_code ? ` · ${mapping.source_code}` : ''
  return `${mapping.eos_department_name} · ${roles[mapping.role || ''] || mapping.role} · ${mapping.source_name}${code}`
}

export default function SupplierAcceptancesPanel({ order, onOrderRefresh, onReceiptStatusChange }: { order: SupplySupplierOrder; onOrderRefresh: () => void; onReceiptStatusChange?: (status: SupplyIikoIncomingReceipt['status'] | null) => void }) {
  const [items, setItems] = useState<SupplySupplierAcceptance[]>([])
  const [documents, setDocuments] = useState<SupplySupplierDocument[]>([])
  const [destinations, setDestinations] = useState<IikoWarehouseMapping[]>([])
  const [draft, setDraft] = useState<SupplySupplierAcceptance | null>(null)
  const [documentId, setDocumentId] = useState('')
  const [destinationMappingId, setDestinationMappingId] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [manualName, setManualName] = useState('')
  const [manualQuantity, setManualQuantity] = useState('')
  const [manualUnitId, setManualUnitId] = useState(order.lines?.[0]?.package_unit.id ?? '')
  const [needDates, setNeedDates] = useState<Record<string, string>>({})
  const [resolutionComments, setResolutionComments] = useState<Record<string, string>>({})
  const [sourceValues, setSourceValues] = useState<Record<string, string>>({})
  const [receipts, setReceipts] = useState<Record<string, SupplyIikoIncomingReceipt>>({})

  const loadReceipts = useCallback(async (acceptances: SupplySupplierAcceptance[]) => {
    const recorded = acceptances.filter((item) => item.status === 'RECORDED')
    const pairs = await Promise.all(recorded.map(async (item) => {
      try { return [item.id, await getSupplyIikoIncomingReceiptForAcceptance(item.id)] as const }
      catch (error) {
        if (error instanceof SupplyApiError && error.status === 404) return null
        throw error
      }
    }))
    const loaded = pairs.filter((item): item is readonly [string, SupplyIikoIncomingReceipt] => item !== null)
    setReceipts(Object.fromEntries(loaded))
    const statuses = loaded.map(([, receipt]) => receipt.status)
    onReceiptStatusChange?.(statuses.includes('POSTED') ? 'POSTED' : statuses.at(-1) ?? null)
  }, [onReceiptStatusChange])

  async function load() {
    const [acceptances, docs] = await Promise.all([getSupplySupplierAcceptances(order.id), getSupplySupplierDocuments(order.id)])
    const recordedDocs = docs.filter((item) => item.status === 'RECORDED')
    setItems(acceptances); setDraft(acceptances.find((item) => item.status === 'DRAFT') ?? null)
    setDocuments(recordedDocs)
    setDocumentId((current) => current || recordedDocs[0]?.id || '')
    await loadReceipts(acceptances)
  }
  useEffect(() => {
    let active = true
    Promise.all([getSupplySupplierAcceptances(order.id), getSupplySupplierDocuments(order.id), getConfirmedDestinationWarehouseMappings()]).then(async ([acceptances, docs, mappings]) => {
      if (!active) return
      setItems(acceptances); setDraft(acceptances.find((item) => item.status === 'DRAFT') ?? null)
      const recordedDocs = docs.filter((item) => item.status === 'RECORDED')
      setDocuments(recordedDocs)
      setDocumentId(recordedDocs[0]?.id ?? '')
      setDestinations(mappings)
      await loadReceipts(acceptances)
    }).catch(() => { if (active) setMessage('Не удалось загрузить приёмки') })
    return () => { active = false }
  }, [loadReceipts, order.id])
  async function run(action: () => Promise<SupplySupplierAcceptance>, success?: string) {
    setBusy(true); setMessage('')
    try { const value = await action(); setDraft(value.status === 'DRAFT' ? value : null); await load(); onOrderRefresh(); if (success) setMessage(success) }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось изменить приёмку') }
    finally { setBusy(false) }
  }
  async function resolveIssue(resolution: SupplyAcceptanceResolution, resolutionType: SupplyAcceptanceResolutionType) {
    setBusy(true); setMessage('')
    try {
      await resolveSupplyAcceptanceResolution(resolution.id, {
        resolution_type: resolutionType,
        need_date: resolutionType === 'RETURN_TO_PROCUREMENT' ? needDates[resolution.id] || null : null,
        comment: resolutionComments[resolution.id] || null,
      })
      await load(); onOrderRefresh(); setMessage('Решение по расхождению зафиксировано')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось зафиксировать решение')
    } finally { setBusy(false) }
  }
  async function runReceipt(acceptanceId: string, action: () => Promise<SupplyIikoIncomingReceipt>, success: string) {
    setBusy(true); setMessage('')
    try {
      const receipt = await action()
      setReceipts((current) => ({ ...current, [acceptanceId]: receipt }))
      await load(); onOrderRefresh(); setMessage(success)
    } catch (error) {
      setMessage(error instanceof SupplyApiError && error.reasons.length
        ? error.reasons.map((reason) => receiptReasonLabels[reason] ?? reason).join(' ')
        : error instanceof SupplyApiError ? error.message : 'Не удалось изменить приход iiko')
    } finally { setBusy(false) }
  }
  function createSummary(receipt: SupplyIikoIncomingReceipt) {
    const lines = receipt.lines.map((line) => `${line.line_no}. ${line.product_name}: ${line.quantity} ${line.unit_name} × ${line.historical_unit_price} = ${line.allocated_sum} ₽`).join('\n')
    return `Поставщик: ${receipt.supplier_name}\nСклад: ${receipt.destination_name}\nДокумент: ${receipt.eos_document_number}\n\n${lines}\n\nИтого: ${receipt.total_sum} ₽\n\nСоздать документ NEW в iiko?`
  }
  function patchLocal(lineId: string, changes: Partial<SupplySupplierAcceptanceLine>) {
    if (draft) setDraft({ ...draft, lines: draft.lines.map((line) => line.id === lineId ? { ...line, ...changes } : line) })
  }
  async function saveLine(line: SupplySupplierAcceptanceLine, changes: Partial<SupplySupplierAcceptanceLine>) {
    if (!draft) return
    const current = { ...line, ...changes }
    await run(() => updateSupplySupplierAcceptanceLine(draft.id, line.id, {
      received_quantity: current.received_quantity, accepted_quantity: current.accepted_quantity,
      rejected_quantity: current.rejected_quantity, accepted_unit_price: current.accepted_unit_price,
      rejection_reason: current.rejection_reason, comment: current.comment,
    }))
  }
  function difference(line: SupplySupplierAcceptanceLine) {
    if (line.documented_quantity === null) return 'Без документа'
    const delta = Number(line.received_quantity) - Number(line.documented_quantity)
    return delta < 0 ? `Недопоставка ${Math.abs(delta)}` : delta > 0 ? `Сверх ${delta}` : 'Нет'
  }
  function delta(value: string | null) {
    if (value === null) return '—'
    const numeric = Number(value)
    return numeric > 0 ? `+${value}` : value
  }
  function planFact(line: SupplySupplierAcceptanceLine) {
    const unit = line.unit_name_snapshot || ''
    return <div>
      <span>Заказано {line.ordered_quantity ?? '—'} {unit}</span><br />
      <span>Подтверждено {line.confirmed_quantity ?? '—'} {unit} ({delta(line.ordered_vs_confirmed)})</span><br />
      <span>В документе {line.documented_quantity ?? '—'} {unit} ({delta(line.confirmed_vs_documented)})</span><br />
      <span>Приехало {line.received_quantity} {unit} ({delta(line.documented_vs_received)})</span><br />
      <span>Принято {line.accepted_quantity} {unit} ({delta(line.received_vs_accepted)}), отклонено {line.rejected_quantity} {unit}</span>
    </div>
  }
  return <section className="supplier-message-panel supplier-documents-panel">
    <div className="supplier-message-heading"><div><span className="field-label">ТЕКУЩИЙ ЭТАП</span><h2>{(order.acceptance_summary?.recorded_count ?? 0) > 0 ? 'Приход в iiko' : 'Фактическая приёмка товара'}</h2></div><span>Основание — зафиксированный документ поставщика</span></div>
    {message && <p className="request-message">{message}</p>}
    {!draft && <div className="supplier-document-create"><label className="eos-field"><span>Документ-основание</span><EosSelect value={documentId} disabled={busy} onChange={(event) => setDocumentId(event.target.value)}><option value="">Выберите документ</option>{documents.map((doc) => <option key={doc.id} value={doc.id}>{doc.document_type === 'UPD' ? 'УПД' : doc.document_type === 'INVOICE' ? 'Счёт' : 'Накладная'} №{doc.document_number || 'без номера'} от {doc.document_date || 'без даты'}</option>)}</EosSelect></label><label className="eos-field"><span>Склад приёмки</span><EosSelect value={destinationMappingId} disabled={busy} onChange={(event) => setDestinationMappingId(event.target.value)}><option value="">Выберите склад</option>{destinations.map((mapping) => <option key={mapping.id} value={mapping.id}>{destinationLabel(mapping)}</option>)}</EosSelect></label><button type="button" className="primary-action" disabled={busy || !documentId || !destinationMappingId} onClick={() => run(() => createSupplySupplierAcceptance(order.id, { supplier_document_id: documentId, destination_mapping_id: destinationMappingId }))}>Создать приёмку</button></div>}
    {draft && <div className="supplier-document-editor">
      <label className="eos-field"><span>Склад приёмки</span><EosSelect value={draft.destination_mapping_id ?? ''} disabled={busy} onChange={(event) => run(() => updateSupplySupplierAcceptance(draft.id, { destination_mapping_id: event.target.value || null }))}><option value="">Выберите склад</option>{destinations.map((mapping) => <option key={mapping.id} value={mapping.id}>{destinationLabel(mapping)}</option>)}</EosSelect></label>
      <label className="eos-field"><span>Комментарий по факту</span><input value={draft.comment ?? ''} disabled={busy} onChange={(event) => setDraft({ ...draft, comment: event.target.value || null })} onBlur={() => run(() => updateSupplySupplierAcceptance(draft.id, { comment: draft.comment }))} /></label>
      <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Позиция</th><th>Заказано</th><th>Подтверждено</th><th>По документу</th><th>Приехало</th><th>Принято</th><th>Отклонено</th><th>Расхождение</th><th>Причина</th><th></th></tr></thead><tbody>{draft.lines.map((line) => <tr key={line.id}><td><strong>{line.product_name_snapshot}</strong>{line.is_unmatched && <small>Не сопоставлено с документом</small>}</td><td>{line.ordered_quantity ?? '—'} {line.unit_name_snapshot}<small>Δ {delta(line.ordered_vs_confirmed)}</small></td><td>{line.confirmed_quantity ?? '—'} {line.unit_name_snapshot}<small>Δ {delta(line.confirmed_vs_documented)}</small></td><td>{line.documented_quantity ?? '—'} {line.unit_name_snapshot}<small>Δ {delta(line.documented_vs_received)}</small></td><td><input aria-label={`Приехало ${line.product_name_snapshot}`} type="number" min="0.000001" step="0.000001" value={line.received_quantity} disabled={busy} onChange={(e) => patchLocal(line.id, { received_quantity: e.target.value })} /></td><td><input aria-label={`Принято ${line.product_name_snapshot}`} type="number" min="0" step="0.000001" value={line.accepted_quantity} disabled={busy} onChange={(e) => patchLocal(line.id, { accepted_quantity: e.target.value })} /><small>Δ {delta(line.received_vs_accepted)}</small></td><td><input aria-label={`Отклонено ${line.product_name_snapshot}`} type="number" min="0" step="0.000001" value={line.rejected_quantity} disabled={busy} onChange={(e) => patchLocal(line.id, { rejected_quantity: e.target.value })} /></td><td>{difference(line)}</td><td><EosSelect value={line.rejection_reason ?? ''} disabled={busy || Number(line.rejected_quantity) === 0} onChange={(e) => patchLocal(line.id, { rejection_reason: (e.target.value || null) as SupplySupplierAcceptanceRejectionReason | null })}><option value="">Выберите</option>{Object.entries(reasons).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</EosSelect>{line.rejection_reason === 'OTHER' && <input aria-label={`Комментарий причины ${line.product_name_snapshot}`} value={line.comment ?? ''} onChange={(e) => patchLocal(line.id, { comment: e.target.value })} />}</td><td><button type="button" className="secondary-action" disabled={busy} onClick={() => saveLine(line, draft.lines.find((x) => x.id === line.id)!)}>Сохранить строку</button></td></tr>)}</tbody></table></div>
      {draft.lines.filter((line) => line.sources.length > 0).map((line) => {
        const target = Math.min(Number(line.accepted_quantity), line.sources.reduce((sum, source) => sum + Number(source.remaining_quantity), 0))
        const value = (sourceId: string, fallback: string) => sourceValues[`${line.id}:${sourceId}`] ?? fallback
        const distributed = line.sources.reduce((sum, source) => sum + Number(value(source.supplier_order_line_source_id, source.accepted_quantity)), 0)
        const left = Math.max(target - distributed, 0)
        return <div className="purchase-source-group" key={`sources-${line.id}`}><h3>Распределение принятого количества · {line.product_name_snapshot}</h3>{line.sources.map((source) => <label className="eos-field" key={source.supplier_order_line_source_id}><span>{source.source_label}</span><small>План {source.planned_quantity}; уже принято {source.already_accepted_quantity}; осталось {source.remaining_quantity} {line.unit_name_snapshot || ''}</small><input aria-label={`Принято по источнику ${line.product_name_snapshot}`} type="number" min="0" step="0.000001" disabled={busy || line.sources.length === 1} value={value(source.supplier_order_line_source_id, source.accepted_quantity)} onChange={(event) => setSourceValues({ ...sourceValues, [`${line.id}:${source.supplier_order_line_source_id}`]: event.target.value })} /></label>)}<p>Распределено: {distributed} / {target} {line.unit_name_snapshot || ''}. Осталось распределить: {left} {line.unit_name_snapshot || ''}</p><p>Нераспределённый принятый излишек: {Math.max(Number(line.accepted_quantity) - distributed, 0)} {line.unit_name_snapshot || ''}</p>{line.sources.length > 1 && <button type="button" className="secondary-action" disabled={busy || Math.abs(left) > 0.000001 || distributed > target + 0.000001} onClick={() => run(() => updateSupplySupplierAcceptanceLineSources(draft.id, line.id, line.sources.filter((source) => Number(value(source.supplier_order_line_source_id, source.accepted_quantity)) > 0).map((source) => ({ supplier_order_line_source_id: source.supplier_order_line_source_id, accepted_quantity: value(source.supplier_order_line_source_id, source.accepted_quantity) }))))}>Сохранить распределение принятого</button>}</div>
      })}
      <div className="supplier-document-extra"><label className="eos-field"><span>Фактически приехавшая позиция вне документа</span><input value={manualName} disabled={busy} onChange={(e) => setManualName(e.target.value)} /></label><label className="eos-field"><span>Количество</span><input type="number" min="0.000001" step="0.000001" value={manualQuantity} disabled={busy} onChange={(e) => setManualQuantity(e.target.value)} /></label><label className="eos-field"><span>Единица</span><EosSelect value={manualUnitId} disabled={busy} onChange={(e) => setManualUnitId(e.target.value)}>{order.lines?.map((line) => <option key={line.package_unit.id} value={line.package_unit.id}>{line.package_unit.short_name_ru}</option>)}</EosSelect></label><button type="button" className="secondary-action" disabled={busy || !manualName.trim() || !manualQuantity || !manualUnitId} onClick={() => run(() => addSupplySupplierAcceptanceLine(draft.id, { product_name_snapshot: manualName, unit_id: manualUnitId, received_quantity: manualQuantity, accepted_quantity: manualQuantity, rejected_quantity: '0' })).then(() => { setManualName(''); setManualQuantity('') })}>Добавить несопоставленную позицию</button></div>
      <div className="purchase-actions"><button type="button" className="primary-action" disabled={busy || !draft.destination_mapping_id || draft.lines.some((line) => line.supplier_order_line_id && line.traceability_status !== 'TRACEABLE')} onClick={() => window.confirm('Зафиксировать факт приёмки?') && run(() => recordSupplySupplierAcceptance(draft.id), 'Приёмка зафиксирована')}>Зафиксировать приёмку</button><button type="button" className="danger-action" disabled={busy} onClick={() => window.confirm('Отменить черновик приёмки?') && run(() => cancelSupplySupplierAcceptance(draft.id))}>Отменить</button></div>
    </div>}
    {(order.acceptance_summary?.cumulative_lines.length ?? 0) > 0 && <div className="supplier-table-wrap"><h3>Накопительный факт приёмки</h3><table className="supplier-table"><thead><tr><th>Позиция</th><th>Источник</th><th>Приехало всего</th><th>Принято всего</th><th>Отклонено всего</th><th>Остаток</th><th>Для будущего прихода</th></tr></thead><tbody>{order.acceptance_summary?.cumulative_lines.map((line, index) => <tr key={`${line.source_type}-${line.source_line_id || index}`}><td>{line.product_name}</td><td>{line.source_type === 'DOCUMENT' ? 'Накладная' : line.source_type === 'CONFIRMATION' ? 'Подтверждение' : line.source_type === 'ORDER' ? 'Заказ' : 'Вне документа'}</td><td>{line.total_received} {line.unit_name || ''}</td><td>{line.total_accepted} {line.unit_name || ''}</td><td>{line.total_rejected} {line.unit_name || ''}</td><td>{line.remaining_quantity ?? '—'} {line.unit_name || ''}</td><td>{line.receipt_eligible_quantity === null ? 'Требуется решение по излишку' : `${line.receipt_eligible_quantity} ${line.unit_name || ''}`}</td></tr>)}</tbody></table></div>}
    {items.length > 0 && <div className="supplier-table-wrap"><h3>История приёмок</h3><table className="supplier-table"><thead><tr><th>Дата</th><th>Склад приёмки</th><th>Источник</th><th>Статус</th><th>Результат</th><th>План / факт</th><th>Комментарий</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{new Date(item.recorded_at || item.created_at).toLocaleString('ru-RU')}</td><td>{item.destination ? `${item.destination.department_name} · ${roles[item.destination.role] || item.destination.role} · ${item.destination.iiko_store_name}` : 'Не выбран'}</td><td>{item.source === 'DOCUMENT' ? 'Документ' : item.source === 'CONFIRMATION' ? 'Ответ поставщика' : 'Заказ'}</td><td>{item.status === 'RECORDED' ? 'Зафиксирована' : item.status === 'DRAFT' ? 'Черновик' : 'Отменена'}{item.open_issues_count > 0 && <small>Открытых расхождений: {item.open_issues_count}</small>}</td><td>{results[item.result]}</td><td>{item.lines.map((line) => <div key={line.id}><strong>{line.product_name_snapshot}</strong>{planFact(line)}{item.status === 'RECORDED' && <small>Принято к учёту: {line.accounted_quantity} {line.unit_name_snapshot || ''}; сумма {line.accounted_sum} ₽</small>}</div>)}</td><td>{item.comment || '—'}</td></tr>)}</tbody></table></div>}
    {items.filter((item) => item.status === 'RECORDED').map((item) => {
      const receipt = receipts[item.id]
      return <div key={`receipt-${item.id}`} className="supplier-document-editor">
        <h3>Приход в iiko</h3>
        {!receipt ? <><p>Приход ещё не подготовлен. Readiness будет проверен без отправки в iiko.</p><button type="button" className="primary-action" disabled={busy} onClick={() => runReceipt(item.id, () => prepareSupplyIikoIncomingReceipt(item.id), 'Приход подготовлен')}>Подготовить</button></> : <>
          <p><strong>{receipt.eos_document_number}</strong> · {receipt.supplier_name} · {receipt.destination_name}</p>
          <p>Статус: {receipt.status}. Readiness: {receipt.readiness_status}</p>
          <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Позиция</th><th>Количество</th><th>Цена</th><th>Сумма</th><th>Принято к учёту</th></tr></thead><tbody>{receipt.lines.map((line) => <tr key={line.id}><td>{line.product_name}</td><td>{line.quantity} {line.unit_name}</td><td>{line.historical_unit_price} ₽</td><td>{line.allocated_sum} ₽</td><td>{line.accounted_quantity} {line.unit_name} / {line.accounted_sum} ₽</td></tr>)}</tbody></table></div>
          <p>Итого: {receipt.total_sum} ₽</p>
          {(receipt.iiko_document_number || receipt.iiko_document_id) && <p>iiko: {receipt.iiko_document_number || 'без номера'} · UUID {receipt.iiko_document_id || 'ещё не определён'}</p>}
          {receipt.last_error_code && <p className="request-message">{receipt.last_error_code}: {receipt.last_error_message}</p>}
          <div className="purchase-actions">
            {receipt.status === 'DRAFT' && <button type="button" className="primary-action" disabled={busy} onClick={() => runReceipt(item.id, () => transitionSupplyIikoIncomingReceipt(receipt.id, 'ready'), 'Snapshot прихода зафиксирован')}>Зафиксировать</button>}
            {receipt.status === 'READY' && <button type="button" className="primary-action" disabled={busy} onClick={() => window.confirm(createSummary(receipt)) && runReceipt(item.id, () => transitionSupplyIikoIncomingReceipt(receipt.id, 'create'), 'Создание в iiko проверено')}>Создать в iiko</button>}
            {receipt.status === 'CREATED' && <button type="button" className="primary-action" disabled={busy} onClick={() => window.confirm('Провести приход в iiko?') && runReceipt(item.id, () => transitionSupplyIikoIncomingReceipt(receipt.id, 'process'), 'Проведение в iiko проверено')}>Провести</button>}
            {['CREATING', 'PROCESSING', 'FAILED'].includes(receipt.status) && <button type="button" className="secondary-action" disabled={busy} onClick={() => runReceipt(item.id, () => transitionSupplyIikoIncomingReceipt(receipt.id, 'retry'), 'Состояние сверено с iiko')}>Повторить проверку</button>}
            {['DRAFT', 'READY'].includes(receipt.status) && receipt.create_attempt_count === 0 && <button type="button" className="danger-action" disabled={busy} onClick={() => window.confirm('Отменить подготовленный приход?') && runReceipt(item.id, () => transitionSupplyIikoIncomingReceipt(receipt.id, 'cancel'), 'Приход отменён')}>Отменить</button>}
          </div>
        </>}
      </div>
    })}
    {items.filter((item) => item.status === 'RECORDED').map((item) => <div key={`issues-${item.id}`} className="supplier-document-editor">
      <h3>Расхождения при приёмке</h3>
      {item.resolution_state === 'CLEAN' && <p>Расхождений нет</p>}
      {item.resolutions.map((resolution) => <div key={resolution.id} className="supplier-document-extra">
        <div><strong>{resolution.product_name}</strong><p>{issueLabels[resolution.issue_type]}: {resolution.quantity} {resolution.unit_name}</p></div>
        {resolution.status === 'OPEN' ? <>
          {(resolution.issue_type === 'SHORTAGE' || resolution.issue_type === 'REJECTED') && <label className="eos-field"><span>Дата потребности, если её нельзя вывести из заказа</span><input aria-label={`Дата потребности ${resolution.product_name}`} type="date" value={needDates[resolution.id] || ''} disabled={busy} onChange={(event) => setNeedDates({ ...needDates, [resolution.id]: event.target.value })} /></label>}
          <label className="eos-field"><span>Комментарий</span><input value={resolutionComments[resolution.id] || ''} disabled={busy} onChange={(event) => setResolutionComments({ ...resolutionComments, [resolution.id]: event.target.value })} /></label>
          <div className="purchase-actions">
            {resolution.issue_type === 'SHORTAGE' && <><button type="button" disabled={busy} onClick={() => resolveIssue(resolution, 'WAIT_FOR_DELIVERY')}>Ждать довоз</button><button type="button" disabled={busy || !resolution.product_id} onClick={() => resolveIssue(resolution, 'RETURN_TO_PROCUREMENT')}>Вернуть в закупку</button><button type="button" disabled={busy} onClick={() => resolveIssue(resolution, 'CLOSE_SHORTAGE')}>Закрыть недопоставку</button></>}
            {resolution.issue_type === 'REJECTED' && <><button type="button" disabled={busy} onClick={() => resolveIssue(resolution, 'WAIT_FOR_REPLACEMENT')}>Ждать замену</button><button type="button" disabled={busy || !resolution.product_id} onClick={() => resolveIssue(resolution, 'RETURN_TO_PROCUREMENT')}>Вернуть в закупку</button><button type="button" disabled={busy} onClick={() => resolveIssue(resolution, 'CLOSE_REJECTION')}>Закрыть</button></>}
            {resolution.issue_type === 'EXCESS' && <><button type="button" disabled={busy} onClick={() => resolveIssue(resolution, 'ACCEPT_EXCESS')}>Принять излишек</button><button type="button" disabled={busy} onClick={() => resolveIssue(resolution, 'REJECT_EXCESS')}>Отклонить излишек</button></>}
          </div>
        </> : <div><strong>{resolution.resolution_type ? resolutionLabels[resolution.resolution_type] : 'Закрыто'}</strong><p>Допустимо для downstream: {resolution.downstream_accepted_quantity} {resolution.unit_name}</p>{resolution.comment && <p>{resolution.comment}</p>}{resolution.procurement_need && <p>Создана потребность: {resolution.procurement_need.quantity} {resolution.unit_name} до {resolution.procurement_need.need_date || 'дата не указана'}</p>}</div>}
      </div>)}
    </div>)}
  </section>
}
