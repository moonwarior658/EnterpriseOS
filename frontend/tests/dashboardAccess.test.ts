import assert from 'node:assert/strict'
import test from 'node:test'
import { dashboardAccess } from '../src/pages/dashboardAccess.ts'
import type { EmployeeRole } from '../src/services/actionContext.ts'

const cases: Array<[EmployeeRole, string[]]> = [
  ['ADMIN', ['/requests/repair', '/supply/requests', '/supply/debts', '/supply/supplier-payments']],
  ['DIRECTOR', ['/requests/repair', '/supply/requests', '/supply/debts', '/supply/supplier-payments']],
  ['DEPUTY_DIRECTOR', ['/requests/repair', '/supply/requests', '/supply/debts', '/supply/supplier-payments']],
  ['NETWORK_MANAGER', ['/requests/repair', '/supply/requests']],
  ['HEAD_OF_PRODUCTION', ['/requests/repair', '/supply/requests', '/supply/production-procurement']],
  ['SUPPLY_MANAGER', ['/requests/repair', '/supply/requests', '/supply/debts', '/supply/supplier-payments']],
  ['ACCOUNTANT', ['/supply/requests', '/supply/debts', '/supply/supplier-payments']],
  ['CHEF_CONFECTIONER', ['/requests/repair', '/supply/requests', '/supply/production-procurement']],
  ['HANDYMAN', ['/requests/repair']],
  ['DRIVER', ['/requests/repair']],
  ['SELLER', ['/requests/repair', '/supply/requests']],
  ['CONFECTIONER', []],
  ['BAKER', []],
]

for (const [role, expectedLinks] of cases) {
  test(`${role} home links reflect readable modules`, () => {
    assert.deepEqual(dashboardAccess([role]).links.map((link) => link.to), expectedLinks)
  })
}

test('combined roles add access without relying on role order', () => {
  const expected = dashboardAccess(['ACCOUNTANT', 'SUPPLY_MANAGER'])
  assert.deepEqual(dashboardAccess(['SUPPLY_MANAGER', 'ACCOUNTANT']), expected)
  assert.equal(expected.readOperationalSupply, true)
  assert.equal(expected.readRepairs, true)
})
