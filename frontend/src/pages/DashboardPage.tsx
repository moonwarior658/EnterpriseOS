import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardGrid, {
  type DashboardWidgetDefinition,
} from '../components/dashboard/DashboardGrid'
import DashboardMascots from '../components/dashboard/DashboardMascots'
import DashboardSystemStatus from '../components/dashboard/DashboardSystemStatus'
import { getApiHealth } from '../services/api'
import {
  getWorkRequests,
  type WorkRequest,
} from '../services/requests'
import {
  activeRequestsByType,
  DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS,
} from './workRequestLogic'
import {
  activeDashboardDirectionCount,
  buildDashboardWidgetConfig,
  type DashboardConnectionState,
} from './dashboardWidgetLogic'

type RequestsState = 'loading' | 'ready' | 'error'

function DashboardPage() {
  const [connectionState, setConnectionState] =
    useState<DashboardConnectionState>('checking')
  const [requestsState, setRequestsState] =
    useState<RequestsState>('loading')
  const [requests, setRequests] = useState<WorkRequest[]>([])

  useEffect(() => {
    let isMounted = true
    let requestInFlight = false
    let hasLoadedRequests = false

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
      .then(() => {
        if (!isMounted) {
          return
        }
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
      window.clearInterval(refreshInterval)
      document.removeEventListener(
        'visibilitychange',
        handleVisibilityChange,
      )
    }
  }, [])

  const active = activeRequestsByType(requests)
  const widgetConfig = buildDashboardWidgetConfig(
    active.warehouse.length,
    active.repair.length,
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
