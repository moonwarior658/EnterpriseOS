import { useEffect, useState } from 'react'
import { EosSelect } from './EosFormControls'
import {
  getConfirmedDestinationWarehouseMappings,
  type IikoWarehouseMapping,
} from '../services/iikoMapping'
import {
  addSupplySupplierAcceptanceLine, cancelSupplySupplierAcceptance, createSupplySupplierAcceptance, getSupplySupplierAcceptances,
  getSupplySupplierDocuments, recordSupplySupplierAcceptance, updateSupplySupplierAcceptance,
  resolveSupplyAcceptanceResolution, updateSupplySupplierAcceptanceLine, SupplyApiError,
  type SupplyAcceptanceResolution, type SupplyAcceptanceResolutionType,
  type SupplySupplierAcceptance, type SupplySupplierAcceptanceLine,
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

function destinationLabel(mapping: IikoWarehouseMapping) {
  const code = mapping.source_code ? ` · ${mapping.source_code}` : ''
  return `${mapping.eos_department_name} · ${roles[mapping.role || ''] || mapping.role} · ${mapping.source_name}${code}`
}

export default function SupplierAcceptancesPanel({ order, onOrderRefresh }: { order: SupplySupplierOrder; onOrderRefresh: () => void }) {
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

  async function load() {
    const [acceptances, docs] = await Promise.all([getSupplySupplierAcceptances(order.id), getSupplySupplierDocuments(order.id)])
    setItems(acceptances); setDraft(acceptances.find((item) => item.status === 'DRAFT') ?? null)
    setDocuments(docs.filter((item) => item.status === 'RECORDED'))
  }
  useEffect(() => {
    let active = true
    Promise.all([getSupplySupplierAcceptances(order.id), getSupplySupplierDocuments(order.id), getConfirmedDestinationWarehouseMappings()]).then(([acceptances, docs, mappings]) => {
      if (!active) return
      setItems(acceptances); setDraft(acceptances.find((item) => item.status === 'DRAFT') ?? null)
      setDocuments(docs.filter((item) => item.status === 'RECORDED'))
      setDestinations(mappings)
    }).catch(() => { if (active) setMessage('Не удалось загрузить приёмки') })
    return () => { active = false }
  }, [order.id])
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
  return <section className="supplier-message-panel supplier-documents-panel">
    <div className="supplier-message-heading"><div><span className="field-label">ПРИЁМКА</span><h2>Фактическая приёмка товара</h2></div><span>Заказ, подтверждение, документ и физический факт показаны раздельно</span></div>
    {message && <p className="request-message">{message}</p>}
    {!draft && <div className="supplier-document-create"><label className="eos-field"><span>Документ-основание</span><EosSelect value={documentId} disabled={busy} onChange={(event) => setDocumentId(event.target.value)}><option value="">Без документа: ответ поставщика или заказ</option>{documents.map((doc) => <option key={doc.id} value={doc.id}>{doc.document_number || doc.document_type} от {doc.document_date || 'без даты'}</option>)}</EosSelect></label><label className="eos-field"><span>Склад приёмки</span><EosSelect value={destinationMappingId} disabled={busy} onChange={(event) => setDestinationMappingId(event.target.value)}><option value="">Выберите склад</option>{destinations.map((mapping) => <option key={mapping.id} value={mapping.id}>{destinationLabel(mapping)}</option>)}</EosSelect></label><button type="button" className="primary-action" disabled={busy || !destinationMappingId} onClick={() => run(() => createSupplySupplierAcceptance(order.id, { supplier_document_id: documentId || null, destination_mapping_id: destinationMappingId }))}>Создать приёмку</button></div>}
    {draft && <div className="supplier-document-editor">
      <label className="eos-field"><span>Склад приёмки</span><EosSelect value={draft.destination_mapping_id ?? ''} disabled={busy} onChange={(event) => run(() => updateSupplySupplierAcceptance(draft.id, { destination_mapping_id: event.target.value || null }))}><option value="">Выберите склад</option>{destinations.map((mapping) => <option key={mapping.id} value={mapping.id}>{destinationLabel(mapping)}</option>)}</EosSelect></label>
      <label className="eos-field"><span>Комментарий по факту</span><input value={draft.comment ?? ''} disabled={busy} onChange={(event) => setDraft({ ...draft, comment: event.target.value || null })} onBlur={() => run(() => updateSupplySupplierAcceptance(draft.id, { comment: draft.comment }))} /></label>
      <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Позиция</th><th>Заказано</th><th>Подтверждено</th><th>По документу</th><th>Приехало</th><th>Принято</th><th>Отклонено</th><th>Расхождение</th><th>Причина</th><th></th></tr></thead><tbody>{draft.lines.map((line) => <tr key={line.id}><td><strong>{line.product_name_snapshot}</strong>{line.is_unmatched && <small>Не сопоставлено с документом</small>}</td><td>{line.ordered_quantity ?? '—'} {line.unit_name_snapshot}</td><td>{line.confirmed_quantity ?? '—'} {line.unit_name_snapshot}</td><td>{line.documented_quantity ?? '—'} {line.unit_name_snapshot}</td><td><input aria-label={`Приехало ${line.product_name_snapshot}`} type="number" min="0.000001" step="0.000001" value={line.received_quantity} disabled={busy} onChange={(e) => patchLocal(line.id, { received_quantity: e.target.value })} /></td><td><input aria-label={`Принято ${line.product_name_snapshot}`} type="number" min="0" step="0.000001" value={line.accepted_quantity} disabled={busy} onChange={(e) => patchLocal(line.id, { accepted_quantity: e.target.value })} /></td><td><input aria-label={`Отклонено ${line.product_name_snapshot}`} type="number" min="0" step="0.000001" value={line.rejected_quantity} disabled={busy} onChange={(e) => patchLocal(line.id, { rejected_quantity: e.target.value })} /></td><td>{difference(line)}</td><td><EosSelect value={line.rejection_reason ?? ''} disabled={busy || Number(line.rejected_quantity) === 0} onChange={(e) => patchLocal(line.id, { rejection_reason: (e.target.value || null) as SupplySupplierAcceptanceRejectionReason | null })}><option value="">Выберите</option>{Object.entries(reasons).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</EosSelect>{line.rejection_reason === 'OTHER' && <input aria-label={`Комментарий причины ${line.product_name_snapshot}`} value={line.comment ?? ''} onChange={(e) => patchLocal(line.id, { comment: e.target.value })} />}</td><td><button type="button" className="secondary-action" disabled={busy} onClick={() => saveLine(line, draft.lines.find((x) => x.id === line.id)!)}>Сохранить строку</button></td></tr>)}</tbody></table></div>
      <div className="supplier-document-extra"><label className="eos-field"><span>Фактически приехавшая позиция вне документа</span><input value={manualName} disabled={busy} onChange={(e) => setManualName(e.target.value)} /></label><label className="eos-field"><span>Количество</span><input type="number" min="0.000001" step="0.000001" value={manualQuantity} disabled={busy} onChange={(e) => setManualQuantity(e.target.value)} /></label><label className="eos-field"><span>Единица</span><EosSelect value={manualUnitId} disabled={busy} onChange={(e) => setManualUnitId(e.target.value)}>{order.lines?.map((line) => <option key={line.package_unit.id} value={line.package_unit.id}>{line.package_unit.short_name_ru}</option>)}</EosSelect></label><button type="button" className="secondary-action" disabled={busy || !manualName.trim() || !manualQuantity || !manualUnitId} onClick={() => run(() => addSupplySupplierAcceptanceLine(draft.id, { product_name_snapshot: manualName, unit_id: manualUnitId, received_quantity: manualQuantity, accepted_quantity: manualQuantity, rejected_quantity: '0' })).then(() => { setManualName(''); setManualQuantity('') })}>Добавить несопоставленную позицию</button></div>
      <div className="purchase-actions"><button type="button" className="primary-action" disabled={busy || !draft.destination_mapping_id} onClick={() => window.confirm('Зафиксировать факт приёмки?') && run(() => recordSupplySupplierAcceptance(draft.id), 'Приёмка зафиксирована')}>Зафиксировать приёмку</button><button type="button" className="danger-action" disabled={busy} onClick={() => window.confirm('Отменить черновик приёмки?') && run(() => cancelSupplySupplierAcceptance(draft.id))}>Отменить</button></div>
    </div>}
    {items.length > 0 && <div className="supplier-table-wrap"><h3>История приёмок</h3><table className="supplier-table"><thead><tr><th>Дата</th><th>Склад приёмки</th><th>Источник</th><th>Статус</th><th>Результат</th><th>Принято / отклонено</th><th>Комментарий</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{new Date(item.recorded_at || item.created_at).toLocaleString('ru-RU')}</td><td>{item.destination ? `${item.destination.department_name} · ${roles[item.destination.role] || item.destination.role} · ${item.destination.iiko_store_name}` : 'Не выбран'}</td><td>{item.source === 'DOCUMENT' ? 'Документ' : item.source === 'CONFIRMATION' ? 'Ответ поставщика' : 'Заказ'}</td><td>{item.status === 'RECORDED' ? 'Зафиксирована' : item.status === 'DRAFT' ? 'Черновик' : 'Отменена'}</td><td>{results[item.result]}</td><td>{item.lines.map((line) => `${line.product_name_snapshot}: ${line.accepted_quantity} / ${line.rejected_quantity} ${line.unit_name_snapshot || ''}`).join('; ')}</td><td>{item.comment || '—'}</td></tr>)}</tbody></table></div>}
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
