import assert from 'node:assert/strict'
import test from 'node:test'
import type { AutomationExecution } from '../src/services/automation.ts'
import {
  createManualRunGuard,
  runScheduleNow,
  updateLatestExecution,
} from '../src/pages/automationScheduleRunLogic.ts'

const EXECUTION: AutomationExecution = {
  id: 101,
  execution_id: '41644d7a-8875-4f35-a493-371b330fb154',
  schedule_id: 42,
  automation_type: 'daily_report',
  scope_type: 'company',
  scope_id: null,
  recipients: [],
  status: 'pending',
  provider: null,
  requested_at: '2026-07-22T10:00:00Z',
  started_at: null,
  finished_at: null,
  error_code: null,
  error_message: null,
  attempt_count: 0,
  max_attempts: 3,
  created_at: '2026-07-22T10:00:00Z',
  updated_at: '2026-07-22T10:00:00Z',
}

test('успешно запускает регламент', async () => {
  let receivedId: number | undefined

  const result = await runScheduleNow(
    42,
    async (scheduleId) => {
      receivedId = scheduleId
      return EXECUTION
    },
    createManualRunGuard(),
  )

  assert.equal(receivedId, 42)
  assert.deepEqual(result, { status: 'success', execution: EXECUTION })
})

test('блокирует повторный запуск до завершения первого', async () => {
  let calls = 0
  let resolveRequest: ((execution: AutomationExecution) => void) | undefined
  const pendingRequest = new Promise<AutomationExecution>((resolve) => {
    resolveRequest = resolve
  })
  const guard = createManualRunGuard()
  const api = async () => {
    calls += 1
    return pendingRequest
  }

  const first = runScheduleNow(42, api, guard)
  const second = await runScheduleNow(42, api, guard)

  assert.deepEqual(second, { status: 'busy' })
  assert.equal(calls, 1)
  assert.ok(resolveRequest)
  resolveRequest(EXECUTION)
  assert.equal((await first).status, 'success')
})

test('переводит backend-ошибку в безопасное русское сообщение', async () => {
  const result = await runScheduleNow(
    42,
    async () => {
      throw new Error('Failed to start automation schedule: db details')
    },
    createManualRunGuard(),
  )

  assert.deepEqual(result, {
    status: 'error',
    message: 'Не удалось запустить регламент. Попробуйте ещё раз',
  })
  assert.equal(JSON.stringify(result).includes('db details'), false)
})

test('обновляет последний статус только для запущенного регламента', () => {
  const previousExecution = { ...EXECUTION, schedule_id: 7, id: 99 }
  const current = new Map([
    [7, previousExecution],
    [42, null],
  ])

  const updated = updateLatestExecution(current, 42, EXECUTION)

  assert.deepEqual(updated.get(42), {
    schedule_id: 42,
    status: 'pending',
    requested_at: EXECUTION.requested_at,
    started_at: null,
    finished_at: null,
    duration_seconds: null,
    user_status: 'Ожидает запуска',
    user_message: 'Запуск ожидает обработки',
    error_category: null,
    error_code: null,
  })
  assert.equal(updated.get(7), previousExecution)
  assert.equal(current.get(42), null)
})
