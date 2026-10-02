import assert from 'node:assert/strict'
import test from 'node:test'
import { buildAttentionItems, upcomingExternalVisits } from '../src/pages/dashboardOverviewLogic.ts'
import type { WorkRequest } from '../src/services/requests.ts'
import type { SupplyDashboardSummary } from '../src/services/supplyAdmin.ts'

test('attention rows come from visible business counts only', () => {
  const summary = { new_requests: 1, mapping_required: 2, critical_debts: 3 } as SupplyDashboardSummary
  const items = buildAttentionItems(2, summary, { readRepairs: true, readOperationalSupply: false, readFinance: true })
  assert.deepEqual(items.map((item) => [item.label, item.count, item.to]), [
    ['Ремонты без стоимости или документов', 2, '/requests/repair'],
    ['Критические долги', 3, '/supply/debts?status=ACTIVE&severity=RED'],
  ])
  assert.deepEqual(buildAttentionItems(0, null, { readRepairs: true, readOperationalSupply: true, readFinance: true }), [])
})

test('assigned events show only three upcoming external visits in time order', () => {
  const visit = (id: number, date: string, status: WorkRequest['status'] = 'waiting_external') => ({ id, request_type: 'repair', status, visit_at: date }) as WorkRequest
  const requests = [
    visit(5, '2026-10-03T16:00:00Z'), visit(2, '2026-10-03T12:00:00Z'),
    visit(1, '2026-10-02T12:00:00Z'), visit(4, '2026-10-03T14:00:00Z'),
    visit(3, '2026-10-03T13:00:00Z'), visit(6, '2026-10-03T11:00:00Z', 'completed'),
  ]
  assert.deepEqual(upcomingExternalVisits(requests, Date.parse('2026-10-03T00:00:00Z')).map((item) => item.id), [2, 3, 4])
})
