import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { getActionContext, type EmployeeRole } from '../services/actionContext'
import type { ReactNode } from 'react'

type ProtectedRouteProps = {
  children: ReactNode
  adminOnly?: boolean
  allowedRoles?: EmployeeRole[]
  allowBootstrap?: boolean
}

function ProtectedRoute({
  children,
  adminOnly = false,
  allowedRoles,
  allowBootstrap = false,
}: ProtectedRouteProps) {
  const { user, isLoading } = useAuth()
  const [access, setAccess] = useState<{ userId: number; roles: EmployeeRole[] } | null>(null)
  const allowedRoleKey = allowedRoles?.join(',')

  useEffect(() => {
    if ((!allowedRoleKey && !adminOnly) || !user) return
    let active = true
    getActionContext().then((context) => {
      if (active) setAccess({ userId: user.id, roles: context.roles })
    }).catch(() => {
      if (active) setAccess({ userId: user.id, roles: [] })
    })
    return () => { active = false }
  }, [user, allowedRoleKey, adminOnly])

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

  if ((allowedRoles || adminOnly) && access?.userId !== user.id) {
    return <main className="login-page"><section className="login-card"><p className="subtitle">Проверяем доступ…</p></section></main>
  }

  if (allowedRoles && !access?.roles.some((role) => allowedRoles.includes(role)) && !(allowBootstrap && user.is_admin)) {
    return <main className="login-page"><section className="login-card"><h1>Доступ запрещён</h1><p className="subtitle">У вас нет доступа к этому разделу.</p></section></main>
  }

  if (adminOnly && !access?.roles.includes('ADMIN')) {
    return (
      <main className="login-page">
        <section className="login-card">
          <h1>Доступ запрещён</h1>
          <p className="subtitle">У вас нет доступа к этому разделу.</p>
        </section>
      </main>
    )
  }

  return children
}

export default ProtectedRoute
