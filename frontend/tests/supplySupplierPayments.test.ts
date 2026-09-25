import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  cancelSupplySupplierPayment,
  createSupplySupplierPayment,
  getSupplySupplierPayments,
  recordSupplySupplierPayment,
  updateSupplySupplierPayment,
} from '../src/services/supplyAdmin.ts'


test('подключает admin-only реестр и убирает payment UX из карточки заказа', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8')
  const detail = readFileSync(new URL('../src/pages/SupplySupplierOrderDetailPage.tsx', import.meta.url), 'utf8')
  const panel = readFileSync(new URL('../src/components/SupplierPaymentsPanel.tsx', import.meta.url), 'utf8')
  const documents = readFileSync(new URL('../src/components/SupplierDocumentsPanel.tsx', import.meta.url), 'utf8')
  const list = readFileSync(new URL('../src/pages/SupplySupplierPaymentsPage.tsx', import.meta.url), 'utf8')

  assert.match(app, /path="\/supply\/supplier-payments"/)
  assert.match(app, /ProtectedRoute adminOnly/)
  assert.match(layout, /Оплаты поставщикам/)
  assert.doesNotMatch(detail, /SupplierPaymentsPanel/)
  assert.match(documents, /Срок оплаты/)
  assert.match(panel, /Предоплата/)
  assert.match(panel, /Постоплата/)
  assert.match(panel, /Создать черновик/)
  assert.match(panel, /Сохранить черновик/)
  assert.match(panel, /Зафиксировать оплату/)
  assert.match(panel, /Отменить черновик/)
  assert.match(panel, /Оплата не означает поставку/)
  assert.match(panel, /Частично оплачено/)
  assert.match(panel, /Переплата/)
  assert.match(panel, /Просрочено/)
  assert.match(panel, /История оплат по заказу/)
  assert.match(panel, /recorded_by_display_name/)
  assert.match(list, /№ платёжного поручения/)
  assert.match(list, /date_from/)
  assert.match(list, /payment_type/)
})


test('API-клиент покрывает list, create, draft edit, record и cancel', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'token', setItem: () => undefined, removeItem: () => undefined },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getSupplySupplierPayments({
      supplier_id: 'supplier', status: 'RECORDED', payment_type: 'POSTPAYMENT',
      date_from: '2026-09-01', date_to: '2026-09-30', payment_order_number: '123',
    })
    await createSupplySupplierPayment({
      supplier_id: 'supplier', supplier_order_id: 'order', supplier_document_id: 'document',
      payment_type: 'POSTPAYMENT', payment_date: '2026-09-17', amount: '30.000001',
      payment_order_number: '123', payment_order_date: '2026-09-17', comment: 'Часть',
    })
    await updateSupplySupplierPayment('payment', { amount: '70.000001' })
    await recordSupplySupplierPayment('payment')
    await cancelSupplySupplierPayment('payment')
  } finally { globalThis.fetch = originalFetch }

  assert.match(calls[0].url, /supplier_id=supplier/)
  assert.match(calls[0].url, /status=RECORDED/)
  assert.match(calls[0].url, /payment_type=POSTPAYMENT/)
  assert.match(calls[0].url, /date_from=2026-09-01/)
  assert.match(calls[0].url, /date_to=2026-09-30/)
  assert.match(calls[0].url, /payment_order_number=123/)
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(calls[2].options.method, 'PATCH')
  assert.match(calls[3].url, /supplier-payments\/payment\/record$/)
  assert.match(calls[4].url, /supplier-payments\/payment\/cancel$/)
})
