import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AutomationExecution,
  AutomationExecutionStatus,
  AutomationLatestExecution,
} from '../src/services/automation.ts'
import {
  latestExecutionFromManualRun,
  loadLatestExecutions,
  noLatestExecution,
} from '../src/pages/automationLatestExecutionsLogic.ts'

const LATEST: AutomationLatestExecution = {
  schedule_id: 42,
  status: 'succeeded',
  requested_at: '2026-07-22T10:00:00Z',
  started_at: '2026-07-22T10:00:01Z',
  finished_at: '2026-07-22T10:01:00Z',
  duration_seconds: 59,
  user_status: 'Выполнено',
  user_message: 'Регламент выполнен',
  error_category: null,
  error_code: null,
}

function manualExecution(
  status: AutomationExecutionStatus,
): AutomationExecution {
  return {
    id: 101,
    execution_id: '41644d7a-8875-4f35-a493-371b330fb154',
    schedule_id: 42,
    automation_type: 'daily_report',
    scope_type: 'company',
    scope_id: null,
    recipients: [],
    status,
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
}

test('загружает последние статусы одним batch-вызовом', async () => {
  let calls = 0
  const result = await loadLatestExecutions([7, 42], async (ids) => {
    calls += 1
    assert.deepEqual(ids, [7, 42])
    return [noLatestExecution(7), LATEST]
  })

  assert.equal(calls, 1)
  assert.equal(result.status, 'success')
  assert.equal(
    result.status === 'success' && result.executions.get(42),
    LATEST,
  )
})

test('корректно представляет регламент без запусков', async () => {
  const result = await loadLatestExecutions([7], async () => [])

  assert.equal(result.status, 'success')
  assert.deepEqual(
    result.status === 'success' && result.executions.get(7),
    noLatestExecution(7),
  )
})

test('не показывает техническую ошибку batch endpoint', async () => {
  const result = await loadLatestExecutions([42], async () => {
    throw new Error('SQL at postgresql://secret and n8n webhook')
  })

  assert.deepEqual(result, {
    status: 'error',
    message: 'Не удалось загрузить последние статусы. Попробуйте ещё раз',
  })
  assert.equal(JSON.stringify(result).includes('postgresql'), false)
  assert.equal(JSON.stringify(result).includes('n8n'), false)
})

test('отображает понятную классификацию всех статусов', () => {
  const expected: Record<AutomationExecutionStatus, string> = {
    pending: 'Ожидает запуска',
    dispatching: 'Запускается',
    running: 'Выполняется',
    retrying: 'Ожидает повторного запуска',
    succeeded: 'Выполнено',
    failed: 'Ошибка выполнения',
    timed_out: 'Превышено время ожидания',
    cancelled: 'Отменено',
  }

  Object.entries(expected).forEach(([status, userStatus]) => {
    const latest = latestExecutionFromManualRun(
      42,
      manualExecution(status as AutomationExecutionStatus),
    )
    assert.equal(latest.user_status, userStatus)
  })
})
