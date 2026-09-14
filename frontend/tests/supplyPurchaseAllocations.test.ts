import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  confirmSupplyPurchaseAllocation,
  createSupplyPurchaseAllocation,
  deleteSupplyPurchaseAllocation,
  getSupplyPurchaseAllocations,
  updateSupplyPurchaseAllocation,
} from '../src/services/supplyAdmin.ts'
import { coverageLabel, suggestedPackages } from '../src/pages/supplyPurchaseAllocationLogic.ts'


test('показывает allocation action только для READY и рабочее место без UUID', () => {
  const detail = readFileSync(new URL('../src/pages/SupplyPurchaseRequestDetailPage.tsx', import.meta.url), 'utf8')
  const workspace = readFileSync(new URL('../src/pages/SupplyPurchaseAllocationWorkspace.tsx', import.meta.url), 'utf8')
  assert.match(detail, /request\.status === 'READY'/)
  assert.match(detail, /Распределить по поставщикам/)
  assert.match(workspace, /Основной/)
  assert.match(workspace, /Резервный/)
  assert.match(workspace, /Подтвердить/)
  assert.match(workspace, /current_terms_changed/)
  assert.doesNotMatch(workspace, />UUID</)
})


test('предлагает округление упаковок вверх и различает coverage', () => {
  assert.equal(suggestedPackages('25', '12'), 3)
  assert.equal(suggestedPackages('0', '12'), 1)
  assert.equal(coverageLabel('20', '0'), 'Осталось: 20')
  assert.equal(coverageLabel('0', '12'), 'Превышение: 12')
  assert.equal(coverageLabel('0', '0'), 'Потребность покрыта')
})


test('API-клиент покрывает read, create, update, delete и confirm', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'token', setItem: () => undefined, removeItem: () => undefined },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify({ lines: [], supplier_subtotals: [] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getSupplyPurchaseAllocations('request')
    await createSupplyPurchaseAllocation('request', 'line', 'relation', 3)
    await updateSupplyPurchaseAllocation('request', 'line', 'allocation', 4)
    await deleteSupplyPurchaseAllocation('request', 'line', 'allocation')
    await confirmSupplyPurchaseAllocation('request', 'line', 'allocation')
  } finally { globalThis.fetch = originalFetch }

  assert.match(calls[0].url, /purchase-requests\/request\/allocations$/)
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(calls[2].options.method, 'PATCH')
  assert.equal(calls[3].options.method, 'DELETE')
  assert.match(calls[4].url, /\/confirm$/)
})
