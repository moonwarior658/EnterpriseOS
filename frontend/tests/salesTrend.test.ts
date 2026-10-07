import assert from 'node:assert/strict'
import test from 'node:test'
import { previousDayDelta, trendGeometry, visibleTrendRows } from '../src/pages/salesTrendLogic.ts'
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

test('unfinished periods stop at source today, closed periods keep all days and ticks are real', () => {
  const rows = Array.from({ length: 31 }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, '0')}`, value: i < 7 ? i : null }))
  assert.equal(visibleTrendRows(rows, '2026-10-07').at(-1)?.date, '2026-10-07')
  assert.equal(visibleTrendRows(rows, '2026-11-07').length, 31)
  const narrow = trendGeometry(rows, 560, 240), wide = trendGeometry(rows, 1400, 240)
  assert(narrow.dates.length < wide.dates.length)
  assert(narrow.dates.every(date => rows.some(row => row.date === date)))
  assert.equal(wide.x(rows.at(-1)!.date), 1375)
})

test('seller mix drill-down preserves period/category and strips personal identity selection', () => {
  const p = new URLSearchParams('period=custom&start=2026-09-01&end=2026-09-30&employee_id=seller&department_id=point&staff=all&iiko_product_id=item&category=Cake')
  assert.equal(workspaceQuery(p, 'seller-products'), 'period=custom&start=2026-09-01&end=2026-09-30&view=seller-products&employee_id=seller&department_id=point&staff=all&category=Cake&iiko_product_id=item')
  assert.equal(workspaceQuery(p, 'me-products'), 'period=custom&start=2026-09-01&end=2026-09-30&view=me-products&category=Cake&iiko_product_id=item')
})
