export type PublicSupplyDepartment = {
  id: string
  code: string
  name: string
  display_order: number
}

export type PublicSupplyDirection = {
  id: string
  code: string
  name: string
}

export type PublicSupplyCycle = {
  id: string
  direction: PublicSupplyDirection
  cycle_date: string
  opens_at: string
  closes_at: string
  hard_closes_at: string | null
  effective_closes_at: string
  server_now: string
  seconds_until_close: number
}

export type PublicSupplyLine = {
  id: string
  raw_text: string
  parsed_name: string | null
  parsed_quantity: string | null
  parsed_unit: string | null
  matched_product_name: string | null
  requested_quantity: string | null
  requested_unit: string | null
  confirmed_quantity: string
  fulfilled_quantity: string
  unresolved_quantity: string
  debt_quantity: string
  match_status: 'UNPROCESSED' | 'PARSED' | 'MATCHED' | 'NEEDS_REVIEW' | 'REJECTED'
  duplicate_status: 'NONE' | 'SUSPECTED' | 'CONFIRMED' | 'RESOLVED'
  public_message: string
  clarification_options: Array<{
    product_id: string
    product_name: string
  }>
}

export type PublicSupplyRequest = {
  request_number: string
  department: PublicSupplyDepartment
  direction: PublicSupplyDirection
  cycle: PublicSupplyCycle
  status:
    | 'DRAFT' | 'SUBMITTED' | 'IN_REVIEW' | 'PLANNED'
    | 'PARTIALLY_FULFILLED' | 'FULFILLED' | 'CANCELLED'
  version: number
  author_name: string | null
  lines: PublicSupplyLine[]
  submitted_at: string | null
  expires_at: string
}

export type PublicSupplySchedule = { summary: string }

export type PublicSupplyRequestCreated = PublicSupplyRequest & {
  public_token: string
}

type PublicSupplyErrorDetail = {
  code?: string
  message?: string
  current_version?: number
  unrecognized_line_ids?: string[]
}

export class PublicSupplyApiError extends Error {
  code: string
  currentVersion?: number

  constructor(detail: PublicSupplyErrorDetail = {}) {
    super(detail.message || 'Не удалось выполнить запрос')
    this.code = detail.code || 'SUPPLY_REQUEST_FAILED'
    this.currentVersion = detail.current_version
  }
}

async function publicSupplyRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`/api/public/supply${path}`, {
    ...options,
    headers,
    cache: 'no-store',
  })
  if (!response.ok) {
    let detail: PublicSupplyErrorDetail = {}
    try {
      const body = await response.json() as { detail?: PublicSupplyErrorDetail }
      detail = body.detail ?? {}
    } catch {
      // The public UI deliberately does not expose unexpected response bodies.
    }
    throw new PublicSupplyApiError(detail)
  }
  return response.json() as Promise<T>
}

export function getPublicSupplyDepartments(): Promise<PublicSupplyDepartment[]> {
  return publicSupplyRequest('/departments')
}

export function getPublicSupplyCycles(
  departmentId?: string,
): Promise<PublicSupplyCycle[]> {
  const query = departmentId
    ? `?department_id=${encodeURIComponent(departmentId)}`
    : ''
  return publicSupplyRequest(`/request-cycles${query}`)
}

export function getPublicSupplySchedule(): Promise<PublicSupplySchedule[]> {
  return publicSupplyRequest('/schedule')
}

export function createPublicSupplyRequest(input: {
  department_id: string
  cycle_id?: string
  author_name: string | null
  multiline_text: string
}): Promise<PublicSupplyRequestCreated> {
  return publicSupplyRequest('/requests', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getPublicSupplyRequest(
  token: string,
): Promise<PublicSupplyRequest> {
  return publicSupplyRequest(`/requests/${encodeURIComponent(token)}`)
}

export function updatePublicSupplyLines(
  token: string,
  input: { expected_version: number; multiline_text: string },
): Promise<PublicSupplyRequest> {
  return publicSupplyRequest(
    `/requests/${encodeURIComponent(token)}/lines`,
    {
      method: 'PUT',
      body: JSON.stringify(input),
    },
  )
}

export function selectPublicSupplyClarification(
  token: string,
  lineId: string,
  input: { expected_version: number; product_id: string },
): Promise<PublicSupplyRequest> {
  return publicSupplyRequest(
    `/requests/${encodeURIComponent(token)}/lines/${lineId}/clarification`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
}

export function submitPublicSupplyRequest(
  token: string,
  input: {
    expected_version: number
    confirm_unrecognized: boolean
  },
): Promise<PublicSupplyRequest> {
  return publicSupplyRequest(
    `/requests/${encodeURIComponent(token)}/submit`,
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )
}
