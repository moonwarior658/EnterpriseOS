import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assignableRoles, canBlockHumanUser, canCreateEmployee, canCreateHumanUser,
  canDismissEmployee, canReadAudit, canReadEmployees, canReadServiceUsers,
  canReadUsers,
} from '../src/services/employeePermissions.ts'

test('director sees Employee and Human User information without write controls', () => {
  const roles = ['DIRECTOR'] as const
  assert.equal(canReadEmployees([...roles]), true)
  assert.equal(canReadUsers([...roles]), true)
  assert.equal(canCreateEmployee([...roles]), false)
  assert.equal(canCreateHumanUser([...roles]), false)
  assert.equal(canDismissEmployee([...roles]), false)
  assert.equal(canBlockHumanUser([...roles]), false)
  assert.equal(canReadServiceUsers([...roles]), false)
  assert.equal(canReadAudit([...roles]), false)
  assert.deepEqual(assignableRoles([...roles]), [])
})

test('deputy controls Employee lifecycle and Human blocking without account creation', () => {
  const roles = ['DEPUTY_DIRECTOR'] as const
  assert.equal(canCreateEmployee([...roles]), true)
  assert.equal(canDismissEmployee([...roles]), true)
  assert.equal(canBlockHumanUser([...roles]), true)
  assert.equal(canCreateHumanUser([...roles]), false)
  assert.equal(canReadServiceUsers([...roles]), false)
  assert.equal(canReadAudit([...roles]), false)
  for (const forbidden of ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR']) {
    assert.equal(assignableRoles([...roles]).includes(forbidden as never), false)
  }
})

test('network manager can create Human accounts and assign only operational roles', () => {
  const roles = ['NETWORK_MANAGER'] as const
  assert.equal(canReadEmployees([...roles]), true)
  assert.equal(canReadUsers([...roles]), true)
  assert.equal(canCreateEmployee([...roles]), true)
  assert.equal(canCreateHumanUser([...roles]), true)
  assert.equal(canDismissEmployee([...roles]), false)
  assert.equal(canBlockHumanUser([...roles]), false)
  assert.equal(canReadServiceUsers([...roles]), false)
  assert.deepEqual(new Set(assignableRoles([...roles])), new Set(['SELLER', 'DRIVER', 'HANDYMAN']))
})

test('multi role union grants write and ADMIN is sole technical role', () => {
  const roles = ['DIRECTOR', 'DEPUTY_DIRECTOR'] as const
  assert.equal(canCreateEmployee([...roles]), true)
  assert.equal(canCreateHumanUser([...roles]), false)
  assert.equal(canReadAudit([...roles]), false)
  assert.equal(canReadServiceUsers(['ADMIN']), true)
  assert.equal(canReadAudit(['ADMIN']), true)
})
