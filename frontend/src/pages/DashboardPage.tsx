import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { getApiHealth, type ApiHealth } from '../services/api'

type ConnectionState = 'checking' | 'online' | 'offline'

function DashboardPage() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()

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

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <div className="brand-mark" aria-hidden="true">
          <span>EOS</span>
        </div>

        <header className="login-header">
          <p className="eyebrow">ENTERPRISEOS</p>
          <h1>Всё спокойно</h1>
          <p className="subtitle">
            {user?.display_name}, сейчас нет событий,
            требующих вашего участия
          </p>
        </header>

        <p className="subtitle">
          {connectionState === 'checking' &&
            'Проверяем соединение с API…'}
          {connectionState === 'online' &&
            `API подключён · ${apiHealth?.service} v${apiHealth?.version}`}
          {connectionState === 'offline' &&
            'Нет соединения с API'}
        </p>

        <div className="login-form">
          <button type="button" onClick={handleLogout}>
            <span>Выйти</span>
            <span className="button-arrow">→</span>
          </button>
        </div>
      </section>
    </main>
  )
}

export default DashboardPage
