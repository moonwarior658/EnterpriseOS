import assert from 'node:assert/strict'
import test from 'node:test'
import { resetEmployeePassword } from '../src/services/users.ts'

test('password reset omits blank optional reason and trims a supplied reason', async () => {
  const requests: string[] = []
  const oldStorage = globalThis.sessionStorage
  const oldFetch = globalThis.fetch
  globalThis.sessionStorage = { getItem: () => 'token' } as unknown as Storage
  globalThis.fetch = async (_input, init) => {
    requests.push(String(init?.body))
    return new Response(JSON.stringify({ username: 'u', temporary_password: 'p' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await resetEmployeePassword('employee', '  ')
    await resetEmployeePassword('employee', '  Причина  ')
    assert.deepEqual(requests.map((body) => JSON.parse(body)), [
      {},
      { reason: 'Причина' },
    ])
  } finally {
    globalThis.sessionStorage = oldStorage
    globalThis.fetch = oldFetch
  }
})
