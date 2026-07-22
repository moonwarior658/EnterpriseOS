import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AutomationExecution,
  AutomationExecutionHistoryPage,
} from '../src/services/automation.ts'
import {
  canReuseHistory,
  loadExecutionHistory,
  prependManualExecution,
  updateHistoryAfterManualExecution,
} from '../src/pages/automationExecutionHistoryLogic.ts'

const PAGE: AutomationExecutionHistoryPage = {
  items: [
    {
      status: 'succeeded',
      requested_at: '2026-07-22T10:00:00Z',
      started_at: '2026-07-22T10:00:01Z',
      finished_at: '2026-07-22T10:01:00Z',
      duration_seconds: 59,
      error_code: null,
      error_message: null,
    },
  ],
  total: 7,
  limit: 6,
  offset: 0,
}

const MANUAL_EXECUTION: AutomationExecution = {
  id: 101,
  execution_id: '41644d7a-8875-4f35-a493-371b330fb154',
  schedule_id: 42,
  automation_type: 'daily_report',
  scope_type: 'company',
  scope_id: null,
  recipients: [],
  status: 'pending',
  provider: null,
  requested_at: '2026-07-22T11:00:00Z',
  started_at: null,
  finished_at: null,
  error_code: null,
  error_message: null,
  attempt_count: 0,
  max_attempts: 3,
  created_at: '2026-07-22T11:00:00Z',
  updated_at: '2026-07-22T11:00:00Z',
}

test('успешно загружает историю выбранного регламента', async () => {
  const result = await loadExecutionHistory(
    42,
    1,
    6,
    async (scheduleId, limit, offset) => {
      assert.equal(scheduleId, 42)
      assert.equal(limit, 6)
      assert.equal(offset, 0)
      return PAGE
    },
  )

  assert.deepEqual(result, { status: 'success', page: PAGE })
})

test('поддерживает пустое состояние', async () => {
  const emptyPage = { ...PAGE, items: [], total: 0 }
  const result = await loadExecutionHistory(
    42,
    1,
    6,
    async () => emptyPage,
  )

  assert.equal(result.status, 'success')
  assert.deepEqual(result.status === 'success' && result.page.items, [])
})

test('не показывает техническую ошибку backend', async () => {
  const result = await loadExecutionHistory(42, 1, 6, async () => {
    throw new Error('database timeout at postgresql://secret')
  })

  assert.deepEqual(result, {
    status: 'error',
    message: 'Не удалось загрузить историю запусков. Попробуйте ещё раз',
  })
  assert.equal(JSON.stringify(result).includes('postgresql'), false)
})

test('рассчитывает offset для следующей страницы', async () => {
  let receivedOffset = -1
  await loadExecutionHistory(42, 3, 6, async (_id, _limit, offset) => {
    receivedOffset = offset
    return { ...PAGE, offset }
  })

  assert.equal(receivedOffset, 12)
})

test('добавляет новый ручной запуск в открытую первую страницу', () => {
  const fullPage = {
    ...PAGE,
    items: Array.from({ length: PAGE.limit }, (_, index) => ({
      ...PAGE.items[0],
      requested_at: `2026-07-22T10:00:0${index}Z`,
    })),
  }
  const updated = prependManualExecution(fullPage, MANUAL_EXECUTION)

  assert.equal(updated.items[0]?.requested_at, '2026-07-22T11:00:00Z')
  assert.equal(updated.items[0]?.status, 'pending')
  assert.equal(updated.items.length, PAGE.limit)
  assert.equal(updated.total, 8)
  assert.equal(updated.offset, 0)
})

test('после ручного запуска со второй страницы загружает первую с backend', async () => {
  const secondPage = { ...PAGE, total: 13, offset: 6 }
  const backendFirstPage = {
    ...PAGE,
    items: [
      {
        ...PAGE.items[0],
        status: 'pending' as const,
        requested_at: MANUAL_EXECUTION.requested_at,
        started_at: null,
        finished_at: null,
        duration_seconds: null,
      },
      ...PAGE.items,
    ],
    total: 14,
  }
  let requestCount = 0

  assert.equal(
    prependManualExecution(secondPage, MANUAL_EXECUTION),
    secondPage,
  )

  const result = await updateHistoryAfterManualExecution(
    secondPage,
    MANUAL_EXECUTION,
    42,
    6,
    async (scheduleId, limit, offset) => {
      requestCount += 1
      assert.equal(scheduleId, 42)
      assert.equal(limit, 6)
      assert.equal(offset, 0)
      return backendFirstPage
    },
  )

  assert.equal(requestCount, 1)
  assert.deepEqual(result, {
    status: 'success',
    page: backendFirstPage,
  })
})

test('повторно открывает тот же регламент с сохранённой страницей', () => {
  assert.equal(canReuseHistory(42, 42, PAGE), true)
  assert.equal(canReuseHistory(7, 42, PAGE), false)
  assert.equal(canReuseHistory(42, 42, null), false)
})
