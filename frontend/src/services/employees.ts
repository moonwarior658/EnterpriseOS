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
  profile_level: 'FULL' | 'BASIC'
  roles?: EmployeeRole[]
  department_ids?: string[]
  id: string
  full_name: string
  birth_date: string
  photo_url: string | null
  phone: string
  residence_address: string
  status: EmployeeStatus | null
  dismissal_date: string | null
  dismissal_reason: string | null
  linked_user_id: number | null
  allowed_actions: string[]
  created_at: string
  updated_at: string
  role_assignments: RoleAssignment[]
  department_assignments: DepartmentAssignment[]
  lifecycle_events: LifecycleEvent[]
}

type BasicEmployee = Pick<Employee, 'id' | 'full_name' | 'photo_url' | 'phone'> & {
  profile_level: 'BASIC'
  roles: EmployeeRole[]
  department_ids: string[]
}

function employeeView(item: Employee | BasicEmployee): Employee {
  if (item.profile_level !== 'BASIC') return item as Employee
  return {
    ...item, birth_date: '', status: null, residence_address: '', dismissal_date: null, dismissal_reason: null,
    linked_user_id: null, allowed_actions: [], created_at: '', updated_at: '',
    role_assignments: [], department_assignments: [], lifecycle_events: [],
  }
}

export type Department = {
  id: string
  code: string
  name: string
  business_type: 'RETAIL_POINT' | 'PRODUCTION' | 'AUTO' | null
  is_active: boolean
}

export type EmployeeBootstrapStatus = {
  available: boolean
  username: string
  unavailable_reason: string | null
}

export type IikoEmployeeCandidate = {
  iiko_user_id: string
  display_name: string
  code: string | null
  birth_date: string | null
  is_deleted: boolean
}

export type IikoEmployeeLink = {
  id: string
  employee_id: string
  iiko_user_id: string
  iiko_display_name: string
  iiko_birth_date: string | null
  valid_from: string
  valid_to: string | null
  reason: string
  created_by_user_id: number
  ended_reason: string | null
  ended_by_user_id: number | null
  created_at: string
  updated_at: string
}

export type EmployeeIikoShift = {
  id: string
  employee_id: string
  iiko_user_id: string
  external_shift_id: string | null
  iiko_department_id: string | null
  department_id: string | null
  opened_at: string
  closed_at: string | null
  duration_minutes: number | null
  source: 'IIKO'
  status: 'OPEN' | 'CLOSED'
  first_seen_at: string
  last_seen_at: string
  department_mapping_resolved: boolean
}

export type EmployeeIikoSyncResult = {
  received: number
  matched: number
  created: number
  updated: number
  unchanged: number
  unresolved_department: number
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

async function employeeBinaryRequest(path: string, options: RequestInit = {}): Promise<Response> {
  const token = getStoredToken()
  if (!token) throw new EmployeeApiError('Сессия не найдена', 401)
  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)
  headers.set('Accept', 'application/json')
  const response = await fetch(`/api${path}`, { ...options, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new EmployeeApiError(typeof body?.detail === 'string' ? body.detail : '', response.status)
  }
  return response
}

export const getEmployees = (status?: EmployeeStatus) =>
  employeeRequest<(Employee | BasicEmployee)[]>(`/employees${status ? `?status=${status}` : ''}`)
    .then((items) => items.map(employeeView))
export const getEmployeeBootstrapStatus = () =>
  employeeRequest<EmployeeBootstrapStatus>('/employees/bootstrap')
export const bootstrapFirstAdmin = (input: {
  full_name: string; birth_date: string; photo_url: string | null; phone: string;
  residence_address: string; department_id: string; reason: string
}) => employeeRequest<Employee>('/employees/bootstrap', {
  method: 'POST', body: JSON.stringify(input),
})
export const getEmployee = (id: string) => employeeRequest<Employee | BasicEmployee>(`/employees/${id}`).then(employeeView)
export const getEmployeeDepartments = () => employeeRequest<Department[]>('/employees/departments')
export const createEmployee = (input: {
  full_name: string; birth_date: string; photo_url: string | null; phone: string;
  residence_address: string; reason: string; department_id?: string
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
export const findEmployeeIikoCandidates = (id: string) =>
  employeeRequest<IikoEmployeeCandidate[]>(`/employees/${id}/iiko/candidates`)
export const getEmployeeIikoLink = (id: string) =>
  employeeRequest<IikoEmployeeLink | null>(`/employees/${id}/iiko/link`)
export const getEmployeeIikoLinkHistory = (id: string) =>
  employeeRequest<IikoEmployeeLink[]>(`/employees/${id}/iiko/link/history`)
export const createEmployeeIikoLink = (id: string, iikoUserId: string, reason: string) =>
  employeeRequest<IikoEmployeeLink>(`/employees/${id}/iiko/link`, {
    method: 'POST', body: JSON.stringify({ iiko_user_id: iikoUserId, reason }),
  })
export const correctEmployeeIikoLink = (id: string, iikoUserId: string, reason: string) =>
  employeeRequest<IikoEmployeeLink>(`/employees/${id}/iiko/link/correct`, {
    method: 'POST', body: JSON.stringify({ iiko_user_id: iikoUserId, reason }),
  })
export const getEmployeeIikoShifts = (id: string, limit = 3) =>
  employeeRequest<EmployeeIikoShift[]>(`/employees/${id}/iiko/shifts?limit=${limit}`)
export type EmployeeIikoShiftPage = { items: EmployeeIikoShift[]; total: number; offset: number; limit: number }
export const getEmployeeIikoShiftPage = (id: string, dateFrom: string, dateTo: string, offset: number) => {
  const params = new URLSearchParams({ limit: '10', offset: String(offset) })
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  return employeeRequest<EmployeeIikoShiftPage>(`/employees/${id}/iiko/shifts/page?${params}`)
}
export const getEmployeeActiveIikoShift = (id: string) =>
  employeeRequest<EmployeeIikoShift | null>(`/employees/${id}/iiko/shifts/active`)
export const refreshEmployeeIikoShifts = (id: string) =>
  employeeRequest<EmployeeIikoSyncResult>(`/employees/${id}/iiko/shifts/refresh`, { method: 'POST' })
export const getEmployeeAvatar = (id: string) =>
  employeeBinaryRequest(`/employees/${id}/avatar`).then((response) => response.blob())
export const uploadEmployeeAvatar = (id: string, photo: File, reason?: string) => {
  const body = new FormData(); body.append('photo', photo)
  if (reason?.trim()) body.append('reason', reason.trim())
  return employeeBinaryRequest(`/employees/${id}/avatar`, { method: 'POST', body })
    .then((response) => response.json() as Promise<Employee>)
}
export const deleteEmployeeAvatar = (id: string, reason?: string) =>
  employeeBinaryRequest(`/employees/${id}/avatar${reason?.trim() ? `?reason=${encodeURIComponent(reason.trim())}` : ''}`, { method: 'DELETE' })
    .then((response) => response.json() as Promise<Employee>)
