import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  addSupplyPurchaseRequestLine,
  cancelSupplyPurchaseRequest,
  collectSupplyPurchaseRequestNeeds,
  createSupplyPurchaseRequest,
  deleteSupplyPurchaseRequestLine,
  getSupplyPurchaseRequest,
  getSupplyPurchaseRequests,
  readySupplyPurchaseRequest,
  updateSupplyPurchaseRequest,
  updateSupplyPurchaseRequestLine,
} from '../src/services/supplyAdmin.ts'


test('подключает admin-only список и редактор закупочных запросов', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8')
  const detail = readFileSync(new URL('../src/pages/SupplyPurchaseRequestDetailPage.tsx', import.meta.url), 'utf8')
  assert.match(app, /path="\/supply\/purchase-requests"/)
  assert.match(app, /path="\/supply\/purchase-requests\/:requestId"/)
  assert.match(layout, /Закупочные запросы/)
  assert.match(detail, /Зафиксировать потребность/)
  assert.match(detail, /Будущая потребность/)
  assert.match(detail, /request\?\.status === 'DRAFT'/)
  assert.doesNotMatch(detail, /SupplySupplier/)
  assert.doesNotMatch(detail, /price_per/)
})


test('API-клиент покрывает CRUD, строки, ready и cancel', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'token', setItem: () => undefined, removeItem: () => undefined },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getSupplyPurchaseRequests()
    await createSupplyPurchaseRequest({ need_date: '2026-09-15' })
    await getSupplyPurchaseRequest('request')
    await updateSupplyPurchaseRequest('request', { comment: 'x' })
    await addSupplyPurchaseRequestLine('request', { product_id: 'product', quantity: '10', unit_id: 'unit' })
    await updateSupplyPurchaseRequestLine('request', 'line', { manual_future_quantity: '12' })
    await deleteSupplyPurchaseRequestLine('request', 'line')
    await collectSupplyPurchaseRequestNeeds('request')
    await readySupplyPurchaseRequest('request')
    await cancelSupplyPurchaseRequest('request')
  } finally { globalThis.fetch = originalFetch }

  assert.equal(calls[0].url, '/api/supply/purchase-requests?limit=100&offset=0')
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(calls[2].url, '/api/supply/purchase-requests/request')
  assert.equal(calls[3].options.method, 'PATCH')
  assert.equal(calls[4].options.method, 'POST')
  assert.equal(calls[5].options.method, 'PATCH')
  assert.equal(calls[6].options.method, 'DELETE')
  assert.match(calls[7].url, /\/collect-needs$/)
  assert.match(calls[8].url, /\/ready$/)
  assert.match(calls[9].url, /\/cancel$/)
})
