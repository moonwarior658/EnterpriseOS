import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { getProductionProcurement } from '../src/services/supplyAdmin.ts'

test('production procurement has a scoped read-only route and menu', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/pages/SupplyProductionProcurementPage.tsx', import.meta.url), 'utf8')
  assert.match(app, /path="\/supply\/production-procurement"/)
  assert.match(app, /allowedRoles=\{\['HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER'\]\}/)
  assert.match(layout, /Закупки производства/)
  assert.match(page, /getProductionProcurement\(\)/)
  assert.doesNotMatch(page, /onClick=/)
})

test('production procurement client calls only the scoped projection', async () => {
  const originalFetch = globalThis.fetch
  const calls: string[] = []
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'token', setItem: () => undefined, removeItem: () => undefined },
  })
  globalThis.fetch = async (input) => {
    calls.push(String(input))
    return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try { await getProductionProcurement() }
  finally { globalThis.fetch = originalFetch }
  assert.deepEqual(calls, ['/api/supply/purchase-requests/production'])
})
