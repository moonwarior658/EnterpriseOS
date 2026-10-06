import assert from 'node:assert/strict'
import test from 'node:test'
import { analyticsQuery, statisticsViews, metricNumber } from '../src/pages/salesAnalyticsLogic.ts'

test('statistics role matrix uses canonical roles and fails closed', () => {
  for (const role of ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER']) assert.deepEqual(statisticsViews([role]), ['overview', 'points', 'sellers', 'products'])
  for (const role of ['CHEF_CONFECTIONER', 'HEAD_OF_PRODUCTION']) assert.deepEqual(statisticsViews([role]), ['products'])
  assert.deepEqual(statisticsViews(['SELLER']), ['me'])
  for (const role of ['ACCOUNTANT', 'SUPPLY_MANAGER', 'DRIVER', 'HANDYMAN', 'BAKER', 'CONFECTIONER', 'CHEF', 'EKLER_MANAGER']) assert.deepEqual(statisticsViews([role]), [])
  assert.deepEqual(statisticsViews([]), [])
  assert.deepEqual(statisticsViews(['SELLER', 'NETWORK_MANAGER']), ['overview', 'points', 'sellers', 'products', 'me'])
})
test('seller queries cannot contain employee, point, staff or product identity', () => {
  const p = new URLSearchParams('period=week&anchor=2026-10-06&employee_id=other&department_id=point&staff=all&iiko_product_id=product&tenant_id=other&start=2026-09-01')
  assert.equal(analyticsQuery(p, 'me'), 'period=week&anchor=2026-10-06')
})
test('custom period and drill-down filters are scoped to each endpoint', () => {
  const p = new URLSearchParams('period=custom&start=2026-10-01&end=2026-10-06&anchor=2026-10-01&employee_id=seller&department_id=point&staff=dismissed&iiko_product_id=product&category=Cake')
  assert.equal(analyticsQuery(p, 'overview'), 'period=custom&start=2026-10-01&end=2026-10-06&department_id=point&employee_id=seller')
  assert.equal(analyticsQuery(p, 'sellers'), 'period=custom&start=2026-10-01&end=2026-10-06&department_id=point&employee_id=seller&staff=dismissed')
  assert.equal(analyticsQuery(p, 'products'), 'period=custom&start=2026-10-01&end=2026-10-06&department_id=point&iiko_product_id=product&category=Cake')
  assert.equal(analyticsQuery(p, 'points'), 'period=custom&start=2026-10-01&end=2026-10-06')
})
test('zero and unavailable facts remain visually distinct', () => {
  assert.equal(metricNumber(null), '—')
  assert.equal(metricNumber('0'), '0')
  assert.match(metricNumber('-1.5'), /-1,5/)
})
