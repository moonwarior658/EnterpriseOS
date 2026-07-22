import { useEffect, useRef, useState } from 'react'
import {
  getAutomationDiagnostics,
  type AutomationDiagnostics,
} from '../services/automation'
import {
  createDiagnosticsPoller,
  overallDiagnosticsStatus,
} from './automationDiagnosticsLogic'
import './AutomationDiagnosticsPage.css'

const STATUS_LABELS = {
  healthy: 'Работает',
  degraded: 'Требует внимания',
  unavailable: 'Недоступно',
  unknown: 'Нет данных',
  known: 'Данные получены',
}

function formatDate(value: string | null): string {
  if (!value) return 'Нет данных'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'medium',
  }).format(new Date(value))
}

function StateCard({
  title,
  status,
  children,
}: {
  title: string
  status: keyof typeof STATUS_LABELS
  children: React.ReactNode
}) {
  return (
    <article className={`diagnostics-card diagnostics-state-${status}`}>
      <div className="diagnostics-card-heading">
        <h2>{title}</h2>
        <span>{STATUS_LABELS[status]}</span>
      </div>
      {children}
    </article>
  )
}

function AutomationDiagnosticsPage() {
  const [diagnostics, setDiagnostics] = useState<AutomationDiagnostics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastSuccess, setLastSuccess] = useState<string | null>(null)
  const pollerRef = useRef<ReturnType<typeof createDiagnosticsPoller> | null>(null)

  useEffect(() => {
    const poller = createDiagnosticsPoller({
      load: getAutomationDiagnostics,
      onLoading: setLoading,
      onSuccess: (snapshot) => {
        setDiagnostics(snapshot)
        setLastSuccess(snapshot.generated_at)
        setError('')
      },
      onError: setError,
    })
    pollerRef.current = poller
    poller.start()
    return () => {
      poller.stop()
      pollerRef.current = null
    }
  }, [])

  const overall = diagnostics ? overallDiagnosticsStatus(diagnostics) : 'unknown'

  return (
    <main className="app-page diagnostics-page">
      <div className="page-shell diagnostics-shell">
        <section className="page-panel diagnostics-panel">
          <div className="page-title-row diagnostics-title-row">
            <div>
              <p className="eyebrow">AUTOMATION CORE</p>
              <h1>Диагностика автоматизаций</h1>
              <p className="subtitle">Безопасное состояние инфраструктуры выполнения</p>
            </div>
            <button
              className="primary-action"
              type="button"
              disabled={loading}
              onClick={() => void pollerRef.current?.refresh()}
            >
              {loading ? 'Обновление…' : 'Обновить'}
            </button>
          </div>

          <div className={`diagnostics-overall diagnostics-state-${overall}`}>
            <strong>Общий статус: {STATUS_LABELS[overall]}</strong>
            <span>Последнее успешное обновление: {formatDate(lastSuccess)}</span>
          </div>

          {error && <p className="diagnostics-error" role="alert">{error}</p>}
          {!diagnostics && loading && <p className="diagnostics-empty">Загружаем состояние…</p>}
          {!diagnostics && !loading && !error && <p className="diagnostics-empty">Данные диагностики пока недоступны</p>}

          {diagnostics && (
            <>
              <div className="diagnostics-grid">
                <StateCard title="Worker" status={diagnostics.worker_state.status}>
                  <p>Heartbeat: {formatDate(diagnostics.worker_state.last_heartbeat_at)}</p>
                  <p>Возраст: {diagnostics.worker_state.heartbeat_age_seconds ?? '—'} сек.</p>
                  <p>Интервал: {diagnostics.worker_state.poll_interval_seconds ?? '—'} сек.</p>
                </StateCard>
                <StateCard title="Scheduler" status={diagnostics.scheduler_state.status}>
                  <p>Последний проход: {formatDate(diagnostics.scheduler_state.last_run_at)}</p>
                  <p>Проверено: {diagnostics.scheduler_state.scanned}; создано: {diagnostics.scheduler_state.created}</p>
                  <p>Ошибки: {diagnostics.scheduler_state.failed}; пропущено: {diagnostics.scheduler_state.skipped}</p>
                </StateCard>
                <StateCard title="n8n" status={diagnostics.n8n_state.status}>
                  <p>{diagnostics.n8n_state.safe_message}</p>
                  <p>Проверено: {formatDate(diagnostics.n8n_state.checked_at)}</p>
                  <p>Задержка: {diagnostics.n8n_state.latency_ms ?? '—'} мс</p>
                </StateCard>
              </div>

              <div className="diagnostics-summary-grid">
                <section>
                  <h2>Outbox</h2>
                  <dl>
                    <div><dt>Ожидают</dt><dd>{diagnostics.outbox_summary.pending}</dd></div>
                    <div><dt>Обрабатываются</dt><dd>{diagnostics.outbox_summary.processing}</dd></div>
                    <div><dt>Повтор запланирован</dt><dd>{diagnostics.outbox_summary.retry_scheduled}</dd></div>
                    <div><dt>Доставлены</dt><dd>{diagnostics.outbox_summary.published}</dd></div>
                    <div><dt>Ошибки</dt><dd>{diagnostics.outbox_summary.failed}</dd></div>
                    <div><dt>Застряли</dt><dd>{diagnostics.outbox_summary.stuck_count}</dd></div>
                  </dl>
                </section>
                <section>
                  <h2>Запуски</h2>
                  <dl>
                    <div><dt>Ожидают</dt><dd>{diagnostics.execution_summary.pending}</dd></div>
                    <div><dt>Выполняются</dt><dd>{diagnostics.execution_summary.running}</dd></div>
                    <div><dt>Успешно</dt><dd>{diagnostics.execution_summary.succeeded}</dd></div>
                    <div><dt>Ошибки</dt><dd>{diagnostics.execution_summary.failed}</dd></div>
                    <div><dt>Таймаут</dt><dd>{diagnostics.execution_summary.timed_out}</dd></div>
                    <div><dt>Отменены</dt><dd>{diagnostics.execution_summary.cancelled}</dd></div>
                  </dl>
                </section>
              </div>

              <section className="diagnostics-alerts">
                <h2>Активные проблемы</h2>
                {diagnostics.alerts.length === 0 ? (
                  <p className="diagnostics-empty">Активных проблем нет</p>
                ) : diagnostics.alerts.map((alert) => (
                  <article key={alert.code} className={`diagnostics-alert diagnostics-alert-${alert.severity}`}>
                    <div><strong>{alert.title}</strong><span>{alert.count}</span></div>
                    <p>{alert.safe_message}</p>
                    <time>{formatDate(alert.detected_at)}</time>
                  </article>
                ))}
              </section>
            </>
          )}
        </section>
      </div>
    </main>
  )
}

export default AutomationDiagnosticsPage
