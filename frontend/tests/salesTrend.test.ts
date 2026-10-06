import assert from 'node:assert/strict'
import test from 'node:test'
import { previousDayDelta, trendGeometry } from '../src/pages/salesTrendLogic.ts'
import { workspaceQuery } from '../src/pages/salesAnalyticsLogic.ts'

test('chart sorts dates, positions by calendar interval, and breaks missing-day lines', () => {
  const model = trendGeometry([{ date: '2026-09-05', value: 10 }, { date: '2026-09-01', value: 20 }, { date: '2026-09-02', value: null }])
  assert.deepEqual(model.rows.map(r => r.date), ['2026-09-01', '2026-09-02', '2026-09-05'])
  assert.equal(model.x('2026-09-02') - model.x('2026-09-01'), (model.x('2026-09-05') - model.x('2026-09-01')) / 4)
  assert.equal(model.segments.length, 2)
  assert(model.ticks.length >= 3)
  assert(model.y(20) < model.y(10))
})
test('tooltip delta uses only the previous calendar day and preserves zero/negative values', () => {
  const rows = [{ date: '2026-09-01', value: 10 }, { date: '2026-09-02', value: 0 }, { date: '2026-09-03', value: -5 }, { date: '2026-09-05', value: 20 }, { date: '2026-09-06', value: null }, { date: '2026-09-07', value: 20 }]
  assert.deepEqual(rows.map((_, i) => previousDayDelta(rows, i)), [null, -10, -5, null, null, null])
  const model = trendGeometry(rows)
  assert(model.ticks[0] <= -5)
  assert.equal(trendGeometry([]).segments.length, 0)
  assert.equal(trendGeometry([{ date: '2026-09-01', value: 0 }]).x('2026-09-01'), 410)
})
test('one workspace query preserves drill-down and excludes personal identity filters', () => {
  const p = new URLSearchParams('period=custom&start=2026-09-01&end=2026-09-30&employee_id=seller&department_id=point&staff=dismissed&iiko_product_id=item&category=Cake')
  assert.equal(workspaceQuery(p, 'me'), 'period=custom&start=2026-09-01&end=2026-09-30&view=me')
  assert.equal(workspaceQuery(p, 'sellers'), 'period=custom&start=2026-09-01&end=2026-09-30&department_id=point&employee_id=seller&view=sellers&staff=dismissed')
  assert.equal(workspaceQuery(p, 'products'), 'period=custom&start=2026-09-01&end=2026-09-30&department_id=point&iiko_product_id=item&category=Cake&view=products')
})
