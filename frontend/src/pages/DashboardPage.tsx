import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import DashboardGrid, {
  type DashboardWidgetDefinition,
} from '../components/dashboard/DashboardGrid'
import DashboardMascots from '../components/dashboard/DashboardMascots'
import DashboardSystemStatus from '../components/dashboard/DashboardSystemStatus'
import { getApiHealth, type ApiHealth } from '../services/api'
import {
  getWorkRequests,
  type WorkRequest,
} from '../services/requests'
import {
  getSupplyDashboardSummary,
  type SupplyDashboardSummary,
} from '../services/supplyAdmin'
import {
  activeRequestsByType,
  DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS,
} from './workRequestLogic'
import {
  activeDashboardDirectionCount,
  buildDashboardWidgetConfig,
  DASHBOARD_EMPTY_TITLE,
  dashboardEmptySystemStatusText,
  dashboardViewMode,
  supplySummaryToDashboardWidgetCounts,
  type DashboardConnectionState,
  type DashboardViewMode,
} from './dashboardWidgetLogic'

type RequestsState = 'loading' | 'ready' | 'error'
const DASHBOARD_EMPTY_TRANSITION_MS = 280

function DashboardPage() {
  const { user } = useAuth()
  const [connectionState, setConnectionState] =
    useState<DashboardConnectionState>('checking')
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null)
  const [requestsState, setRequestsState] =
    useState<RequestsState>('loading')
  const [requests, setRequests] = useState<WorkRequest[]>([])
  const [supplySummary, setSupplySummary] =
    useState<SupplyDashboardSummary | null>(null)
  const [displayedView, setDisplayedView] =
    useState<DashboardViewMode>('empty')

  useEffect(() => {
    let isMounted = true
    let requestInFlight = false
    let hasLoadedRequests = false
    const controller = new AbortController()

    async function loadRequests() {
      if (!isMounted || requestInFlight) {
        return
      }

      requestInFlight = true
      try {
        const items = await getWorkRequests()
        if (!isMounted) {
          return
        }
        setRequests(items)
        if (user?.is_admin) {
          try {
            const summary = await getSupplyDashboardSummary(
              controller.signal,
            )
            if (!isMounted) return
            setSupplySummary(summary)
          } catch {
            if (
              !controller.signal.aborted
              && !hasLoadedRequests
            ) setSupplySummary(null)
          }
        }
        setRequestsState('ready')
        hasLoadedRequests = true
      } catch {
        if (isMounted && !hasLoadedRequests) {
          setRequestsState('error')
        }
      } finally {
        requestInFlight = false
      }
    }

    getApiHealth()
      .then((health) => {
        if (!isMounted) {
          return
        }
        setApiHealth(health)
        setConnectionState('online')
      })
      .catch(() => {
        if (isMounted) {
          setConnectionState('offline')
        }
      })

    void loadRequests()

    const refreshInterval = window.setInterval(
      () => void loadRequests(),
      DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS,
    )

    function handleVisibilityChange() {
      if (document.visibilityState === 'visible') {
        void loadRequests()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      isMounted = false
      controller.abort()
      window.clearInterval(refreshInterval)
      document.removeEventListener(
        'visibilitychange',
        handleVisibilityChange,
      )
    }
  }, [user?.is_admin])

  const active = activeRequestsByType(requests)
  const widgetConfig = buildDashboardWidgetConfig(
    active.warehouse.length,
    active.repair.length,
    supplySummaryToDashboardWidgetCounts(supplySummary),
  )
  const widgetContent = {
    'warehouse-requests': (
      <>
        <p className="eyebrow">СКЛАД</p>
        <h2>Заявки на склад</h2>
        <strong>{active.warehouse.length}</strong>
        <Link className="dashboard-widget-action" to="/requests/warehouse">
          Открыть
        </Link>
      </>
    ),
    'repair-requests': (
      <>
        <p className="eyebrow">РЕМОНТ</p>
        <h2>Заявки на ремонт</h2>
        <strong>{active.repair.length}</strong>
        <Link className="dashboard-widget-action" to="/requests/repair">
          Открыть
        </Link>
      </>
    ),
    'supply-new': (
      <>
        <p className="eyebrow">СНАБЖЕНИЕ</p>
        <h2>Новые заявки</h2>
        <strong>{supplySummary?.new_requests ?? 0}</strong>
        <Link className="dashboard-widget-action" to="/supply/requests?status=SUBMITTED">Открыть</Link>
      </>
    ),
    'supply-mapping': (
      <>
        <p className="eyebrow">СНАБЖЕНИЕ</p>
        <h2>Требуется сопоставление</h2>
        <strong>{supplySummary?.mapping_required ?? 0}</strong>
        <Link className="dashboard-widget-action" to="/supply/requests?has_needs_review=true">Открыть</Link>
      </>
    ),
    'supply-progress': (
      <>
        <p className="eyebrow">СНАБЖЕНИЕ</p>
        <h2>В обработке</h2>
        <strong>{supplySummary?.requests_in_progress ?? 0}</strong>
        <Link className="dashboard-widget-action" to="/supply/requests">Открыть</Link>
      </>
    ),
    'supply-debts': (
      <>
        <p className="eyebrow">СНАБЖЕНИЕ</p>
        <h2>Долги</h2>
        <strong>{supplySummary?.active_debts ?? 0}</strong>
        <Link className="dashboard-widget-action" to="/supply/debts?status=ACTIVE">Открыть</Link>
      </>
    ),
    'supply-critical-debts': (
      <>
        <p className="eyebrow">КРИТИЧНО</p>
        <h2>Критические долги</h2>
        <strong>{supplySummary?.critical_debts ?? 0}</strong>
        <Link className="dashboard-widget-action" to="/supply/debts?status=ACTIVE&severity=CRITICAL">Открыть</Link>
      </>
    ),
  }
  const widgets: DashboardWidgetDefinition[] = widgetConfig.map(
    (widget) => ({
      id: widget.id,
      size: widget.size,
      order: widget.order,
      content: widgetContent[widget.id],
    }),
  )
  const activeDirectionCount =
    activeDashboardDirectionCount(widgetConfig)
  const requestedView = dashboardViewMode(activeDirectionCount)

  useEffect(() => {
    if (requestedView === displayedView) {
      return
    }

    const timeout = window.setTimeout(() => {
      setDisplayedView(requestedView)
    }, DASHBOARD_EMPTY_TRANSITION_MS)

    return () => window.clearTimeout(timeout)
  }, [displayedView, requestedView])

  if (displayedView === 'empty') {
    const isEmptyLeaving = requestedView === 'active'
    const systemStatusText = dashboardEmptySystemStatusText(
      connectionState,
      apiHealth,
    )

    return (
      <section className="dashboard-view dashboard-view-empty">
        <div
          className={`dashboard-empty${isEmptyLeaving ? ' dashboard-empty-leaving' : ''}`}
        >
          <div className="dashboard-status-mark" aria-hidden="true">
            <span />
          </div>

          <p className="eyebrow">ENTERPRISEOS</p>
          <h1>{DASHBOARD_EMPTY_TITLE}</h1>
          <p>
            {user?.display_name}, сейчас нет событий,
            <br />
            требующих вашего участия
          </p>
        </div>

        <footer
          aria-live="polite"
          className="dashboard-system-state"
          role="status"
        >
          <span
            className={
              connectionState === 'offline'
                ? 'status-dot status-dot-error'
                : 'status-dot'
            }
          />
          {systemStatusText}
        </footer>
      </section>
    )
  }

  return (
    <section className="dashboard-view dashboard-view-active">
      <div className="dashboard-summary">
        <DashboardSystemStatus
          activeDirectionCount={activeDirectionCount}
          connectionState={connectionState}
        />

        {requestsState === 'loading' && (
          <p className="dashboard-loading">Загружаем заявки…</p>
        )}
        {requestsState === 'error' && (
          <p className="dashboard-load-error">
            Не удалось загрузить заявки
          </p>
        )}

        <DashboardGrid widgets={widgets} />
      </div>

      <DashboardMascots />
    </section>
  )
}

export default DashboardPage
