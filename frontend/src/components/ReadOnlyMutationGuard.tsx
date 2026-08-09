import type { ReactNode } from 'react'
import { useAuth } from '../contexts/AuthContext'


function ReadOnlyMutationGuard({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <p className="page-state">Проверяем доступ…</p>
  }

  if (user?.can_view_requests && !user.is_admin) {
    return (
      <main className="login-page">
        <section className="login-card">
          <h1>Доступ запрещён</h1>
          <p className="subtitle">
            Для вашей учётной записи доступен только просмотр заявок.
          </p>
        </section>
      </main>
    )
  }

  return children
}

export default ReadOnlyMutationGuard
