import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { EosDateField, EosSelect } from '../components/EosFormControls'
import { EosDialog } from '../components/EosDialog'
import { formatDateOnly } from '../utils/dateFormat'
import {
  createSupplySupplierPayment, getAvailablePaymentOrders, getSupplySupplierDocuments,
  getSupplySupplierPayments, getSupplySuppliers, recordSupplySupplierPayment,
  uploadSupplySupplierPaymentPhoto, getSupplySupplierPaymentPhotoUrl,
  type AvailablePaymentOrder, type SupplySupplier, type SupplySupplierDocument,
  type SupplySupplierPayment, type SupplySupplierPaymentStatus, type SupplySupplierPaymentType,
} from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const statusLabels = { DRAFT: 'Черновик', RECORDED: 'Зафиксирована', CANCELLED: 'Отменена' } as const
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 10)

export default function SupplySupplierPaymentsPage() {
  const [items, setItems] = useState<SupplySupplierPayment[]>([])
  const [suppliers, setSuppliers] = useState<SupplySupplier[]>([])
  const [supplierId, setSupplierId] = useState('')
  const [status, setStatus] = useState<SupplySupplierPaymentStatus | ''>('')
  const [paymentType, setPaymentType] = useState<SupplySupplierPaymentType | ''>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [paymentOrderNumber, setPaymentOrderNumber] = useState('')
  const [message, setMessage] = useState('Загружаем оплаты…')
  const [formOpen, setFormOpen] = useState(false)
  const [formSupplier, setFormSupplier] = useState('')
  const [formOrder, setFormOrder] = useState('')
  const [formDocument, setFormDocument] = useState('')
  const [formType, setFormType] = useState<SupplySupplierPaymentType>('PREPAYMENT')
  const [formAmount, setFormAmount] = useState('')
  const [formDate, setFormDate] = useState(today)
  const [formNumber, setFormNumber] = useState('')
  const [formComment, setFormComment] = useState('')
  const [formPhoto, setFormPhoto] = useState<File | null>(null)
  const [photoNotice, setPhotoNotice] = useState('')
  const [orders, setOrders] = useState<AvailablePaymentOrder[]>([])
  const [documents, setDocuments] = useState<SupplySupplierDocument[]>([])
  const [recordId, setRecordId] = useState('')
  const [recordReason, setRecordReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      getSupplySupplierPayments({ supplier_id: supplierId, status, payment_type: paymentType, date_from: dateFrom, date_to: dateTo, payment_order_number: paymentOrderNumber }, controller.signal),
      getSupplySuppliers(true, '', 0, 100, controller.signal),
      getSupplySuppliers(false, '', 0, 100, controller.signal),
    ]).then(([page, active, archived]) => {
      setItems(page.items); setSuppliers([...active.items, ...archived.items])
      setMessage(page.items.length ? '' : 'Оплат пока нет')
    }).catch(() => { if (!controller.signal.aborted) setMessage('Не удалось загрузить оплаты') })
    return () => controller.abort()
  }, [supplierId, status, paymentType, dateFrom, dateTo, paymentOrderNumber, revision])

  useEffect(() => {
    if (!formOpen || !formSupplier) return
    let alive = true
    getAvailablePaymentOrders(formSupplier).then((loaded) => { if (alive) setOrders(loaded) })
      .catch(() => { if (alive) setFormError('Не удалось загрузить доступные заказы') })
    return () => { alive = false }
  }, [formOpen, formSupplier])

  useEffect(() => {
    if (!formOpen || !formOrder || formType !== 'POSTPAYMENT') return
    let alive = true
    getSupplySupplierDocuments(formOrder).then((loaded) => { if (alive) setDocuments(loaded.filter((item) => item.status === 'RECORDED' && item.financial_role === 'PAYABLE' && Number(item.remaining_to_pay) > 0)) })
      .catch(() => { if (alive) setFormError('Не удалось загрузить документы заказа') })
    return () => { alive = false }
  }, [formOpen, formOrder, formType])

  function openForm() {
    setFormSupplier(''); setFormOrder(''); setFormDocument(''); setFormType('PREPAYMENT'); setOrders([]); setDocuments([])
    setFormAmount(''); setFormDate(today()); setFormNumber(''); setFormComment(''); setFormPhoto(null); setFormError(''); setFormOpen(true)
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !formSupplier || !formDate || Number(formAmount) <= 0 || (formType === 'POSTPAYMENT' && !formDocument)) return
    const order = orders.find((item) => item.id === formOrder)
    if (order && Number(formAmount) > Number(order.remaining_amount)) { setFormError('Сумма превышает остаток по заказу'); return }
    setBusy(true); setFormError('')
    try {
      const created = await createSupplySupplierPayment({ supplier_id: formSupplier, supplier_order_id: formOrder || null,
        supplier_document_id: formType === 'POSTPAYMENT' ? formDocument : null,
        payment_type: formType, payment_date: formDate, amount: formAmount,
        payment_order_number: formNumber.trim() || null, payment_order_date: formNumber.trim() ? formDate : null,
        comment: formComment.trim() || null })
      setFormOpen(false); setRevision((value) => value + 1)
      if (formPhoto) {
        try { await uploadSupplySupplierPaymentPhoto(created.id, formPhoto); setRevision((value) => value + 1) }
        catch { setPhotoNotice('Оплата создана, но фото не прикрепилось. Добавьте его в строке черновика.') }
      }
    } catch { setFormError('Не удалось создать оплату. Проверьте поставщика, заказ, документ и сумму.') }
    finally { setBusy(false) }
  }

  async function attachPhoto(paymentId: string, file: File | undefined) {
    if (!file || busy) return
    setBusy(true); setPhotoNotice('')
    try { await uploadSupplySupplierPaymentPhoto(paymentId, file); setRevision((value) => value + 1) }
    catch { setPhotoNotice('Не удалось прикрепить фото. Допустимы JPEG, PNG и WebP до 10 МБ.') }
    finally { setBusy(false) }
  }

  async function openPhoto(paymentId: string) {
    try {
      const url = await getSupplySupplierPaymentPhotoUrl(paymentId)
      const link = document.createElement('a')
      link.href = url; link.target = '_blank'; link.rel = 'noopener'; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch { setPhotoNotice('Не удалось открыть фото оплаты.') }
  }

  async function record(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!recordId || !recordReason.trim() || busy) return
    setBusy(true); setFormError('')
    try { await recordSupplySupplierPayment(recordId, recordReason.trim()); setRecordId(''); setRecordReason(''); setRevision((value) => value + 1) }
    catch { setFormError('Не удалось зафиксировать оплату. Проверьте остаток по заказу и реквизиты.') }
    finally { setBusy(false) }
  }

  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ · ФИНАНСЫ</p><h1>Оплаты поставщикам</h1></div><button className="primary-action" type="button" onClick={openForm}>+ Добавить оплату</button></div>
    <div className="purchase-request-header">
      <label className="eos-field"><span>Поставщик</span><EosSelect value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="">Все</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.display_name}</option>)}</EosSelect></label>
      <label className="eos-field"><span>Статус</span><EosSelect value={status} onChange={(event) => setStatus(event.target.value as SupplySupplierPaymentStatus | '')}><option value="">Все</option><option value="DRAFT">Черновик</option><option value="RECORDED">Зафиксирована</option><option value="CANCELLED">Отменена</option></EosSelect></label>
      <label className="eos-field"><span>Тип</span><EosSelect value={paymentType} onChange={(event) => setPaymentType(event.target.value as SupplySupplierPaymentType | '')}><option value="">Все</option><option value="PREPAYMENT">Предоплата</option><option value="POSTPAYMENT">Постоплата</option></EosSelect></label>
      <EosDateField label="С даты" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
      <EosDateField label="По дату" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
      <label className="eos-field"><span>№ платёжного поручения</span><input value={paymentOrderNumber} onChange={(event) => setPaymentOrderNumber(event.target.value)} /></label>
    </div>
    {photoNotice && <p className="request-message request-message-error" role="alert">{photoNotice}</p>}
    {message ? <p className="page-state">{message}</p> : <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Дата</th><th>Поставщик</th><th>Документ / заказ</th><th>Тип</th><th>Сумма</th><th>Платёжное поручение</th><th>Фото</th><th>Статус</th><th>Действие</th></tr></thead><tbody>{items.map((payment) => <tr key={payment.id}><td>{formatDateOnly(payment.payment_date)}</td><td>{payment.supplier_display_name}</td><td>{payment.supplier_document_number ?? (payment.supplier_order_id ? <Link className="supplier-payment-order-link" to={`/supply/supplier-orders/${payment.supplier_order_id}`}>{payment.supplier_order_number}</Link> : 'Аванс поставщику')}</td><td>{payment.payment_type === 'PREPAYMENT' ? 'Предоплата' : 'Постоплата'}</td><td>{money.format(Number(payment.amount))}</td><td>{payment.payment_order_number ? `№${payment.payment_order_number} от ${formatDateOnly(payment.payment_order_date)}` : '—'}</td><td>{payment.photo_original_name ? <button className="secondary-action" type="button" onClick={() => void openPhoto(payment.id)}>Открыть фото</button> : payment.status === 'DRAFT' ? <label className="supplier-payment-photo-picker">Прикрепить фото<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={(event) => { void attachPhoto(payment.id, event.target.files?.[0]); event.target.value = '' }} /></label> : '—'}</td><td>{statusLabels[payment.status]}</td><td>{payment.status === 'DRAFT' && <button className="secondary-action" type="button" onClick={() => { setRecordId(payment.id); setRecordReason(''); setFormError('') }}>Зафиксировать</button>}</td></tr>)}</tbody></table></div>}
  </div>
  {formOpen && <EosDialog title="Добавить оплату" onClose={() => { if (!busy) setFormOpen(false) }}><form className="request-form" onSubmit={(event) => void save(event)}>
    <label className="eos-field"><span>Поставщик</span><EosSelect required value={formSupplier} disabled={busy} onChange={(event) => { setFormSupplier(event.target.value); setFormOrder(''); setFormDocument(''); setOrders([]); setDocuments([]) }}><option value="">Выберите поставщика</option>{suppliers.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</EosSelect></label>
    <label className="eos-field"><span>Заказ (необязательно)</span><EosSelect value={formOrder} disabled={busy || !formSupplier} onChange={(event) => { setFormOrder(event.target.value); setFormDocument(''); setDocuments([]); if (!event.target.value) setFormType('PREPAYMENT') }}><option value="">Аванс без заказа</option>{orders.map((item) => <option key={item.id} value={item.id}>{item.number} · осталось {money.format(Number(item.remaining_amount))}</option>)}</EosSelect></label>
    <label className="eos-field"><span>Тип</span><EosSelect value={formType} disabled={busy} onChange={(event) => { setFormType(event.target.value as SupplySupplierPaymentType); setFormDocument(''); setDocuments([]) }}><option value="PREPAYMENT">Предоплата</option>{formOrder && <option value="POSTPAYMENT">Постоплата</option>}</EosSelect></label>
    {formType === 'POSTPAYMENT' && <label className="eos-field"><span>Документ поставщика</span><EosSelect value={formDocument} disabled={busy} required onChange={(event) => setFormDocument(event.target.value)}><option value="">Выберите документ</option>{documents.map((item) => <option key={item.id} value={item.id}>{item.document_number || 'Документ'} · осталось {money.format(Number(item.remaining_to_pay))}</option>)}</EosSelect></label>}
    <label className="eos-field"><span>Сумма, ₽</span><input type="number" min="0.01" step="0.01" required value={formAmount} disabled={busy} onChange={(event) => setFormAmount(event.target.value)} /></label>
    <EosDateField label="Дата оплаты" required value={formDate} disabled={busy} onChange={(event) => setFormDate(event.target.value)} />
    <label className="eos-field"><span>№ платёжного поручения</span><input value={formNumber} maxLength={128} disabled={busy} onChange={(event) => setFormNumber(event.target.value)} /></label>
    <label className="eos-field"><span>Фото оплаты (необязательно)</span><input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={(event) => setFormPhoto(event.target.files?.[0] ?? null)} /></label>
    <label className="eos-field"><span>Комментарий</span><textarea value={formComment} maxLength={2000} disabled={busy} onChange={(event) => setFormComment(event.target.value)} /></label>
    {formError && <p className="request-message request-message-error">{formError}</p>}
    <div className="user-actions"><button className="primary-action" type="submit" disabled={busy || !formSupplier || Number(formAmount) <= 0 || (formType === 'POSTPAYMENT' && !formDocument)}>{busy ? 'Сохраняем…' : 'Создать черновик'}</button><button className="secondary-action" type="button" disabled={busy} onClick={() => setFormOpen(false)}>Отмена</button></div>
  </form></EosDialog>}
  {recordId && <EosDialog title="Зафиксировать оплату" onClose={() => { if (!busy) setRecordId('') }}><form className="request-form" onSubmit={(event) => void record(event)}><label className="eos-field"><span>Причина фиксации</span><textarea required value={recordReason} maxLength={1000} onChange={(event) => setRecordReason(event.target.value)} /></label>{formError && <p className="request-message request-message-error">{formError}</p>}<div className="user-actions"><button className="primary-action" type="submit" disabled={busy || !recordReason.trim()}>Зафиксировать</button><button className="secondary-action" type="button" disabled={busy} onClick={() => setRecordId('')}>Отмена</button></div></form></EosDialog>}
  </section>
}
