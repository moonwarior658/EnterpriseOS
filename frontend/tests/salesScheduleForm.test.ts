import assert from 'node:assert/strict'
import test from 'node:test'
import { DEFAULT_SCHEDULE_FORM_VALUES, selectScheduleAutomationType, validateScheduleForm, buildCreateInput, createSubmissionGuard, submitScheduleForm, translateScheduleApiError } from '../src/pages/automationScheduleFormLogic.ts'
import type { AutomationSchedule } from '../src/services/automation.ts'

test('sales selection uses company scope and fifteen minutes without technical source fields', () => {
  const values = selectScheduleAutomationType({ ...DEFAULT_SCHEDULE_FORM_VALUES, name: 'Продажи', scopeType: 'department', scopeId: 'point', isEnabled: true }, 'sales.sync_iiko')
  assert.equal(values.scopeType, 'company')
  assert.equal(values.scopeId, '')
  assert.equal(values.scheduleType, 'interval')
  assert.equal(values.intervalMinutes, '15')
  assert.deepEqual(validateScheduleForm(values), {})
  assert.deepEqual(buildCreateInput(values).payload, {})
  assert(validateScheduleForm({ ...values, intervalMinutes: '10' }).intervalMinutes)
  assert(validateScheduleForm({ ...values, scheduleType: 'daily' }).scheduleType)
  assert(validateScheduleForm({ ...values, scopeType: 'department', scopeId: 'point' }).scopeType)
})
test('UI submission sends empty source payload for server resolution', async () => {
  const values = selectScheduleAutomationType({ ...DEFAULT_SCHEDULE_FORM_VALUES, name: 'Продажи', isEnabled: true }, 'sales.sync_iiko')
  let count = 0
  const result = await submitScheduleForm({ type: 'create' }, values, {
    async create(input) {
      count++; assert.deepEqual(input.payload, {}); assert.deepEqual(input.schedule_config, { type: 'interval', minutes: 15 })
      return { ...input, id: 10, payload: { source_id: 'server-resolved' } } as AutomationSchedule
    },
    async update() { throw Error('unexpected update') },
  }, createSubmissionGuard(), new Set(['sales.sync_iiko']))
  assert.equal(result.status, 'success'); assert.equal(count, 1)
  assert.match(translateScheduleApiError(Error('Источник данных продаж не настроен однозначно. Обратитесь к администратору')), /Источник данных продаж/)
})
