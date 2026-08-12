import { getStoredToken } from './auth.ts'

export type SupplyStatus =
  | 'DRAFT' | 'SUBMITTED' | 'IN_REVIEW' | 'PLANNED'
  | 'PARTIALLY_FULFILLED' | 'FULFILLED' | 'CANCELLED'

export type SupplyUnit = {
  id: string
  code: string
  name_ru: string
  short_name_ru: string
  allows_fraction: boolean
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
  active_debt_requires_matching: boolean
  debt_inclusion_status:
    | 'NONE' | 'COVERED_BY_REQUEST' | 'REQUEST_BELOW_DEBT' | 'CONFIRMED_PARTIAL'
  debt_quantity_included: string
  requires_debt_confirmation: boolean
  unallocated_quantity: string
  planning_status: string
  context_mapping_suggestion: {
    mapping_id: string | null
    mapping_version: number | null
    department_id: string
    phrase: string
    product_id: string
    product_name: string
    correction_count: number
  } | null
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

export type SupplyIikoDocument = {
  document_write_id: string
  document_type: 'OUTGOING_INVOICE'
  source_store_id: string
  flow: 'MAIN' | 'PACKAGING' | 'HOUSEHOLD'
  status: 'PENDING' | 'CREATED' | 'FAILED' | 'UNKNOWN'
  iiko_document_id: string | null
  document_number: string | null
  error_code: string | null
  operator_message: string | null
  printable: boolean
}

export type SupplyIikoSourceWarehouse = {
  mapping_id: string
  iiko_warehouse_id: string
  name: string
  role: 'MAIN' | 'PACKAGING' | 'HOUSEHOLD' | 'FIXED_ASSETS' | 'OTHER'
  legal_contour: 'IP' | 'OOO'
}

export type SupplyIikoStockLine = {
  line_id: string
  position: number
  product_name: string
  requested_quantity: string | null
  requested_unit: SupplyUnit | null
  stock_quantity: string | null
  is_sufficient: boolean | null
  deficit: string | null
  unavailable_reason: string | null
}

export type SupplyIikoStockCheck = {
  request_version: number
  legal_contour: 'IP' | 'OOO' | null
  available_sources: SupplyIikoSourceWarehouse[]
  selected_source: SupplyIikoSourceWarehouse | null
  last_sync_at: string | null
  lines: SupplyIikoStockLine[]
}

export type SupplyStockCalculationLine = {
  id: string
  version: number
  request_line_id: string
  position: number
  product_id: string
  product_name: string
  requested_unit: SupplyUnit | null
  requested_quantity: string | null
  source_warehouse_mapping_id: string | null
  source_name: string | null
  iiko_snapshot_at: string | null
  available_quantity: string | null
  transferable_quantity: string | null
  deficit_quantity: string | null
  unavailable_reason: string | null
}

export type SupplyStockCalculation = {
  id: string
  request_id: string
  revision: number
  version: number
  status: 'PRELIMINARY' | 'CONFIRMED'
  is_preliminary: boolean
  calculated_at: string
  snapshot_at: string | null
  confirmed_at: string | null
  groups: Array<{
    source_mapping_id: string | null
    source_name: string | null
    snapshot_at: string | null
    lines: SupplyStockCalculationLine[]
  }>
}

export type SupplyProductSourceOption = {
  mapping_id: string
  iiko_warehouse_id: string
  name: string
  role: 'MAIN' | 'PACKAGING' | 'HOUSEHOLD'
  legal_contour: 'IP' | 'OOO'
}

export type SupplyProductSourcePreview = {
  request_id: string
  legal_contour: 'IP' | 'OOO' | null
  assigned_products: number
  total_products: number
  ready_for_shipment: boolean
  blocking_reasons: string[]
  products: Array<{
    product_id: string
    product_name: string
    role: 'MAIN' | 'PACKAGING' | 'HOUSEHOLD' | null
    iiko_mapping_confirmed: boolean
    assigned_source: SupplyProductSourceOption | null
    mapping_version: number | null
    available_sources: SupplyProductSourceOption[]
    blocking_reason: string | null
  }>
  groups: Array<{
    source: SupplyProductSourceOption
    lines: Array<{
      line_id: string
      position: number
      product_id: string
      product_name: string
      quantity: string | null
      unit: SupplyUnit | null
    }>
  }>
}

export type SupplyProductSourceBootstrap = {
  created: number
  already_mapped: number
  conflicts: number
  missing_source: number
  ambiguous_source: number
  unsupported_prefix: number
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
  severity: 'NONE' | 'YELLOW' | 'RED'
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

export type SupplyReference = {
  id: string
  code: string
  name: string
  legal_contour?: 'IP' | 'OOO' | null
  is_active: boolean
}
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
): Promise<{ items: SupplyRequestSummary[]; total: number }> {
  const token = getStoredToken()
  if (!token) {
    return Promise.reject(
      new SupplyApiError('Сессия не найдена', null, null),
    )
  }
  return fetch(
    `/api/supply/requests?${withFreshRequest(query).toString()}`,
    {
      cache: 'no-store',
      signal,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
      },
    },
  ).then(async (response) => {
    if (!response.ok) {
      throw new SupplyApiError('Не удалось загрузить заявки', null, null)
    }
    return {
      items: await response.json() as SupplyRequestSummary[],
      total: Number(response.headers.get('X-Total-Count') ?? 0),
    }
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

export function getSupplyIikoStockCheck(
  id: string,
  signal?: AbortSignal,
): Promise<SupplyIikoStockCheck> {
  return request(`/supply/requests/${id}/iiko-stock-check`, {
    cache: 'no-store',
    signal,
  })
}

export function selectSupplyIikoSourceWarehouse(
  id: string,
  mappingId: string,
  expectedVersion: number,
): Promise<SupplyIikoStockCheck> {
  return request(`/supply/requests/${id}/iiko-source-warehouse`, {
    method: 'PUT',
    body: JSON.stringify({
      mapping_id: mappingId,
      expected_version: expectedVersion,
    }),
  })
}

export function getSupplyStockCalculation(
  id: string,
  signal?: AbortSignal,
): Promise<SupplyStockCalculation | null> {
  return request(`/supply/requests/${id}/stock-calculation`, {
    cache: 'no-store',
    signal,
  })
}

export function calculateSupplyStock(id: string): Promise<SupplyStockCalculation> {
  return request(`/supply/requests/${id}/stock-calculation/calculate`, {
    method: 'POST',
  })
}

export function updateSupplyStockTransferable(
  requestId: string,
  calculation: SupplyStockCalculation,
  line: SupplyStockCalculationLine,
  quantity: string,
): Promise<SupplyStockCalculation> {
  return request(
    `/supply/requests/${requestId}/stock-calculation/lines/${line.id}`,
    {
      method: 'PATCH',
      body: JSON.stringify({
        calculation_id: calculation.id,
        expected_revision: calculation.revision,
        expected_version: calculation.version,
        expected_line_version: line.version,
        quantity,
      }),
    },
  )
}

export function confirmSupplyStockCalculation(
  id: string,
  calculation: SupplyStockCalculation,
): Promise<SupplyStockCalculation> {
  return request(`/supply/requests/${id}/stock-calculation/confirm`, {
    method: 'POST',
    body: JSON.stringify({
      calculation_id: calculation.id,
      expected_revision: calculation.revision,
      expected_version: calculation.version,
    }),
  })
}

export function getSupplyProductSourcePreview(
  requestId: string,
  signal?: AbortSignal,
): Promise<SupplyProductSourcePreview> {
  return request(`/supply/requests/${requestId}/source-groups-preview`, {
    cache: 'no-store',
    signal,
  })
}

export function assignSupplyProductSource(
  productId: string,
  legalContour: 'IP' | 'OOO',
  sourceMappingId: string,
  expectedVersion: number | null,
  comment: string | null,
): Promise<unknown> {
  return request(`/supply/products/${productId}/source-mapping`, {
    method: 'PUT',
    body: JSON.stringify({
      legal_contour: legalContour,
      source_mapping_id: sourceMappingId,
      expected_version: expectedVersion,
      comment,
    }),
  })
}

export function bootstrapSupplyProductSources(): Promise<SupplyProductSourceBootstrap> {
  return request('/supply/product-source-mappings/bootstrap', {
    method: 'POST',
  })
}

export function getSupplyProducts(
  search = '',
  signal?: AbortSignal,
): Promise<{ items: SupplyProduct[] }> {
  const query = new URLSearchParams({
    active: 'true',
    limit: '20',
    offset: '0',
  })
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
  },
): Promise<SupplyLine> {
  return request(`/supply/requests/${requestId}/lines/${lineId}/match`, {
    method: 'POST',
    body: JSON.stringify({ ...input, action: 'MATCH' }),
  })
}

export function confirmSupplyContextMapping(
  requestId: string,
  lineId: string,
  productId: string,
  expectedVersion: number | null,
): Promise<{ id: string }> {
  return request(
    `/supply/requests/${requestId}/lines/${lineId}/context-mapping`,
    {
      method: 'POST',
      body: JSON.stringify({
        product_id: productId,
        expected_version: expectedVersion,
      }),
    },
  )
}

export function recognizeSupplyRequest(
  requestId: string,
  expectedVersion: number,
  signal?: AbortSignal,
): Promise<{
  total: number
  matched: number
  needs_review: number
  skipped: number
}> {
  return request(`/supply/requests/${requestId}/recognize`, {
    method: 'POST',
    body: JSON.stringify({ expected_version: expectedVersion }),
    signal,
  })
}

export function reparseSupplyLine(
  requestId: string,
  lineId: string,
  expectedVersion: number,
): Promise<{ request_version: number; line: SupplyLine }> {
  return request(`/supply/requests/${requestId}/lines/${lineId}/reparse`, {
    method: 'POST',
    body: JSON.stringify({ expected_version: expectedVersion }),
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

export function getSupplyIikoDocuments(
  requestId: string,
  signal?: AbortSignal,
): Promise<SupplyIikoDocument[]> {
  return request(`/supply/requests/${requestId}/iiko-documents`, { signal })
}

export async function openSupplyIikoDocumentPdf(
  requestId: string,
  documentWriteId?: string,
): Promise<void> {
  const token = getStoredToken()
  if (!token) throw new SupplyApiError('Сессия не найдена', null, null)
  const suffix = documentWriteId
    ? `/iiko-documents/${documentWriteId}/pdf`
    : '/iiko-documents/pdf'
  const response = await fetch(`/api/supply/requests/${requestId}${suffix}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/pdf' },
  })
  if (!response.ok) {
    let code: string | null = null
    try {
      const body = await response.json() as { detail?: unknown }
      code = typeof body.detail === 'string' ? body.detail : null
    } catch {
      // Keep the safe generic error when the response is not JSON.
    }
    throw new SupplyApiError('Не удалось сформировать PDF', code, null)
  }
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = documentWriteId
    ? `supply-${requestId}-${documentWriteId}.pdf`
    : `supply-${requestId}-iiko-documents.pdf`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
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
  requestId: string,
  expectedVersion: number,
  items: Array<{ line_id: string; fulfilled_quantity: string }>,
): Promise<SupplyRequest> {
  return request(`/supply/requests/${requestId}/fulfill-as-planned`, {
    method: 'POST',
    body: JSON.stringify({ expected_version: expectedVersion, items }),
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
