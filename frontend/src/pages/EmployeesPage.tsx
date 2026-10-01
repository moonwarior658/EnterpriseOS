import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { EosSearchField, EosSelect } from '../components/EosFormControls'
import { GeneratedCredentialsPanel } from '../components/GeneratedCredentialsPanel'
import { getActionContext, type EmployeeRole as AccessRole } from '../services/actionContext'
import { assignableRoles, canCreateEmployee, canCreateHumanUser } from '../services/employeePermissions'
import {
  EMPLOYEE_ROLES, assignEmployeeDepartment, assignEmployeeRole, bootstrapFirstAdmin,
  createEmployee, getEmployeeBootstrapStatus, getEmployeeDepartments, getEmployees,
  linkEmployeeUser, type Department, type Employee, type EmployeeStatus, type EmployeeBootstrapStatus,
  type EmployeeRole,
} from '../services/employees'
import { createUser, getUsers, type GeneratedCredentials, type UserRecord } from '../services/users'
import {
  ROLE_LABELS, activeAt, availableHumanUsers, departmentName, employeeErrorMessage,
  filterEmployees,
} from './employeeAdminLogic'

const initialReason = 'Первичное назначение при создании сотрудника'
const nowLocal = () => new Date().toISOString()

function EmployeesPage() {
  const navigate = useNavigate()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [accessRoles, setAccessRoles] = useState<AccessRole[]>([])
  const canWrite = canCreateEmployee(accessRoles)
  const canCreateUser = canCreateHumanUser(accessRoles)
  const allowedRoles = assignableRoles(accessRoles)
  const [departments, setDepartments] = useState<Department[]>([])
  const [users, setUsers] = useState<UserRecord[]>([])
  const [bootstrapStatus, setBootstrapStatus] = useState<EmployeeBootstrapStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<'ALL' | EmployeeStatus>('ACTIVE')
  const [departmentFilter, setDepartmentFilter] = useState('')
  const [roleFilter, setRoleFilter] = useState<'' | EmployeeRole>('')
  const [fullName, setFullName] = useState('')
  const [birthDate, setBirthDate] = useState('')
  const [phone, setPhone] = useState('')
  const [address, setAddress] = useState('')
  const [photoUrl, setPhotoUrl] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [roles, setRoles] = useState<EmployeeRole[]>([])
  const [reason, setReason] = useState(initialReason)
  const [userMode, setUserMode] = useState<'NONE' | 'EXISTING' | 'NEW'>('NONE')
  const [userId, setUserId] = useState('')
  const [login, setLogin] = useState('')
  const [generatedCredentials, setGeneratedCredentials] = useState<GeneratedCredentials | null>(null)
  const [userIsAdmin, setUserIsAdmin] = useState(false)
  const [userCanViewRequests, setUserCanViewRequests] = useState(false)

  async function load() {
    setLoading(true)
    setError('')
    try {
      const currentBootstrapStatus = await getEmployeeBootstrapStatus()
      setBootstrapStatus(currentBootstrapStatus)
      if (currentBootstrapStatus.available) {
        setEmployees([])
        setUsers([])
        setDepartments(await getEmployeeDepartments())
        return
      }
      const [employeeItems, departmentItems, userItems, context] = await Promise.all([
        getEmployees(), getEmployeeDepartments(), getUsers().catch(() => []), getActionContext(),
      ])
      setAccessRoles(context.roles)
      setEmployees(employeeItems)
      setDepartments(departmentItems)
      setUsers(userItems)
    } catch (requestError) {
      setError(employeeErrorMessage(requestError, 'Не удалось загрузить сотрудников'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    getEmployeeBootstrapStatus()
      .then(async (currentBootstrapStatus) => {
        if (cancelled) return
        setBootstrapStatus(currentBootstrapStatus)
        if (currentBootstrapStatus.available) {
          const departmentItems = await getEmployeeDepartments()
          if (!cancelled) setDepartments(departmentItems)
          return
        }
        const [employeeItems, departmentItems, userItems, context] = await Promise.all([
          getEmployees(), getEmployeeDepartments(), getUsers().catch(() => []), getActionContext(),
        ])
        if (!cancelled) {
          setEmployees(employeeItems)
          setDepartments(departmentItems)
          setUsers(userItems)
          setAccessRoles(context.roles)
        }
      })
      .catch((requestError) => {
        if (!cancelled) setError(employeeErrorMessage(requestError, 'Не удалось загрузить сотрудников'))
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const candidates = useMemo(
    () => availableHumanUsers(users, employees), [users, employees],
  )
  const filtered = useMemo(
    () => filterEmployees(employees, query, status, departmentFilter, roleFilter),
    [employees, query, status, departmentFilter, roleFilter],
  )
  const usersById = useMemo(() => new Map(users.map((user) => [user.id, user])), [users])

  function toggleRole(role: EmployeeRole) {
    setRoles((current) => current.includes(role)
      ? current.filter((item) => item !== role) : [...current, role])
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!reason.trim()) { setError('Укажите причину изменения'); return }
    if (!departmentId || (!bootstrapStatus?.available && roles.length === 0)) {
      setError('Выберите основное подразделение и хотя бы одну роль')
      return
    }
    setBusy(true)
    setError('')
    let created: Employee | null = null
    try {
      if (bootstrapStatus?.available) {
        created = await bootstrapFirstAdmin({
          full_name: fullName, birth_date: birthDate, phone,
          residence_address: address, photo_url: photoUrl.trim() || null,
          department_id: departmentId, reason: reason.trim(),
        })
        navigate(`/employees/${created.id}`)
        return
      }
      created = await createEmployee({
        full_name: fullName, birth_date: birthDate, phone,
        residence_address: address, photo_url: photoUrl.trim() || null, reason: reason.trim(),
        department_id: departmentId,
      })
      const validFrom = nowLocal()
      if (!created.department_assignments.some((item) => item.is_primary && activeAt(item.valid_from, item.valid_to))) {
        await assignEmployeeDepartment(created.id, departmentId, true, validFrom, reason.trim())
      }
      await Promise.all(roles.map((role) => assignEmployeeRole(created!.id, role, validFrom, reason.trim())))
      let selectedUserId: number | null = null
      if (userMode === 'EXISTING') selectedUserId = Number(userId)
      if (userMode === 'NEW') {
        const newUser = await createUser({
          username: login, display_name: fullName,
          is_admin: userIsAdmin, can_view_requests: userCanViewRequests, account_type: 'HUMAN',
          employee_id: created.id,
        })
        selectedUserId = newUser.id
        if (newUser.temporary_password) {
          setGeneratedCredentials({
            username: newUser.username,
            temporary_password: newUser.temporary_password,
          })
        }
      }
      if (selectedUserId && userMode === 'EXISTING') await linkEmployeeUser(created.id, selectedUserId, reason.trim())
      if (userMode === 'NEW') {
        setShowCreate(false)
        await load()
        return
      }
      navigate(`/employees/${created.id}`)
    } catch (requestError) {
      setError(employeeErrorMessage(
        requestError,
        created
          ? 'Сотрудник создан, но не все первоначальные назначения выполнены. Откройте карточку и завершите настройку.'
          : 'Не удалось создать сотрудника',
      ))
      if (created) await load()
    } finally { setBusy(false) }
  }

  return (
    <main className="app-page employee-admin-page">
      <div className="page-shell">
        <section className="page-panel">
          <div className="page-title-row">
            <div><p className="eyebrow">АДМИНИСТРИРОВАНИЕ</p><h1>Сотрудники</h1>
              <p className="subtitle">Сотрудники, назначения и доступ в EOS</p></div>
            {(canWrite || bootstrapStatus?.available) && <button className="primary-action" type="button" onClick={() => setShowCreate((value) => !value)}>
              {showCreate ? 'Отмена' : 'Добавить сотрудника'}
            </button>}
          </div>

          {(canWrite || bootstrapStatus?.available) && showCreate && (
            <form className="employee-form" onSubmit={handleCreate}>
              <h2>{bootstrapStatus?.available ? 'Первый администратор' : 'Новый сотрудник'}</h2>
              <div className="employee-form-grid">
                <label><span>ФИО</span><input value={fullName} onChange={(e) => setFullName(e.target.value)} required /></label>
                <label><span>Дата рождения</span><input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} required /></label>
                <label><span>Телефон</span><input value={phone} onChange={(e) => setPhone(e.target.value)} required /></label>
                <label className="employee-wide-field"><span>Адрес проживания</span><input value={address} onChange={(e) => setAddress(e.target.value)} required /></label>
                <label><span>Ссылка на фото</span><input type="url" value={photoUrl} onChange={(e) => setPhotoUrl(e.target.value)} placeholder="Необязательно" /></label>
                <label><span>Основное подразделение</span><EosSelect value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} required>
                  <option value="">Выберите</option>{departments.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </EosSelect></label>
              </div>
              {bootstrapStatus?.available ? (
                <fieldset className="employee-role-picker"><legend>Роль</legend>
                  <label><input type="checkbox" checked disabled /> {ROLE_LABELS.ADMIN}</label>
                </fieldset>
              ) : (
                <fieldset className="employee-role-picker"><legend>Роли</legend>
                  {allowedRoles.map((role) => <label key={role}><input type="checkbox" checked={roles.includes(role)} onChange={() => toggleRole(role)} /> {ROLE_LABELS[role]}</label>)}
                </fieldset>
              )}
              <div className="employee-form-grid">
                {bootstrapStatus?.available ? (
                  <label className="employee-wide-field"><span>Доступ в EOS</span>
                    <strong>Связать с текущей учётной записью @{bootstrapStatus.username}</strong>
                  </label>
                ) : <>
                  {canCreateUser && <label><span>Доступ в EOS</span><EosSelect value={userMode} onChange={(e) => setUserMode(e.target.value as typeof userMode)}>
                    <option value="NONE">Нет доступа</option>{accessRoles.includes('ADMIN') && <option value="EXISTING">Связать существующего User</option>}<option value="NEW">Создать HUMAN User</option>
                  </EosSelect></label>}
                  {userMode === 'EXISTING' && <label><span>Учётная запись</span><EosSelect value={userId} onChange={(e) => setUserId(e.target.value)} required>
                    <option value="">Выберите</option>{candidates.map((item) => <option key={item.id} value={item.id}>@{item.username} — {item.display_name}</option>)}
                  </EosSelect></label>}
                  {userMode === 'NEW' && <><label><span>Логин</span><input value={login} onChange={(e) => setLogin(e.target.value)} minLength={3} required /></label>
                    {accessRoles.includes('ADMIN') && <><label className="employee-check"><input type="checkbox" checked={userIsAdmin} onChange={(e) => setUserIsAdmin(e.target.checked)} /> Администратор EOS</label>
                    <label className="employee-check"><input type="checkbox" checked={userCanViewRequests} onChange={(e) => setUserCanViewRequests(e.target.checked)} /> Просмотр заявок</label></>}</>}
                </>}
                <label className="employee-wide-field"><span>Причина изменения</span><input value={reason} onChange={(e) => setReason(e.target.value)} required /></label>
              </div>
              <button className="primary-action" disabled={busy} type="submit">{busy ? 'Создаём…' : bootstrapStatus?.available ? `Создать Employee и связать @${bootstrapStatus.username}` : 'Создать сотрудника'}</button>
            </form>
          )}

          {generatedCredentials && <GeneratedCredentialsPanel
            username={generatedCredentials.username}
            temporaryPassword={generatedCredentials.temporary_password}
            onClose={() => setGeneratedCredentials(null)}
          />}

          <div className="employee-filters">
            <EosSearchField label="Поиск по ФИО" value={query} onChange={(e) => setQuery(e.target.value)} />
            <label><span>Статус</span><EosSelect value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="ACTIVE">Активные</option><option value="DISMISSED">Уволенные</option><option value="ALL">Все</option></EosSelect></label>
            <label><span>Подразделение</span><EosSelect value={departmentFilter} onChange={(e) => setDepartmentFilter(e.target.value)}><option value="">Все</option>{departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</EosSelect></label>
            <label><span>Роль</span><EosSelect value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as '' | EmployeeRole)}><option value="">Все</option>{EMPLOYEE_ROLES.map((role) => <option key={role} value={role}>{ROLE_LABELS[role]}</option>)}</EosSelect></label>
          </div>
          {error && <p className="page-error" role="alert">{error}</p>}
          {loading ? <p className="empty-state">Загружаем сотрудников…</p> : filtered.length === 0 ? <p className="empty-state">Сотрудники не найдены</p> : (
            <div className="employee-list" role="table">
              <div className="employee-list-head" role="row"><span>Сотрудник</span><span>Статус</span><span>Доступ</span><span>Роли</span><span>Основное подразделение</span><span>Телефон</span></div>
              {filtered.map((employee) => {
                const linkedUser = employee.linked_user_id ? usersById.get(employee.linked_user_id) : undefined
                const activeRoles = employee.role_assignments.filter((item) => activeAt(item.valid_from, item.valid_to))
                const primary = employee.department_assignments.find((item) => item.is_primary && activeAt(item.valid_from, item.valid_to))
                return <button className="employee-list-row" role="row" type="button" key={employee.id} onClick={() => navigate(`/employees/${employee.id}`)}>
                  <strong>{employee.full_name}</strong><span>{employee.profile_level === 'BASIC' ? '—' : <b className={`badge ${employee.status === 'ACTIVE' ? 'badge-active' : 'badge-blocked'}`}>{employee.status === 'ACTIVE' ? 'Активен' : `Уволен${employee.dismissal_date ? ` ${employee.dismissal_date}` : ''}`}</b>}</span>
                  <span>{employee.profile_level === 'BASIC' ? '—' : linkedUser ? <><b>@{linkedUser.username}</b><small>{linkedUser.is_active ? 'Доступ есть' : 'Заблокирован'}</small></> : <small>Нет доступа</small>}</span>
                  <span>{employee.profile_level === 'BASIC' ? employee.roles?.map((role) => ROLE_LABELS[role]).join(', ') || '—' : activeRoles.map((item) => ROLE_LABELS[item.role]).join(', ') || '—'}</span>
                  <span>{employee.profile_level === 'BASIC' ? employee.department_ids?.map((id) => departmentName(departments, id)).join(', ') || '—' : primary ? departmentName(departments, primary.department_id) : '—'}</span><span>{employee.phone}</span>
                </button>
              })}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

export default EmployeesPage
