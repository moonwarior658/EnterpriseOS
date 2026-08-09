import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import type { ReactNode } from 'react'

type ProtectedRouteProps = {
  children: ReactNode
  adminOnly?: boolean
  requestViewOnly?: boolean
}

function ProtectedRoute({
  children,
  adminOnly = false,
  requestViewOnly = false,
}: ProtectedRouteProps) {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <main className="login-page">
        <section className="login-card">
          <p className="subtitle">Проверяем сессию…</p>
        </section>
      </main>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (adminOnly && !user.is_admin) {
    return (
      <main className="login-page">
        <section className="login-card">
          <h1>Доступ запрещён</h1>
          <p className="subtitle">У вас нет доступа к этому разделу.</p>
        </section>
      </main>
    )
  }

  if (
    requestViewOnly
    && !user.is_admin
    && !user.can_view_requests
  ) {
    return (
      <main className="login-page">
        <section className="login-card">
          <h1>Доступ запрещён</h1>
          <p className="subtitle">
            У вас нет доступа к просмотру заявок.
          </p>
        </section>
      </main>
    )
  }

  return children
}

export default ProtectedRoute
