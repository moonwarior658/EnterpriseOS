import { useEffect, useState } from 'react'
import { EosDateField, EosSelect } from './EosFormControls'
import {
  createSupplySupplierSettlementAdjustment,
  getSupplySupplierSettlement,
  getSupplySupplierSettlementStatement,
  type SupplySupplierOrder,
  type SupplySupplierSettlementStatement,
  type SupplySupplierSettlementSummary,
  SupplyApiError,
} from '../services/supplyAdmin'

const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })
const today = () => new Date().toISOString().slice(0, 10)
const monthStart = () => `${today().slice(0, 8)}01`
const movementLabels: Record<string, string> = {
  PAYABLE_DOCUMENT: 'Документ к оплате', PAYMENT: 'Оплата', SUPPLIER_REFUND: 'Возврат поставщика',
  MANUAL_CORRECTION_INCREASE_DEBT: 'Корректировка: увеличить долг',
  MANUAL_CORRECTION_DECREASE_DEBT: 'Корректировка: уменьшить долг',
  PAYMENT_ALLOCATION: 'Распределение оплаты',
  PAYMENT_ALLOCATION_REVERSAL: 'Отмена распределения',
}

export default function SupplierSettlementPanel({ order }: { order: SupplySupplierOrder }) {
  const [summary, setSummary] = useState<SupplySupplierSettlementSummary | null>(null)
  const [statement, setStatement] = useState<SupplySupplierSettlementStatement | null>(null)
  const [dateFrom, setDateFrom] = useState(monthStart())
  const [dateTo, setDateTo] = useState(today())
  const [direction, setDirection] = useState<'INCREASE_DEBT' | 'DECREASE_DEBT'>('INCREASE_DEBT')
  const [amount, setAmount] = useState('')
  const [comment, setComment] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    const [nextSummary, nextStatement] = await Promise.all([
      getSupplySupplierSettlement(order.supplier_id),
      getSupplySupplierSettlementStatement(order.supplier_id, dateFrom, dateTo),
    ])
    setSummary(nextSummary); setStatement(nextStatement)
  }

  useEffect(() => {
    let active = true
    Promise.all([
      getSupplySupplierSettlement(order.supplier_id),
      getSupplySupplierSettlementStatement(order.supplier_id, dateFrom, dateTo),
    ]).then(([nextSummary, nextStatement]) => { if (active) { setSummary(nextSummary); setStatement(nextStatement) } })
      .catch(() => { if (active) setMessage('Не удалось загрузить взаиморасчёты') })
    return () => { active = false }
  }, [order.supplier_id, dateFrom, dateTo])

  async function correct() {
    if (!amount || !comment.trim()) return
    setBusy(true); setMessage('')
    try {
      await createSupplySupplierSettlementAdjustment({ supplier_id: order.supplier_id, type: 'MANUAL_CORRECTION', direction, amount, effective_date: today(), comment })
      setAmount(''); setComment(''); await load(); setMessage('Корректировка зафиксирована')
    } catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось сохранить корректировку') }
    finally { setBusy(false) }
  }

  return <section className="supplier-message-panel supplier-settlement-panel">
    <div className="supplier-message-heading"><div><span className="field-label">ВЗАИМОРАСЧЁТЫ</span><h2>Баланс с поставщиком</h2></div><span>Положительный баланс — мы должны; отрицательный — переплата</span></div>
    {message && <p className="request-message">{message}</p>}
    {summary && <><div className="allocation-summary"><div><span>Документы</span><strong>{money.format(Number(summary.documented_amount))}</strong></div><div><span>Оплачено</span><strong>{money.format(Number(summary.recorded_payment_amount))}</strong></div><div><span>Баланс</span><strong>{money.format(Number(summary.running_balance))}</strong><small>{Number(summary.running_balance) > 0 ? 'Мы должны' : Number(summary.running_balance) < 0 ? 'Переплата / поставщик должен нам' : 'Закрыто'}</small></div><div><span>Просрочено</span><strong>{money.format(Number(summary.overdue_debt))}</strong></div><div><span>Нераспределённый аванс</span><strong>{money.format(Number(summary.unallocated_prepayment_amount))}</strong></div></div>{(summary.payment_without_supply || summary.supply_without_payment) && <p className="supplier-message-warning">{summary.payment_without_supply ? 'Есть оплата без поставки. ' : ''}{summary.supply_without_payment ? 'Есть поставка без оплаты.' : ''}</p>}</>}
    <div className="supplier-document-editor"><h3>Ручная корректировка</h3><div className="purchase-request-header"><label className="eos-field"><span>Направление</span><EosSelect value={direction} disabled={busy} onChange={(event) => setDirection(event.target.value as typeof direction)}><option value="INCREASE_DEBT">Увеличить долг</option><option value="DECREASE_DEBT">Уменьшить долг</option></EosSelect></label><label className="eos-field"><span>Сумма</span><input type="number" min="0.000001" step="0.000001" value={amount} disabled={busy} onChange={(event) => setAmount(event.target.value)} /></label><label className="eos-field"><span>Причина</span><input value={comment} disabled={busy} onChange={(event) => setComment(event.target.value)} /></label><button type="button" className="primary-action" disabled={busy || !amount || !comment.trim()} onClick={correct}>Зафиксировать</button></div></div>
    <div className="supplier-document-editor"><h3>Внутренняя сверка</h3><div className="purchase-request-header"><EosDateField label="С" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /><EosDateField label="По" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></div>{statement && <><div className="allocation-summary"><div><span>Начальный баланс</span><strong>{money.format(Number(statement.opening_balance))}</strong></div><div><span>Конечный баланс</span><strong>{money.format(Number(statement.closing_balance))}</strong></div></div><div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Дата</th><th>Движение</th><th>Дебет</th><th>Кредит</th><th>Баланс</th></tr></thead><tbody>{statement.movements.map((item) => <tr key={`${item.created_at}-${item.type}-${item.reference}`}><td>{item.date}</td><td>{movementLabels[item.type] ?? item.type}</td><td>{money.format(Number(item.debit))}</td><td>{money.format(Number(item.credit))}</td><td>{money.format(Number(item.running_balance))}</td></tr>)}</tbody></table>{statement.movements.length === 0 && <p>За период движений нет.</p>}</div></>}</div>
  </section>
}
