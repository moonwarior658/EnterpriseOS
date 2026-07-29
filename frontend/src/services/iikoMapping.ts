import { getStoredToken } from './auth.ts'

export type IikoMappingStatus =
  | 'UNMAPPED' | 'SUGGESTED' | 'CONFIRMED' | 'CONFLICT' | 'IGNORED'

export type IikoWarehouseRole =
  | 'MAIN' | 'PACKAGING' | 'HOUSEHOLD' | 'FIXED_ASSETS' | 'OTHER'

export type IikoWarehouseDestinationType = 'DESTINATION' | 'SOURCE'

export type IikoLegalContour = 'IP' | 'OOO'

type MappingBase = {
  id: string
  source_name: string
  source_code: string | null
  is_deleted: boolean
  status: IikoMappingStatus
  confidence: number | null
  reasons: string[]
  decided_at: string | null
}

export type IikoProductMapping = MappingBase & {
  iiko_product_id: string
  source_sku: string | null
  source_unit_id: string | null
  eos_product_id: string | null
  eos_product_name: string | null
}

export type IikoUnitMapping = MappingBase & {
  iiko_unit_id: string
  eos_unit_id: string | null
  eos_unit_name: string | null
}

export type IikoWarehouseMapping = MappingBase & {
  iiko_warehouse_id: string
  eos_department_id: string | null
  eos_department_name: string | null
  destination_type: IikoWarehouseDestinationType
  role: IikoWarehouseRole | null
  legal_contour: IikoLegalContour | null
}

export type IikoMappingKind = 'products' | 'units' | 'warehouses'

export type IikoMappingPage<T> = {
  items: T[]
  total: number
  limit: number
  offset: number
}

export type IikoReferenceSyncResult = {
  products: number
  units: number
  warehouses: number
  warning: string | null
}

type IikoSyncRun = {
  status: 'RUNNING' | 'SUCCEEDED' | 'PARTIALLY_SUCCEEDED' | 'FAILED'
  error_message: string | null
}

type IikoGenerationStatus = {
  generation_id: string
  status: 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'UNKNOWN'
  result: Record<string, number> | null
}

export class IikoMappingApiError extends Error {
  status: number | null

  constructor(message: string, status: number | null = null) {
    super(message)
    this.status = status
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getStoredToken()
  if (!token) throw new IikoMappingApiError('Сессия не найдена')
  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)
  headers.set('Accept', 'application/json')
  if (options.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api/integrations/iiko/mappings${path}`, {
    ...options,
    headers,
    cache: 'no-store',
  })
  if (!response.ok) {
    let message = 'Не удалось выполнить действие'
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // Safe generic message is already selected.
    }
    throw new IikoMappingApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

async function referenceRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getStoredToken()
  if (!token) throw new IikoMappingApiError('Сессия не найдена')
  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)
  headers.set('Accept', 'application/json')
  const response = await fetch(`/api/integrations/iiko${path}`, {
    ...options,
    headers,
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new IikoMappingApiError('Не удалось обновить данные iiko')
  }
  return response.json() as Promise<T>
}

export async function syncIikoReferenceData(): Promise<
  IikoReferenceSyncResult
> {
  const run = await referenceRequest<IikoSyncRun>(
    '/sync/reference-snapshot',
    { method: 'POST' },
  )
  if (
    run.status !== 'SUCCEEDED'
    && run.status !== 'PARTIALLY_SUCCEEDED'
  ) {
    throw new IikoMappingApiError('Не удалось обновить данные iiko')
  }
  const query = '?limit=1&offset=0'
  const [products, units, warehouses] = await Promise.all([
    referenceRequest<IikoMappingPage<unknown>>(`/products${query}`),
    referenceRequest<IikoMappingPage<unknown>>(`/units${query}`),
    referenceRequest<IikoMappingPage<unknown>>(`/warehouses${query}`),
  ])
  return {
    products: products.total,
    units: units.total,
    warehouses: warehouses.total,
    warning: run.status === 'PARTIALLY_SUCCEEDED'
      ? run.error_message ?? 'Часть справочников iiko недоступна'
      : null,
  }
}

export function mappingQuery(values: {
  status?: IikoMappingStatus | ''
  search?: string
  includeDeleted?: boolean
  conflictsOnly?: boolean
  limit?: number
  offset?: number
}): URLSearchParams {
  const query = new URLSearchParams({
    limit: String(values.limit ?? 100),
    offset: String(values.offset ?? 0),
  })
  if (values.status) query.set('status', values.status)
  if (values.search?.trim()) query.set('search', values.search.trim())
  if (values.includeDeleted) query.set('include_deleted', 'true')
  if (values.conflictsOnly) query.set('conflicts_only', 'true')
  return query
}

export function getProductMappings(query: URLSearchParams) {
  return request<IikoMappingPage<IikoProductMapping>>(`/products?${query}`)
}

export function getUnitMappings(query: URLSearchParams) {
  return request<IikoMappingPage<IikoUnitMapping>>(`/units?${query}`)
}

export function getWarehouseMappings(query: URLSearchParams) {
  return request<IikoMappingPage<IikoWarehouseMapping>>(
    `/warehouses?${query}`,
  )
}

async function waitForGeneration(
  generationId: string,
): Promise<Record<string, number>> {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const progress = await request<IikoGenerationStatus>(
      `/generate/status?generation_id=${encodeURIComponent(generationId)}`,
    )
    if (progress.status === 'SUCCEEDED' && progress.result) {
      return progress.result
    }
    if (progress.status === 'FAILED' || progress.status === 'UNKNOWN') {
      throw new IikoMappingApiError(
        'Не удалось сформировать предложения',
      )
    }
    await new Promise((resolve) => globalThis.setTimeout(resolve, 1000))
  }
  throw new IikoMappingApiError('Не удалось сформировать предложения')
}

export async function generateMappingCandidates(): Promise<
  Record<string, number>
> {
  const generationId = crypto.randomUUID()
  try {
    return await request('/generate', {
      method: 'POST',
      headers: { 'X-EOS-Generation-ID': generationId },
    })
  } catch (error) {
    if (
      error instanceof IikoMappingApiError
      && ![502, 503, 504].includes(error.status ?? 0)
    ) {
      throw error
    }
    return waitForGeneration(generationId)
  }
}

export function confirmProductMapping(
  mappingId: string,
  eosProductId: string,
  replace: boolean,
): Promise<IikoProductMapping> {
  return request(`/products/${mappingId}/${replace ? 'replace' : 'confirm'}`, {
    method: 'POST',
    body: JSON.stringify({ eos_product_id: eosProductId }),
  })
}

export function confirmUnitMapping(
  mappingId: string,
  eosUnitId: string,
  replace: boolean,
): Promise<IikoUnitMapping> {
  return request(`/units/${mappingId}/${replace ? 'replace' : 'confirm'}`, {
    method: 'POST',
    body: JSON.stringify({ eos_unit_id: eosUnitId }),
  })
}

export function confirmWarehouseMapping(
  mappingId: string,
  payload: {
    destination_type: 'DESTINATION'
    eos_department_id: string
    role: IikoWarehouseRole
  } | {
    destination_type: 'SOURCE'
    legal_contour: IikoLegalContour
    role: IikoWarehouseRole
  },
  replace: boolean,
): Promise<IikoWarehouseMapping> {
  return request(
    `/warehouses/${mappingId}/${replace ? 'replace' : 'confirm'}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}

export function ignoreMapping(kind: IikoMappingKind, mappingId: string) {
  return request(`/${kind}/${mappingId}/ignore`, { method: 'POST' })
}

export function unmapMapping(kind: IikoMappingKind, mappingId: string) {
  return request(`/${kind}/${mappingId}/unmap`, { method: 'POST' })
}
