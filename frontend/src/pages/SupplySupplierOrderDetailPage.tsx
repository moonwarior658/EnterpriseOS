import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EosDateField } from '../components/EosFormControls'
import SupplierConfirmationPanel from '../components/SupplierConfirmationPanel'
import SupplierDocumentsPanel from '../components/SupplierDocumentsPanel'
import SupplierAcceptancesPanel from '../components/SupplierAcceptancesPanel'
import { useAuth } from '../contexts/AuthContext'
import {
  cancelSupplySupplierOrder, getSupplySupplierOrder, readySupplySupplierOrder,
  prepareSupplySupplierOrderMessage, retrySupplySupplierOrderSend,
  sendSupplySupplierOrder, updateSupplySupplierOrder,
  type SupplyIikoIncomingReceiptStatus,
  type SupplySupplierOrder, type SupplySupplierOrderMessagePreview, SupplyApiError,
} from '../services/supplyAdmin'
import './SupplyPurchaseRequestsPage.css'
import { formatMoney, formatQuantity } from '../utils/format'

const labels = { DRAFT: 'Черновик', READY: 'Готов', SENT: 'Отправлен', CANCELLED: 'Отменён' } as const
const dateTime = (value?: string | null) => value ? new Date(value).toLocaleString('ru-RU') : '—'

export default function SupplySupplierOrderDetailPage() {
  const { orderId = '' } = useParams()
  const { user } = useAuth()
  const [order, setOrder] = useState<SupplySupplierOrder | null>(null)
  const [deliveryDate, setDeliveryDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [responsiblePhone, setResponsiblePhone] = useState('')
  const [preview, setPreview] = useState<SupplySupplierOrderMessagePreview | null>(null)
  const [receiptStatus, setReceiptStatus] = useState<SupplyIikoIncomingReceiptStatus | null>(null)

  const refreshOrder = useCallback(() => {
    getSupplySupplierOrder(orderId).then(setOrder).catch(() => undefined)
  }, [orderId])
  useEffect(() => {
    const controller = new AbortController()
    getSupplySupplierOrder(orderId, controller.signal).then((loaded) => {
      setOrder(loaded); setDeliveryDate(loaded.planned_delivery_date ?? '')
      setResponsiblePhone(loaded.responsible_phone_snapshot ?? '')
    }).catch(() => { if (!controller.signal.aborted) setMessage('Не удалось загрузить заказ') })
    return () => controller.abort()
  }, [orderId])
  useEffect(() => {
    const status = order?.latest_delivery_attempt?.status
    if (status !== 'PENDING' && status !== 'DISPATCHED') return
    const timer = window.setInterval(refreshOrder, 2000)
    return () => window.clearInterval(timer)
  }, [order?.latest_delivery_attempt?.status, refreshOrder])

  async function saveAndReady() {
    setBusy(true); setMessage('')
    try {
      await updateSupplySupplierOrder(orderId, { planned_delivery_date: deliveryDate || null })
      setOrder(await readySupplySupplierOrder(orderId))
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось зафиксировать заказ')
    } finally { setBusy(false) }
  }
  async function cancel() {
    if (!window.confirm('Отменить заказ поставщику?')) return
    setBusy(true); setMessage('')
    try { setOrder(await cancelSupplySupplierOrder(orderId)) }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось отменить заказ') }
    finally { setBusy(false) }
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
    if (!window.confirm(`Кому: ${order.recipient_email_snapshot}\nЗаказ: ${order.number}\nСумма: ${formatMoney(order.total_amount)}\n\nОтправить?`)) return
    setBusy(true); setMessage('')
    try {
      const attempt = retry ? await retrySupplySupplierOrderSend(orderId) : await sendSupplySupplierOrder(orderId)
      setOrder((current) => current ? { ...current, latest_delivery_attempt: attempt, delivery_history: [...(current.delivery_history ?? []), attempt] } : current)
      setMessage('Заказ поставлен в очередь на отправку')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось поставить заказ в очередь')
    } finally { setBusy(false) }
  }

  if (!order) return <section className="request-page"><div className="request-panel"><p className="page-state">{message || 'Загружаем заказ…'}</p></div></section>

  const draft = order.status === 'DRAFT'
  const sent = order.status === 'SENT'
  const confirmationDone = Boolean(order.latest_confirmation)
  const decisionsOpen = order.supplier_confirmation_review_state === 'REQUIRES_DECISION'
  const documentsDone = (order.supplier_documents_summary?.recorded_documents_count ?? 0) > 0
  const acceptancesDone = (order.acceptance_summary?.recorded_count ?? 0) > 0
  const completed = receiptStatus === 'POSTED'
  const currentStage = draft ? 'Зафиксируйте заказ'
    : order.status === 'READY' ? 'Отправьте заказ поставщику'
      : order.status === 'CANCELLED' ? 'Заказ отменён'
        : !confirmationDone ? 'Зафиксируйте ответ поставщика'
          : decisionsOpen ? 'Примите решения по изменениям'
            : !documentsDone ? 'Добавьте УПД или счёт'
              : !acceptancesDone ? 'Оформите фактическую приёмку'
                : completed ? 'Заказ завершён' : 'Проведите приход в iiko'

  const history = [
    { title: 'Заказ создан', value: dateTime(order.created_at) },
    order.confirmed_at ? { title: 'Заказ зафиксирован', value: dateTime(order.confirmed_at) } : null,
    order.sent_at ? { title: 'Отправлен поставщику', value: dateTime(order.sent_at) } : null,
    order.latest_confirmation?.recorded_at ? { title: 'Ответ поставщика зафиксирован', value: dateTime(order.latest_confirmation.recorded_at) } : null,
    confirmationDone && !decisionsOpen && (order.latest_confirmation?.deviation_count ?? 0) > 0 ? { title: 'Решения по изменениям приняты', value: `${order.latest_confirmation?.deviation_count} отклонений` } : null,
    documentsDone && order.supplier_documents_summary?.latest_document ? { title: `${order.supplier_documents_summary.latest_document.document_type === 'UPD' ? 'УПД' : 'Документ'} добавлен`, value: dateTime(order.supplier_documents_summary.latest_document.recorded_at) } : null,
    acceptancesDone ? { title: 'Приёмка оформлена', value: dateTime(order.acceptance_summary?.latest_acceptance?.recorded_at) } : null,
    completed ? { title: 'Приход проведён в iiko', value: 'Проведён' } : null,
  ].filter((item): item is { title: string; value: string } => item !== null)

  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ · ЗАКАЗ ПОСТАВЩИКУ</p><h1>Заказ {order.number}</h1></div><Link className="request-back-link" to="/supply/supplier-orders">К списку →</Link></div>
    <div className="purchase-request-header supplier-order-header"><div><span className="field-label">Поставщик</span><strong>{order.supplier_display_name}</strong></div><div><span className="field-label">Закупочный запрос</span><Link to={`/supply/purchase-requests/${order.purchase_request_id}`}>{order.purchase_request_number}</Link></div><div><span className="field-label">Статус</span><span className={`purchase-status purchase-status-${order.status.toLowerCase()}`}>{labels[order.status]}</span></div></div>
    <div className="supplier-current-step" aria-live="polite"><span>Текущий этап</span><strong>{currentStage}</strong></div>
    {draft ? <EosDateField className="supplier-delivery-date" label="Плановая дата поставки" value={deliveryDate} disabled={busy} onChange={(event) => setDeliveryDate(event.target.value)} /> : <div className="supplier-order-fact"><span className="field-label">Плановая дата поставки</span><strong>{order.planned_delivery_date ? new Date(`${order.planned_delivery_date}T00:00:00`).toLocaleDateString('ru-RU') : 'Не указана'}</strong></div>}
    {message && <p className="request-message">{message}</p>}
    <div className="supplier-table-wrap supplier-order-table-wrap"><table className="supplier-table supplier-order-lines"><thead><tr><th>Товар</th><th>Количество</th><th>Цена</th><th>Сумма</th></tr></thead><tbody>{order.lines?.map((line) => <tr key={line.id}><td><strong>{line.product_name}</strong><small>{formatQuantity(line.package_quantity_snapshot)} {line.package_unit.short_name_ru} × {formatQuantity(line.packages_count)} уп.</small></td><td>{formatQuantity(line.quantity_base)} {line.package_unit.short_name_ru}</td><td>{formatMoney(line.price_per_package_snapshot)} / уп.</td><td>{formatMoney(line.planned_amount)}</td></tr>)}</tbody></table></div>
    <div className="supplier-order-total"><span>Итого</span><strong>{formatMoney(order.total_amount)}</strong><small>{order.minimum_order_status === 'BELOW_MINIMUM' ? `До минимальной суммы не хватает ${formatMoney(order.minimum_order_shortfall)}` : order.minimum_order_status === 'MET' ? 'Минимальная сумма выполнена' : 'Минимальная сумма не задана'}</small></div>
    {draft && <div className="purchase-actions"><button type="button" className="primary-action" disabled={busy} onClick={saveAndReady}>Зафиксировать заказ</button><button type="button" className="secondary-action" disabled={busy} onClick={cancel}>Отменить</button></div>}

    {order.status === 'READY' && <section className="supplier-message-panel">
      <div className="supplier-message-heading"><div><span className="field-label">ТЕКУЩИЙ ЭТАП</span><h2>Подготовить и отправить заказ</h2></div><span>Ответственный: {order.responsible_name_snapshot ?? user?.display_name}</span></div>
      <label className="eos-field"><span>Телефон ответственного</span><input value={responsiblePhone} disabled={busy || Boolean(order.responsible_phone_snapshot)} onChange={(event) => setResponsiblePhone(event.target.value)} placeholder="+7 900 000-00-00" /></label>
      {!order.planned_delivery_date && <p className="supplier-message-warning">Дата поставки не указана</p>}
      <div className="supplier-stage-actions"><button type="button" className="primary-action" disabled={busy || (!responsiblePhone.trim() && !order.responsible_phone_snapshot)} onClick={prepareMessage}>Подготовить заказ</button></div>
      {preview && <div className="supplier-message-preview"><div><span className="field-label">Кому</span><strong>{preview.recipient.email}</strong></div><div><span className="field-label">Тема</span><strong>{preview.subject}</strong></div><div><span className="field-label">Текст</span><pre>{preview.body_text}</pre></div><div className="supplier-table-wrap supplier-order-table-wrap"><table className="supplier-table supplier-order-lines"><thead><tr><th>Товар</th><th>Количество</th><th>Цена</th><th>Сумма</th></tr></thead><tbody>{preview.lines.map((line, index) => <tr key={`${line.product_name}-${index}`}><td><strong>{line.product_name}</strong><small>{formatQuantity(line.package_quantity)} {line.package_unit} × {formatQuantity(line.packages_count)} уп.</small></td><td>{formatQuantity(line.total_quantity)} {line.package_unit}</td><td>{formatMoney(line.price_per_package)} / уп.</td><td>{formatMoney(line.planned_amount)}</td></tr>)}</tbody></table></div><div className="purchase-actions"><button type="button" className="secondary-action" onClick={() => copy(preview.subject, 'Тема скопирована')}>Скопировать тему</button><button type="button" className="secondary-action" onClick={() => copy(preview.body_text, 'Текст скопирован')}>Скопировать текст</button><button type="button" className="secondary-action" onClick={() => copy(`${preview.subject}\n\n${preview.body_text}`, 'Заказ скопирован')}>Скопировать полный заказ</button></div></div>}
      {order.recipient_email_snapshot && !order.latest_delivery_attempt && <div className="supplier-stage-actions"><button type="button" className="primary-action" disabled={busy} onClick={() => send(false)}>Отправить поставщику</button></div>}
      {order.latest_delivery_attempt?.status === 'FAILED' && <><p className="request-message">{order.latest_delivery_attempt.error_message ?? 'Не удалось отправить заказ'}</p><button type="button" className="primary-action" disabled={busy} onClick={() => send(true)}>Повторить отправку</button></>}
      {['PENDING', 'DISPATCHED'].includes(order.latest_delivery_attempt?.status ?? '') && <p>Заказ отправляется…</p>}
    </section>}

    {sent && (!confirmationDone || decisionsOpen) && <SupplierConfirmationPanel order={order} onOrderRefresh={refreshOrder} />}
    {sent && confirmationDone && !decisionsOpen && !documentsDone && <SupplierDocumentsPanel order={order} onOrderRefresh={refreshOrder} />}
    {sent && confirmationDone && !decisionsOpen && documentsDone && <SupplierAcceptancesPanel order={order} onOrderRefresh={refreshOrder} onReceiptStatusChange={setReceiptStatus} />}

    {history.length > 1 && <section className="supplier-order-history"><h2>История заказа</h2>{history.map((item, index) => <details key={`${item.title}-${index}`}><summary><span aria-hidden="true">✓</span><strong>{item.title}</strong><time>{item.value}</time></summary><p>Этап завершён. Зафиксированное значение: {item.value}.</p></details>)}</section>}
  </div></section>
}
