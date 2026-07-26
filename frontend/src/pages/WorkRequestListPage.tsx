import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getWorkRequests,
  type WorkRequest,
  type WorkRequestType,
} from '../services/requests'
import {
  isActiveRequest,
  priorityLabel,
  sortWorkRequests,
  statusLabel,
  warehouseCategoryLabel,
} from './workRequestLogic'

type WorkRequestListPageProps = {
  requestType: WorkRequestType
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

function WorkRequestListPage({
  requestType,
}: WorkRequestListPageProps) {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>(
    'loading',
  )
  const [requests, setRequests] = useState<WorkRequest[]>([])
  const isWarehouse = requestType === 'warehouse'

  useEffect(() => {
    getWorkRequests()
      .then((items) => {
        setRequests(
          sortWorkRequests(
            items.filter((item) => item.request_type === requestType),
          ),
        )
        setState('ready')
      })
      .catch(() => setState('error'))
  }, [requestType])

  const active = requests.filter(isActiveRequest)
  const closed = requests.filter((request) => !isActiveRequest(request)).slice(0, 20)

  function renderRows(items: WorkRequest[]) {
    return (
      <div className="work-request-list">
        {items.map((request) => (
          <Link
            className="work-request-row"
            to={`/requests/${request.id}`}
            key={request.id}
          >
            <div className="work-request-row-main">
              <div className="dashboard-request-meta">
                <strong>{request.department}</strong>
                <span>{statusLabel(request.status)}</span>
                <span>
                  {isWarehouse
                    ? warehouseCategoryLabel(request.warehouse_category)
                    : request.repair_category}
                </span>
                {!isWarehouse && <span>{priorityLabel(request.priority)}</span>}
                {!isWarehouse && (
                  <span>Фото: {request.attachment_count}</span>
                )}
              </div>
              <p>{request.description}</p>
              <small>
                {formatDate(request.created_at)} · {request.created_by_name}
              </small>
            </div>
            <span aria-hidden="true">→</span>
          </Link>
        ))}
      </div>
    )
  }

  return (
    <section className="request-page request-list-page">
      <div className="request-panel">
        <div className="request-heading">
          <div>
            <p className="eyebrow">РАБОТА С ЗАЯВКАМИ</p>
            <h1>
              {isWarehouse ? 'Заявки на склад' : 'Заявки на ремонт'}
            </h1>
            <p className="request-intro">
              Активных заявок: {active.length}
            </p>
          </div>
          <Link className="request-back-link" to="/dashboard">
            ← На Dashboard
          </Link>
        </div>

        {state === 'loading' && <p className="page-state">Загружаем заявки…</p>}
        {state === 'error' && (
          <p className="request-message request-message-error">
            Не удалось загрузить заявки
          </p>
        )}
        {state === 'ready' && requests.length === 0 && (
          <p className="page-state">Заявок пока нет</p>
        )}
        {state === 'ready' && active.length > 0 && (
          <section className="request-list-section">
            <h2>Активные</h2>
            {renderRows(active)}
          </section>
        )}
        {state === 'ready' && closed.length > 0 && (
          <section className="request-list-section">
            <h2>Последние завершённые и отменённые</h2>
            {renderRows(closed)}
          </section>
        )}
      </div>
    </section>
  )
}

export default WorkRequestListPage
