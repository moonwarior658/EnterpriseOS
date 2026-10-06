import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { getActionContext, type EmployeeRole } from '../services/actionContext'
import DashboardGrid, {
  type DashboardWidgetDefinition,
} from '../components/dashboard/DashboardGrid'
import DashboardMascots from '../components/dashboard/DashboardMascots'
import DashboardSalesWidget from '../components/dashboard/DashboardSalesWidget'
import { dashboardSalesKind } from './dashboardSalesLogic'
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
import { dashboardAccess } from './dashboardAccess'
import { buildAttentionItems, upcomingExternalVisits } from './dashboardOverviewLogic'
import { formatDateTime } from '../utils/dateFormat'

type RequestsState = 'loading' | 'ready' | 'error'
const DASHBOARD_EMPTY_TRANSITION_MS = 280

function DashboardPage() {
  const { user } = useAuth()
  const userId = user?.id
  const [roleContext, setRoleContext] = useState<{ userId: number; roles: EmployeeRole[] } | null>(null)
  const roles = roleContext?.userId === user?.id ? roleContext?.roles ?? [] : []
  const salesKind = dashboardSalesKind(roles)
  const access = dashboardAccess(roles)
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
    let active = true
    getActionContext().then((context) => {
      if (active && userId !== undefined) setRoleContext({ userId, roles: context.roles })
    }).catch(() => {
      if (active) setRoleContext(null)
    })
    return () => { active = false }
  }, [userId])

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
        const items = access.readRepairs ? await getWorkRequests() : []
        if (!isMounted) {
          return
        }
        setRequests(items)
        if (access.readSupplySummary) {
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
  }, [access.readRepairs, access.readSupplySummary])

  const active = activeRequestsByType(requests)
  const repairAttention = requests.filter((item) => item.request_type === 'repair' && item.needs_action)
  const attentionItems = buildAttentionItems(repairAttention.length, supplySummary, access)
  const attentionTotal = attentionItems.length
  const assignedEvents = upcomingExternalVisits(requests)
  const widgetConfig = buildDashboardWidgetConfig(
    0,
    access.readRepairs ? active.repair.length : 0,
    supplySummaryToDashboardWidgetCounts(supplySummary),
  ).filter((widget) => {
    if (widget.id.startsWith('supply-') && widget.id !== 'supply-debts' && widget.id !== 'supply-critical-debts') return access.readOperationalSupply
    if (widget.id === 'supply-debts' || widget.id === 'supply-critical-debts') return access.readFinance
    return true
  })
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
        <Link className="dashboard-widget-action" to="/supply/debts?status=ACTIVE&severity=RED">Открыть</Link>
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
  if (salesKind) widgets.unshift({
    id: 'sales-analytics', size: salesKind === 'personal' ? '1x1' : '1x2', order: 0,
    content: <DashboardSalesWidget key={`${user?.id}:${roles.join(',')}`} kind={salesKind} />,
  })
  const activeDirectionCount =
    activeDashboardDirectionCount(widgetConfig)
  const requestedView = widgets.length || attentionTotal || assignedEvents.length ? 'active' : dashboardViewMode(activeDirectionCount)

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
        <div className="dashboard-overview-heading"><div><p className="eyebrow">ENTERPRISEOS</p><h1>Обзор</h1></div>{connectionState === 'offline' && <span className="dashboard-connection-warning" role="status">Нет связи с системой</span>}</div>

        {requestsState === 'loading' && (
          <p className="dashboard-loading">Загружаем заявки…</p>
        )}
        {requestsState === 'error' && (
          <p className="dashboard-load-error">
            Не удалось загрузить заявки
          </p>
        )}

        <div className="dashboard-overview-grid">
          <section className="dashboard-overview-card dashboard-overview-card-warning" aria-labelledby="dashboard-attention-title">
            <div className="dashboard-overview-card-heading"><h2 id="dashboard-attention-title">Требует внимания</h2><span className="dashboard-attention-count">{attentionTotal}</span></div>
            {attentionItems.length ? <div className="dashboard-attention-list">{attentionItems.map((item) => <Link key={item.to} to={item.to}><span>{item.label}</span><strong>{item.count}</strong></Link>)}</div> : <p className="dashboard-overview-empty">Сейчас нет задач, требующих внимания.</p>}
          </section>
          <section className="dashboard-overview-card" aria-labelledby="dashboard-events-title">
            <div className="dashboard-overview-card-heading"><h2 id="dashboard-events-title">Назначенные события</h2></div>
            {assignedEvents.length ? <div className="dashboard-event-list">{assignedEvents.map((item) => <article key={item.id} className="dashboard-event-item"><time dateTime={item.visit_at!}>{formatDateTime(item.visit_at)}</time><strong>Визит внешнего мастера</strong><span>Ремонт №{item.id} · {item.department}</span><Link className="secondary-action" to={`/requests/${item.id}`}>Открыть ремонт</Link></article>)}</div> : <p className="dashboard-overview-empty">Ближайших визитов нет.</p>}
          </section>
        </div>
        <DashboardGrid widgets={widgets} key={`${user?.id}:${roles.join(',')}`} />
      </div>

      <DashboardMascots />
    </section>
  )
}

export default DashboardPage
