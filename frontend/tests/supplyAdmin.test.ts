import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  getSupplyRequests,
  matchSupplyLine,
  saveSupplyAllocations,
} from '../src/services/supplyAdmin.ts'

test('подключает защищённые маршруты реестра и карточки', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(
    new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8',
  )
  assert.match(app, /path="\/supply\/requests"/)
  assert.match(app, /path="\/supply\/requests\/:requestId"/)
  assert.match(app, /ProtectedRoute adminOnly/)
  assert.match(layout, /Заявки снабжения/)
})

test('реестр обновляется раз в 10 секунд и при возврате на вкладку', () => {
  const source = readFileSync(
    new URL('../src/pages/SupplyRequestListPage.tsx', import.meta.url), 'utf8',
  )
  assert.match(source, /10_000/)
  assert.match(source, /visibilitychange/)
  assert.match(source, /inFlight/)
  assert.match(source, /Требует сопоставления/)
})

test('API-клиент передаёт фильтры, expected_version, алиас и allocations', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  const storage = new Map([['eos_access_token', 'token']])
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify([]), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getSupplyRequests(new URLSearchParams({ has_needs_review: 'true' }))
    await matchSupplyLine('request', 'line', {
      expected_version: 4,
      product_id: 'product',
      unit_id: 'unit',
      quantity: '2',
      save_alias: true,
    })
    await saveSupplyAllocations(
      'request', 'line', 5,
      { transfer: '1', purchase: '1', cancel: '0', comment: 'решение' },
      'unit',
    )
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.match(calls[0].url, /has_needs_review=true/)
  assert.equal(JSON.parse(String(calls[1].options.body)).save_alias, true)
  const allocationBody = JSON.parse(String(calls[2].options.body))
  assert.equal(allocationBody.expected_version, 5)
  assert.deepEqual(
    allocationBody.allocations.map((item: { action: string }) => item.action),
    ['TRANSFER', 'PURCHASE'],
  )
})
