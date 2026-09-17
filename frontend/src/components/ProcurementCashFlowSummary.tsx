import type { SupplyProcurementCashFlowSummary } from '../services/supplyAdmin'


const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const amount = (value: string | null, unavailable = false) => unavailable || value === null
  ? 'Нет надёжных данных'
  : money.format(Number(value))
const exceptionLabels: Record<string, string> = {
  PAYMENT_WITHOUT_SUPPLY: 'Оплата без подтверждённой поставки',
  SUPPLY_WITHOUT_PAYMENT: 'Поставка ожидает оплаты',
  OVERDUE_PAYMENT: 'Просроченная оплата',
  OVERPAYMENT: 'Переплата поставщику',
  UNALLOCATED_PREPAYMENT: 'Нераспределённый аванс',
  MANUAL_CORRECTION_PRESENT: 'Есть ручная корректировка',
  AMBIGUOUS_FINANCIAL_LINK: 'Неоднозначная финансовая связь',
  OPEN_PRICE_DEVIATION: 'Открытое отклонение цены',
}


export default function ProcurementCashFlowSummary({ value }: { value: SupplyProcurementCashFlowSummary }) {
  const period = value.date_from || value.date_to
    ? `Период: ${value.date_from ?? 'начало истории'} — ${value.date_to ?? 'сегодня'}`
    : 'За весь доступный период'
  const cards = [
    ['Расчётно', amount(value.planned_amount, value.planned_amount_status === 'UNAVAILABLE')],
    ['Заказано', amount(value.ordered_amount)],
    ['Подтверждено', amount(value.confirmed_amount)],
    ['По документам', amount(value.payable_documented_amount)],
    ['Принято товара', amount(value.accepted_goods_amount, value.accepted_goods_amount_status === 'UNAVAILABLE')],
    ['Оплачено', amount(value.gross_paid_amount)],
    ['Долг', amount(value.current_debt_amount)],
    ['Просрочено', amount(value.overdue_debt_amount)],
  ]
  return <section className="supplier-message-panel supplier-cash-flow-panel">
    <div className="supplier-message-heading"><div><span className="field-label">ЗАКУПОЧНЫЙ КОНТУР</span><h2>Денежный поток</h2><small>{period}</small></div><span>Этапы отражают разные факты и не образуют одну бухгалтерскую формулу</span></div>
    <div className="allocation-summary">{cards.map(([label, display]) => <div key={label}><span>{label}</span><strong>{display}</strong></div>)}</div>
    <div className="allocation-summary">
      <div><span>Авансы</span><strong>{amount(value.unallocated_prepayment_amount)}</strong></div>
      <div><span>Возвраты</span><strong>{amount(value.supplier_refund_amount)}</strong></div>
      <div><span>Оплачено нетто</span><strong>{amount(value.net_paid_amount)}</strong></div>
      <div><span>Кредит поставщика</span><strong>{amount(value.supplier_credit_amount)}</strong></div>
      <div><span>Финансовые исключения</span><strong>{value.financial_exception_count}</strong><small>{value.requires_decision ? 'Требуется решение руководства' : 'Информационно'}</small></div>
    </div>
    <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Разница этапов</th><th>Сумма</th></tr></thead><tbody>
      <tr><td>Заказ → подтверждение</td><td>{amount(value.ordered_vs_confirmed_amount)}</td></tr>
      <tr><td>Подтверждение → документы</td><td>{amount(value.confirmed_vs_documented_amount)}</td></tr>
      <tr><td>Документы → принято товара</td><td>{amount(value.documented_vs_accepted_goods_amount, value.accepted_goods_amount_status === 'UNAVAILABLE')}</td></tr>
    </tbody></table></div>
    <p className="page-state">Разница — не «экономия»: незакупленная или непринятая потребность остаётся видимой.</p>
    {value.financial_exceptions.length > 0 && <div className="supplier-message-warning" role="status"><strong>Требуют внимания:</strong> {value.financial_exceptions.map((item) => exceptionLabels[item.code] ?? item.code).join(' · ')}</div>}
  </section>
}
