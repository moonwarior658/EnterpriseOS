import { useState } from 'react'
import {
  NavLink,
  Outlet,
  useNavigate,
} from 'react-router-dom'
import { useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { getActionContext, type ActionContext } from '../services/actionContext'
import { canReadAudit, canReadEmployees, canReadUsers } from '../services/employeePermissions'
import { getEmployeeBootstrapStatus } from '../services/employees'
import { changeOwnPassword } from '../services/users'
import { EosDialog } from '../components/EosDialog'
import type { FormEvent } from 'react'

function AppLayout() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [actionContext, setActionContext] = useState<ActionContext | null>(null)
  const [bootstrapAvailable, setBootstrapAvailable] = useState<{ userId: number; available: boolean } | null>(null)
  const [passwordFormOpen, setPasswordFormOpen] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [passwordError, setPasswordError] = useState('')
  const [passwordChanged, setPasswordChanged] = useState(false)
  const roles = actionContext && user && actionContext.user_id === user.id ? actionContext.roles : []
  const showAudit = canReadAudit(roles)
  const showEmployees = canReadEmployees(roles) || Boolean(bootstrapAvailable && user && bootstrapAvailable.userId === user.id && bootstrapAvailable.available)
  const showUsers = canReadUsers(roles)
  const repairReaders = ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'ACCOUNTANT', 'SUPPLY_MANAGER', 'HANDYMAN', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'DRIVER', 'CONFECTIONER', 'BAKER']
  const repairCreators = ['ADMIN', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'DRIVER', 'CONFECTIONER', 'BAKER', 'HANDYMAN']
  const supplyRequestReaders = ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER', 'SUPPLY_MANAGER', 'ACCOUNTANT']
  const supplyFinancialReaders = ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT']

  useEffect(() => {
    let active = true
    if (user) getActionContext().then((context) => {
      if (active) setActionContext(context)
    }).catch(async () => {
      if (!active) return
      setActionContext(null)
      if (user.is_admin) {
        const status = await getEmployeeBootstrapStatus().catch(() => null)
        if (active) setBootstrapAvailable({ userId: user.id, available: status?.available === true })
      }
    })
    return () => { active = false }
  }, [user])

  function closeMenu() {
    setMenuOpen(false)
  }

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (passwordBusy) return
    if (!newPassword || !confirmPassword) { setPasswordError('Заполните оба поля'); return }
    if (newPassword !== confirmPassword) { setPasswordError('Пароли не совпадают'); return }
    setPasswordBusy(true)
    setPasswordError('')
    try {
      await changeOwnPassword(newPassword)
      setNewPassword('')
      setConfirmPassword('')
      setPasswordChanged(true)
      setPasswordFormOpen(false)
    } catch (error) {
      setPasswordError(error instanceof Error ? error.message : 'Не удалось сменить пароль')
    } finally {
      setPasswordBusy(false)
    }
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

          {roles.some((role) => repairCreators.includes(role)) && (
            <>
              <p className="menu-section-label">Создать заявку</p>
              <NavLink
                to="/requests/repair/new"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Заявка на ремонт</span>
                <span>→</span>
              </NavLink>
            </>
          )}

          {roles.some((role) => repairReaders.includes(role)) && (
            <>
              <p className="menu-section-label">Работа с заявками</p>
              <NavLink
                to="/requests/repair"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Заявки на ремонт</span>
                <span>→</span>
              </NavLink>
            </>
          )}

          {roles.some((role) => supplyRequestReaders.includes(role)) && (
            <NavLink
              to="/supply/requests"
              onClick={closeMenu}
              className={({ isActive }) => isActive ? 'menu-link menu-link-active' : 'menu-link'}
            >
              <span>Заявки снабжения</span>
              <span>→</span>
            </NavLink>
          )}

          {roles.some((role) => ['HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER'].includes(role)) && (
            <NavLink to="/supply/production-procurement" onClick={closeMenu} className={({ isActive }) => isActive ? 'menu-link menu-link-active' : 'menu-link'}>
              <span>Закупки производства</span><span>→</span>
            </NavLink>
          )}

          {roles.some((role) => ['ADMIN', 'SUPPLY_MANAGER'].includes(role)) && (
            <NavLink to="/repairs/contractors" onClick={closeMenu} className={({ isActive }) => isActive ? 'menu-link menu-link-active' : 'menu-link'}>
              <span>Подрядчики ремонта</span><span>→</span>
            </NavLink>
          )}

          {roles.some((role) => supplyFinancialReaders.includes(role)) && (
            <>
              <p className="menu-section-label">Администрирование</p>
              <NavLink
                to="/supply/debts"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Долги подразделений</span>
                <span>→</span>
              </NavLink>

              <NavLink
                to="/supply/suppliers"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Поставщики</span>
                <span>→</span>
              </NavLink>

              <NavLink
                to="/supply/purchase-requests"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Закупочные запросы</span>
                <span>→</span>
              </NavLink>

              <NavLink
                to="/supply/supplier-orders"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Заказы поставщикам</span>
                <span>→</span>
              </NavLink>

              <NavLink
                to="/supply/supplier-payments"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Оплаты поставщикам</span>
                <span>→</span>
              </NavLink>

              {roles.includes('ADMIN') && <NavLink
                to="/integrations/iiko/mappings"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Mapping iiko ↔ EOS</span>
                <span>→</span>
              </NavLink>}

              {roles.includes('ADMIN') && <NavLink
                to="/automation/schedules"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Регламентные задачи</span>
                <span>→</span>
              </NavLink>}

              {roles.includes('ADMIN') && <NavLink
                to="/automation/diagnostics"
                onClick={closeMenu}
                className={({ isActive }) =>
                  isActive ? 'menu-link menu-link-active' : 'menu-link'
                }
              >
                <span>Диагностика автоматизаций</span>
                <span>→</span>
              </NavLink>}
            </>
          )}
          {showEmployees && <NavLink to="/employees" onClick={closeMenu} className={({ isActive }) => isActive ? 'menu-link menu-link-active' : 'menu-link'}><span>Сотрудники</span><span>→</span></NavLink>}
          {showUsers && <NavLink to="/users" onClick={closeMenu} className={({ isActive }) => isActive ? 'menu-link menu-link-active' : 'menu-link'}><span>Пользователи</span><span>→</span></NavLink>}
          {showAudit && (
            <NavLink
              to="/audit"
              onClick={closeMenu}
              className={({ isActive }) =>
                isActive ? 'menu-link menu-link-active' : 'menu-link'
              }
            >
              <span>Аудит</span>
              <span>→</span>
            </NavLink>
          )}
        </nav>

        <div className="menu-footer">
          <div>
            <strong>{user?.display_name}</strong>
            <span>@{user?.username}</span>
          </div>

          {user?.account_type === 'HUMAN' && <button className="secondary-action" type="button" onClick={() => { setPasswordFormOpen(true); setPasswordError(''); setPasswordChanged(false) }}>Сменить пароль</button>}
          {passwordChanged && <p role="status">Пароль изменён</p>}

          <button type="button" onClick={handleLogout}>
            Выйти
          </button>
        </div>
      </aside>

      <main className="workspace-content">
        <Outlet />
      </main>
      {passwordFormOpen && <EosDialog title="Смена пароля" onClose={() => { if (!passwordBusy) setPasswordFormOpen(false) }}>
        <form className="password-change-form" onSubmit={submitPassword}>
          <label><span>Новый пароль</span><input type="password" autoComplete="new-password" minLength={12} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required autoFocus /></label>
          <label><span>Подтвердите пароль</span><input type="password" autoComplete="new-password" minLength={12} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required /></label>
          {passwordError && <p className="field-error" role="alert">{passwordError}</p>}
          <div className="user-actions"><button className="primary-action" type="submit" disabled={passwordBusy}>{passwordBusy ? 'Сохраняем…' : 'Сохранить'}</button><button className="secondary-action" type="button" disabled={passwordBusy} onClick={() => setPasswordFormOpen(false)}>Отмена</button></div>
        </form>
      </EosDialog>}
    </div>
  )
}

export default AppLayout
