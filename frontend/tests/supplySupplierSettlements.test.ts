import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  createSupplySupplierPaymentAllocation,
  createSupplySupplierSettlementAdjustment,
  getSupplySupplierSettlement,
  getSupplySupplierSettlementStatement,
  reverseSupplySupplierPaymentAllocation,
} from '../src/services/supplyAdmin.ts'


test('UI покрывает overview, allocation, reversal, statement, overdue и overpayment', () => {
  const detail = readFileSync(new URL('../src/pages/SupplySupplierOrderDetailPage.tsx', import.meta.url), 'utf8')
  const payments = readFileSync(new URL('../src/components/SupplierPaymentsPanel.tsx', import.meta.url), 'utf8')
  const settlement = readFileSync(new URL('../src/components/SupplierSettlementPanel.tsx', import.meta.url), 'utf8')
  const documents = readFileSync(new URL('../src/components/SupplierDocumentsPanel.tsx', import.meta.url), 'utf8')
  assert.doesNotMatch(detail, /SupplierSettlementPanel/)
  assert.match(payments, /Распределить платёж/)
  assert.match(payments, /отмены распределения/i)
  assert.match(payments, /Возврат/)
  assert.match(payments, /Эффективная сумма/)
  assert.match(payments, /Источники зачёта/)
  assert.match(settlement, /Баланс с поставщиком/)
  assert.match(settlement, /Просрочено/)
  assert.match(settlement, /Переплата/)
  assert.match(settlement, /Внутренняя сверка/)
  assert.match(settlement, /За период движений нет/)
  assert.match(documents, /Финансовая роль/)
  assert.match(documents, /Финансовое обязательство/)
  assert.match(documents, /Создать новое/)
})


test('API client покрывает settlement endpoints', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: { getItem: () => 'token' } })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify({ movements: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    await getSupplySupplierSettlement('supplier')
    await getSupplySupplierSettlementStatement('supplier', '2026-09-01', '2026-09-30')
    await createSupplySupplierPaymentAllocation({ payment_id: 'payment', supplier_document_id: 'document', amount: '10' })
    await reverseSupplySupplierPaymentAllocation('allocation', 'Ошибка', '3')
    await createSupplySupplierSettlementAdjustment({ supplier_id: 'supplier', type: 'MANUAL_CORRECTION', direction: 'INCREASE_DEBT', amount: '5', effective_date: '2026-09-17', comment: 'Причина' })
  } finally { globalThis.fetch = originalFetch }
  assert.match(calls[0].url, /suppliers\/supplier\/settlement$/)
  assert.match(calls[1].url, /settlement\/statement\?date_from=2026-09-01&date_to=2026-09-30/)
  assert.equal(calls[2].options.method, 'POST')
  assert.match(calls[3].url, /allocations\/allocation\/reverse$/)
  assert.equal(calls[3].options.body, JSON.stringify({ reason: 'Ошибка', amount: '3' }))
  assert.equal(calls[4].options.method, 'POST')
})
