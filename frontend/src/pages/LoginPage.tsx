import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

function LoginPage() {
  const navigate = useNavigate()
  const { user, login } = useAuth()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (user) {
    return <Navigate to="/dashboard" replace />
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)

    try {
      await login(username, password)
      navigate('/dashboard', { replace: true })
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось выполнить вход',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <div className="background-glow background-glow-left" />
      <div className="background-glow background-glow-right" />

      <section className="login-card">
        <div className="brand-mark" aria-hidden="true">
          <span>EOS</span>
        </div>

        <header className="login-header">
          <p className="eyebrow">ENTERPRISEOS</p>
          <h1>Добро пожаловать</h1>
          <p className="subtitle">
            Единое рабочее пространство компании
          </p>
        </header>

        <form className="login-form" onSubmit={handleSubmit}>
          <label>
            <span>Логин</span>
            <input
              type="text"
              name="username"
              placeholder="Введите логин"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </label>

          <label>
            <span>Пароль</span>
            <input
              type="password"
              name="password"
              placeholder="Введите пароль"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>

          <button type="submit" disabled={isSubmitting}>
            <span>
              {isSubmitting ? 'Выполняется вход…' : 'Войти'}
            </span>
            <span className="button-arrow">→</span>
          </button>

          {error && <p className="form-message">{error}</p>}
        </form>
      </section>

      <footer className="system-status">
        <span className="status-dot" />
        Система работает
      </footer>
    </main>
  )
}

export default LoginPage
