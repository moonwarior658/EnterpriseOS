import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EosDateField } from '../components/EosFormControls'
import SupplierConfirmationPanel from '../components/SupplierConfirmationPanel'
import { useAuth } from '../contexts/AuthContext'
import {
  cancelSupplySupplierOrder, getSupplySupplierOrder, readySupplySupplierOrder,
  prepareSupplySupplierOrderMessage, retrySupplySupplierOrderSend,
  sendSupplySupplierOrder, updateSupplySupplierOrder,
  type SupplySupplierOrder, type SupplySupplierOrderMessagePreview, SupplyApiError,
} from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'

const labels = { DRAFT: 'Черновик', READY: 'Готов', SENT: 'Отправлен', CANCELLED: 'Отменён' } as const
const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })

export default function SupplySupplierOrderDetailPage() {
  const { orderId = '' } = useParams()
  const { user } = useAuth()
  const [order, setOrder] = useState<SupplySupplierOrder | null>(null)
  const [deliveryDate, setDeliveryDate] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [responsiblePhone, setResponsiblePhone] = useState('')
  const [preview, setPreview] = useState<SupplySupplierOrderMessagePreview | null>(null)
  function refreshOrder() { getSupplySupplierOrder(orderId).then(setOrder).catch(() => undefined) }
  useEffect(() => {
    const controller = new AbortController()
    getSupplySupplierOrder(orderId, controller.signal).then((loaded) => {
      setOrder(loaded); setDeliveryDate(loaded.planned_delivery_date ?? ''); setComment(loaded.comment ?? '')
      setResponsiblePhone(loaded.responsible_phone_snapshot ?? '')
    }).catch(() => { if (!controller.signal.aborted) setMessage('Не удалось загрузить заказ') })
    return () => controller.abort()
  }, [orderId])
  useEffect(() => {
    const status = order?.latest_delivery_attempt?.status
    if (status !== 'PENDING' && status !== 'DISPATCHED') return
    const timer = window.setInterval(() => {
      getSupplySupplierOrder(orderId).then(setOrder).catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [orderId, order?.latest_delivery_attempt?.status])
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
  async function prepareMessage() {
    setBusy(true); setMessage('')
    try {
      const prepared = await prepareSupplySupplierOrderMessage(orderId, responsiblePhone)
      setPreview(prepared); setResponsiblePhone(prepared.responsible.phone)
      setOrder((current) => current ? {
        ...current,
        recipient_email_snapshot: prepared.recipient.email,
        recipient_name_snapshot: prepared.recipient.supplier_display_name,
        responsible_name_snapshot: prepared.responsible.name,
        responsible_phone_snapshot: prepared.responsible.phone,
      } : current)
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось подготовить заказ')
    } finally { setBusy(false) }
  }
  async function copy(value: string, successMessage: string) {
    try { await navigator.clipboard.writeText(value); setMessage(successMessage) }
    catch { setMessage('Не удалось скопировать текст') }
  }
  async function send(retry = false) {
    if (!order) return
    const question = `Кому: ${order.recipient_email_snapshot}\nЗаказ: ${order.number}\nСумма: ${money.format(Number(order.total_amount))}\n\nОтправить?`
    if (!window.confirm(question)) return
    setBusy(true); setMessage('')
    try {
      const attempt = retry
        ? await retrySupplySupplierOrderSend(orderId)
        : await sendSupplySupplierOrder(orderId)
      setOrder((current) => current ? {
        ...current,
        latest_delivery_attempt: attempt,
        delivery_history: [...(current.delivery_history ?? []), attempt],
      } : current)
      setMessage('Заказ поставлен в очередь на отправку')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось поставить заказ в очередь')
    } finally { setBusy(false) }
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
    {order.status === 'READY' && <section className="supplier-message-panel">
      <div className="supplier-message-heading"><div><span className="field-label">ПОДГОТОВКА СООБЩЕНИЯ</span><h2>Заказ поставщику</h2></div><span>Ответственный: {order.responsible_name_snapshot ?? user?.display_name}</span></div>
      <label className="eos-field"><span>Телефон ответственного</span><input value={responsiblePhone} disabled={busy || Boolean(order.responsible_phone_snapshot)} onChange={(event) => setResponsiblePhone(event.target.value)} placeholder="+7 900 000-00-00" /></label>
      {!order.planned_delivery_date && <p className="supplier-message-warning">Дата поставки не указана</p>}
      {order.minimum_order_status === 'BELOW_MINIMUM' && <p className="supplier-message-warning">Внутреннее предупреждение: до минимальной суммы не хватает {money.format(Number(order.minimum_order_shortfall))}. В сообщение поставщику это не включено.</p>}
      <button type="button" className="primary-action" disabled={busy || (!responsiblePhone.trim() && !order.responsible_phone_snapshot)} onClick={prepareMessage}>Подготовить заказ</button>
      {preview && <div className="supplier-message-preview">
        <div><span className="field-label">Кому</span><strong>{preview.recipient.email}</strong><small>{preview.recipient.supplier_display_name}</small></div>
        <div><span className="field-label">Тема</span><strong>{preview.subject}</strong></div>
        <div><span className="field-label">Текст</span><pre>{preview.body_text}</pre></div>
        <div className="supplier-table-wrap"><table className="supplier-table purchase-lines-table"><thead><tr><th>Товар</th><th>Упаковка</th><th>Количество упаковок</th><th>Общее количество</th><th>Цена за упаковку</th><th>Сумма</th></tr></thead><tbody>{preview.lines.map((line, index) => <tr key={`${line.product_name}-${index}`}><td><strong>{line.product_name}</strong></td><td>{line.package_quantity} {line.package_unit}</td><td>{line.packages_count}</td><td>{line.total_quantity} {line.package_unit}</td><td>{money.format(Number(line.price_per_package))}</td><td>{money.format(Number(line.planned_amount))}</td></tr>)}</tbody></table></div>
        <div><span className="field-label">Ответственный</span><strong>{preview.responsible.name}</strong><small>{preview.responsible.phone}</small></div>
        <div className="purchase-actions"><button type="button" className="secondary-action" onClick={() => copy(preview.subject, 'Тема скопирована')}>Скопировать тему</button><button type="button" className="secondary-action" onClick={() => copy(preview.body_text, 'Текст скопирован')}>Скопировать текст</button><button type="button" className="secondary-action" onClick={() => copy(`${preview.subject}\n\n${preview.body_text}`, 'Заказ скопирован')}>Скопировать полный заказ</button></div>
      </div>}
      {order.recipient_email_snapshot && !order.latest_delivery_attempt && <div className="purchase-actions"><button type="button" className="primary-action" disabled={busy} onClick={() => send(false)}>Отправить поставщику</button></div>}
    </section>}
    {order.latest_delivery_attempt && <section className="supplier-message-panel">
      <div className="supplier-message-heading"><div><span className="field-label">ДОСТАВКА</span><h2>{order.latest_delivery_attempt.status === 'PENDING' ? 'Заказ поставлен в очередь на отправку' : order.latest_delivery_attempt.status === 'DISPATCHED' ? 'Заказ отправляется' : order.latest_delivery_attempt.status === 'FAILED' ? 'Не удалось отправить' : 'Заказ отправлен'}</h2></div><span>{order.latest_delivery_attempt.recipient_email}</span></div>
      {order.latest_delivery_attempt.status === 'FAILED' && <><p className="request-message">{order.latest_delivery_attempt.error_message ?? 'Почтовый transport не смог отправить письмо'}</p><button type="button" className="primary-action" disabled={busy} onClick={() => send(true)}>Повторить</button></>}
      {order.latest_delivery_attempt.status === 'SUCCEEDED' && <p>Отправлено: {new Date(order.sent_at ?? order.latest_delivery_attempt.completed_at ?? '').toLocaleString('ru-RU')}</p>}
      {(order.delivery_history?.length ?? 0) > 1 && <div className="supplier-table-wrap"><table className="supplier-table"><thead><tr><th>Попытка</th><th>Получатель</th><th>Статус</th><th>Создана</th><th>Завершена</th></tr></thead><tbody>{order.delivery_history?.map((attempt) => <tr key={attempt.id}><td>№{attempt.attempt_number}</td><td>{attempt.recipient_email}</td><td>{attempt.status}</td><td>{new Date(attempt.created_at).toLocaleString('ru-RU')}</td><td>{attempt.completed_at ? new Date(attempt.completed_at).toLocaleString('ru-RU') : '—'}</td></tr>)}</tbody></table></div>}
    </section>}
    {order.status === 'SENT' && <SupplierConfirmationPanel order={order} onOrderRefresh={refreshOrder} />}
  </div></section>
}
