import { getStoredToken } from './auth.ts'

export type SupplyStatus =
  | 'DRAFT' | 'SUBMITTED' | 'IN_REVIEW' | 'PLANNED'
  | 'PARTIALLY_FULFILLED' | 'FULFILLED' | 'CANCELLED'

export type SupplyUnit = {
  id: string
  code: string
  name_ru: string
  short_name_ru: string
  is_active: boolean
}

export type SupplyProduct = {
  id: string
  name: string
  is_active: boolean
  default_unit: SupplyUnit
  aliases: Array<{ id: string; alias: string; status: string }>
}

export type SupplyAllocation = {
  id: string
  action: 'TRANSFER' | 'PURCHASE' | 'CANCEL'
  planned_quantity: string
  unit_id: string
  comment: string | null
}

export type SupplyLine = {
  id: string
  position: number
  raw_text: string
  parsed_name: string | null
  parsed_quantity: string | null
  parsed_unit: SupplyUnit | null
  product: SupplyProduct | null
  requested_unit: SupplyUnit | null
  quantity: string | null
  match_status: string
  match_method: string | null
  duplicate_status: string
  allocations: SupplyAllocation[]
  planned_transfer: string
  planned_purchase: string
  planned_cancel: string
  planned_total: string
  unallocated_quantity: string
  planning_status: string
}

export type SupplyRequestSummary = {
  id: string
  public_number: string
  department: { id: string; code: string; name: string }
  direction: { id: string; code: string; name: string }
  cycle_id: string | null
  cycle: { id: string; cycle_date: string } | null
  status: SupplyStatus
  version: number
  submitted_at: string | null
  created_at: string
  public_author_name: string | null
  lines_total: number
  lines_matched: number
  lines_needs_review: number
  duplicate_groups: number
  planning_complete_lines: number
  planning_incomplete_lines: number
  total_unallocated_lines: number
  can_start_review: boolean
  can_plan: boolean
}

export type SupplyRequest = SupplyRequestSummary & {
  source_type: string
  raw_input: string
  updated_at: string
  planned_at: string | null
  cancelled_at: string | null
  cancellation_reason: string | null
  lines: SupplyLine[]
}

export type SupplyReference = { id: string; code: string; name: string }
export type SupplyCycle = { id: string; cycle_date: string; direction_id: string }

export class SupplyApiError extends Error {
  code: string | null
  currentVersion: number | null

  constructor(message: string, code: string | null, currentVersion: number | null) {
    super(message)
    this.code = code
    this.currentVersion = currentVersion
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken()
  if (!token) throw new SupplyApiError('Сессия не найдена', null, null)
  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)
  headers.set('Accept', 'application/json')
  if (options.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, { ...options, headers })
  if (!response.ok) {
    let detail: unknown
    try {
      const body = await response.json() as { detail?: unknown }
      detail = body.detail
    } catch {
      detail = null
    }
    const payload = typeof detail === 'object' && detail !== null
      ? detail as { code?: string; current_version?: number }
      : null
    throw new SupplyApiError(
      'Не удалось выполнить действие',
      payload?.code ?? null,
      payload?.current_version ?? null,
    )
  }
  return response.json() as Promise<T>
}

export function getSupplyRequests(query: URLSearchParams): Promise<SupplyRequestSummary[]> {
  return request(`/supply/requests?${query.toString()}`, { cache: 'no-store' })
}

export function getSupplyDepartments(): Promise<SupplyReference[]> {
  return request('/supply/departments')
}

export function getSupplyDirections(): Promise<SupplyReference[]> {
  return request('/supply/request-directions')
}

export function getSupplyCycles(): Promise<{ items: SupplyCycle[] }> {
  return request('/supply/request-cycles?limit=100&offset=0')
}

export function getSupplyRequest(id: string): Promise<SupplyRequest> {
  return request(`/supply/requests/${id}`)
}

export function getSupplyProducts(search = ''): Promise<{ items: SupplyProduct[] }> {
  const query = new URLSearchParams({ active: 'true', limit: '100' })
  if (search) query.set('search', search)
  return request(`/supply/products?${query}`)
}

export function disableSupplyAlias(
  productId: string, aliasId: string,
): Promise<{ id: string; status: string }> {
  return request(`/supply/products/${productId}/aliases/${aliasId}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: 'DISABLED' }),
  })
}

export function matchSupplyLine(
  requestId: string,
  lineId: string,
  input: {
    expected_version: number
    product_id: string
    unit_id: string
    quantity: string
    save_alias: boolean
  },
): Promise<SupplyLine> {
  return request(`/supply/requests/${requestId}/lines/${lineId}/match`, {
    method: 'POST',
    body: JSON.stringify({ ...input, action: 'MATCH' }),
  })
}

export function saveSupplyAllocations(
  requestId: string,
  lineId: string,
  expectedVersion: number,
  values: { transfer: string; purchase: string; cancel: string; comment: string },
  unitId: string,
): Promise<SupplyRequest> {
  const allocations = ([
    ['TRANSFER', values.transfer],
    ['PURCHASE', values.purchase],
    ['CANCEL', values.cancel],
  ] as const)
    .filter(([, quantity]) => Number(quantity) > 0)
    .map(([action, planned_quantity]) => ({
      action, planned_quantity, unit_id: unitId,
      comment: values.comment.trim() || null,
    }))
  return request(`/supply/requests/${requestId}/lines/${lineId}/allocations`, {
    method: 'PUT',
    body: JSON.stringify({ expected_version: expectedVersion, allocations }),
  })
}

export function planSupplyRequest(id: string, version: number): Promise<SupplyRequest> {
  return request(`/supply/requests/${id}/plan`, {
    method: 'POST',
    body: JSON.stringify({ expected_version: version }),
  })
}

export function cancelSupplyRequest(
  id: string, version: number, reason: string,
): Promise<SupplyRequest> {
  return request(`/supply/requests/${id}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ expected_version: version, reason }),
  })
}
