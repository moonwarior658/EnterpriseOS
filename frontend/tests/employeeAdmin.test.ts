import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  assignEmployeeDepartment, assignEmployeeRole, createEmployee, dismissEmployee,
  correctEmployeeIikoLink, createEmployeeIikoLink, EmployeeApiError,
  findEmployeeIikoCandidates, getEmployeeActiveIikoShift, getEmployeeIikoLink,
  getEmployeeIikoLinkHistory, getEmployeeIikoShifts, getEmployees,
  linkEmployeeUser, reactivateEmployee, refreshEmployeeIikoShifts,
  type Employee,
} from '../src/services/employees.ts'
import {
  availableHumanUsers, employeeErrorMessage, filterEmployees,
} from '../src/pages/employeeAdminLogic.ts'
import type { UserRecord } from '../src/services/users.ts'

const EMPLOYEE: Employee = {
  id: 'employee-1', full_name: 'Иванов Иван Иванович', birth_date: '1990-01-01',
  photo_url: null, phone: '+7 900 000-00-00', residence_address: 'Екатеринбург',
  status: 'ACTIVE', dismissal_date: null, dismissal_reason: null, linked_user_id: null,
  created_at: '2026-09-28T10:00:00Z', updated_at: '2026-09-28T10:00:00Z',
  role_assignments: [{ id: 'r1', role: 'SELLER', valid_from: '2026-09-28T10:00:00Z', valid_to: null, reason: 'Приём', ended_reason: null }],
  department_assignments: [{ id: 'd1', department_id: 'dep-1', is_primary: true, valid_from: '2026-09-28T10:00:00Z', valid_to: null, reason: 'Приём', ended_reason: null }],
  lifecycle_events: [],
}

const USER = (changes: Partial<UserRecord> = {}): UserRecord => ({
  id: 1, username: 'ivanov.ii', display_name: 'Иванов И.И.', avatar_url: null,
  is_active: true, is_admin: false, can_view_requests: false, account_type: 'HUMAN',
  blocked_by_employee_dismissal: false, created_at: '2026-09-28T10:00:00Z', ...changes,
})

test('ADMIN route и navigation entry защищены, delete Employee отсутствует', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8')
  const list = readFileSync(new URL('../src/pages/EmployeesPage.tsx', import.meta.url), 'utf8')
  const detail = readFileSync(new URL('../src/pages/EmployeeDetailPage.tsx', import.meta.url), 'utf8')
  assert.match(app, /path="\/employees" element={<ProtectedRoute adminOnly>/)
  assert.match(app, /path="\/employees\/:employeeId" element={<ProtectedRoute adminOnly>/)
  assert.match(layout, /\{user\?\.is_admin && \([\s\S]*?to="\/employees"/)
  assert.match(layout, /Сотрудники/)
  assert.doesNotMatch(`${list}\n${detail}`, /Удалить сотрудника|deleteEmployee/)
})

test('реестр показывает Employee, фильтрует ФИО, статус, роль и primary department', () => {
  assert.deepEqual(filterEmployees([EMPLOYEE], 'иванов', 'ACTIVE', 'dep-1', 'SELLER'), [EMPLOYEE])
  assert.deepEqual(filterEmployees([EMPLOYEE], 'петров', 'ALL', '', ''), [])
  assert.deepEqual(filterEmployees([EMPLOYEE], '', 'DISMISSED', '', ''), [])
})

test('Employee без User поддерживается, SERVICE и уже связанный User не предлагаются', () => {
  const occupied = { ...EMPLOYEE, id: 'employee-2', linked_user_id: 2 }
  const candidates = availableHumanUsers([
    USER(), USER({ id: 2, username: 'busy' }), USER({ id: 3, username: 'service', account_type: 'SERVICE' }),
  ], [EMPLOYEE, occupied])
  assert.equal(EMPLOYEE.linked_user_id, null)
  assert.deepEqual(candidates.map((item) => item.id), [1])
})

test('API client покрывает создание, несколько ролей, primary, User link, увольнение и реактивацию', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: { getItem: () => 'token' } })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify(EMPLOYEE), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    await getEmployees()
    await createEmployee({ full_name: EMPLOYEE.full_name, birth_date: EMPLOYEE.birth_date, photo_url: null, phone: EMPLOYEE.phone, residence_address: EMPLOYEE.residence_address, reason: 'Приём' })
    await assignEmployeeRole(EMPLOYEE.id, 'SELLER', '2026-09-28T10:00:00Z', 'Приём')
    await assignEmployeeRole(EMPLOYEE.id, 'SUPPLY_MANAGER', '2026-09-28T10:00:00Z', 'Совмещение')
    await assignEmployeeDepartment(EMPLOYEE.id, 'dep-1', true, '2026-09-28T10:00:00Z', 'Приём')
    await linkEmployeeUser(EMPLOYEE.id, 1, 'Выдан доступ')
    await dismissEmployee(EMPLOYEE.id, '2026-09-28', 'Увольнение')
    await reactivateEmployee(EMPLOYEE.id, '2026-09-29', 'Повторный приём')
  } finally { globalThis.fetch = originalFetch }
  assert.equal(calls[0].url, '/api/employees')
  assert.equal(calls[1].options.method, 'POST')
  assert.match(calls[2].url, /\/roles$/)
  assert.match(calls[3].url, /\/roles$/)
  assert.deepEqual(JSON.parse(String(calls[4].options.body)), { department_id: 'dep-1', is_primary: true, valid_from: '2026-09-28T10:00:00Z', reason: 'Приём' })
  assert.match(calls[5].url, /\/user$/)
  assert.match(calls[6].url, /\/dismiss$/)
  assert.match(calls[7].url, /\/reactivate$/)
})

test('reason обязателен в формах, User conflict переводится без raw JSON', () => {
  const list = readFileSync(new URL('../src/pages/EmployeesPage.tsx', import.meta.url), 'utf8')
  const detail = readFileSync(new URL('../src/pages/EmployeeDetailPage.tsx', import.meta.url), 'utf8')
  assert.match(list, /Причина изменения/)
  assert.match(detail, /if \(!reason\.trim\(\)\)/)
  assert.equal(employeeErrorMessage(
    new EmployeeApiError('User is already linked to another employee', 409), 'fallback',
  ), 'Эта учётная запись уже связана с другим сотрудником')
  assert.equal(employeeErrorMessage(new EmployeeApiError('[{"secret":"raw"}]', 422), 'fallback'), 'Проверьте заполнение полей и укажите содержательную причину изменения')
})

test('карточка и API client покрывают iiko identity, correction и personal shifts', async () => {
  const detail = readFileSync(new URL('../src/pages/EmployeeDetailPage.tsx', import.meta.url), 'utf8')
  assert.match(detail, /Исправить связь с iiko/)
  assert.match(detail, /Подразделение iiko не сопоставлено/)
  assert.match(detail, /Активная смена/)
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: { getItem: () => 'token' } })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    const url = String(input)
    const payload = url.endsWith('/candidates') || url.endsWith('/history') || url.endsWith('/shifts') ? [] : null
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    await findEmployeeIikoCandidates(EMPLOYEE.id)
    await getEmployeeIikoLink(EMPLOYEE.id)
    await getEmployeeIikoLinkHistory(EMPLOYEE.id)
    await createEmployeeIikoLink(EMPLOYEE.id, 'iiko-1', 'Подтверждение')
    await correctEmployeeIikoLink(EMPLOYEE.id, 'iiko-2', 'Исправление')
    await getEmployeeIikoShifts(EMPLOYEE.id)
    await getEmployeeActiveIikoShift(EMPLOYEE.id)
    await refreshEmployeeIikoShifts(EMPLOYEE.id)
  } finally { globalThis.fetch = originalFetch }
  assert.match(calls[0].url, /\/iiko\/candidates$/)
  assert.match(calls[3].url, /\/iiko\/link$/)
  assert.deepEqual(JSON.parse(String(calls[4].options.body)), { iiko_user_id: 'iiko-2', reason: 'Исправление' })
  assert.match(calls[7].url, /\/iiko\/shifts\/refresh$/)
})
