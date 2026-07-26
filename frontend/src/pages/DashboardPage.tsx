import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardGrid, {
  type DashboardWidgetDefinition,
} from '../components/dashboard/DashboardGrid'
import DashboardMascots from '../components/dashboard/DashboardMascots'
import { useAuth } from '../contexts/AuthContext'
import { getApiHealth, type ApiHealth } from '../services/api'
import {
  getWorkRequests,
  type WorkRequest,
} from '../services/requests'
import {
  activeRequestsByType,
  DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS,
} from './workRequestLogic'
import { buildDashboardWidgetConfig } from './dashboardWidgetLogic'

type ConnectionState = 'checking' | 'online' | 'offline'
type RequestsState = 'loading' | 'ready' | 'error'

function DashboardPage() {
  const { user } = useAuth()
  const [connectionState, setConnectionState] =
    useState<ConnectionState>('checking')
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null)
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
  const hasActiveRequests = widgets.length > 0

  return (
    <section className="dashboard-view dashboard-view-active">
      <div className="dashboard-summary">
        <div className="dashboard-requests-heading">
          <p className="eyebrow">ENTERPRISEOS</p>
          <h1>{hasActiveRequests ? 'Рабочий Dashboard' : 'Всё спокойно'}</h1>
          <p className="request-intro">
            {hasActiveRequests
              ? 'Активные заявки подразделений'
              : `${user?.display_name}, сейчас нет активных заявок`}
          </p>
        </div>

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
      <footer className="dashboard-system-state">
        <span
          className={
            connectionState === 'offline'
              ? 'status-dot status-dot-error'
              : 'status-dot'
          }
        />
        {connectionState === 'checking' && 'Проверяем состояние системы…'}
        {connectionState === 'online' &&
          `Система работает · ${apiHealth?.service} v${apiHealth?.version}`}
        {connectionState === 'offline' && 'Нет соединения с ядром системы'}
      </footer>
    </section>
  )
}

export default DashboardPage
