import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { EosSelect } from '../components/EosFormControls'
import { GeneratedCredentialsPanel } from '../components/GeneratedCredentialsPanel'
import {
  EMPLOYEE_ROLES, assignEmployeeDepartment, assignEmployeeRole, dismissEmployee,
  correctEmployeeIikoLink, createEmployeeIikoLink, findEmployeeIikoCandidates,
  endEmployeeDepartment, endEmployeeRole, getEmployee, getEmployeeDepartments,
  getEmployeeActiveIikoShift, getEmployeeIikoLink, getEmployeeIikoLinkHistory,
  getEmployeeIikoShifts, getEmployees, linkEmployeeUser, reactivateEmployee,
  refreshEmployeeIikoShifts, unlinkEmployeeUser, updateEmployee, type Department,
  type Employee, type EmployeeIikoShift, type EmployeeRole,
  type IikoEmployeeCandidate, type IikoEmployeeLink,
} from '../services/employees'
import {
  getUsers, resetEmployeePassword, type GeneratedCredentials, type UserRecord,
} from '../services/users'
import {
  ROLE_LABELS, activeAt, availableHumanUsers, departmentName, employeeErrorMessage,
} from './employeeAdminLogic'

const localDateTime = () => {
  const now = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000)
  return now.toISOString().slice(0, 16)
}
const today = () => new Date().toISOString().slice(0, 10)
const iso = (value: string) => new Date(value).toISOString()
const dateTimeLabel = (value: string | null) => value
  ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : 'по настоящее время'
const durationLabel = (minutes: number) => `${Math.floor(minutes / 60)} ч ${minutes % 60} мин`

type ReasonDialogProps = {
  title: string
  dateLabel?: string
  dateType?: 'date' | 'datetime-local'
  initialDate?: string
  confirmLabel: string
  busy: boolean
  onCancel: () => void
  onConfirm: (reason: string, date: string) => Promise<void>
}

function ReasonDialog({ title, dateLabel, dateType = 'datetime-local', initialDate, confirmLabel, busy, onCancel, onConfirm }: ReasonDialogProps) {
  const [reason, setReason] = useState('')
  const [date, setDate] = useState(initialDate ?? (dateType === 'date' ? today() : localDateTime()))
  const [validation, setValidation] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!reason.trim()) { setValidation('Укажите причину изменения'); return }
    await onConfirm(reason.trim(), date)
  }
  return <div className="employee-dialog-backdrop" role="presentation">
    <form className="employee-dialog" role="dialog" aria-modal="true" aria-labelledby="reason-dialog-title" onSubmit={submit}>
      <h2 id="reason-dialog-title">{title}</h2>
      {dateLabel && <label><span>{dateLabel}</span><input type={dateType} value={date} onChange={(event) => setDate(event.target.value)} required /></label>}
      <label><span>Причина изменения</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} autoFocus required /></label>
      {validation && <p className="field-error">{validation}</p>}
      <div className="user-actions"><button className="primary-action" type="submit" disabled={busy}>{busy ? 'Выполняем…' : confirmLabel}</button><button className="secondary-action" type="button" disabled={busy} onClick={onCancel}>Отмена</button></div>
    </form>
  </div>
}

function EmployeeDetailPage() {
  const navigate = useNavigate()
  const { employeeId = '' } = useParams()
  const [employee, setEmployee] = useState<Employee | null>(null)
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
  const [photoUrl, setPhotoUrl] = useState('')
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
  const [dialog, setDialog] = useState<null | { kind: 'dismiss' | 'reactivate' | 'unlink' | 'link' | 'resetPassword' | 'endRole' | 'endDepartment'; assignmentId?: string }>(null)
  const [generatedCredentials, setGeneratedCredentials] = useState<GeneratedCredentials | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const [item, allEmployees, departmentItems, userItems] = await Promise.all([
        getEmployee(employeeId), getEmployees(), getEmployeeDepartments(), getUsers(),
      ])
      setEmployee(item); setEmployees(allEmployees); setDepartments(departmentItems); setUsers(userItems)
      setFullName(item.full_name); setBirthDate(item.birth_date); setPhone(item.phone)
      setAddress(item.residence_address); setPhotoUrl(item.photo_url ?? '')
    } catch (requestError) { setError(employeeErrorMessage(requestError, 'Не удалось загрузить карточку сотрудника')) }
    finally { setLoading(false) }
  }, [employeeId])

  const loadIiko = useCallback(async (searchCandidates = false) => {
    setIikoLoading(true); setIikoError('')
    try {
      const [link, history, shifts, active] = await Promise.all([
        getEmployeeIikoLink(employeeId), getEmployeeIikoLinkHistory(employeeId),
        getEmployeeIikoShifts(employeeId), getEmployeeActiveIikoShift(employeeId),
      ])
      setIikoLink(link); setIikoHistory(history); setIikoShifts(shifts); setActiveIikoShift(active)
      if (searchCandidates || !link) setIikoCandidates(await findEmployeeIikoCandidates(employeeId))
    } catch (requestError) {
      setIikoError(employeeErrorMessage(requestError, 'Не удалось загрузить данные iiko'))
    } finally { setIikoLoading(false) }
  }, [employeeId])

  useEffect(() => {
    let cancelled = false
    Promise.all([getEmployee(employeeId), getEmployees(), getEmployeeDepartments(), getUsers()])
      .then(([item, allEmployees, departmentItems, userItems]) => {
        if (cancelled) return
        setEmployee(item); setEmployees(allEmployees); setDepartments(departmentItems); setUsers(userItems)
        setFullName(item.full_name); setBirthDate(item.birth_date); setPhone(item.phone)
        setAddress(item.residence_address); setPhotoUrl(item.photo_url ?? '')
      })
      .catch((requestError) => {
        if (!cancelled) setError(employeeErrorMessage(requestError, 'Не удалось загрузить карточку сотрудника'))
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [employeeId])
  useEffect(() => {
    const timeout = window.setTimeout(() => { void loadIiko() }, 0)
    return () => window.clearTimeout(timeout)
  }, [loadIiko])
  const usersById = useMemo(() => new Map(users.map((item) => [item.id, item])), [users])
  const candidates = useMemo(() => availableHumanUsers(users, employees, employeeId), [users, employees, employeeId])
  const linkedUser = employee?.linked_user_id ? usersById.get(employee.linked_user_id) : undefined
  const activeRoles = employee?.role_assignments.filter((item) => activeAt(item.valid_from, item.valid_to)) ?? []
  const activeDepartments = employee?.department_assignments.filter((item) => activeAt(item.valid_from, item.valid_to)) ?? []

  async function mutation(action: () => Promise<unknown>, fallback: string) {
    setBusy(true); setError('')
    try { await action(); setDialog(null); await load() }
    catch (requestError) { setError(employeeErrorMessage(requestError, fallback)) }
    finally { setBusy(false) }
  }

  async function saveBasic(event: FormEvent) {
    event.preventDefault()
    if (!editReason.trim()) { setError('Укажите причину изменения'); return }
    await mutation(() => updateEmployee(employeeId, {
      full_name: fullName, birth_date: birthDate, phone, residence_address: address,
      photo_url: photoUrl.trim() || null, reason: editReason.trim(),
    }), 'Не удалось сохранить основные данные')
    setEditing(false); setEditReason('')
  }

  async function addRole(event: FormEvent) {
    event.preventDefault()
    if (!roleReason.trim()) { setError('Укажите причину изменения'); return }
    await mutation(() => assignEmployeeRole(employeeId, role, iso(roleFrom), roleReason.trim()), 'Не удалось назначить роль')
    setRoleReason('')
  }

  async function addDepartment(event: FormEvent) {
    event.preventDefault()
    if (!departmentReason.trim()) { setError('Укажите причину изменения'); return }
    await mutation(() => assignEmployeeDepartment(employeeId, departmentId, isPrimary, iso(departmentFrom), departmentReason.trim()), 'Не удалось назначить подразделение')
    setDepartmentReason(''); setIsPrimary(false)
  }

  async function confirmDialog(reason: string, date: string) {
    if (!dialog) return
    if (dialog.kind === 'dismiss') return mutation(() => dismissEmployee(employeeId, date, reason), 'Не удалось уволить сотрудника')
    if (dialog.kind === 'reactivate') return mutation(() => reactivateEmployee(employeeId, date, reason), 'Не удалось восстановить сотрудника')
    if (dialog.kind === 'unlink') return mutation(() => unlinkEmployeeUser(employeeId, reason), 'Не удалось отвязать учётную запись')
    if (dialog.kind === 'link') return mutation(() => linkEmployeeUser(employeeId, Number(selectedUserId), reason), 'Не удалось связать учётную запись')
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
      setSelectedIikoUserId(''); setIikoReason(''); await loadIiko(false)
    } catch (requestError) { setIikoError(employeeErrorMessage(requestError, 'Не удалось сохранить связь с iiko')); setIikoLoading(false) }
  }

  async function refreshShifts() {
    setIikoLoading(true); setIikoError('')
    try { await refreshEmployeeIikoShifts(employeeId); await loadIiko(false) }
    catch (requestError) { setIikoError(employeeErrorMessage(requestError, 'Не удалось обновить смены iiko')); setIikoLoading(false) }
  }

  if (loading) return <main className="app-page"><div className="page-shell"><p className="empty-state">Загружаем карточку сотрудника…</p></div></main>
  if (!employee) return <main className="app-page"><div className="page-shell"><p className="page-error">{error || 'Сотрудник не найден'}</p></div></main>

  const missingAssignments = employee.status === 'ACTIVE' && (activeRoles.length === 0 || !activeDepartments.some((item) => item.is_primary))
  return <main className="app-page employee-admin-page"><div className="page-shell">
    <div className="employee-detail-heading"><button className="secondary-action" type="button" onClick={() => navigate('/employees')}>← Сотрудники</button>
      <div><p className="eyebrow">КАРТОЧКА СОТРУДНИКА</p><h1>{employee.full_name}</h1></div>
      {employee.status === 'ACTIVE'
        ? <button className="danger-action" type="button" onClick={() => setDialog({ kind: 'dismiss' })}>Уволить сотрудника</button>
        : <button className="primary-action" type="button" onClick={() => setDialog({ kind: 'reactivate' })}>Восстановить сотрудника</button>}
    </div>
    {error && <p className="page-error" role="alert">{error}</p>}
    {missingAssignments && <p className="employee-warning">Сотрудник активен, но ему ещё не назначены актуальные роль и основное подразделение.</p>}

    <section className="employee-card"><div className="employee-section-heading"><h2>Основное</h2><button className="secondary-action" type="button" onClick={() => setEditing((value) => !value)}>{editing ? 'Отмена' : 'Редактировать'}</button></div>
      {editing ? <form className="employee-form-grid" onSubmit={saveBasic}>
        <label><span>ФИО</span><input value={fullName} onChange={(e) => setFullName(e.target.value)} required /></label>
        <label><span>Дата рождения</span><input type="date" value={birthDate} onChange={(e) => setBirthDate(e.target.value)} required /></label>
        <label><span>Телефон</span><input value={phone} onChange={(e) => setPhone(e.target.value)} required /></label>
        <label><span>Адрес</span><input value={address} onChange={(e) => setAddress(e.target.value)} required /></label>
        <label><span>Ссылка на фото</span><input type="url" value={photoUrl} onChange={(e) => setPhotoUrl(e.target.value)} /></label>
        <label><span>Причина изменения</span><input value={editReason} onChange={(e) => setEditReason(e.target.value)} required /></label>
        <button className="primary-action" type="submit" disabled={busy}>Сохранить</button>
      </form> : <dl className="employee-facts"><div><dt>Статус</dt><dd>{employee.status === 'ACTIVE' ? 'Активен' : 'Уволен'}</dd></div><div><dt>Дата рождения</dt><dd>{employee.birth_date}</dd></div><div><dt>Телефон</dt><dd>{employee.phone}</dd></div><div><dt>Адрес</dt><dd>{employee.residence_address}</dd></div><div><dt>Дата увольнения</dt><dd>{employee.dismissal_date ?? '—'}</dd></div><div><dt>Причина увольнения</dt><dd>{employee.dismissal_reason ?? '—'}</dd></div></dl>}
    </section>

    <section className="employee-card"><h2>Доступ в EOS</h2>
      {linkedUser ? <div className="employee-access"><div><strong>@{linkedUser.username}</strong><span>{linkedUser.display_name}</span><span>{linkedUser.is_active ? 'Доступ активен' : 'Доступ заблокирован'}</span></div><div className="user-actions"><button className="secondary-action" type="button" disabled={busy} onClick={() => setDialog({ kind: 'resetPassword' })}>Сбросить пароль</button><button className="secondary-action" type="button" disabled={busy} onClick={() => setDialog({ kind: 'unlink' })}>Отвязать User</button></div></div>
        : <div className="employee-access"><div><strong>Нет доступа</strong><span>Employee существует без учётной записи</span></div><div className="user-actions"><EosSelect value={selectedUserId} onChange={(e) => setSelectedUserId(e.target.value)}><option value="">Выберите HUMAN User</option>{candidates.map((item) => <option key={item.id} value={item.id}>@{item.username} — {item.display_name}</option>)}</EosSelect><button className="primary-action" type="button" disabled={!selectedUserId || busy} onClick={() => setDialog({ kind: 'link' })}>Связать</button></div></div>}
      {generatedCredentials && <GeneratedCredentialsPanel username={generatedCredentials.username} temporaryPassword={generatedCredentials.temporary_password} onClose={() => setGeneratedCredentials(null)} />}
    </section>

    <section className="employee-card"><div className="employee-section-heading"><h2>iiko</h2><button className="secondary-action" type="button" disabled={iikoLoading} onClick={() => void loadIiko(true)}>Найти сотрудника iiko</button></div>
      {iikoError && <p className="page-error" role="alert">{iikoError}</p>}
      {iikoLink ? <dl className="employee-facts"><div><dt>Связанный сотрудник</dt><dd>{iikoLink.iiko_display_name}</dd></div><div><dt>iiko user ID</dt><dd>{iikoLink.iiko_user_id}</dd></div><div><dt>Статус</dt><dd><b className="badge badge-active">Активна</b></dd></div><div><dt>Создана</dt><dd>{dateTimeLabel(iikoLink.valid_from)}</dd></div></dl>
        : <p className="employee-help">Связь с сотрудником iiko ещё не подтверждена.</p>}
      {iikoCandidates.length > 0 && <form className="employee-assignment-form employee-iiko-form" onSubmit={saveIikoLink}><label><span>Кандидат iiko</span><EosSelect value={selectedIikoUserId} onChange={(event) => setSelectedIikoUserId(event.target.value)} required><option value="">Выберите сотрудника</option>{iikoCandidates.filter((item) => !item.is_deleted && item.iiko_user_id !== iikoLink?.iiko_user_id).map((item) => <option key={item.iiko_user_id} value={item.iiko_user_id}>{item.display_name}{item.code ? ` · ${item.code}` : ''}</option>)}</EosSelect></label><label><span>Причина изменения</span><input value={iikoReason} onChange={(event) => setIikoReason(event.target.value)} required /></label><button className={iikoLink ? 'danger-action' : 'primary-action'} type="submit" disabled={iikoLoading || !selectedIikoUserId}>{iikoLink ? 'Исправить связь с iiko' : 'Связать с iiko'}</button></form>}
      {iikoCandidates.length === 0 && !iikoLoading && <p className="employee-help">Кандидаты по ФИО не найдены. Это не мешает работе карточки Employee.</p>}
      {iikoHistory.length > 0 && <div className="employee-history"><h3>История связи</h3>{iikoHistory.map((item, index) => <article key={item.id}><div><strong>{item.iiko_display_name}</strong><span>{item.iiko_user_id}</span><span>{dateTimeLabel(item.valid_from)} — {dateTimeLabel(item.valid_to)}</span><span>Причина: {item.reason}</span>{item.ended_reason && <span>Причина исправления: {item.ended_reason}</span>}{item.valid_to && iikoHistory[index - 1] && <span>Исправлено на: {iikoHistory[index - 1].iiko_display_name} ({iikoHistory[index - 1].iiko_user_id})</span>}<span>Автор связи: User #{item.created_by_user_id}</span>{item.ended_by_user_id && <span>Исправил: User #{item.ended_by_user_id}</span>}</div></article>)}</div>}
    </section>

    <section className="employee-card"><div className="employee-section-heading"><h2>Смены iiko</h2><button className="secondary-action" type="button" disabled={iikoLoading || !iikoLink} onClick={() => void refreshShifts()}>{iikoLoading ? 'Обновляем…' : 'Обновить смены'}</button></div>
      {activeIikoShift ? <div className="employee-warning"><strong>Активная смена</strong><div>{activeIikoShift.department_id ? departmentName(departments, activeIikoShift.department_id) : 'Подразделение iiko не сопоставлено'}</div><div>Открыта: {dateTimeLabel(activeIikoShift.opened_at)} · на момент обновления {durationLabel(Math.max(0, Math.floor((new Date(activeIikoShift.last_seen_at).getTime() - new Date(activeIikoShift.opened_at).getTime()) / 60_000)))}</div></div> : <p className="employee-help">Активной личной смены нет.</p>}
      <div className="employee-history">{iikoShifts.map((item) => <article key={item.id}><div><strong>{item.status === 'OPEN' ? 'Открыта' : 'Закрыта'} · {item.department_id ? departmentName(departments, item.department_id) : 'Подразделение не сопоставлено'}</strong><span>{dateTimeLabel(item.opened_at)} — {dateTimeLabel(item.closed_at)}</span><span>{item.duration_minutes == null ? 'Смена продолжается' : durationLabel(item.duration_minutes)}</span>{!item.department_mapping_resolved && item.iiko_department_id && <span className="field-error">Подразделение iiko не сопоставлено</span>}</div></article>)}</div>
    </section>

    <section className="employee-card"><h2>Роли</h2>
      {employee.status === 'ACTIVE' && <form className="employee-assignment-form" onSubmit={addRole}><label><span>Роль</span><EosSelect value={role} onChange={(e) => setRole(e.target.value as EmployeeRole)}>{EMPLOYEE_ROLES.map((item) => <option key={item} value={item}>{ROLE_LABELS[item]}</option>)}</EosSelect></label><label><span>Действует с</span><input type="datetime-local" value={roleFrom} onChange={(e) => setRoleFrom(e.target.value)} required /></label><label><span>Причина изменения</span><input value={roleReason} onChange={(e) => setRoleReason(e.target.value)} required /></label><button className="primary-action" disabled={busy}>Назначить роль</button></form>}
      <div className="employee-history">{[...employee.role_assignments].reverse().map((item) => <article key={item.id}><div><strong>{ROLE_LABELS[item.role]}</strong><span>{dateTimeLabel(item.valid_from)} — {dateTimeLabel(item.valid_to)}</span><span>Причина: {item.reason}</span>{item.ended_reason && <span>Причина завершения: {item.ended_reason}</span>}</div>{activeAt(item.valid_from, item.valid_to) && <button className="secondary-action" type="button" onClick={() => setDialog({ kind: 'endRole', assignmentId: item.id })}>Завершить</button>}</article>)}</div>
    </section>

    <section className="employee-card"><h2>Подразделения</h2>
      {employee.status === 'ACTIVE' && <form className="employee-assignment-form" onSubmit={addDepartment}><label><span>Подразделение</span><EosSelect value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} required><option value="">Выберите</option>{departments.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</EosSelect></label><label><span>Действует с</span><input type="datetime-local" value={departmentFrom} onChange={(e) => setDepartmentFrom(e.target.value)} required /></label><label className="employee-check"><input type="checkbox" checked={isPrimary} onChange={(e) => setIsPrimary(e.target.checked)} /> Основное</label><label><span>Причина изменения</span><input value={departmentReason} onChange={(e) => setDepartmentReason(e.target.value)} required /></label><button className="primary-action" disabled={busy}>Назначить подразделение</button></form>}
      <p className="employee-help">Чтобы сменить основное подразделение, завершите текущее назначение и создайте новое как основное. Backend не поддерживает отдельную атомарную операцию смены primary.</p>
      <div className="employee-history">{[...employee.department_assignments].reverse().map((item) => <article key={item.id}><div><strong>{departmentName(departments, item.department_id)} {item.is_primary && <b className="badge">Основное</b>}</strong><span>{dateTimeLabel(item.valid_from)} — {dateTimeLabel(item.valid_to)}</span><span>Причина: {item.reason}</span>{item.ended_reason && <span>Причина завершения: {item.ended_reason}</span>}</div>{activeAt(item.valid_from, item.valid_to) && <button className="secondary-action" type="button" onClick={() => setDialog({ kind: 'endDepartment', assignmentId: item.id })}>Завершить</button>}</article>)}</div>
    </section>

    <section className="employee-card"><h2>История жизненного цикла</h2><div className="employee-history">{[...employee.lifecycle_events].reverse().map((item) => <article key={item.id}><div><strong>{({ CREATED: 'Создан', UPDATED: 'Данные изменены', DISMISSED: 'Уволен', REACTIVATED: 'Восстановлен', USER_LINKED: 'User связан', USER_UNLINKED: 'User отвязан' } as const)[item.event_type]}</strong><span>{item.effective_date}</span><span>{item.reason}</span></div></article>)}</div></section>
  </div>
  {dialog && <ReasonDialog title={({ dismiss: 'Уволить сотрудника', reactivate: 'Восстановить сотрудника', unlink: 'Отвязать User', link: 'Связать User', resetPassword: 'Сбросить пароль', endRole: 'Завершить назначение роли', endDepartment: 'Завершить назначение подразделения' } as const)[dialog.kind]} confirmLabel={({ dismiss: 'Уволить', reactivate: 'Восстановить', unlink: 'Отвязать', link: 'Связать', resetPassword: 'Сбросить пароль', endRole: 'Завершить', endDepartment: 'Завершить' } as const)[dialog.kind]} dateLabel={dialog.kind === 'dismiss' ? 'Дата увольнения' : dialog.kind === 'reactivate' ? 'Дата восстановления' : dialog.kind.startsWith('end') ? 'Действует до' : undefined} dateType={dialog.kind === 'dismiss' || dialog.kind === 'reactivate' ? 'date' : 'datetime-local'} busy={busy} onCancel={() => setDialog(null)} onConfirm={confirmDialog} />}
  </main>
}

export default EmployeeDetailPage
