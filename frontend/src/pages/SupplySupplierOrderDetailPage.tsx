import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EosDateField } from '../components/EosFormControls'
import {
  cancelSupplySupplierOrder, getSupplySupplierOrder, readySupplySupplierOrder,
  updateSupplySupplierOrder, type SupplySupplierOrder, SupplyApiError,
} from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'

const labels = { DRAFT: 'Черновик', READY: 'Готов', CANCELLED: 'Отменён' } as const
const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })

export default function SupplySupplierOrderDetailPage() {
  const { orderId = '' } = useParams()
  const [order, setOrder] = useState<SupplySupplierOrder | null>(null)
  const [deliveryDate, setDeliveryDate] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    getSupplySupplierOrder(orderId, controller.signal).then((loaded) => {
      setOrder(loaded); setDeliveryDate(loaded.planned_delivery_date ?? ''); setComment(loaded.comment ?? '')
    }).catch(() => { if (!controller.signal.aborted) setMessage('Не удалось загрузить заказ') })
    return () => controller.abort()
  }, [orderId])
  async function save() {
    setBusy(true); setMessage('')
    try { setOrder(await updateSupplySupplierOrder(orderId, { planned_delivery_date: deliveryDate || null, comment: comment || null })); setMessage('Изменения сохранены') }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось сохранить заказ') } finally { setBusy(false) }
  }
  async function transition(action: 'ready' | 'cancel') {
    if (action === 'cancel' && !window.confirm('Отменить заказ поставщику?')) return
    setBusy(true); setMessage('')
    try { setOrder(action === 'ready' ? await readySupplySupplierOrder(orderId) : await cancelSupplySupplierOrder(orderId)) }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось изменить статус заказа') } finally { setBusy(false) }
  }
  if (!order) return <section className="request-page"><div className="request-panel"><p className="page-state">{message || 'Загружаем заказ…'}</p></div></section>
  const draft = order.status === 'DRAFT'
  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ · ЗАКАЗ ПОСТАВЩИКУ</p><h1>Заказ {order.number}</h1></div><Link className="request-back-link" to="/supply/supplier-orders">К списку →</Link></div>
    <div className="purchase-request-header"><div><span className="field-label">Поставщик</span><strong>{order.supplier_display_name}</strong></div><div><span className="field-label">Закупочный запрос</span><Link to={`/supply/purchase-requests/${order.purchase_request_id}`}>{order.purchase_request_number}</Link></div><div><span className="field-label">Статус</span><span className={`purchase-status purchase-status-${order.status.toLowerCase()}`}>{labels[order.status]}</span></div></div>
    <div className="purchase-request-header"><EosDateField label="Плановая дата поставки" value={deliveryDate} disabled={!draft || busy} onChange={(event) => setDeliveryDate(event.target.value)} /><label className="eos-field"><span>Комментарий</span><input value={comment} disabled={!draft || busy} onChange={(event) => setComment(event.target.value)} /></label></div>
    {message && <p className="request-message">{message}</p>}
    {draft && <div className="purchase-actions"><button type="button" className="secondary-action" disabled={busy} onClick={save}>Сохранить</button><button type="button" className="primary-action" disabled={busy} onClick={() => transition('ready')}>Зафиксировать заказ</button><button type="button" className="danger-action" disabled={busy} onClick={() => transition('cancel')}>Отменить</button></div>}
    <div className="supplier-table-wrap"><table className="supplier-table purchase-lines-table"><thead><tr><th>Товар</th><th>Фасовка</th><th>Упаковок</th><th>Количество</th><th>Цена упаковки</th><th>Сумма</th></tr></thead><tbody>{order.lines?.map((line) => <tr key={line.id}><td><strong>{line.product_name}</strong></td><td>{line.package_quantity_snapshot} {line.package_unit.short_name_ru}</td><td>{line.packages_count}</td><td>{line.quantity_base} {line.package_unit.short_name_ru}</td><td>{money.format(Number(line.price_per_package_snapshot))}</td><td>{money.format(Number(line.planned_amount))}</td></tr>)}</tbody></table></div>
    <div className="allocation-summary"><div><span>Итого</span><strong>{money.format(Number(order.total_amount))}</strong><small>{order.minimum_order_status === 'NOT_CONFIGURED' ? 'Минимальная сумма не задана' : order.minimum_order_status === 'MET' ? `Минимум ${money.format(Number(order.minimum_order_amount))} выполнен` : `До минимума не хватает ${money.format(Number(order.minimum_order_shortfall))}`}</small></div></div>
  </div></section>
}
