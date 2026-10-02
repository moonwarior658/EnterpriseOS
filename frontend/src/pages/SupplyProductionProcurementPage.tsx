import { useEffect, useState } from 'react'
import { getProductionProcurement, type ProductionProcurementCard } from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const statusLabels = { DRAFT: 'Черновик', READY: 'Зафиксирован', CANCELLED: 'Отменён' } as const

export default function SupplyProductionProcurementPage() {
  const [cards, setCards] = useState<ProductionProcurementCard[]>([])
  const [message, setMessage] = useState('Загружаем закупки производства…')

  useEffect(() => {
    getProductionProcurement().then((items) => {
      setCards(items)
      setMessage(items.length ? '' : 'Закупок по заявкам производства пока нет')
    }).catch(() => setMessage('Не удалось загрузить закупки производства'))
  }, [])

  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ · ПРОИЗВОДСТВО</p><h1>Закупки по заявкам производства</h1></div></div>
    {message && <p className="page-state">{message}</p>}
    {cards.map((card) => <section key={card.id} className="supplier-message-panel">
      <div className="supplier-message-heading"><div><span className="field-label">ЗАКУПОЧНЫЙ ЗАПРОС {card.number}</span><h2>{statusLabels[card.status]}</h2></div><span>Потребность к {card.need_date}</span></div>
      <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Товар</th><th>Количество производства</th><th>Цена</th><th>Сумма</th></tr></thead><tbody>
        {card.lines.map((line, index) => <tr key={`${card.id}-${index}`}><td>{line.product_name}</td><td>{line.quantity} {line.unit_name}</td><td>{line.allocations.length ? line.allocations.map((item) => money.format(Number(item.unit_price))).join(', ') : '—'}</td><td>{line.allocations.length ? money.format(line.allocations.reduce((sum, item) => sum + Number(item.amount), 0)) : '—'}</td></tr>)}
      </tbody></table></div>
    </section>)}
  </div></section>
}
