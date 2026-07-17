import { useState, type FormEvent } from 'react'
import './App.css'

function App() {
  const [submitted, setSubmitted] = useState(false)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitted(true)
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
          <p className="subtitle">Единое рабочее пространство компании</p>
        </header>

        <form className="login-form" onSubmit={handleSubmit}>
          <label>
            <span>Логин</span>
            <input
              type="text"
              name="username"
              placeholder="Введите логин"
              autoComplete="username"
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
              required
            />
          </label>

          <button type="submit">
            <span>Войти</span>
            <span className="button-arrow">→</span>
          </button>

          {submitted && (
            <p className="form-message">
              Экран готов. Подключение авторизации — следующий шаг.
            </p>
          )}
        </form>
      </section>

      <footer className="system-status">
        <span className="status-dot" />
        Система работает
      </footer>
    </main>
  )
}

export default App
