import type { AutomationDiagnostics } from '../services/automation.ts'

export const DIAGNOSTICS_POLL_INTERVAL_MS = 20_000
export const SAFE_DIAGNOSTICS_ERROR =
  'Не удалось обновить диагностику. Попробуйте ещё раз'

type PollerOptions = {
  load: () => Promise<AutomationDiagnostics>
  onLoading: (loading: boolean) => void
  onSuccess: (diagnostics: AutomationDiagnostics) => void
  onError: (message: string) => void
  intervalMs?: number
  schedule?: (callback: () => void, intervalMs: number) => unknown
  cancel?: (handle: unknown) => void
}

export function overallDiagnosticsStatus(
  diagnostics: AutomationDiagnostics,
): 'healthy' | 'degraded' | 'unavailable' | 'unknown' {
  if (
    diagnostics.n8n_state.status === 'unavailable' ||
    diagnostics.alerts.some((alert) => alert.severity === 'critical')
  ) {
    return 'unavailable'
  }

  if (
    diagnostics.alerts.length > 0 ||
    diagnostics.worker_state.status === 'degraded' ||
    diagnostics.scheduler_state.status === 'degraded' ||
    diagnostics.n8n_state.status === 'degraded'
  ) {
    return 'degraded'
  }

  if (
    diagnostics.worker_state.status === 'unknown' ||
    diagnostics.scheduler_state.status === 'unknown' ||
    diagnostics.n8n_state.status === 'unknown'
  ) {
    return 'unknown'
  }

  return 'healthy'
}

export function createDiagnosticsPoller(options: PollerOptions) {
  const schedule = options.schedule ?? ((callback, intervalMs) =>
    window.setInterval(callback, intervalMs))
  const cancel = options.cancel ?? ((handle) =>
    window.clearInterval(handle as number))
  let active = false
  let inFlight: Promise<void> | null = null
  let intervalHandle: unknown = null

  async function refresh(): Promise<void> {
    if (inFlight) {
      return inFlight
    }

    options.onLoading(true)
    inFlight = options.load()
      .then((diagnostics) => {
        if (active) {
          options.onSuccess(diagnostics)
        }
      })
      .catch(() => {
        if (active) {
          options.onError(SAFE_DIAGNOSTICS_ERROR)
        }
      })
      .finally(() => {
        inFlight = null
        if (active) {
          options.onLoading(false)
        }
      })

    return inFlight
  }

  function start() {
    if (active) {
      return
    }
    active = true
    void refresh()
    intervalHandle = schedule(
      () => void refresh(),
      options.intervalMs ?? DIAGNOSTICS_POLL_INTERVAL_MS,
    )
  }

  function stop() {
    active = false
    if (intervalHandle !== null) {
      cancel(intervalHandle)
      intervalHandle = null
    }
  }

  return { start, stop, refresh }
}
