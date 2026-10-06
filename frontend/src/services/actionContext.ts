import { getStoredToken } from './auth'

export type EmployeeRole =
  | 'ADMIN' | 'DIRECTOR' | 'DEPUTY_DIRECTOR' | 'ACCOUNTANT'
  | 'SUPPLY_MANAGER' | 'DRIVER' | 'HANDYMAN' | 'NETWORK_MANAGER'
  | 'CHEF_CONFECTIONER' | 'CONFECTIONER' | 'BAKER'
  | 'HEAD_OF_PRODUCTION' | 'SELLER'

export type ActionContext = {
  user_id: number
  employee_id: string
  roles: EmployeeRole[]
  authorized_as: EmployeeRole | null
  primary_department_id: string | null
  actual_department_id: string | null
  shift_id: string | null
  shift_opened_at: string | null
  substitution_confirmed: boolean
  determined_at: string
}

type ActionErrorDetail = {
  code?: string
  message?: string
  shift_id?: string
  primary_department_name?: string
  actual_department_name?: string
}

export class BusinessActionError extends Error {
  code: string
  detail: ActionErrorDetail

  constructor(detail: ActionErrorDetail) {
    super(detail.message || 'Не удалось выполнить действие')
    this.code = detail.code || 'BUSINESS_ACTION_FAILED'
    this.detail = detail
  }
}

async function actionRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken()
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, { ...options, headers, cache: 'no-store' })
  if (!response.ok) {
    let detail: ActionErrorDetail = {}
    try {
      detail = ((await response.json()) as { detail?: ActionErrorDetail }).detail ?? {}
    } catch {
      // Unexpected backend bodies are not exposed to the user.
    }
    throw new BusinessActionError(detail)
  }
  return response.json() as Promise<T>
}

export function getActionContext(): Promise<ActionContext> {
  return actionRequest('/auth/action-context')
}

export function confirmShiftSubstitution(shiftId: string): Promise<ActionContext> {
  return actionRequest('/auth/action-context/shift-substitution-confirmation', {
    method: 'POST',
    body: JSON.stringify({ shift_id: shiftId }),
  })
}

export type CreatedEmployeeSupplyRequest = {
  id: string
  public_number: string
  status: string
  department: { id: string; name: string }
}

export function createEmployeeSupplyRequest(input: {
  department_id: string
  direction_id: string
  cycle_id: string
  need_date: string | null
  multiline_text: string
}): Promise<CreatedEmployeeSupplyRequest> {
  return actionRequest('/supply/requests', {
    method: 'POST',
    body: JSON.stringify({
      department_id: input.department_id,
      direction_id: input.direction_id,
      cycle_id: input.cycle_id,
      need_date: input.need_date,
      raw_input: input.multiline_text,
      lines: input.multiline_text
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((raw_text) => ({ raw_text })),
    }),
  })
}

export type SellerRequest = {
  id: string
  status: string
  version: number
  raw_input: string
}

export type SellerWindow = {
  is_open: boolean
  can_write: boolean
  department_label: string
  allowed_actions: string[]
  closes_at: string | null
  need_date: string | null
  cycle_id: string | null
  department: { id: string; name: string } | null
  allowed_departments: { id: string; name: string }[]
  supported_units: string[]
  request: SellerRequest | null
  reason: string | null
}

export function getSellerWindow(departmentId?: string): Promise<SellerWindow> {
  const query = departmentId ? `?department_id=${encodeURIComponent(departmentId)}` : ''
  return actionRequest(`/supply/seller/window${query}`, { cache: 'no-store' })
}

export function saveSellerRequest(input: {
  department_id?: string
  raw_input: string
  expected_version?: number
}): Promise<SellerRequest> {
  return actionRequest('/supply/seller/request', {
    method: 'PUT', body: JSON.stringify(input),
  })
}

export function confirmSellerRequest(input: {
  department_id?: string
  expected_version: number
}): Promise<SellerRequest> {
  return actionRequest('/supply/seller/request/confirm', {
    method: 'POST', body: JSON.stringify(input),
  })
}
