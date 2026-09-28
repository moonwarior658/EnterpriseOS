import { getStoredToken } from './auth.ts'

export const EMPLOYEE_ROLES = [
  'ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'ACCOUNTANT', 'SUPPLY_MANAGER',
  'DRIVER', 'HANDYMAN', 'NETWORK_MANAGER', 'CHEF_CONFECTIONER',
  'CONFECTIONER', 'BAKER', 'HEAD_OF_PRODUCTION', 'SELLER',
] as const

export type EmployeeRole = typeof EMPLOYEE_ROLES[number]
export type EmployeeStatus = 'ACTIVE' | 'DISMISSED'

export type RoleAssignment = {
  id: string
  role: EmployeeRole
  valid_from: string
  valid_to: string | null
  reason: string
  ended_reason: string | null
}

export type DepartmentAssignment = {
  id: string
  department_id: string
  is_primary: boolean
  valid_from: string
  valid_to: string | null
  reason: string
  ended_reason: string | null
}

export type LifecycleEvent = {
  id: string
  event_type: 'CREATED' | 'UPDATED' | 'DISMISSED' | 'REACTIVATED' | 'USER_LINKED' | 'USER_UNLINKED'
  effective_date: string
  reason: string
  created_at: string
}

export type Employee = {
  id: string
  full_name: string
  birth_date: string
  photo_url: string | null
  phone: string
  residence_address: string
  status: EmployeeStatus
  dismissal_date: string | null
  dismissal_reason: string | null
  linked_user_id: number | null
  created_at: string
  updated_at: string
  role_assignments: RoleAssignment[]
  department_assignments: DepartmentAssignment[]
  lifecycle_events: LifecycleEvent[]
}

export type Department = {
  id: string
  code: string
  name: string
  is_active: boolean
}

export class EmployeeApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function employeeRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken()
  if (!token) throw new EmployeeApiError('Сессия не найдена', 401)
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : ''
    throw new EmployeeApiError(detail, response.status)
  }
  return response.json() as Promise<T>
}

export const getEmployees = (status?: EmployeeStatus) =>
  employeeRequest<Employee[]>(`/employees${status ? `?status=${status}` : ''}`)
export const getEmployee = (id: string) => employeeRequest<Employee>(`/employees/${id}`)
export const getEmployeeDepartments = () => employeeRequest<Department[]>('/supply/departments')
export const createEmployee = (input: {
  full_name: string; birth_date: string; photo_url: string | null; phone: string;
  residence_address: string; reason: string
}) => employeeRequest<Employee>('/employees', { method: 'POST', body: JSON.stringify(input) })
export const updateEmployee = (id: string, input: Partial<{
  full_name: string; birth_date: string; photo_url: string | null; phone: string;
  residence_address: string
}> & { reason: string }) => employeeRequest<Employee>(`/employees/${id}`, {
  method: 'PATCH', body: JSON.stringify(input),
})
export const assignEmployeeRole = (id: string, role: EmployeeRole, validFrom: string, reason: string) =>
  employeeRequest<RoleAssignment>(`/employees/${id}/roles`, {
    method: 'POST', body: JSON.stringify({ role, valid_from: validFrom, reason }),
  })
export const endEmployeeRole = (id: string, assignmentId: string, validTo: string, reason: string) =>
  employeeRequest<RoleAssignment>(`/employees/${id}/roles/${assignmentId}/end`, {
    method: 'POST', body: JSON.stringify({ valid_to: validTo, reason }),
  })
export const assignEmployeeDepartment = (
  id: string, departmentId: string, isPrimary: boolean, validFrom: string, reason: string,
) => employeeRequest<DepartmentAssignment>(`/employees/${id}/departments`, {
  method: 'POST', body: JSON.stringify({
    department_id: departmentId, is_primary: isPrimary, valid_from: validFrom, reason,
  }),
})
export const endEmployeeDepartment = (
  id: string, assignmentId: string, validTo: string, reason: string,
) => employeeRequest<DepartmentAssignment>(`/employees/${id}/departments/${assignmentId}/end`, {
  method: 'POST', body: JSON.stringify({ valid_to: validTo, reason }),
})
export const linkEmployeeUser = (id: string, userId: number, reason: string) =>
  employeeRequest<Employee>(`/employees/${id}/user`, {
    method: 'POST', body: JSON.stringify({ user_id: userId, reason }),
  })
export const unlinkEmployeeUser = (id: string, reason: string) =>
  employeeRequest<Employee>(`/employees/${id}/user/unlink`, {
    method: 'POST', body: JSON.stringify({ reason }),
  })
export const dismissEmployee = (id: string, dismissalDate: string, reason: string) =>
  employeeRequest<Employee>(`/employees/${id}/dismiss`, {
    method: 'POST', body: JSON.stringify({ dismissal_date: dismissalDate, reason }),
  })
export const reactivateEmployee = (id: string, effectiveDate: string, reason: string) =>
  employeeRequest<Employee>(`/employees/${id}/reactivate`, {
    method: 'POST', body: JSON.stringify({ effective_date: effectiveDate, reason }),
  })
