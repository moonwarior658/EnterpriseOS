import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  confirmSupplyPurchaseAllocation,
  createSupplyPurchaseAllocation,
  deleteSupplyPurchaseAllocation,
  getSupplyPurchaseAllocations,
  updateSupplyPurchaseAllocation,
  updateSupplyPurchaseAllocationSources,
} from '../src/services/supplyAdmin.ts'
import {
  coverageLabel,
  minimumOrderLabel,
  suggestedPackages,
} from '../src/pages/supplyPurchaseAllocationLogic.ts'


test('показывает allocation action только для READY и рабочее место без UUID', () => {
  const detail = readFileSync(new URL('../src/pages/SupplyPurchaseRequestDetailPage.tsx', import.meta.url), 'utf8')
  const workspace = readFileSync(new URL('../src/pages/SupplyPurchaseAllocationWorkspace.tsx', import.meta.url), 'utf8')
  assert.match(detail, /request\.status === 'READY'/)
  assert.match(detail, /Распределить по поставщикам/)
  assert.match(workspace, /Основной/)
  assert.match(workspace, /Резервный/)
  assert.match(workspace, /Подтвердить/)
  assert.match(workspace, /current_terms_changed/)
  assert.match(workspace, /minimumOrderLabel/)
  assert.match(workspace, /minimum_order_status === 'BELOW_MINIMUM'/)
  assert.match(workspace, /planned_total_amount/)
  assert.match(workspace, /Распределение по источникам/)
  assert.match(workspace, /Осталось распределить/)
  assert.match(workspace, /излишек фасовки/)
  assert.match(workspace, /UNTRACEABLE_LEGACY/)
  assert.doesNotMatch(workspace, />UUID</)
})

test('показывает все minimum order состояния и точный недобор', () => {
  const base = {
    supplier_id: 'supplier',
    supplier_display_name: 'Поставщик',
    planned_total_amount: '8400.00',
    minimum_order_amount: '10000.00',
    minimum_order_status: 'BELOW_MINIMUM' as const,
    minimum_order_shortfall: '1600.00',
    allocation_count: 3,
  }
  const format = (value: string) => `${value} ₽`
  assert.equal(
    minimumOrderLabel(base, format),
    'Минимальный заказ: 10000.00 ₽ · не хватает 1600.00 ₽',
  )
  assert.equal(
    minimumOrderLabel({
      ...base, minimum_order_status: 'MET', minimum_order_shortfall: '0',
    }, format),
    'Минимальный заказ: 10000.00 ₽ · минимум выполнен',
  )
  assert.equal(
    minimumOrderLabel({
      ...base,
      minimum_order_amount: null,
      minimum_order_status: 'NOT_CONFIGURED',
      minimum_order_shortfall: '0',
    }, format),
    'Минимальная сумма не задана',
  )
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
    await updateSupplyPurchaseAllocationSources('request', 'line', 'allocation', [
      { purchase_request_line_source_id: 'source', allocated_quantity: '10' },
    ])
  } finally { globalThis.fetch = originalFetch }

  assert.match(calls[0].url, /purchase-requests\/request\/allocations$/)
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(calls[2].options.method, 'PATCH')
  assert.equal(calls[3].options.method, 'DELETE')
  assert.match(calls[4].url, /\/confirm$/)
  assert.equal(calls[5].options.method, 'PUT')
  assert.match(calls[5].url, /\/sources$/)
})
