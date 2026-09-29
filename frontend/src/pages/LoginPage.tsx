import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { passwordInputType, passwordToggleLabel } from '../utils/passwordUx'

function LoginPage() {
  const navigate = useNavigate()
  const { user, login } = useAuth()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [passwordVisible, setPasswordVisible] = useState(false)

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
            <span className="password-input-row">
              <input
                type={passwordInputType(passwordVisible)}
                name="password"
                placeholder="Введите пароль"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button
                className="password-visibility-action"
                type="button"
                aria-label={passwordToggleLabel(passwordVisible)}
                aria-pressed={passwordVisible}
                onClick={() => setPasswordVisible((value) => !value)}
              >
                {passwordVisible ? (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3 3l18 18" />
                    <path d="M10.6 10.7a2 2 0 0 0 2.7 2.7" />
                    <path d="M9.9 4.2A10.8 10.8 0 0 1 12 4c5.2 0 8.7 4.7 9 5.2a1.5 1.5 0 0 1 0 1.6 16 16 0 0 1-2.2 2.8" />
                    <path d="M6.6 6.6A16 16 0 0 0 3 9.2a1.5 1.5 0 0 0 0 1.6c.3.5 3.8 5.2 9 5.2 1 0 2-.2 2.8-.5" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3 9.2C3.3 8.7 6.8 4 12 4s8.7 4.7 9 5.2a1.5 1.5 0 0 1 0 1.6c-.3.5-3.8 5.2-9 5.2s-8.7-4.7-9-5.2a1.5 1.5 0 0 1 0-1.6Z" />
                    <circle cx="12" cy="10" r="2.5" />
                  </svg>
                )}
              </button>
            </span>
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
