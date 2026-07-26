import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { getApiHealth, type ApiHealth } from '../services/api'
import {
  getWorkRequests,
  updateWorkRequestStatus,
  type WorkRequest,
  type WorkRequestStatus,
  type WorkRequestType,
} from '../services/requests'
import {
  activeRequestsByType,
  priorityLabel,
  REQUEST_STATUSES,
  statusLabel,
  warehouseCategoryLabel,
} from './workRequestLogic'

type ConnectionState = 'checking' | 'online' | 'offline'
type RequestsState = 'loading' | 'ready' | 'error'

function requestDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

function DashboardPage() {
  const { user } = useAuth()
  const [connectionState, setConnectionState] =
    useState<ConnectionState>('checking')
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null)
  const [requestsState, setRequestsState] =
    useState<RequestsState>('loading')
  const [requests, setRequests] = useState<WorkRequest[]>([])
  const [updatingIds, setUpdatingIds] = useState<Set<number>>(new Set())
  const [statusError, setStatusError] = useState('')

  useEffect(() => {
    getApiHealth()
      .then((health) => {
        setApiHealth(health)
        setConnectionState('online')
      })
      .catch(() => {
        setConnectionState('offline')
      })

    getWorkRequests()
      .then((items) => {
        setRequests(items)
        setRequestsState('ready')
      })
      .catch(() => {
        setRequestsState('error')
      })
  }, [])

  const active = activeRequestsByType(requests)
  const hasActiveRequests =
    active.warehouse.length > 0 || active.repair.length > 0

  async function changeStatus(
    requestId: number,
    status: WorkRequestStatus,
  ) {
    if (updatingIds.has(requestId)) {
      return
    }

    setStatusError('')
    setUpdatingIds((current) => new Set(current).add(requestId))

    try {
      const updated = await updateWorkRequestStatus(requestId, status)
      setRequests((current) =>
        current.map((request) =>
          request.id === updated.id ? updated : request,
        ),
      )
    } catch {
      setStatusError('Не удалось изменить статус заявки')
    } finally {
      setUpdatingIds((current) => {
        const next = new Set(current)
        next.delete(requestId)
        return next
      })
    }
  }

  function renderSection(
    title: string,
    requestType: WorkRequestType,
    items: WorkRequest[],
  ) {
    return (
      <section className="dashboard-request-section">
        <div className="dashboard-section-heading">
          <h2>{title}</h2>
          <span>{items.length}</span>
        </div>

        {items.length === 0 ? (
          <p className="dashboard-section-empty">Активных заявок нет</p>
        ) : (
          <div className="dashboard-request-list">
            {items.map((request) => (
              <article className="dashboard-request-card" key={request.id}>
                <div className="dashboard-request-main">
                  <div className="dashboard-request-meta">
                    <strong>{request.department}</strong>
                    <span>
                      {requestType === 'warehouse'
                        ? warehouseCategoryLabel(request.warehouse_category)
                        : request.repair_category}
                    </span>
                    {requestType === 'repair' && (
                      <span>{priorityLabel(request.priority)}</span>
                    )}
                  </div>
                  <p>{request.description}</p>
                  <small>
                    {requestDate(request.created_at)} ·{' '}
                    {request.created_by_name}
                  </small>
                </div>

                {user?.is_admin ? (
                  <select
                    className="dashboard-status-select"
                    value={request.status}
                    aria-label={`Статус заявки ${request.id}`}
                    disabled={updatingIds.has(request.id)}
                    onChange={(event) =>
                      void changeStatus(
                        request.id,
                        event.target.value as WorkRequestStatus,
                      )
                    }
                  >
                    {REQUEST_STATUSES.map((status) => (
                      <option key={status.value} value={status.value}>
                        {status.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="request-status-badge">
                    {statusLabel(request.status)}
                  </span>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
    )
  }

  return (
    <section
      className={
        hasActiveRequests
          ? 'dashboard-view dashboard-view-active'
          : 'dashboard-view'
      }
    >
      {requestsState === 'loading' && (
        <p className="dashboard-loading">Загружаем заявки…</p>
      )}

      {requestsState === 'error' && (
        <p className="dashboard-load-error">Не удалось загрузить заявки</p>
      )}

      {requestsState === 'ready' && hasActiveRequests && (
        <div className="dashboard-requests">
          <div className="dashboard-requests-heading">
            <p className="eyebrow">АКТИВНЫЕ ЗАЯВКИ</p>
            <h1>Рабочий Dashboard</h1>
          </div>
          {statusError && (
            <p className="dashboard-load-error">{statusError}</p>
          )}
          {renderSection(
            'Заявки на склад',
            'warehouse',
            active.warehouse,
          )}
          {renderSection(
            'Заявки на ремонт',
            'repair',
            active.repair,
          )}
        </div>
      )}

      {requestsState === 'ready' && !hasActiveRequests && (
        <div className="dashboard-empty">
          <div className="dashboard-status-mark">
            <span />
          </div>

          <p className="eyebrow">ENTERPRISEOS</p>
          <h1>Всё спокойно</h1>
          <p>
            {user?.display_name}, сейчас нет событий,
            требующих вашего участия
          </p>
        </div>
      )}

      <footer className="dashboard-system-state">
        <span
          className={
            connectionState === 'offline'
              ? 'status-dot status-dot-error'
              : 'status-dot'
          }
        />

        {connectionState === 'checking' &&
          'Проверяем состояние системы…'}

        {connectionState === 'online' &&
          `Система работает · ${apiHealth?.service} v${apiHealth?.version}`}

        {connectionState === 'offline' &&
          'Нет соединения с ядром системы'}
      </footer>
    </section>
  )
}

export default DashboardPage
