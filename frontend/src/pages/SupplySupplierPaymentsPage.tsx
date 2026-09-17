import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { EosDateField, EosSelect } from '../components/EosFormControls'
import {
  getSupplySupplierPayments,
  getSupplySuppliers,
  type SupplySupplier,
  type SupplySupplierPayment,
  type SupplySupplierPaymentStatus,
  type SupplySupplierPaymentType,
} from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const statusLabels = { DRAFT: 'Черновик', RECORDED: 'Зафиксирована', CANCELLED: 'Отменена' } as const

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
  }, [supplierId, status, paymentType, dateFrom, dateTo, paymentOrderNumber])

  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ · ФИНАНСЫ</p><h1>Оплаты поставщикам</h1></div></div>
    <div className="purchase-request-header">
      <label className="eos-field"><span>Поставщик</span><EosSelect value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="">Все</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.display_name}</option>)}</EosSelect></label>
      <label className="eos-field"><span>Статус</span><EosSelect value={status} onChange={(event) => setStatus(event.target.value as SupplySupplierPaymentStatus | '')}><option value="">Все</option><option value="DRAFT">Черновик</option><option value="RECORDED">Зафиксирована</option><option value="CANCELLED">Отменена</option></EosSelect></label>
      <label className="eos-field"><span>Тип</span><EosSelect value={paymentType} onChange={(event) => setPaymentType(event.target.value as SupplySupplierPaymentType | '')}><option value="">Все</option><option value="PREPAYMENT">Предоплата</option><option value="POSTPAYMENT">Постоплата</option></EosSelect></label>
      <EosDateField label="С даты" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
      <EosDateField label="По дату" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
      <label className="eos-field"><span>№ платёжного поручения</span><input value={paymentOrderNumber} onChange={(event) => setPaymentOrderNumber(event.target.value)} /></label>
    </div>
    {message ? <p className="page-state">{message}</p> : <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Дата</th><th>Поставщик</th><th>Документ / заказ</th><th>Тип</th><th>Сумма</th><th>Платёжное поручение</th><th>Статус</th></tr></thead><tbody>{items.map((payment) => <tr key={payment.id}><td>{payment.payment_date}</td><td>{payment.supplier_display_name}</td><td>{payment.supplier_document_number ?? (payment.supplier_order_id ? <Link to={`/supply/supplier-orders/${payment.supplier_order_id}`}>{payment.supplier_order_number}</Link> : 'Без документа и заказа')}</td><td>{payment.payment_type === 'PREPAYMENT' ? 'Предоплата' : 'Постоплата'}</td><td>{money.format(Number(payment.amount))}</td><td>{payment.payment_order_number ? `№${payment.payment_order_number} от ${payment.payment_order_date}` : '—'}</td><td>{statusLabels[payment.status]}</td></tr>)}</tbody></table></div>}
  </div></section>
}
