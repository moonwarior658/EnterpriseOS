import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { getApiHealth, type ApiHealth } from '../services/api'

type ConnectionState = 'checking' | 'online' | 'offline'

function DashboardPage() {
  const { user } = useAuth()

  const [connectionState, setConnectionState] =
    useState<ConnectionState>('checking')
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null)

  useEffect(() => {
    getApiHealth()
      .then((health) => {
        setApiHealth(health)
        setConnectionState('online')
      })
      .catch(() => {
        setConnectionState('offline')
      })
  }, [])

  return (
    <section className="dashboard-view">
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
