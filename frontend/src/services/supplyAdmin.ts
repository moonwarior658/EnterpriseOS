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
  fulfilled_quantity: string
  fulfilled_at: string | null
  fulfillment_comment: string | null
}

export type SupplyLine = {
  id: string
  position: number
  raw_text: string
  working_name: string
  parsed_name: string | null
  parsed_quantity: string | null
  parsed_unit: SupplyUnit | null
  product: SupplyProduct | null
  product_id: string | null
  requested_unit: SupplyUnit | null
  quantity: string | null
  send_quantity: string | null
  match_status: string
  match_method: string | null
  duplicate_status: string
  allocations: SupplyAllocation[]
  planned_transfer: string
  planned_purchase: string
  planned_cancel: string
  planned_total: string
  fulfilled_transfer: string
  fulfilled_purchase: string
  fulfilled_total: string
  unresolved_quantity: string
  active_debt_id: string | null
  active_debt_quantity: string
  debt_inclusion_status:
    | 'NONE' | 'COVERED_BY_REQUEST' | 'REQUEST_BELOW_DEBT' | 'CONFIRMED_PARTIAL'
  debt_quantity_included: string
  requires_debt_confirmation: boolean
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
  fulfilled_at: string | null
  cancellation_reason: string | null
  lines: SupplyLine[]
}

export type SupplyDebtEvent = {
  id: string
  event_type: string
  quantity_delta: string
  quantity_before: string
  quantity_after: string
  request_id: string | null
  comment: string | null
  created_at: string
}

export type SupplyDebt = {
  id: string
  department: SupplyReference
  product: SupplyProduct | null
  working_name: string
  unit: SupplyUnit
  outstanding_quantity: string
  original_quantity: string
  status: 'ACTIVE' | 'CLOSED' | 'CANCELLED'
  version: number
  first_request_id: string
  latest_request_id: string
  opened_at: string
  updated_at: string
  cycle_count: number
  severity: 'YELLOW' | 'PURPLE' | 'RED' | 'CRITICAL'
  close_comment: string | null
  cancel_comment: string | null
  events: SupplyDebtEvent[]
}

export type SupplyDashboardSummary = {
  new_requests: number
  mapping_required: number
  requests_in_progress: number
  active_debts: number
  critical_debts: number
}

export type SupplyReference = { id: string; code: string; name: string }
export type SupplyDirection = SupplyReference & { is_active: boolean }
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

function withFreshRequest(query: URLSearchParams): URLSearchParams {
  const fresh = new URLSearchParams(query)
  fresh.set('_ts', `${Date.now()}-${Math.random()}`)
  return fresh
}

export function getSupplyRequests(
  query: URLSearchParams,
  signal?: AbortSignal,
): Promise<SupplyRequestSummary[]> {
  return request(`/supply/requests?${withFreshRequest(query).toString()}`, {
    cache: 'no-store',
    signal,
  })
}

export function getSupplyDepartments(): Promise<SupplyReference[]> {
  return request('/supply/departments')
}

export function getSupplyDirections(): Promise<SupplyDirection[]> {
  return request('/supply/request-directions')
}

export function getSupplyCycles(): Promise<{ items: SupplyCycle[] }> {
  return request('/supply/request-cycles?limit=100&offset=0')
}

export function getSupplyRequest(
  id: string,
  signal?: AbortSignal,
): Promise<SupplyRequest> {
  const query = withFreshRequest(new URLSearchParams())
  return request(`/supply/requests/${id}?${query.toString()}`, {
    cache: 'no-store',
    signal,
  })
}

export function getSupplyProducts(
  search = '',
  signal?: AbortSignal,
): Promise<{ items: SupplyProduct[] }> {
  const query = new URLSearchParams({ active: 'true', limit: '100' })
  if (search) query.set('search', search)
  return request(`/supply/products?${query}`, { signal })
}

export function getSupplyUnits(signal?: AbortSignal): Promise<SupplyUnit[]> {
  return request('/supply/units', { signal })
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

export function saveSupplyLineWorkingValues(
  requestId: string,
  lineId: string,
  input: {
    request_version: number
    working_name: string
    requested_quantity: string | null
    send_quantity: string
    requested_unit_id: string
  },
): Promise<{ request_version: number; line: SupplyLine }> {
  return request(
    `/supply/requests/${requestId}/lines/${lineId}/working-values`,
    {
      method: 'PATCH',
      body: JSON.stringify(input),
    },
  )
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

export function planSupplyRequest(
  id: string,
  version: number,
  simpleMode = false,
): Promise<SupplyRequest> {
  return request(`/supply/requests/${id}/plan`, {
    method: 'POST',
    body: JSON.stringify({
      expected_version: version,
      simple_mode: simpleMode,
    }),
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

export function saveSupplyFulfillment(
  requestId: string,
  lineId: string,
  expectedVersion: number,
  items: Array<{
    allocation_id: string
    fulfilled_quantity: string
    comment: string | null
  }>,
): Promise<SupplyRequest> {
  return request(`/supply/requests/${requestId}/lines/${lineId}/fulfillment`, {
    method: 'PUT',
    body: JSON.stringify({ expected_version: expectedVersion, items }),
  })
}

export function fulfillSupplyAsPlanned(
  requestId: string, expectedVersion: number,
): Promise<SupplyRequest> {
  return request(`/supply/requests/${requestId}/fulfill-as-planned`, {
    method: 'POST',
    body: JSON.stringify({ expected_version: expectedVersion }),
  })
}

export function confirmSupplyDebtInclusion(
  requestId: string,
  lineId: string,
  expectedVersion: number,
  includedQuantity: string,
): Promise<SupplyRequest> {
  return request(
    `/supply/requests/${requestId}/lines/${lineId}/confirm-debt-inclusion`,
    {
      method: 'POST',
      body: JSON.stringify({
        expected_version: expectedVersion,
        included_quantity: includedQuantity,
      }),
    },
  )
}

export function getSupplyDebts(
  query: URLSearchParams,
  signal?: AbortSignal,
): Promise<{
  items: SupplyDebt[]
  total: number
  limit: number
  offset: number
}> {
  return request(`/supply/debts?${withFreshRequest(query).toString()}`, {
    cache: 'no-store',
    signal,
  })
}

export function getSupplyDebt(
  id: string,
  signal?: AbortSignal,
): Promise<SupplyDebt> {
  const query = withFreshRequest(new URLSearchParams())
  return request(`/supply/debts/${id}?${query.toString()}`, {
    cache: 'no-store',
    signal,
  })
}

export function closeSupplyDebt(
  id: string, version: number, quantity: string, comment: string,
): Promise<SupplyDebt> {
  return request(`/supply/debts/${id}/close`, {
    method: 'POST',
    body: JSON.stringify({
      expected_version: version, quantity, comment,
    }),
  })
}

export function cancelSupplyDebt(
  id: string, version: number, comment: string,
): Promise<SupplyDebt> {
  return request(`/supply/debts/${id}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ expected_version: version, comment }),
  })
}

export function getSupplyDashboardSummary(
  signal?: AbortSignal,
): Promise<SupplyDashboardSummary> {
  const query = withFreshRequest(new URLSearchParams())
  return request(`/supply/summary/dashboard?${query.toString()}`, {
    cache: 'no-store',
    signal,
  })
}
