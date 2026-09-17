import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  cancelSupplySupplierOrder, createSupplySupplierOrders, getSupplySupplierOrder,
  getSupplySupplierOrders, prepareSupplySupplierOrderMessage,
  readySupplySupplierOrder, retrySupplySupplierOrderSend,
  sendSupplySupplierOrder, updateSupplySupplierOrder,
  cancelSupplySupplierConfirmation, createSupplySupplierConfirmation,
  decideSupplySupplierConfirmationDeviation,
  getSupplySupplierConfirmations, recordSupplySupplierConfirmation,
  updateSupplySupplierConfirmation, updateSupplySupplierConfirmationLine,
} from '../src/services/supplyAdmin.ts'


test('подключает admin-only список, карточку и формирование из allocation workspace', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8')
  const workspace = readFileSync(new URL('../src/pages/SupplyPurchaseAllocationWorkspace.tsx', import.meta.url), 'utf8')
  const list = readFileSync(new URL('../src/pages/SupplySupplierOrdersPage.tsx', import.meta.url), 'utf8')
  const detail = readFileSync(new URL('../src/pages/SupplySupplierOrderDetailPage.tsx', import.meta.url), 'utf8')
  const confirmation = readFileSync(new URL('../src/components/SupplierConfirmationPanel.tsx', import.meta.url), 'utf8')
  assert.match(app, /path="\/supply\/supplier-orders"/)
  assert.match(app, /path="\/supply\/supplier-orders\/:orderId"/)
  assert.match(layout, /Заказы поставщикам/)
  assert.match(workspace, /Сформировать заказы/)
  assert.match(workspace, /allocation\.status === 'CONFIRMED'/)
  assert.match(list, /Поиск по номеру/)
  assert.match(detail, /Плановая дата поставки/)
  assert.match(detail, /Зафиксировать заказ/)
  assert.match(detail, /minimum_order_status/)
  assert.match(detail, /order\.status === 'READY'/)
  assert.match(detail, /Подготовить заказ/)
  assert.match(detail, /preview\.recipient\.email/)
  assert.match(detail, /Дата поставки не указана/)
  assert.match(detail, /Скопировать полный заказ/)
  assert.match(detail, /Отправить поставщику/)
  assert.match(detail, /window\.confirm\(question\)/)
  assert.match(detail, /setInterval/)
  assert.match(detail, /Заказ поставлен в очередь на отправку/)
  assert.match(detail, /Не удалось отправить/)
  assert.match(detail, /Повторить/)
  assert.match(detail, /Заказ отправлен/)
  assert.doesNotMatch(detail, />UUID</)
  assert.match(detail, /order\.status === 'SENT'/)
  assert.match(confirmation, /Зафиксировать ответ поставщика/)
  assert.match(confirmation, /Подтверждённая дата поставки/)
  assert.match(confirmation, /CONFIRMED/)
  assert.match(confirmation, /CHANGED/)
  assert.match(confirmation, /REJECTED/)
  assert.match(confirmation, /История ответов/)
  assert.match(confirmation, /Отменить черновик/)
  assert.match(confirmation, /ordered_packages_count !== line\.confirmed_packages_count/)
  assert.match(confirmation, /ОТКЛОНЕНИЯ · РЕВИЗИЯ/)
  assert.match(confirmation, /Требует решения/)
  assert.match(confirmation, /Информационно/)
  assert.match(confirmation, /decideSupplySupplierConfirmationDeviation/)
  assert.match(confirmation, />Принять</)
  assert.match(confirmation, />Отклонить</)
  assert.match(detail, /open_required_deviations_count/)
})


test('API-клиент покрывает create, list, detail, draft edit, ready и cancel', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'token', setItem: () => undefined, removeItem: () => undefined },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify({ orders: [], items: [], total: 0, limit: 50, offset: 0 }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await createSupplySupplierOrders('request')
    await getSupplySupplierOrders({ status: 'DRAFT', supplier_id: 'supplier', search: 'PO-1' })
    await getSupplySupplierOrder('order')
    await updateSupplySupplierOrder('order', { planned_delivery_date: '2026-09-16', comment: 'После 14:00' })
    await readySupplySupplierOrder('order')
    await cancelSupplySupplierOrder('order')
    await prepareSupplySupplierOrderMessage('order', '+7 900 000-00-00')
    await sendSupplySupplierOrder('order')
    await retrySupplySupplierOrderSend('order')
    await createSupplySupplierConfirmation('order')
    await getSupplySupplierConfirmations('order')
    await updateSupplySupplierConfirmation('confirmation', { supplier_reference: 'SUP-42' })
    await updateSupplySupplierConfirmationLine('confirmation', 'line', { response_status: 'REJECTED' })
    await recordSupplySupplierConfirmation('confirmation')
    await cancelSupplySupplierConfirmation('confirmation')
    await decideSupplySupplierConfirmationDeviation('deviation', 'ACCEPT', 'Согласовано')
  } finally { globalThis.fetch = originalFetch }
  assert.match(calls[0].url, /purchase-requests\/request\/supplier-orders$/)
  assert.equal(calls[0].options.method, 'POST')
  assert.match(calls[1].url, /status=DRAFT/)
  assert.match(calls[1].url, /supplier_id=supplier/)
  assert.match(calls[1].url, /search=PO-1/)
  assert.equal(calls[2].url, '/api/supply/supplier-orders/order')
  assert.equal(calls[3].options.method, 'PATCH')
  assert.match(calls[4].url, /\/ready$/)
  assert.match(calls[5].url, /\/cancel$/)
  assert.match(calls[6].url, /\/prepare-message$/)
  assert.equal(calls[6].options.method, 'POST')
  assert.equal(calls[6].options.body, JSON.stringify({ responsible_phone: '+7 900 000-00-00' }))
  assert.match(calls[7].url, /\/send$/)
  assert.match(calls[8].url, /\/retry-send$/)
  assert.equal(calls[7].options.method, 'POST')
  assert.equal(calls[8].options.method, 'POST')
  assert.match(calls[9].url, /supplier-orders\/order\/confirmations$/)
  assert.equal(calls[9].options.method, 'POST')
  assert.match(calls[10].url, /supplier-orders\/order\/confirmations$/)
  assert.match(calls[11].url, /supplier-confirmations\/confirmation$/)
  assert.equal(calls[11].options.method, 'PATCH')
  assert.match(calls[12].url, /supplier-confirmations\/confirmation\/lines\/line$/)
  assert.match(calls[13].url, /supplier-confirmations\/confirmation\/record$/)
  assert.match(calls[14].url, /supplier-confirmations\/confirmation\/cancel$/)
  assert.match(calls[15].url, /supplier-confirmation-deviations\/deviation\/decision$/)
  assert.equal(calls[15].options.method, 'POST')
  assert.equal(calls[15].options.body, JSON.stringify({ decision: 'ACCEPT', comment: 'Согласовано' }))
})
