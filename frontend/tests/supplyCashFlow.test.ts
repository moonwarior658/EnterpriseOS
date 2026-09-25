import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  getSupplyPurchaseRequestCashFlow,
  getSupplySupplierCashFlow,
} from '../src/services/supplyAdmin.ts'


test('денежный поток показывает funnel, недоступную стоимость и финансовые исключения без savings', () => {
  const component = readFileSync(new URL('../src/components/ProcurementCashFlowSummary.tsx', import.meta.url), 'utf8')
  const supplierPanel = readFileSync(new URL('../src/components/SupplierSettlementPanel.tsx', import.meta.url), 'utf8')
  const requestPage = readFileSync(new URL('../src/pages/SupplyPurchaseRequestDetailPage.tsx', import.meta.url), 'utf8')
  for (const label of ['Расчётно', 'Заказано', 'Подтверждено', 'По документам', 'Принято товара', 'Оплачено', 'Долг', 'Просрочено', 'Авансы', 'Возвраты', 'Финансовые исключения']) {
    assert.match(component, new RegExp(label))
  }
  assert.match(component, /Нет надёжных данных/)
  assert.match(component, /Поставка ожидает оплаты/)
  assert.match(component, /Просроченная оплата/)
  assert.match(component, /Переплата поставщику/)
  assert.match(component, /Нераспределённый аванс/)
  assert.match(component, /Требуется решение руководства/)
  assert.match(component, /не «экономия»/)
  assert.doesNotMatch(component, /savings/)
  assert.match(supplierPanel, /getSupplySupplierCashFlow/)
  assert.doesNotMatch(requestPage, /getSupplyPurchaseRequestCashFlow/)
  assert.doesNotMatch(requestPage, /ProcurementCashFlowSummary/)
})


test('API-клиент передаёт supplier date range и отдельный PR scope', async () => {
  const calls: string[] = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'token', setItem: () => undefined, removeItem: () => undefined },
  })
  globalThis.fetch = async (input) => {
    calls.push(String(input))
    return new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    await getSupplySupplierCashFlow('supplier', '2026-09-01', '2026-09-30')
    await getSupplyPurchaseRequestCashFlow('request')
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.equal(calls[0], '/api/supply/suppliers/supplier/cash-flow?date_from=2026-09-01&date_to=2026-09-30')
  assert.equal(calls[1], '/api/supply/purchase-requests/request/cash-flow')
})
