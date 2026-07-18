import { useState } from 'react'
import {
  NavLink,
  Outlet,
  useNavigate,
} from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

function AppLayout() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)

  function closeMenu() {
    setMenuOpen(false)
  }

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="workspace-shell">
      <header className="workspace-topbar">
        <div className="workspace-topbar-left">
          <button
            className="menu-toggle"
            type="button"
            aria-label="Открыть меню"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((current) => !current)}
          >
            <span />
            <span />
          </button>

          <button
            className="workspace-logo"
            type="button"
            onClick={() => navigate('/dashboard')}
          >
            EOS
          </button>
        </div>

        <div className="workspace-user">
          <span className="workspace-avatar">
            {user?.display_name.charAt(0).toUpperCase()}
          </span>
          <span>{user?.display_name}</span>
        </div>
      </header>

      {menuOpen && (
        <button
          className="menu-backdrop"
          type="button"
          aria-label="Закрыть меню"
          onClick={closeMenu}
        />
      )}

      <aside
        className={
          menuOpen
            ? 'workspace-menu workspace-menu-open'
            : 'workspace-menu'
        }
      >
        <div className="menu-header">
          <p className="eyebrow">ENTERPRISEOS</p>
          <strong>Рабочее пространство</strong>
        </div>

        <nav className="menu-navigation">
          <NavLink
            to="/dashboard"
            onClick={closeMenu}
            className={({ isActive }) =>
              isActive ? 'menu-link menu-link-active' : 'menu-link'
            }
          >
            <span>Главная</span>
            <span>→</span>
          </NavLink>

          {user?.is_admin && (
            <NavLink
              to="/users"
              onClick={closeMenu}
              className={({ isActive }) =>
                isActive ? 'menu-link menu-link-active' : 'menu-link'
              }
            >
              <span>Пользователи</span>
              <span>→</span>
            </NavLink>
          )}
        </nav>

        <div className="menu-footer">
          <div>
            <strong>{user?.display_name}</strong>
            <span>@{user?.username}</span>
          </div>

          <button type="button" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </aside>

      <main className="workspace-content">
        <Outlet />
      </main>
    </div>
  )
}

export default AppLayout
