import assert from 'node:assert/strict'
import test from 'node:test'
import type { AutomationDiagnostics } from '../src/services/automation.ts'
import {
  createDiagnosticsPoller,
  overallDiagnosticsStatus,
  SAFE_DIAGNOSTICS_ERROR,
} from '../src/pages/automationDiagnosticsLogic.ts'

function snapshot(): AutomationDiagnostics {
  return {
    generated_at: '2026-07-22T10:00:00Z',
    worker_state: {
      status: 'healthy',
      last_heartbeat_at: '2026-07-22T10:00:00Z',
      heartbeat_age_seconds: 0,
      worker_id: 'worker-123456789abc',
      poll_interval_seconds: 1,
    },
    scheduler_state: {
      status: 'healthy',
      last_run_at: '2026-07-22T10:00:00Z',
      age_seconds: 0,
      scanned: 1,
      claimed: 1,
      created: 1,
      failed: 0,
      skipped: 0,
      poll_interval_seconds: 1,
    },
    n8n_state: {
      configured: true,
      reachable: true,
      checked_at: '2026-07-22T10:00:00Z',
      latency_ms: 12,
      status: 'healthy',
      safe_message: 'n8n доступен',
    },
    outbox_summary: {
      pending: 0,
      processing: 0,
      retry_scheduled: 0,
      published: 3,
      failed: 0,
      oldest_pending_at: null,
      oldest_pending_age_seconds: null,
      stuck_count: 0,
    },
    execution_summary: {
      pending: 0,
      running: 0,
      succeeded: 3,
      failed: 0,
      timed_out: 0,
      cancelled: 0,
      running_too_long_count: 0,
      recent_system_errors: [],
    },
    alerts: [],
  }
}

test('определяет healthy и degraded состояния с активными alerts', () => {
  const healthy = snapshot()
  assert.equal(overallDiagnosticsStatus(healthy), 'healthy')

  const degraded = snapshot()
  degraded.alerts.push({
    code: 'SCHEDULER_STALE',
    severity: 'warning',
    title: 'Scheduler требует внимания',
    safe_message: 'Последний проход устарел',
    count: 1,
    detected_at: degraded.generated_at,
  })
  assert.equal(overallDiagnosticsStatus(degraded), 'degraded')
})

test('manual refresh и polling используют один запрос без параллельных вызовов', async () => {
  let resolveLoad: ((value: AutomationDiagnostics) => void) | undefined
  let calls = 0
  let scheduled: (() => void) | undefined
  const poller = createDiagnosticsPoller({
    load: () => {
      calls += 1
      return new Promise((resolve) => { resolveLoad = resolve })
    },
    onLoading: () => undefined,
    onSuccess: () => undefined,
    onError: () => undefined,
    schedule: (callback, intervalMs) => {
      assert.equal(intervalMs, 20_000)
      scheduled = callback
      return 7
    },
    cancel: () => undefined,
  })

  poller.start()
  const manual = poller.refresh()
  scheduled?.()
  assert.equal(calls, 1)
  resolveLoad?.(snapshot())
  await manual
})

test('cleanup отменяет polling и не публикует поздний результат', async () => {
  let cancelled: unknown
  let successCount = 0
  let resolveLoad: ((value: AutomationDiagnostics) => void) | undefined
  const poller = createDiagnosticsPoller({
    load: () => new Promise((resolve) => { resolveLoad = resolve }),
    onLoading: () => undefined,
    onSuccess: () => { successCount += 1 },
    onError: () => undefined,
    schedule: () => 'timer',
    cancel: (handle) => { cancelled = handle },
  })

  poller.start()
  poller.stop()
  resolveLoad?.(snapshot())
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(cancelled, 'timer')
  assert.equal(successCount, 0)
})

test('ошибка диагностики заменяется безопасным сообщением', async () => {
  const errors: string[] = []
  const poller = createDiagnosticsPoller({
    load: async () => {
      throw new Error('postgresql://secret n8n token stack trace')
    },
    onLoading: () => undefined,
    onSuccess: () => undefined,
    onError: (message) => errors.push(message),
    schedule: () => 1,
    cancel: () => undefined,
  })

  poller.start()
  await poller.refresh()
  assert.deepEqual(errors, [SAFE_DIAGNOSTICS_ERROR])
  assert.equal(errors.join(' ').includes('secret'), false)
  poller.stop()
})
