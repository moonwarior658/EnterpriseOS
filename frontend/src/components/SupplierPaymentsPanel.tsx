import { useEffect, useState } from 'react'
import { EosDateField, EosSelect } from './EosFormControls'
import {
  cancelSupplySupplierPayment,
  createSupplySupplierPayment,
  createSupplySupplierPaymentAllocation,
  createSupplySupplierSettlementAdjustment,
  getSupplySupplierDocuments,
  getSupplySupplierPayments,
  getSupplySupplierPaymentSettlement,
  reverseSupplySupplierPaymentAllocation,
  recordSupplySupplierPayment,
  updateSupplySupplierPayment,
  type SupplySupplierDocument,
  type SupplySupplierOrder,
  type SupplySupplierPayment,
  type SupplySupplierPaymentType,
  type SupplySupplierPaymentAllocation,
  SupplyApiError,
} from '../services/supplyAdmin'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const paymentStateLabels = {
  UNPAID: 'Не оплачено', PARTIALLY_PAID: 'Частично оплачено',
  PAID: 'Оплачено', OVERPAID: 'Переплата',
} as const

type Props = { order: SupplySupplierOrder; onOrderRefresh: () => void }

export default function SupplierPaymentsPanel({ order, onOrderRefresh }: Props) {
  const [documents, setDocuments] = useState<SupplySupplierDocument[]>([])
  const [payments, setPayments] = useState<SupplySupplierPayment[]>([])
  const [draftId, setDraftId] = useState<string | null>(null)
  const [paymentType, setPaymentType] = useState<SupplySupplierPaymentType>('PREPAYMENT')
  const [documentId, setDocumentId] = useState('')
  const [paymentDate, setPaymentDate] = useState('')
  const [amount, setAmount] = useState('')
  const [orderNumber, setOrderNumber] = useState('')
  const [orderDate, setOrderDate] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [allocationPaymentId, setAllocationPaymentId] = useState('')
  const [allocationDocumentId, setAllocationDocumentId] = useState('')
  const [allocationAmount, setAllocationAmount] = useState('')
  const [paymentSettlements, setPaymentSettlements] = useState<Record<string, { refunded_amount: string; effective_payment_amount: string; allocated_amount: string; available_amount: string; allocations: SupplySupplierPaymentAllocation[] }>>({})

  async function load() {
    const [loadedDocuments, page] = await Promise.all([
      getSupplySupplierDocuments(order.id),
      getSupplySupplierPayments({ supplier_id: order.supplier_id }),
    ])
    setDocuments(loadedDocuments)
    const related = page.items.filter((item) => item.supplier_order_id === order.id)
    setPayments(related)
    const settlements = await Promise.all(related.filter((item) => item.status === 'RECORDED').map(async (item) => [item.id, await getSupplySupplierPaymentSettlement(item.id)] as const))
    setPaymentSettlements(Object.fromEntries(settlements))
  }

  useEffect(() => {
    let active = true
    Promise.all([
      getSupplySupplierDocuments(order.id),
      getSupplySupplierPayments({ supplier_id: order.supplier_id }),
    ]).then(([loadedDocuments, page]) => {
      if (!active) return
      setDocuments(loadedDocuments)
      const related = page.items.filter((item) => item.supplier_order_id === order.id)
      setPayments(related)
      Promise.all(related.filter((item) => item.status === 'RECORDED').map(async (item) => [item.id, await getSupplySupplierPaymentSettlement(item.id)] as const)).then((rows) => { if (active) setPaymentSettlements(Object.fromEntries(rows)) })
      const draft = related.find((item) => item.status === 'DRAFT')
      if (draft) fillDraft(draft)
    }).catch(() => { if (active) setMessage('Не удалось загрузить оплаты') })
    return () => { active = false }
  }, [order.id, order.supplier_id])

  function fillDraft(payment: SupplySupplierPayment) {
    setDraftId(payment.id); setPaymentType(payment.payment_type)
    setDocumentId(payment.supplier_document_id ?? '')
    setPaymentDate(payment.payment_date); setAmount(payment.amount)
    setOrderNumber(payment.payment_order_number ?? '')
    setOrderDate(payment.payment_order_date ?? '')
    setComment(payment.comment ?? '')
  }

  function clearForm() {
    setDraftId(null); setPaymentType('PREPAYMENT'); setDocumentId('')
    setPaymentDate(''); setAmount(''); setOrderNumber(''); setOrderDate(''); setComment('')
  }

  function payload() {
    return {
      supplier_id: order.supplier_id,
      supplier_order_id: order.id,
      supplier_document_id: documentId || null,
      payment_type: paymentType,
      payment_date: paymentDate,
      amount,
      payment_order_number: orderNumber || null,
      payment_order_date: orderDate || null,
      comment: comment || null,
    }
  }

  function draftPayload() {
    const value = payload()
    return {
      supplier_order_id: value.supplier_order_id,
      supplier_document_id: value.supplier_document_id,
      payment_date: value.payment_date,
      amount: value.amount,
      payment_order_number: value.payment_order_number,
      payment_order_date: value.payment_order_date,
      comment: value.comment,
    }
  }

  async function saveDraft() {
    setBusy(true); setMessage('')
    try {
      const value = draftId
        ? await updateSupplySupplierPayment(draftId, draftPayload())
        : await createSupplySupplierPayment(payload())
      fillDraft(value); await load(); setMessage('Черновик оплаты сохранён')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось сохранить оплату')
    } finally { setBusy(false) }
  }

  async function record() {
    if (!draftId || !window.confirm('Зафиксировать реальную оплату? После этого изменить её нельзя.')) return
    setBusy(true); setMessage('')
    try {
      await updateSupplySupplierPayment(draftId, draftPayload())
      await recordSupplySupplierPayment(draftId)
      clearForm(); await load(); onOrderRefresh(); setMessage('Оплата зафиксирована')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось зафиксировать оплату')
    } finally { setBusy(false) }
  }

  async function cancel() {
    if (!draftId || !window.confirm('Отменить черновик оплаты?')) return
    setBusy(true); setMessage('')
    try {
      await cancelSupplySupplierPayment(draftId)
      clearForm(); await load(); setMessage('Черновик оплаты отменён')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось отменить черновик')
    } finally { setBusy(false) }
  }

  async function allocate() {
    if (!allocationPaymentId || !allocationDocumentId || !allocationAmount) return
    setBusy(true); setMessage('')
    try {
      await createSupplySupplierPaymentAllocation({ payment_id: allocationPaymentId, supplier_document_id: allocationDocumentId, amount: allocationAmount })
      setAllocationAmount(''); await load(); onOrderRefresh(); setMessage('Сумма распределена')
    } catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось распределить платёж') } finally { setBusy(false) }
  }

  async function reverse(allocation: SupplySupplierPaymentAllocation) {
    const amount = window.prompt(`Сумма отмены (максимум ${money.format(Number(allocation.amount))})`, allocation.amount)?.trim()
    if (!amount) return
    const reason = window.prompt('Причина отмены распределения')?.trim()
    if (!reason) return
    setBusy(true); setMessage('')
    try { await reverseSupplySupplierPaymentAllocation(allocation.id, reason, amount); await load(); onOrderRefresh(); setMessage('Распределение отменено') }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось отменить распределение') }
    finally { setBusy(false) }
  }

  async function refund(payment: SupplySupplierPayment) {
    const available = paymentSettlements[payment.id]?.available_amount ?? '0'
    const value = window.prompt(`Сумма возврата (доступно ${money.format(Number(available))})`)?.trim()
    if (!value) return
    setBusy(true); setMessage('')
    try {
      await createSupplySupplierSettlementAdjustment({ supplier_id: order.supplier_id, supplier_payment_id: payment.id, type: 'SUPPLIER_REFUND', amount: value, effective_date: new Date().toISOString().slice(0, 10) })
      await load(); onOrderRefresh(); setMessage('Возврат поставщика зафиксирован')
    } catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось зафиксировать возврат') }
    finally { setBusy(false) }
  }

  const recordedDocuments = documents.filter((item) => item.status === 'RECORDED' && item.financial_role === 'PAYABLE')
  const recordedPayments = payments.filter((item) => item.status === 'RECORDED')
  const allocationSources = (documentId: string) => payments.flatMap((payment) =>
    (paymentSettlements[payment.id]?.allocations ?? [])
      .filter((allocation) => allocation.status === 'ACTIVE' && allocation.supplier_document_id === documentId)
      .map((allocation) => ({ payment, allocation })),
  )
  return <section className="supplier-message-panel supplier-payments-panel">
    <div className="supplier-message-heading"><div><span className="field-label">ОПЛАТЫ</span><h2>Оплаты поставщику</h2></div><span>Оплата не означает поставку</span></div>
    <div className="allocation-summary">
      <div><span>Предоплата по заказу</span><strong>{money.format(Number(order.prepayment_summary?.prepayment_total ?? 0))}</strong></div>
      <div><span>Не распределено по документам</span><strong>{money.format(Number(order.prepayment_summary?.unallocated_prepayment_amount ?? 0))}</strong><small>{order.prepayment_summary?.unallocated_prepayment_count ?? 0} оплат</small></div>
    </div>
    {recordedPayments.length > 0 && recordedDocuments.length > 0 && <div className="supplier-document-editor"><h3>Распределить платёж</h3><div className="purchase-request-header"><label className="eos-field"><span>Платёж</span><EosSelect value={allocationPaymentId} disabled={busy} onChange={(event) => setAllocationPaymentId(event.target.value)}><option value="">Выберите платёж</option>{recordedPayments.filter((item) => Number(paymentSettlements[item.id]?.available_amount ?? 0) > 0).map((item) => <option key={item.id} value={item.id}>{item.payment_date} · доступно {money.format(Number(paymentSettlements[item.id]?.available_amount ?? 0))}</option>)}</EosSelect></label><label className="eos-field"><span>Документ</span><EosSelect value={allocationDocumentId} disabled={busy} onChange={(event) => setAllocationDocumentId(event.target.value)}><option value="">Выберите документ</option>{recordedDocuments.map((item) => <option key={item.id} value={item.id}>{item.document_number ?? item.document_type} · осталось {money.format(Number(item.remaining_to_pay))}</option>)}</EosSelect></label><label className="eos-field"><span>Сумма</span><input type="number" min="0.000001" step="0.000001" value={allocationAmount} disabled={busy} onChange={(event) => setAllocationAmount(event.target.value)} /></label><button type="button" className="primary-action" disabled={busy || !allocationPaymentId || !allocationDocumentId || !allocationAmount} onClick={allocate}>Распределить</button></div></div>}
    {message && <p className="request-message">{message}</p>}
    <div className="supplier-document-editor">
      <div className="purchase-request-header">
        <label className="eos-field"><span>Тип</span><EosSelect value={paymentType} disabled={busy || Boolean(draftId)} onChange={(event) => { const value = event.target.value as SupplySupplierPaymentType; setPaymentType(value); if (value === 'PREPAYMENT') setDocumentId('') }}><option value="PREPAYMENT">Предоплата</option><option value="POSTPAYMENT">Постоплата</option></EosSelect></label>
        <label className="eos-field"><span>Документ</span><EosSelect value={documentId} disabled={busy} onChange={(event) => setDocumentId(event.target.value)}><option value="">{paymentType === 'POSTPAYMENT' ? 'Выберите документ' : 'Без документа'}</option>{recordedDocuments.map((document) => <option key={document.id} value={document.id}>{document.document_number ?? document.document_type} · {money.format(Number(document.total_amount))}</option>)}</EosSelect></label>
        <EosDateField label="Дата оплаты" value={paymentDate} disabled={busy} onChange={(event) => setPaymentDate(event.target.value)} />
        <label className="eos-field"><span>Сумма</span><input type="number" min="0.000001" step="0.000001" value={amount} disabled={busy} onChange={(event) => setAmount(event.target.value)} /></label>
        <label className="eos-field"><span>№ платёжного поручения</span><input value={orderNumber} disabled={busy} onChange={(event) => setOrderNumber(event.target.value)} /></label>
        <EosDateField label="Дата платёжного поручения" value={orderDate} disabled={busy} onChange={(event) => setOrderDate(event.target.value)} />
      </div>
      <label className="eos-field"><span>Комментарий</span><input value={comment} disabled={busy} onChange={(event) => setComment(event.target.value)} /></label>
      <div className="purchase-actions"><button type="button" className="secondary-action" disabled={busy || !paymentDate || !amount || (paymentType === 'POSTPAYMENT' && !documentId) || Boolean(orderNumber) !== Boolean(orderDate)} onClick={saveDraft}>{draftId ? 'Сохранить черновик' : 'Создать черновик'}</button>{draftId && <button type="button" className="primary-action" disabled={busy} onClick={record}>Зафиксировать оплату</button>}{draftId && <button type="button" className="danger-action" disabled={busy} onClick={cancel}>Отменить черновик</button>}</div>
    </div>
    {recordedDocuments.map((document) => <div className="supplier-message-preview" key={document.id}>
      <div className="supplier-message-heading"><div><span className="field-label">ДОКУМЕНТ {document.document_number ?? 'БЕЗ НОМЕРА'}</span><h3>{paymentStateLabels[document.payment_state]}</h3></div><span>{document.overdue_state === 'OVERDUE' ? 'Просрочено' : document.payment_due_date ? `Срок ${new Date(`${document.payment_due_date}T00:00:00`).toLocaleDateString('ru-RU')}` : 'Срок не указан'}</span></div>
      <div className="allocation-summary"><div><span>Документ</span><strong>{money.format(Number(document.document_total_amount))}</strong></div><div><span>Оплачено</span><strong>{money.format(Number(document.recorded_payments_amount))}</strong></div><div><span>Осталось</span><strong>{money.format(Number(document.remaining_to_pay))}</strong></div></div>
      {allocationSources(document.id).length > 0 && <div className="supplier-table-wrap"><h4>Источники зачёта</h4><table className="supplier-table"><thead><tr><th>Дата платежа</th><th>Источник</th><th>Зачтено</th><th>Зафиксировал</th></tr></thead><tbody>{allocationSources(document.id).map(({ payment, allocation }) => <tr key={allocation.id}><td>{new Date(`${payment.payment_date}T00:00:00`).toLocaleDateString('ru-RU')}</td><td>{payment.payment_order_number ? `Платёж №${payment.payment_order_number}` : payment.payment_type === 'PREPAYMENT' ? 'Предоплата' : 'Постоплата'}</td><td>{money.format(Number(allocation.amount))}</td><td>{payment.recorded_by_display_name ?? '—'}</td></tr>)}</tbody></table></div>}
    </div>)}
      {payments.length > 0 && <div className="supplier-table-wrap"><h3>История оплат по заказу</h3><table className="supplier-table"><thead><tr><th>Дата</th><th>Документ</th><th>Тип</th><th>Сумма</th><th>Возвращено</th><th>Эффективная сумма</th><th>Распределено</th><th>Доступно</th><th>Действия</th></tr></thead><tbody>{payments.map((payment) => { const settlement = paymentSettlements[payment.id]; return <tr key={payment.id}><td>{payment.payment_date}</td><td>{payment.supplier_document_number ?? 'Аванс без документа'}</td><td>{payment.payment_type === 'PREPAYMENT' ? 'Предоплата' : 'Постоплата'}</td><td>{money.format(Number(payment.amount))}</td><td>{money.format(Number(settlement?.refunded_amount ?? 0))}</td><td>{money.format(Number(settlement?.effective_payment_amount ?? payment.amount))}</td><td>{money.format(Number(settlement?.allocated_amount ?? 0))}</td><td>{money.format(Number(settlement?.available_amount ?? 0))}</td><td>{payment.status === 'RECORDED' && Number(settlement?.available_amount ?? 0) > 0 && <button type="button" className="secondary-action" disabled={busy} onClick={() => refund(payment)}>Возврат</button>}{settlement?.allocations.filter((item) => item.status === 'ACTIVE').map((item) => <button key={item.id} type="button" className="danger-action" disabled={busy} onClick={() => reverse(item)}>Отменить {money.format(Number(item.amount))}</button>)}</td></tr> })}</tbody></table></div>}
  </section>
}
