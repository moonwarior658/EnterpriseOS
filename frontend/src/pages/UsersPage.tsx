import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import {
  createUser,
  getUsers,
  updateUser,
  type UpdateUserInput,
  type UserRecord,
} from '../services/users'

function UsersPage() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const [users, setUsers] = useState<UserRecord[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isCreating, setIsCreating] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingUser, setEditingUser] =
    useState<UserRecord | null>(null)
  const [error, setError] = useState('')

  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)

  const [editUsername, setEditUsername] = useState('')
  const [editDisplayName, setEditDisplayName] = useState('')
  const [editPassword, setEditPassword] = useState('')
  const [editIsAdmin, setEditIsAdmin] = useState(false)

  useEffect(() => {
    getUsers()
      .then(setUsers)
      .catch((requestError) => {
        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Не удалось загрузить пользователей',
        )
      })
      .finally(() => {
        setIsLoading(false)
      })
  }, [])

  function openCreateForm() {
    setEditingUser(null)
    setShowCreateForm((current) => !current)
    setError('')
  }

  function openEditForm(target: UserRecord) {
    setShowCreateForm(false)
    setEditingUser(target)
    setEditUsername(target.username)
    setEditDisplayName(target.display_name)
    setEditPassword('')
    setEditIsAdmin(target.is_admin)
    setError('')
  }

  async function handleCreate(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()
    setError('')
    setIsCreating(true)

    try {
      const createdUser = await createUser({
        username,
        display_name: displayName,
        password,
        is_admin: isAdmin,
      })

      setUsers((currentUsers) => [
        ...currentUsers,
        createdUser,
      ])
      setUsername('')
      setDisplayName('')
      setPassword('')
      setIsAdmin(false)
      setShowCreateForm(false)
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось создать пользователя',
      )
    } finally {
      setIsCreating(false)
    }
  }

  async function handleEdit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault()

    if (!editingUser) {
      return
    }

    setError('')
    setIsEditing(true)

    const updates: UpdateUserInput = {
      username: editUsername,
      display_name: editDisplayName,
      is_admin: editIsAdmin,
    }

    if (editPassword) {
      updates.password = editPassword
    }

    try {
      const updatedUser = await updateUser(
        editingUser.id,
        updates,
      )

      setUsers((currentUsers) =>
        currentUsers.map((currentUser) =>
          currentUser.id === updatedUser.id
            ? updatedUser
            : currentUser,
        ),
      )

      setEditingUser(null)

      if (updatedUser.id === user?.id) {
        window.location.reload()
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось сохранить изменения',
      )
    } finally {
      setIsEditing(false)
    }
  }

  async function handleToggleActive(target: UserRecord) {
    const action = target.is_active
      ? 'заблокировать'
      : 'разблокировать'

    if (!window.confirm(`${action} пользователя ${target.display_name}?`)) {
      return
    }

    setError('')

    try {
      const updatedUser = await updateUser(target.id, {
        is_active: !target.is_active,
      })

      setUsers((currentUsers) =>
        currentUsers.map((currentUser) =>
          currentUser.id === updatedUser.id
            ? updatedUser
            : currentUser,
        ),
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось изменить пользователя',
      )
    }
  }

  return (
    <main className="app-page">
      <header className="app-topbar">
        <button
          className="app-brand"
          type="button"
          onClick={() => navigate('/dashboard')}
        >
          EOS
        </button>

        <div className="app-user">
          <span>{user?.display_name}</span>
          <button
            type="button"
            onClick={() => navigate('/dashboard')}
          >
            На главную
          </button>
        </div>
      </header>

      <div className="page-shell">
        <section className="page-panel">
          <div className="page-title-row">
            <div>
              <p className="eyebrow">АДМИНИСТРИРОВАНИЕ</p>
              <h1>Пользователи</h1>
              <p className="subtitle">
                Сотрудники с доступом к EnterpriseOS
              </p>
            </div>

            <button
              className="primary-action"
              type="button"
              onClick={openCreateForm}
            >
              {showCreateForm ? 'Отмена' : 'Добавить'}
            </button>
          </div>

          {showCreateForm && (
            <form
              className="user-create-form"
              onSubmit={handleCreate}
            >
              <div className="form-grid">
                <label>
                  <span>Имя сотрудника</span>
                  <input
                    value={displayName}
                    onChange={(event) =>
                      setDisplayName(event.target.value)
                    }
                    placeholder="Например, Анна"
                    required
                  />
                </label>

                <label>
                  <span>Логин</span>
                  <input
                    value={username}
                    onChange={(event) =>
                      setUsername(event.target.value)
                    }
                    placeholder="anna"
                    minLength={3}
                    required
                  />
                </label>

                <label>
                  <span>Временный пароль</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(event) =>
                      setPassword(event.target.value)
                    }
                    placeholder="Минимум 12 символов"
                    minLength={12}
                    required
                  />
                </label>

                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={isAdmin}
                    onChange={(event) =>
                      setIsAdmin(event.target.checked)
                    }
                  />
                  <span>Администратор</span>
                </label>
              </div>

              <button
                className="primary-action"
                type="submit"
                disabled={isCreating}
              >
                {isCreating
                  ? 'Создаём…'
                  : 'Создать пользователя'}
              </button>
            </form>
          )}

          {editingUser && (
            <form
              className="user-create-form"
              onSubmit={handleEdit}
            >
              <div>
                <p className="eyebrow">РЕДАКТИРОВАНИЕ</p>
                <strong>{editingUser.display_name}</strong>
              </div>

              <div className="form-grid">
                <label>
                  <span>Имя сотрудника</span>
                  <input
                    value={editDisplayName}
                    onChange={(event) =>
                      setEditDisplayName(event.target.value)
                    }
                    required
                  />
                </label>

                <label>
                  <span>Логин</span>
                  <input
                    value={editUsername}
                    onChange={(event) =>
                      setEditUsername(event.target.value)
                    }
                    minLength={3}
                    required
                  />
                </label>

                <label>
                  <span>Новый пароль</span>
                  <input
                    type="password"
                    value={editPassword}
                    onChange={(event) =>
                      setEditPassword(event.target.value)
                    }
                    placeholder="Оставить прежний"
                    minLength={12}
                  />
                </label>

                <label className="checkbox-field">
                  <input
                    type="checkbox"
                    checked={editIsAdmin}
                    disabled={editingUser.id === user?.id}
                    onChange={(event) =>
                      setEditIsAdmin(event.target.checked)
                    }
                  />
                  <span>Администратор</span>
                </label>
              </div>

              <div className="user-actions">
                <button
                  className="primary-action"
                  type="submit"
                  disabled={isEditing}
                >
                  {isEditing ? 'Сохраняем…' : 'Сохранить'}
                </button>

                <button
                  className="secondary-action"
                  type="button"
                  onClick={() => setEditingUser(null)}
                >
                  Отмена
                </button>
              </div>
            </form>
          )}

          {error && <p className="page-error">{error}</p>}

          {isLoading ? (
            <p className="empty-state">
              Загружаем пользователей…
            </p>
          ) : (
            <div className="users-list">
              {users.map((listedUser) => (
                <article
                  className="user-row"
                  key={listedUser.id}
                >
                  <div className="user-avatar">
                    {listedUser.display_name
                      .charAt(0)
                      .toUpperCase()}
                  </div>

                  <div className="user-identity">
                    <strong>{listedUser.display_name}</strong>
                    <span>@{listedUser.username}</span>
                  </div>

                  <div className="user-badges">
                    {listedUser.is_admin && (
                      <span className="badge">
                        Администратор
                      </span>
                    )}

                    <span
                      className={
                        listedUser.is_active
                          ? 'badge badge-active'
                          : 'badge badge-blocked'
                      }
                    >
                      {listedUser.is_active
                        ? 'Активен'
                        : 'Заблокирован'}
                    </span>
                  </div>

                  <div className="user-actions">
                    <button
                      className="secondary-action"
                      type="button"
                      onClick={() => openEditForm(listedUser)}
                    >
                      Изменить
                    </button>

                    <button
                      className="secondary-action"
                      type="button"
                      disabled={listedUser.id === user?.id}
                      onClick={() =>
                        handleToggleActive(listedUser)
                      }
                    >
                      {listedUser.is_active
                        ? 'Заблокировать'
                        : 'Разблокировать'}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

export default UsersPage
