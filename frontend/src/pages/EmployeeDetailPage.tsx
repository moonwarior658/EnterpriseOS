import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { EosCheckbox, EosSelect } from '../components/EosFormControls'
import { EosDialog } from '../components/EosDialog'
import { useAuth } from '../contexts/AuthContext'
import { GeneratedCredentialsPanel } from '../components/GeneratedCredentialsPanel'
import { getActionContext, type EmployeeRole as AccessRole } from '../services/actionContext'
import { assignableRoles, canCreateEmployee, canDismissEmployee, canReadEmployees, canReadUsers } from '../services/employeePermissions'
import {
  assignEmployeeDepartment, assignEmployeeRole, dismissEmployee,
  correctEmployeeIikoLink, createEmployeeIikoLink, findEmployeeIikoCandidates,
  endEmployeeDepartment, endEmployeeRole, getEmployee, getEmployeeDepartments,
  getEmployeeActiveIikoShift, getEmployeeIikoLink, getEmployeeIikoLinkHistory,
  getEmployeeIikoShifts, getEmployeeIikoShiftPage, getEmployeeAvatar, getEmployees, linkEmployeeUser, reactivateEmployee,
  refreshEmployeeIikoShifts, unlinkEmployeeUser, updateEmployee, uploadEmployeeAvatar,
  deleteEmployeeAvatar, type Department,
  type Employee, type EmployeeIikoShift, type EmployeeRole,
  type IikoEmployeeCandidate, type IikoEmployeeLink,
} from '../services/employees'
import {
  createUser, getUsers, resetEmployeePassword, updateUser, type GeneratedCredentials, type UserRecord,
} from '../services/users'
import {
  ROLE_LABELS, activeAt, assignableDepartments, availableHumanUsers, departmentName, employeeErrorMessage,
} from './employeeAdminLogic'
import { formatDateOnly, formatDateTime } from '../utils/dateFormat'

const localDateTime = () => {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000)
  return now.toISOString().slice(0, 16)
}
const today = () => new Date().toISOString().slice(0, 10)
const iso = (value: string) => new Date(value).toISOString()
const dateTimeLabel = (value: string | null) => formatDateTime(value, 'по настоящее время')
const durationLabel = (minutes: number) => `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`

type ReasonDialogProps = {
  title: string
  dateLabel?: string
  dateType?: 'date' | 'datetime-local'
  initialDate?: string
  confirmLabel: string
  busy: boolean
  reasonRequired?: boolean
  onCancel: () => void
  onConfirm: (reason: string, date: string) => Promise<unknown>
}

function ReasonDialog({ title, dateLabel, dateType = 'datetime-local', initialDate, confirmLabel, busy, reasonRequired = true, onCancel, onConfirm }: ReasonDialogProps) {
  const [reason, setReason] = useState('')
  const [date, setDate] = useState(initialDate ?? (dateType === 'date' ? today() : localDateTime()))
  const [validation, setValidation] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (reasonRequired && !reason.trim()) { setValidation('Укажите причину изменения'); return }
    await onConfirm(reason.trim(), date)
  }
  return <div className="employee-dialog-backdrop" role="presentation">
    <form className="employee-dialog" role="dialog" aria-modal="true" aria-labelledby="reason-dialog-title" onSubmit={submit}>
      <h2 id="reason-dialog-title">{title}</h2>
      {dateLabel && <label><span>{dateLabel}</span><input type={dateType} value={date} onChange={(event) => setDate(event.target.value)} required /></label>}
      {reasonRequired && <label><span>Причина изменения</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} autoFocus required /></label>}
      {validation && <p className="field-error">{validation}</p>}
      <div className="user-actions"><button className="primary-action" type="submit" disabled={busy}>{busy ? 'Выполняем…' : confirmLabel}</button><button className="secondary-action" type="button" disabled={busy} onClick={onCancel}>Отмена</button></div>
    </form>
  </div>
}

function EmployeeDetailPage() {
  const navigate = useNavigate()
  const { user: currentUser } = useAuth()
  const { employeeId = '' } = useParams()
  const [employee, setEmployee] = useState<Employee | null>(null)
  const [accessRoles, setAccessRoles] = useState<AccessRole[]>([])
  const canWrite = canCreateEmployee(accessRoles)
  const canLifecycle = canDismissEmployee(accessRoles)
  const canManageUser = employee ? employee.allowed_actions.includes(
    employee.linked_user_id ? 'manage_user_access' : 'create_human_user',
  ) : false
  const isAdmin = accessRoles.includes('ADMIN')
  const [actorEmployeeId, setActorEmployeeId] = useState('')
  const canReadShifts = (actorEmployeeId === employeeId) || accessRoles.some((role) => ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'SUPPLY_MANAGER'].includes(role))
  const allowedRoles = assignableRoles(accessRoles)
  const [employees, setEmployees] = useState<Employee[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [users, setUsers] = useState<UserRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(false)
  const [fullName, setFullName] = useState('')
  const [birthDate, setBirthDate] = useState('')
  const [phone, setPhone] = useState('')
  const [address, setAddress] = useState('')
  const [avatarUrl, setAvatarUrl] = useState('')
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [avatarOpen, setAvatarOpen] = useState(false)
  const [accessOpen, setAccessOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsTab, setSettingsTab] = useState<'iiko' | 'roles' | 'departments' | 'history'>('iiko')
  const [allShiftsOpen, setAllShiftsOpen] = useState(false)
  const [shiftFrom, setShiftFrom] = useState('')
  const [shiftTo, setShiftTo] = useState('')
  const [shiftOffset, setShiftOffset] = useState(0)
  const [shiftPage, setShiftPage] = useState<{ items: EmployeeIikoShift[]; total: number } | null>(null)
  const [shiftError, setShiftError] = useState('')
  const [editReason, setEditReason] = useState('')
  const [role, setRole] = useState<EmployeeRole>('SELLER')
  const [roleFrom, setRoleFrom] = useState(localDateTime())
  const [roleReason, setRoleReason] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [departmentFrom, setDepartmentFrom] = useState(localDateTime())
  const [isPrimary, setIsPrimary] = useState(false)
  const [departmentReason, setDepartmentReason] = useState('')
  const [selectedUserId, setSelectedUserId] = useState('')
  const [iikoLink, setIikoLink] = useState<IikoEmployeeLink | null>(null)
  const [iikoHistory, setIikoHistory] = useState<IikoEmployeeLink[]>([])
  const [iikoCandidates, setIikoCandidates] = useState<IikoEmployeeCandidate[]>([])
  const [iikoShifts, setIikoShifts] = useState<EmployeeIikoShift[]>([])
  const [activeIikoShift, setActiveIikoShift] = useState<EmployeeIikoShift | null>(null)
  const [selectedIikoUserId, setSelectedIikoUserId] = useState('')
  const [iikoReason, setIikoReason] = useState('')
  const [iikoLoading, setIikoLoading] = useState(false)
  const [iikoError, setIikoError] = useState('')
  const [dialog, setDialog] = useState<null | { kind: 'dismiss' | 'reactivate' | 'unlink' | 'link' | 'resetPassword' | 'toggleAccess' | 'endRole' | 'endDepartment'; assignmentId?: string }>(null)
  const [generatedCredentials, setGeneratedCredentials] = useState<GeneratedCredentials | null>(null)
  const [accessDialog, setAccessDialog] = useState<'create' | 'link' | null>(null)
  const [newUsername, setNewUsername] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [item, context] = await Promise.all([getEmployee(employeeId), getActionContext()])
      const [allEmployees, departmentItems, userItems] = await Promise.all([
        canReadEmployees(context.roles) ? getEmployees() : Promise.resolve([]),
        getEmployeeDepartments(),
        canReadUsers(context.roles) ? getUsers().catch(() => []) : Promise.resolve([]),
      ])
      setAccessRoles(context.roles)
      setEmployee(item); setEmployees(allEmployees); setDepartments(departmentItems); setUsers(userItems)
      setFullName(item.full_name); setBirthDate(item.birth_date); setPhone(item.phone)
      setAddress(item.residence_address); setActorEmployeeId(context.employee_id)
    } catch (requestError) { setError(employeeErrorMessage(requestError, 'Не удалось загрузить карточку сотрудника')) }
    finally { setLoading(false) }
  }, [employeeId])

  const loadIikoAdmin = useCallback(async (searchCandidates = false) => {
    setIikoLoading(true); setIikoError('')
    try {
      const [link, history] = await Promise.all([
        getEmployeeIikoLink(employeeId), getEmployeeIikoLinkHistory(employeeId),
      ])
      setIikoLink(link); setIikoHistory(history)
      if (searchCandidates || !link) setIikoCandidates(await findEmployeeIikoCandidates(employeeId))
    } catch (requestError) {
      setIikoError(employeeErrorMessage(requestError, 'Не удалось загрузить данные iiko'))
    } finally { setIikoLoading(false) }
  }, [employeeId])

  const loadShifts = useCallback(async () => {
    setIikoLoading(true); setIikoError('')
    try {
      const [shifts, active] = await Promise.all([
        getEmployeeIikoShifts(employeeId), getEmployeeActiveIikoShift(employeeId),
      ])
      setIikoShifts(shifts); setActiveIikoShift(active)
    } catch (requestError) { setIikoError(employeeErrorMessage(requestError, 'Не удалось загрузить смены iiko')) }
    finally { setIikoLoading(false) }
  }, [employeeId])

  useEffect(() => { const timeout = window.setTimeout(() => { void load() }, 0); return () => window.clearTimeout(timeout) }, [load])
  useEffect(() => {
    if (!allShiftsOpen) return
    let alive = true
    const timeout = window.setTimeout(() => {
      setShiftError('')
      getEmployeeIikoShiftPage(employeeId, shiftFrom, shiftTo, shiftOffset).then((page) => { if (alive) setShiftPage(page) }).catch(() => { if (alive) setShiftError('Не удалось загрузить смены') })
    }, 0)
    return () => { alive = false; window.clearTimeout(timeout) }
  }, [allShiftsOpen, employeeId, shiftFrom, shiftTo, shiftOffset])
  useEffect(() => {
    if (!isAdmin) return
    const timeout = window.setTimeout(() => { void loadIikoAdmin() }, 0)
    return () => window.clearTimeout(timeout)
  }, [loadIikoAdmin, isAdmin])
  useEffect(() => {
    if (!canReadShifts) return
    const timeout = window.setTimeout(() => { void loadShifts() }, 0)
    return () => window.clearTimeout(timeout)
  }, [loadShifts, canReadShifts])
  useEffect(() => {
    if (!employee?.photo_url) return
    let active = true; let objectUrl = ''
    getEmployeeAvatar(employeeId).then((blob) => {
      if (!active) return
      objectUrl = URL.createObjectURL(blob); setAvatarUrl(objectUrl)
    }).catch(() => { if (active && employee.photo_url !== 'employee-avatar') setAvatarUrl(employee.photo_url ?? '') })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [employee?.photo_url, employeeId])
  const visibleAvatarUrl = employee?.photo_url ? avatarUrl : ''
  const usersById = useMemo(() => new Map(users.map((item) => [item.id, item])), [users])
  const candidates = useMemo(() => availableHumanUsers(users, employees, employeeId), [users, employees, employeeId])
  const linkedUser = employee?.linked_user_id ? usersById.get(employee.linked_user_id) ?? (actorEmployeeId === employeeId && currentUser?.id === employee.linked_user_id ? currentUser : undefined) : undefined
  const activeRoles = employee?.role_assignments.filter((item) => activeAt(item.valid_from, item.valid_to)) ?? []
  const activeDepartments = employee?.department_assignments.filter((item) => activeAt(item.valid_from, item.valid_to)) ?? []
  const networkOnly = accessRoles.includes('NETWORK_MANAGER')
    && !accessRoles.includes('ADMIN') && !accessRoles.includes('DEPUTY_DIRECTOR')
  const primaryCategory = departments.find((item) => item.id === activeDepartments.find((assignment) => assignment.is_primary)?.department_id)?.business_type
  const roleChoices = networkOnly ? allowedRoles.filter((item) => (
    item === 'HANDYMAN' || (item === 'SELLER' && primaryCategory === 'RETAIL_POINT')
    || (item === 'DRIVER' && primaryCategory === 'AUTO')
  )) : allowedRoles
  const selectedRole = roleChoices.includes(role) ? role : roleChoices[0]
  const departmentChoices = assignableDepartments(
    departments, activeRoles.map((item) => item.role),
    networkOnly,
  )

  const mutationPending = useRef(false)

  async function mutation(action: () => Promise<unknown>, fallback: string) {
    if (mutationPending.current) return false
    mutationPending.current = true
    setBusy(true); setError('')
    try { await action(); setDialog(null); await load(); return true }
    catch (requestError) { setError(employeeErrorMessage(requestError, fallback)); return false }
    finally { mutationPending.current = false; setBusy(false) }
  }

  async function saveBasic(event: FormEvent) {
    event.preventDefault()
    if (!editReason.trim()) { setError('Укажите причину изменения'); return }
    await mutation(() => updateEmployee(employeeId, {
      full_name: fullName, birth_date: birthDate, phone, residence_address: address,
      reason: editReason.trim(),
    }), 'Не удалось сохранить основные данные')
    setEditing(false); setEditReason('')
  }

  async function addRole(event: FormEvent) {
    event.preventDefault()
    if (!roleReason.trim()) { setError('Укажите причину изменения'); return }
    if (!selectedRole || !roleFrom || Number.isNaN(new Date(roleFrom).getTime())) { setError('Выберите роль и корректную дату начала'); return }
    if (await mutation(() => assignEmployeeRole(employeeId, selectedRole, iso(roleFrom), roleReason.trim()), 'Не удалось назначить роль')) setRoleReason('')
  }

  async function addDepartment(event: FormEvent) {
    event.preventDefault()
    if (!departmentReason.trim()) { setError('Укажите причину изменения'); return }
    if (!departmentChoices.some((item) => item.id === departmentId)) {
      setError('Выберите подразделение допустимой категории')
      return
    }
    await mutation(() => assignEmployeeDepartment(employeeId, departmentId, isPrimary, iso(departmentFrom), departmentReason.trim()), 'Не удалось назначить подразделение')
    setDepartmentReason(''); setIsPrimary(false)
  }

  async function confirmDialog(reason: string, date: string) {
    if (!dialog) return
    if (dialog.kind === 'dismiss') return mutation(() => dismissEmployee(employeeId, date, reason), 'Не удалось уволить сотрудника')
    if (dialog.kind === 'reactivate') return mutation(() => reactivateEmployee(employeeId, date, reason), 'Не удалось восстановить сотрудника')
    if (dialog.kind === 'unlink') return mutation(() => unlinkEmployeeUser(employeeId, reason), 'Не удалось отвязать учётную запись')
    if (dialog.kind === 'link') return mutation(() => linkEmployeeUser(employeeId, Number(selectedUserId), reason), 'Не удалось связать учётную запись')
    if (dialog.kind === 'toggleAccess' && linkedUser) return mutation(() => updateUser(linkedUser.id, { is_active: !linkedUser.is_active, reason }), 'Не удалось изменить доступ')
    if (dialog.kind === 'resetPassword') {
      setBusy(true); setError('')
      try {
        setGeneratedCredentials(await resetEmployeePassword(employeeId, reason))
        setDialog(null)
      } catch (requestError) {
        setError(employeeErrorMessage(requestError, 'Не удалось сбросить пароль'))
      } finally { setBusy(false) }
      return
    }
    if (dialog.kind === 'endRole') return mutation(() => endEmployeeRole(employeeId, dialog.assignmentId!, iso(date), reason), 'Не удалось завершить назначение роли')
    return mutation(() => endEmployeeDepartment(employeeId, dialog.assignmentId!, iso(date), reason), 'Не удалось завершить назначение подразделения')
  }

  async function saveIikoLink(event: FormEvent) {
    event.preventDefault()
    if (!selectedIikoUserId || !iikoReason.trim()) { setIikoError('Выберите сотрудника iiko и укажите причину'); return }
    setIikoLoading(true); setIikoError('')
    try {
      if (iikoLink) await correctEmployeeIikoLink(employeeId, selectedIikoUserId, iikoReason.trim())
      else await createEmployeeIikoLink(employeeId, selectedIikoUserId, iikoReason.trim())
      setSelectedIikoUserId(''); setIikoReason(''); await loadIikoAdmin(false)
    } catch (requestError) { setIikoError(employeeErrorMessage(requestError, 'Не удалось сохранить связь с iiko')); setIikoLoading(false) }
  }

  async function refreshShifts() {
    setIikoLoading(true); setIikoError('')
    try { await refreshEmployeeIikoShifts(employeeId); await loadShifts() }
    catch (requestError) { setIikoError(employeeErrorMessage(requestError, 'Не удалось обновить смены iiko')); setIikoLoading(false) }
  }

  async function saveAvatar() {
    if (!avatarFile) { setError('Выберите фотографию'); return }
    await mutation(() => uploadEmployeeAvatar(employeeId, avatarFile), 'Не удалось загрузить фото')
    setAvatarFile(null)
  }

  async function removeAvatar() {
    await mutation(() => deleteEmployeeAvatar(employeeId), 'Не удалось удалить фото')
    setAvatarOpen(false)
  }

  async function createAccess() {
    if (!employee || !newUsername.trim()) { setError('Укажите логин'); return }
    setBusy(true); setError('')
    try {
      const created = await createUser({ username: newUsername.trim(), display_name: employee.full_name,
        is_admin: false, can_view_requests: false, account_type: 'HUMAN', employee_id: employee.id })
      if (!created.temporary_password) throw new Error('Пароль не создан')
      setGeneratedCredentials({ username: created.username, temporary_password: created.temporary_password })
      setNewUsername(''); setAccessDialog(null); await load()
    } catch (requestError) { setError(employeeErrorMessage(requestError, 'Не удалось создать доступ')) }
    finally { setBusy(false) }
  }

  if (loading) return <main className="app-page"><div className="page-shell"><p className="empty-state">Загружаем карточку сотрудника…</p></div></main>
  if (!employee) return <main className="app-page"><div className="page-shell"><p className="page-error">{error || 'Сотрудник не найден'}</p></div></main>

  const missingAssignments = employee.status === 'ACTIVE' && (activeRoles.length === 0 || !activeDepartments.some((item) => item.is_primary))
  return <main className="app-page employee-admin-page"><div className="page-shell">
    <div className="employee-detail-heading"><button className="secondary-action" type="button" onClick={() => navigate(canReadEmployees(accessRoles) ? '/employees' : '/dashboard')}>← Назад</button>
      <div><p className="eyebrow">КАРТОЧКА СОТРУДНИКА</p><h1>{employee.full_name}</h1></div>
    </div>
    {error && <p className="page-error" role="alert">{error}</p>}
    {employee.profile_level === 'FULL' && missingAssignments && <p className="employee-warning">Сотрудник активен, но ему ещё не назначены актуальные роль и основное подразделение.</p>}

    <section className="employee-card"><div className="employee-section-heading"><h2>Основное</h2>{canWrite && <button className="secondary-action" type="button" onClick={() => setEditing((value) => !value)}>{editing ? 'Отмена' : 'Редактировать'}</button>}</div>
      <div className="employee-profile-layout"><button className="employee-avatar-preview" type="button" aria-label="Открыть фотографию сотрудника" onClick={() => setAvatarOpen(true)}>
        {visibleAvatarUrl ? <img className="employee-avatar-image" src={visibleAvatarUrl} alt={`Фото ${employee.full_name}`} /> : <span className="employee-avatar-placeholder">{employee.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase()}</span>}
      </button>
      {editing ? <form className="employee-form-grid employee-profile-details" onSubmit={saveBasic}>
        <label><span>ФИО</span><input value={fullName} onChange={(e) => setFullName(e.target.value)} required /></label>
        <label><span>Дата рождения</span><input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} required /></label>
        <label><span>Телефон</span><input value={phone} onChange={(e) => setPhone(e.target.value)} required /></label>
        <label><span>Адрес</span><input value={address} onChange={(e) => setAddress(e.target.value)} required /></label>
        <label><span>Причина изменения</span><input value={editReason} onChange={(e) => setEditReason(e.target.value)} required /></label>
        <button className="primary-action" type="submit" disabled={busy}>Сохранить</button>
      </form> : <dl className="employee-facts employee-profile-details">{employee.profile_level === 'FULL' && <><div><dt>Статус</dt><dd>{employee.status === 'ACTIVE' ? 'Активен' : 'Уволен'}</dd></div><div><dt>Дата рождения</dt><dd>{formatDateOnly(employee.birth_date)}</dd></div></>}<div><dt>Телефон</dt><dd>{employee.phone}</dd></div>{employee.profile_level === 'FULL' && <><div><dt>Адрес</dt><dd>{employee.residence_address}</dd></div><div><dt>Дата увольнения</dt><dd>{formatDateOnly(employee.dismissal_date)}</dd></div><div><dt>Причина увольнения</dt><dd>{employee.dismissal_reason ?? '—'}</dd></div></>}</dl>}
      </div>
    </section>

    {(isAdmin || accessRoles.includes('DIRECTOR') || accessRoles.includes('DEPUTY_DIRECTOR') || canManageUser || actorEmployeeId === employee.id) && <section className="employee-card"><div className="employee-section-heading"><h2>Доступ в EOS</h2>{canManageUser && <button className="secondary-action" type="button" onClick={() => setAccessOpen(true)}>Изменить</button>}</div><div className="employee-access"><div><strong>{linkedUser ? `@${linkedUser.username}` : 'Нет доступа'}</strong><span>{linkedUser?.display_name ?? 'Учётная запись не привязана'}</span><span>{linkedUser ? (linkedUser.is_active ? 'Доступ активен' : 'Доступ заблокирован') : 'Доступ не настроен'}</span></div></div></section>}

    {canReadShifts && <section className="employee-card"><div className="employee-section-heading"><div><h2>Смены iiko</h2><p className="employee-help">Обновлено: {iikoShifts.length ? dateTimeLabel(iikoShifts.reduce((latest, item) => item.last_seen_at > latest ? item.last_seen_at : latest, iikoShifts[0].last_seen_at)) : 'данных пока нет'}</p></div><button className="secondary-action" type="button" onClick={() => { setShiftOffset(0); setAllShiftsOpen(true) }}>Все смены</button></div>
      {activeIikoShift ? <div className="employee-warning"><strong>Активная смена</strong><div>{activeIikoShift.department_id ? departmentName(departments, activeIikoShift.department_id) : 'Точка смены не определена'}</div><div>Открыта: {dateTimeLabel(activeIikoShift.opened_at)} · на момент обновления {durationLabel(Math.max(0, Math.floor((new Date(activeIikoShift.last_seen_at).getTime() - new Date(activeIikoShift.opened_at).getTime()) / 60_000)))}</div></div> : <p className="employee-help">Активной личной смены нет.</p>}
      <div className="employee-history">{iikoShifts.slice(0, 3).map((item) => <article key={item.id}><div><strong>{item.status === 'OPEN' ? 'Открыта' : 'Закрыта'} · {item.department_id ? departmentName(departments, item.department_id) : 'Точка смены не определена'}</strong><span>{dateTimeLabel(item.opened_at)} — {dateTimeLabel(item.closed_at)}</span><span>{item.duration_minutes == null ? 'Смена продолжается' : durationLabel(item.duration_minutes)}</span>{!item.department_mapping_resolved && item.iiko_department_id && <span className="field-error">Подразделение iiko не сопоставлено</span>}</div></article>)}</div>
    </section>}

    <section className="employee-card"><div className="employee-section-heading"><h2>Рабочие настройки</h2>{employee.profile_level === 'FULL' && <button className="secondary-action" type="button" onClick={() => setSettingsOpen(true)}>Изменить</button>}</div><dl className="employee-facts"><div><dt>Роль</dt><dd>{employee.profile_level === 'BASIC' ? employee.roles?.map((item) => ROLE_LABELS[item]).join(', ') || '—' : activeRoles.map((item) => ROLE_LABELS[item.role]).join(', ') || '—'}</dd></div><div><dt>Подразделение</dt><dd>{employee.profile_level === 'BASIC' ? employee.department_ids?.map((id) => departmentName(departments, id)).join(', ') || '—' : activeDepartments.filter((item) => item.is_primary).map((item) => departmentName(departments, item.department_id)).join(', ') || '—'}</dd></div><div><dt>iiko</dt><dd>{iikoLink?.iiko_display_name ?? 'Не указано'}</dd></div></dl></section>
    {canLifecycle && <section className="employee-card"><h2>Управление сотрудником</h2>{employee.status === 'ACTIVE' ? <button className="danger-action" type="button" onClick={() => setDialog({ kind: 'dismiss' })}>Уволить сотрудника</button> : <button className="primary-action" type="button" onClick={() => setDialog({ kind: 'reactivate' })}>Восстановить сотрудника</button>}</section>}
  </div>
  {accessOpen && <EosDialog title="Доступ в EOS" onClose={() => setAccessOpen(false)}>
    {(isAdmin || accessRoles.includes('DIRECTOR') || accessRoles.includes('DEPUTY_DIRECTOR') || canManageUser) && <section className="employee-card"><h2>Доступ в EOS</h2>
      {linkedUser ? <div className="employee-access"><div><strong>@{linkedUser.username}</strong><span>{linkedUser.display_name}</span><span>{linkedUser.is_active ? 'Доступ активен' : 'Доступ заблокирован'}</span></div>{canManageUser && <div className="user-actions"><button className="secondary-action" type="button" disabled={busy} onClick={() => setDialog({ kind: 'resetPassword' })}>Сбросить пароль</button><button className="secondary-action" type="button" disabled={busy || linkedUser.id === currentUser?.id} onClick={() => setDialog({ kind: 'toggleAccess' })}>{linkedUser.is_active ? 'Заблокировать' : 'Разблокировать'}</button><button className="secondary-action" type="button" disabled={busy} onClick={() => setDialog({ kind: 'unlink' })}>Отвязать User</button></div>}</div>
        : <div className="employee-access"><div><strong>Нет доступа</strong><span>Employee существует без учётной записи</span></div>{canManageUser && <div className="user-actions"><button className="primary-action" type="button" onClick={() => setAccessDialog('create')}>Создать доступ</button><button className="secondary-action" type="button" onClick={() => setAccessDialog('link')}>Привязать существующий User</button></div>}</div>}
      {generatedCredentials && <GeneratedCredentialsPanel username={generatedCredentials.username} temporaryPassword={generatedCredentials.temporary_password} onClose={() => setGeneratedCredentials(null)} />}
    </section>}

  </EosDialog>}
  {settingsOpen && <EosDialog title="Рабочие настройки" onClose={() => setSettingsOpen(false)} className="employee-settings-dialog">
    {error && <p className="page-error" role="alert">{error}</p>}
    <div className="employee-settings-tabs" role="tablist">{([['iiko', 'iiko'], ['roles', 'Роли'], ['departments', 'Подразделения'], ['history', 'История']] as const).map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={settingsTab === key} className={settingsTab === key ? 'secondary-action is-active' : 'secondary-action'} onClick={() => setSettingsTab(key)}>{label}</button>)}</div>
    {settingsTab === 'iiko' && <>
    {isAdmin && <section className="employee-card"><div className="employee-section-heading"><h2>Техническая связь iiko</h2><button className="secondary-action" type="button" disabled={iikoLoading} onClick={() => void loadIikoAdmin(true)}>Найти сотрудника iiko</button></div>
      {iikoError && <p className="page-error" role="alert">{iikoError}</p>}
      {iikoLink ? <dl className="employee-facts"><div><dt>Связанный сотрудник</dt><dd>{iikoLink.iiko_display_name}</dd></div><div><dt>iiko user ID</dt><dd>{iikoLink.iiko_user_id}</dd></div><div><dt>Статус</dt><dd><b className="badge badge-active">Активна</b></dd></div><div><dt>Создана</dt><dd>{dateTimeLabel(iikoLink.valid_from)}</dd></div></dl>
        : <p className="employee-help">Связь с сотрудником iiko ещё не подтверждена.</p>}
      {iikoCandidates.length > 0 && <form className="employee-assignment-form employee-iiko-form" onSubmit={saveIikoLink}><label><span>Кандидат iiko</span><EosSelect value={selectedIikoUserId} onChange={(event) => setSelectedIikoUserId(event.target.value)} required><option value="">Выберите сотрудника</option>{iikoCandidates.filter((item) => !item.is_deleted && item.iiko_user_id !== iikoLink?.iiko_user_id).map((item) => <option key={item.iiko_user_id} value={item.iiko_user_id}>{item.display_name}{item.code ? ` · ${item.code}` : ''}</option>)}</EosSelect></label><label><span>Причина изменения</span><input value={iikoReason} onChange={(event) => setIikoReason(event.target.value)} required /></label><button className={iikoLink ? 'danger-action' : 'primary-action'} type="submit" disabled={iikoLoading || !selectedIikoUserId}>{iikoLink ? 'Исправить связь с iiko' : 'Связать с iiko'}</button></form>}
      {iikoCandidates.length === 0 && !iikoLoading && !iikoError && <p className="employee-help">Кандидаты по ФИО не найдены. Это не мешает работе карточки Employee.</p>}
      {iikoHistory.length > 0 && <div className="employee-history"><h3>История связи</h3>{iikoHistory.map((item, index) => <article key={item.id}><div><strong>{item.iiko_display_name}</strong><span>{item.iiko_user_id}</span><span>{dateTimeLabel(item.valid_from)} — {dateTimeLabel(item.valid_to)}</span><span>Причина: {item.reason}</span>{item.ended_reason && <span>Причина исправления: {item.ended_reason}</span>}{item.valid_to && iikoHistory[index - 1] && <span>Исправлено на: {iikoHistory[index - 1].iiko_display_name} ({iikoHistory[index - 1].iiko_user_id})</span>}<span>Автор связи: User #{item.created_by_user_id}</span>{item.ended_by_user_id && <span>Исправил: User #{item.ended_by_user_id}</span>}</div></article>)}</div>}
    </section>}

      {isAdmin && <button className="secondary-action" type="button" disabled={iikoLoading || !iikoLink} onClick={() => void refreshShifts()}>{iikoLoading ? 'Обновляем…' : 'Обновить смены сейчас'}</button>}
    </>}
    {settingsTab === 'roles' && <>    {employee.profile_level === 'FULL' && <section className="employee-card"><h2>Роли</h2>
      {roleChoices.length > 0 && employee.status === 'ACTIVE' && <form className="employee-assignment-form employee-role-assignment-form" onSubmit={addRole}><label><span>Роль</span><EosSelect value={selectedRole} onChange={(e) => setRole(e.target.value as EmployeeRole)}>{roleChoices.map((item) => <option key={item} value={item}>{ROLE_LABELS[item]}</option>)}</EosSelect></label><label><span>Действует с</span><input type="datetime-local" value={roleFrom} onChange={(e) => setRoleFrom(e.target.value)} required /></label><label><span>Причина изменения</span><input value={roleReason} onChange={(e) => setRoleReason(e.target.value)} required /></label><button type="submit" className="primary-action" disabled={busy}>Назначить роль</button></form>}
      <div className="employee-history">{[...employee.role_assignments].reverse().map((item) => <article key={item.id}><div><strong>{ROLE_LABELS[item.role]}</strong><span>{formatDateOnly(item.valid_from)} — {formatDateOnly(item.valid_to, 'по настоящее время')}</span><span>Причина: {item.reason}</span>{item.ended_reason && <span>Причина завершения: {item.ended_reason}</span>}</div>{canWrite && allowedRoles.includes(item.role) && activeAt(item.valid_from, item.valid_to) && <button className="secondary-action" type="button" onClick={() => setDialog({ kind: 'endRole', assignmentId: item.id })}>Завершить</button>}</article>)}</div>
    </section>}

</>}
    {settingsTab === 'departments' && <>    {employee.profile_level === 'FULL' && <section className="employee-card"><h2>Подразделения</h2>
      {canWrite && employee.status === 'ACTIVE' && <form className="employee-assignment-form employee-department-assignment-form" onSubmit={addDepartment}><label><span>Подразделение</span><EosSelect value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} required><option value="">Выберите</option>{departmentChoices.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</EosSelect></label><label><span>Действует с</span><input type="datetime-local" value={departmentFrom} onChange={(e) => setDepartmentFrom(e.target.value)} required /></label><EosCheckbox className="employee-primary-checkbox" label="Основное" checked={isPrimary} onChange={(e) => setIsPrimary(e.target.checked)} /><label className="employee-assignment-reason"><span>Причина изменения</span><input value={departmentReason} onChange={(e) => setDepartmentReason(e.target.value)} required /></label><button className="primary-action" disabled={busy}>Назначить подразделение</button></form>}
      <p className="employee-help">Чтобы сменить основное подразделение, сначала завершите текущее назначение.</p>
      <div className="employee-history">{[...employee.department_assignments].reverse().map((item) => <article key={item.id}><div><strong>{departmentName(departments, item.department_id)} {item.is_primary && <b className="badge">Основное</b>}</strong><span>{formatDateOnly(item.valid_from)} — {formatDateOnly(item.valid_to, 'по настоящее время')}</span><span>Причина: {item.reason}</span>{item.ended_reason && <span>Причина завершения: {item.ended_reason}</span>}</div>{canWrite && activeAt(item.valid_from, item.valid_to) && <button className="secondary-action" type="button" onClick={() => setDialog({ kind: 'endDepartment', assignmentId: item.id })}>Завершить</button>}</article>)}</div>
    </section>}

</>}
    {settingsTab === 'history' && <>    {employee.profile_level === 'FULL' && <section className="employee-card"><h2>История жизненного цикла</h2><div className="employee-history">{[...employee.lifecycle_events].reverse().map((item) => <article key={item.id}><div><strong>{({ CREATED: 'Создан', UPDATED: 'Данные изменены', DISMISSED: 'Уволен', REACTIVATED: 'Восстановлен', USER_LINKED: 'User связан', USER_UNLINKED: 'User отвязан' } as const)[item.event_type]}</strong><span>{formatDateOnly(item.effective_date)}</span><span>{item.reason}</span></div></article>)}</div></section>}
</>}
  </EosDialog>}
  {allShiftsOpen && <EosDialog title="Все смены iiko" onClose={() => setAllShiftsOpen(false)} className="employee-settings-dialog"><div className="employee-shift-filters"><label className="eos-field"><span>С даты</span><input type="date" value={shiftFrom} onChange={(event) => { setShiftFrom(event.target.value); setShiftOffset(0) }} /></label><label className="eos-field"><span>По дату</span><input type="date" value={shiftTo} onChange={(event) => { setShiftTo(event.target.value); setShiftOffset(0) }} /></label></div>
    {shiftError && <p className="page-error">{shiftError}</p>}
    <div className="employee-history">{shiftPage?.items.map((item) => <article key={item.id}><div><strong>{item.status === 'OPEN' ? 'Открыта' : 'Закрыта'} · {item.department_id ? departmentName(departments, item.department_id) : 'Точка смены не определена'}</strong><span>{dateTimeLabel(item.opened_at)} — {dateTimeLabel(item.closed_at)}</span><span>{item.duration_minutes == null ? 'Смена продолжается' : durationLabel(item.duration_minutes)}</span>{!item.department_mapping_resolved && item.iiko_department_id && <span className="field-error">Подразделение iiko не сопоставлено</span>}</div></article>)}</div>
    {shiftPage && <div className="user-actions"><button className="secondary-action" type="button" disabled={shiftOffset === 0} onClick={() => setShiftOffset(Math.max(0, shiftOffset - 10))}>Назад</button><span>{shiftPage.total ? `${shiftOffset + 1}–${Math.min(shiftOffset + 10, shiftPage.total)} из ${shiftPage.total}` : 'Смен нет'}</span><button className="secondary-action" type="button" disabled={shiftOffset + 10 >= shiftPage.total} onClick={() => setShiftOffset(shiftOffset + 10)}>Далее</button></div>}
  </EosDialog>}
  {avatarOpen && <EosDialog title="Фотография сотрудника" className="employee-avatar-dialog" onClose={() => { if (!busy) { setAvatarOpen(false); setAvatarFile(null) } }}>
    <div className="employee-avatar-dialog-preview">{visibleAvatarUrl ? <img src={visibleAvatarUrl} alt={`Фото ${employee.full_name}`} /> : <span className="employee-avatar-placeholder">{employee.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase()}</span>}</div>
    {(canWrite || actorEmployeeId === employee.id) && <div className="employee-avatar-dialog-actions"><label className="secondary-action employee-avatar-picker">{employee.photo_url ? 'Изменить' : 'Загрузить фото'}<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setAvatarFile(event.target.files?.[0] ?? null)} /></label>{employee.photo_url && <button className="danger-action" type="button" disabled={busy} onClick={() => void removeAvatar()}>Удалить</button>}</div>}
    {avatarFile && <div className="employee-avatar-file"><span>{avatarFile.name}</span><button className="primary-action" type="button" disabled={busy} onClick={() => void saveAvatar()}>Сохранить фото</button></div>}
  </EosDialog>}
  {accessDialog === 'create' && <EosDialog title="Создать доступ в EOS" onClose={() => { if (!busy) setAccessDialog(null) }}>
    <label><span>Логин</span><input value={newUsername} minLength={3} maxLength={64} placeholder="ivanov.ii" onChange={(event) => setNewUsername(event.target.value)} autoFocus /></label>
    <label><span>Имя</span><input value={employee.full_name} disabled /></label>
    <div className="user-actions"><button className="primary-action" type="button" disabled={!newUsername.trim() || busy} onClick={() => void createAccess()}>{busy ? 'Создаём…' : 'Создать'}</button><button className="secondary-action" type="button" disabled={busy} onClick={() => setAccessDialog(null)}>Отмена</button></div>
  </EosDialog>}
  {accessDialog === 'link' && <EosDialog title="Привязать существующий User" onClose={() => setAccessDialog(null)}>
    <label><span>Учётная запись</span><EosSelect value={selectedUserId} onChange={(e) => setSelectedUserId(e.target.value)}><option value="">Выберите HUMAN User</option>{candidates.map((item) => <option key={item.id} value={item.id}>@{item.username} — {item.display_name}</option>)}</EosSelect></label>
    <div className="user-actions"><button className="primary-action" type="button" disabled={!selectedUserId || busy} onClick={() => { setAccessDialog(null); setDialog({ kind: 'link' }) }}>Продолжить</button><button className="secondary-action" type="button" onClick={() => setAccessDialog(null)}>Отмена</button></div>
  </EosDialog>}
  {dialog && <ReasonDialog reasonRequired={dialog.kind !== 'resetPassword'} title={({ dismiss: 'Уволить сотрудника', reactivate: 'Восстановить сотрудника', unlink: 'Отвязать User', link: 'Связать User', resetPassword: 'Сбросить пароль', toggleAccess: linkedUser?.is_active ? 'Заблокировать доступ' : 'Разблокировать доступ', endRole: 'Завершить назначение роли', endDepartment: 'Завершить назначение подразделения' } as const)[dialog.kind]} confirmLabel={({ dismiss: 'Уволить', reactivate: 'Восстановить', unlink: 'Отвязать', link: 'Связать', resetPassword: 'Сбросить пароль', toggleAccess: linkedUser?.is_active ? 'Заблокировать доступ' : 'Разблокировать доступ', endRole: 'Завершить', endDepartment: 'Завершить' } as const)[dialog.kind]} dateLabel={dialog.kind === 'dismiss' ? 'Дата увольнения' : dialog.kind === 'reactivate' ? 'Дата восстановления' : dialog.kind.startsWith('end') ? 'Действует до' : undefined} dateType={dialog.kind === 'dismiss' || dialog.kind === 'reactivate' ? 'date' : 'datetime-local'} busy={busy} onCancel={() => setDialog(null)} onConfirm={confirmDialog} />}
  </main>
}

export default EmployeeDetailPage
