import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import type { EmployeeRole } from '../src/services/actionContext.ts'

const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
const menu = readFileSync(new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8')
const allRoles: EmployeeRole[] = [
  'ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER',
  'HEAD_OF_PRODUCTION', 'SUPPLY_MANAGER', 'ACCOUNTANT', 'CHEF_CONFECTIONER',
  'HANDYMAN', 'DRIVER', 'SELLER', 'CONFECTIONER', 'BAKER',
]

function names(source: string): Set<EmployeeRole> {
  return new Set([...source.matchAll(/'([A-Z_]+)'/g)].map((match) => match[1] as EmployeeRole))
}

function menuRoles(variable: string): Set<EmployeeRole> {
  const match = menu.match(new RegExp(`const ${variable} = (\\[[^\\]]+\\])`))
  assert.ok(match, `missing menu role set ${variable}`)
  return names(match[1])
}

function routeRoles(path: string): Set<EmployeeRole> {
  const index = app.indexOf(`path="${path}"`)
  assert.ok(index >= 0, `missing route ${path}`)
  const match = app.slice(index, index + 380).match(/allowedRoles=\{(\[[^\]]+\])\}/)
  assert.ok(match, `missing role guard for ${path}`)
  return names(match[1])
}

test('all 13 roles see only routes admitted by the matching menu group', () => {
  assert.equal(allRoles.length, 13)
  const groups = [
    [menuRoles('repairReaders'), routeRoles('/requests/repair')],
    [menuRoles('repairCreators'), routeRoles('/requests/repair/new')],
    [menuRoles('supplyRequestReaders'), routeRoles('/supply/requests')],
    [menuRoles('supplyFinancialReaders'), routeRoles('/supply/debts')],
    [menuRoles('supplyFinancialReaders'), routeRoles('/supply/suppliers')],
    [menuRoles('supplyFinancialReaders'), routeRoles('/supply/purchase-requests')],
    [menuRoles('supplyFinancialReaders'), routeRoles('/supply/supplier-orders')],
    [menuRoles('supplyFinancialReaders'), routeRoles('/supply/supplier-payments')],
  ]
  for (const role of allRoles) {
    for (const [visible, admitted] of groups) {
      assert.equal(visible.has(role), admitted.has(role), `${role}: menu and route differ`)
    }
  }
  assert.equal(menuRoles('supplyRequestReaders').has('DRIVER'), false)
  assert.equal(menuRoles('supplyFinancialReaders').has('NETWORK_MANAGER'), false)
})

test('read only Supply request view does not fetch restricted iiko or print endpoints', () => {
  const detail = readFileSync(new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url), 'utf8')
  for (const functionName of ['getSupplyIikoDocuments', 'getSupplyPrintJobs']) {
    const call = detail.indexOf(`${functionName}(requestId`, detail.indexOf('getSupplyRequestHistory(requestId'))
    assert.ok(call >= 0, `${functionName} call is missing`)
    const effect = detail.slice(detail.lastIndexOf('useEffect(() => {', call), call)
    assert.match(effect, /if \(readOnly(?: \|\|[\s\S]*?)?\) return/)
  }
})
