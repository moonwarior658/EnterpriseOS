import type { Employee, EmployeeRole, Department } from '../services/employees.ts'
import { EmployeeApiError } from '../services/employees.ts'
import type { UserRecord } from '../services/users.ts'

export const ROLE_LABELS: Record<EmployeeRole, string> = {
  ADMIN: 'Администратор', DIRECTOR: 'Директор', DEPUTY_DIRECTOR: 'Заместитель директора',
  ACCOUNTANT: 'Бухгалтер', SUPPLY_MANAGER: 'Менеджер снабжения', DRIVER: 'Водитель',
  HANDYMAN: 'Разнорабочий', NETWORK_MANAGER: 'Управляющий сетью',
  CHEF_CONFECTIONER: 'Шеф-кондитер', CONFECTIONER: 'Кондитер', BAKER: 'Пекарь',
  HEAD_OF_PRODUCTION: 'Заведующий производством', SELLER: 'Продавец',
}

export const activeAt = (validFrom: string, validTo: string | null, now = Date.now()) =>
  new Date(validFrom).getTime() <= now && (validTo === null || new Date(validTo).getTime() > now)

export function availableHumanUsers(users: UserRecord[], employees: Employee[], currentId?: string) {
  const occupied = new Set(employees.filter((item) => item.id !== currentId).map((item) => item.linked_user_id))
  return users.filter((user) => user.account_type === 'HUMAN' && !occupied.has(user.id))
}

export function filterEmployees(
  employees: Employee[], query: string, status: 'ALL' | Employee['status'],
  departmentId: string, role: '' | EmployeeRole,
) {
  const needle = query.trim().toLocaleLowerCase('ru')
  return employees.filter((employee) => {
    if (status !== 'ALL' && employee.status !== status) return false
    if (needle && !employee.full_name.toLocaleLowerCase('ru').includes(needle)) return false
    if (departmentId && !employee.department_assignments.some(
      (item) => item.department_id === departmentId && activeAt(item.valid_from, item.valid_to),
    )) return false
    if (role && !employee.role_assignments.some(
      (item) => item.role === role && activeAt(item.valid_from, item.valid_to),
    )) return false
    return true
  })
}

const KNOWN_ERRORS: Record<string, string> = {
  'User is already linked to another employee': 'Эта учётная запись уже связана с другим сотрудником',
  'Service account cannot be linked to an employee': 'Сервисную учётную запись нельзя связать с сотрудником',
  'Role assignment overlaps an existing assignment': 'Эта роль уже назначена на выбранный период',
  'Employee already has an active assignment for this department': 'Это подразделение уже назначено сотруднику',
  'Employee already has an active primary department': 'У сотрудника уже есть основное подразделение',
  'Employee is already dismissed': 'Сотрудник уже уволен',
  'Employee is already active': 'Сотрудник уже активен',
  'Assignments cannot be changed for a dismissed employee': 'Назначения уволенного сотрудника менять нельзя',
}

export function employeeErrorMessage(error: unknown, fallback: string) {
  if (!(error instanceof EmployeeApiError)) return fallback
  if (error.status === 403) return 'Недостаточно прав для этого действия'
  if (error.status === 422) return 'Проверьте заполнение полей и укажите содержательную причину изменения'
  if (error.status === 409 && error.message.startsWith('iiko employee is already linked to ')) {
    return `Этот сотрудник iiko уже связан: ${error.message.slice('iiko employee is already linked to '.length)}`
  }
  if (error.status === 409) return KNOWN_ERRORS[error.message] ?? 'Изменение конфликтует с текущим состоянием сотрудника'
  if (error.status === 404) return 'Сотрудник или связанная запись не найдены'
  return fallback
}

export function departmentName(departments: Department[], id: string) {
  const department = departments.find((item) => item.id === id)
  return department ? department.name : 'Подразделение недоступно'
}
