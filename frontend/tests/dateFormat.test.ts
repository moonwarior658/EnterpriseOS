import assert from 'node:assert/strict'
import test from 'node:test'

import { formatDateOnly } from '../src/utils/dateFormat.ts'

test('Employee calendar dates use DD-MM-YYYY without timezone conversion', () => {
  assert.equal(formatDateOnly('2000-04-13'), '13-04-2000')
  assert.equal(formatDateOnly('2026-10-02T23:30:00-03:00'), '02-10-2026')
  assert.equal(formatDateOnly(null), '—')
  assert.equal(formatDateOnly(null, 'по настоящее время'), 'по настоящее время')
})
