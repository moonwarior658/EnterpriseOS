import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { EosSelect } from '../components/EosFormControls'
import { getSupplySupplierOrders, getSupplySuppliers, type SupplySupplier, type SupplySupplierOrder, type SupplySupplierOrderStatus } from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'

const labels = { DRAFT: 'Черновик', READY: 'Готов', CANCELLED: 'Отменён' } as const
const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })

export default function SupplySupplierOrdersPage() {
  const [items, setItems] = useState<SupplySupplierOrder[]>([])
  const [status, setStatus] = useState<SupplySupplierOrderStatus | ''>('')
  const [search, setSearch] = useState('')
  const [supplierId, setSupplierId] = useState('')
  const [suppliers, setSuppliers] = useState<SupplySupplier[]>([])
  const [message, setMessage] = useState('Загружаем заказы…')

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([
      getSupplySupplierOrders({ status, search, supplier_id: supplierId }, controller.signal),
      getSupplySuppliers(true, '', 0, 100, controller.signal),
      getSupplySuppliers(false, '', 0, 100, controller.signal),
    ])
      .then(([page, activeSuppliers, archivedSuppliers]) => {
        setItems(page.items); setSuppliers([...activeSuppliers.items, ...archivedSuppliers.items])
        setMessage(page.items.length ? '' : 'Заказов пока нет')
      })
      .catch(() => { if (!controller.signal.aborted) setMessage('Не удалось загрузить заказы') })
    return () => controller.abort()
  }, [status, search, supplierId])

  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ</p><h1>Заказы поставщикам</h1></div></div>
    <div className="purchase-request-header">
      <label className="eos-field"><span>Поиск по номеру</span><input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <label className="eos-field"><span>Статус</span><EosSelect value={status} onChange={(event) => setStatus(event.target.value as SupplySupplierOrderStatus | '')}><option value="">Все</option><option value="DRAFT">Черновик</option><option value="READY">Готов</option><option value="CANCELLED">Отменён</option></EosSelect></label>
      <label className="eos-field"><span>Поставщик</span><EosSelect value={supplierId} onChange={(event) => setSupplierId(event.target.value)}><option value="">Все</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.display_name}</option>)}</EosSelect></label>
    </div>
    {message ? <p className="page-state">{message}</p> : <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Заказ</th><th>Поставщик</th><th>Закупочный запрос</th><th>Статус</th><th>Поставка</th><th>Позиций</th><th>Итого</th></tr></thead><tbody>{items.map((order) => <tr key={order.id}>
      <td><Link to={`/supply/supplier-orders/${order.id}`}>{order.number}</Link></td><td>{order.supplier_display_name}</td><td><Link to={`/supply/purchase-requests/${order.purchase_request_id}`}>{order.purchase_request_number}</Link></td><td><span className={`purchase-status purchase-status-${order.status.toLowerCase()}`}>{labels[order.status]}</span></td><td>{order.planned_delivery_date ?? '—'}</td><td>{order.line_count}</td><td>{money.format(Number(order.total_amount))}</td>
    </tr>)}</tbody></table></div>}
  </div></section>
}
