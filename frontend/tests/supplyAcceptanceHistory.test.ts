import assert from 'node:assert/strict'
import test from 'node:test'
import { hasAcceptanceDiscrepancy, summarizeAcceptanceQuantity } from '../src/components/supplierAcceptanceHistory.ts'

const line = (ordered: string | null, accepted: string, unit = 'кг', rejected = '0', shortage = '0', excess = '0') => ({
  unit_name_snapshot: unit,
  ordered_quantity: ordered,
  accepted_quantity: accepted,
  rejected_quantity: rejected,
  shortage_quantity: shortage,
  excess_quantity: excess,
})

test('история суммирует только заказанное и принятое без потери единиц', () => {
  const lines = [line('100.000000', '90.500000'), line('11.000000', '10.500000')]
  assert.equal(summarizeAcceptanceQuantity(lines, 'ordered_quantity'), '111 кг')
  assert.equal(summarizeAcceptanceQuantity(lines, 'accepted_quantity'), '101 кг')
  assert.equal(summarizeAcceptanceQuantity([line('2', '2', 'шт.'), line('1.5', '1.5', 'кг')], 'accepted_quantity'), '2 шт. · 1,5 кг')
})

test('история различает чистую приёмку, недостачу, излишек и отклонение', () => {
  assert.equal(hasAcceptanceDiscrepancy([line('111', '111')], 'FULLY_ACCEPTED'), false)
  assert.equal(hasAcceptanceDiscrepancy([line('111', '100', 'кг', '0', '11')], 'PARTIALLY_ACCEPTED'), true)
  assert.equal(hasAcceptanceDiscrepancy([line('111', '120', 'кг', '0', '0', '9')], 'OVER_DELIVERED'), true)
  assert.equal(hasAcceptanceDiscrepancy([line('111', '100', 'кг', '11')], 'MIXED'), true)
})
