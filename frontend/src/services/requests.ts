import { getStoredToken } from './auth.ts'

export type WorkRequestType = 'warehouse' | 'repair'
export type WorkRequestStatus =
  | 'new'
  | 'in_progress'
  | 'waiting_external'
  | 'escalated'
  | 'completed'
  | 'reopened'
  | 'cancelled'
export type WarehouseCategory = 'products' | 'household' | 'packaging'
export type RepairPriority = 'routine' | 'important' | 'urgent'

export type WorkRequestAttachment = {
  id: number
  original_filename: string
  content_type: string
  size_bytes: number
  created_at: string
}

export type WorkRequest = {
  id: number
  request_type: WorkRequestType
  department: string
  description: string
  status: WorkRequestStatus
  warehouse_category: WarehouseCategory | null
  repair_category: string | null
  priority: RepairPriority | null
  created_at: string
  updated_at: string
  created_by_name: string
  attachment_count: number
  attachments: WorkRequestAttachment[]
  department_id: string | null
  responsible_role: 'HANDYMAN' | 'SUPPLY_MANAGER' | null
  responsible_employee_id: string | null
  responsibility_started_at: string | null
  contractor_id: string | null
  contractor_name: string | null
  contractor_phone: string | null
  specialization_id: string | null
  specialization_name: string | null
  responsible_employee_name: string | null
  visit_at: string | null
  closed_at: string | null
  allowed_actions: string[]
}

export type RepairRequestInput = {
  request_type: 'repair'
  department_id: string
  description: string
  repair_category: string
  priority: RepairPriority
}

export type UpdateWorkRequestInput = {
  department?: string
  description?: string
  status?: WorkRequestStatus
  repair_category?: string
  priority?: RepairPriority
}

export type WorkRequestComment = {
  id: number
  body: string
  created_at: string
  author_name: string
}

let lastWorkRequestsCacheBuster = 0

function nextWorkRequestsCacheBuster(): number {
  const now = Date.now()
  lastWorkRequestsCacheBuster = Math.max(
    now,
    lastWorkRequestsCacheBuster + 1,
  )
  return lastWorkRequestsCacheBuster
}

async function authorizedResponse(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getStoredToken()
  if (!token) {
    throw new Error('Сессия не найдена')
  }

  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }
  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
  })
  if (!response.ok) {
    throw new Error('Не удалось выполнить запрос')
  }
  return response
}

async function authorizedRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await authorizedResponse(path, options)
  return response.json() as Promise<T>
}

export function createRepairRequest(
  input: RepairRequestInput,
  photos: File[],
): Promise<WorkRequest> {
  const body = new FormData()
  for (const [key, value] of Object.entries(input)) {
    if (key === 'request_type') continue
    body.append(key, value)
  }
  for (const photo of photos) {
    body.append('photos', photo)
  }
  return authorizedRequest<WorkRequest>('/repairs', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body,
  })
}

export type RepairDepartment = { id: string; name: string }
export type RepairContractor = { id: string; name: string; phone: string; is_active: boolean; notes: string | null; price_notes: string | null; specialization_ids: string[] }
export type RepairSpecialization = { id: string; name: string; is_active: boolean }
export type RepairTimelineEvent = { at: string; action: string; actor: string | null; role: string | null; reason: string | null; details: string }

export function getRepairDepartments(): Promise<RepairDepartment[]> {
  return authorizedRequest('/repairs/departments')
}

export function getRepairContractors(): Promise<RepairContractor[]> {
  return authorizedRequest('/repairs/contractors')
}

export function getRepairSpecializations(): Promise<RepairSpecialization[]> {
  return authorizedRequest('/repairs/specializations')
}

export function createRepairSpecialization(name: string): Promise<RepairSpecialization> {
  return authorizedRequest('/repairs/specializations', { method: 'POST', body: JSON.stringify({ name }) })
}

export function updateRepairSpecialization(id: string, input: object): Promise<RepairSpecialization> {
  return authorizedRequest(`/repairs/specializations/${id}`, { method: 'PATCH', body: JSON.stringify(input) })
}

export function createRepairContractor(input: object): Promise<RepairContractor> {
  return authorizedRequest('/repairs/contractors', { method: 'POST', body: JSON.stringify(input) })
}

export function updateRepairContractor(id: string, input: object): Promise<RepairContractor> {
  return authorizedRequest(`/repairs/contractors/${id}`, { method: 'PATCH', body: JSON.stringify(input) })
}

export type ContractorHistory = { repair_id: number; created_at: string; department: string; category: string; description: string; specialization: string | null; visit_at: string | null; status: WorkRequestStatus; closed_at: string | null; reopened: boolean }
export function getContractorHistory(id: string): Promise<ContractorHistory[]> {
  return authorizedRequest(`/repairs/contractors/${id}/history`)
}

export function getRepairTimeline(id: number): Promise<RepairTimelineEvent[]> {
  return authorizedRequest(`/repairs/${id}/timeline`)
}

export function repairAction(id: number, action: 'take' | 'assign-contractor' | 'schedule-external-visit' | 'escalate-to-supply' | 'close' | 'reopen', body?: object): Promise<WorkRequest> {
  return authorizedRequest(`/repairs/${id}/${action}`, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
}

export function updateRepairDetails(id: number, input: { description: string; repair_category: string; priority: RepairPriority }): Promise<WorkRequest> {
  return authorizedRequest(`/repairs/${id}/details`, { method: 'PATCH', body: JSON.stringify(input) })
}

export function addRepairPhoto(id: number, photo: File): Promise<WorkRequestAttachment> {
  const body = new FormData()
  body.append('photo', photo)
  return authorizedRequest(`/repairs/${id}/photos`, { method: 'POST', body })
}

export function getWorkRequests(): Promise<WorkRequest[]> {
  const cacheBuster = nextWorkRequestsCacheBuster()
  return authorizedRequest<WorkRequest[]>(
    `/requests?_ts=${cacheBuster}`,
    {
      method: 'GET',
      cache: 'no-store',
      headers: {
        'Cache-Control': 'no-cache',
      },
    },
  )
}

export function getWorkRequest(requestId: number): Promise<WorkRequest> {
  return authorizedRequest<WorkRequest>(`/requests/${requestId}`)
}

export function updateWorkRequest(
  requestId: number,
  input: UpdateWorkRequestInput,
): Promise<WorkRequest> {
  return authorizedRequest<WorkRequest>(`/requests/${requestId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function updateWorkRequestStatus(
  requestId: number,
  status: WorkRequestStatus,
): Promise<WorkRequest> {
  return authorizedRequest<WorkRequest>(
    `/requests/${requestId}/status`,
    {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    },
  )
}

export function getWorkRequestComments(
  requestId: number,
): Promise<WorkRequestComment[]> {
  return authorizedRequest<WorkRequestComment[]>(
    `/requests/${requestId}/comments`,
  )
}

export function createWorkRequestComment(
  requestId: number,
  body: string,
): Promise<WorkRequestComment> {
  return authorizedRequest<WorkRequestComment>(
    `/requests/${requestId}/comments`,
    {
      method: 'POST',
      body: JSON.stringify({ body }),
    },
  )
}

export async function getWorkRequestAttachmentUrl(
  requestId: number,
  attachmentId: number,
): Promise<string> {
  const response = await authorizedResponse(
    `/requests/${requestId}/attachments/${attachmentId}`,
  )
  return URL.createObjectURL(await response.blob())
}
