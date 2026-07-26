import { getStoredToken } from './auth.ts'

export type WorkRequestType = 'warehouse' | 'repair'
export type WorkRequestStatus =
  | 'new'
  | 'in_progress'
  | 'completed'
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
}

export type CreateWorkRequestInput = {
  request_type: WorkRequestType
  department: string
  description: string
  warehouse_category?: WarehouseCategory
  repair_category?: string
  priority?: RepairPriority
}

export type PublicWarehouseRequestInput = {
  request_type: 'warehouse'
  department: string
  description: string
  warehouse_category: WarehouseCategory
}

export type PublicRepairRequestInput = {
  request_type: 'repair'
  department: string
  description: string
  repair_category: string
  priority: RepairPriority
}

export type UpdateWorkRequestInput = {
  department?: string
  description?: string
  status?: WorkRequestStatus
  warehouse_category?: WarehouseCategory
  repair_category?: string
  priority?: RepairPriority
}

export type WorkRequestComment = {
  id: number
  body: string
  created_at: string
  author_name: string
}

async function authorizedResponse(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const token = getStoredToken()
  if (!token) {
    throw new Error('Сессия не найдена')
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
      ...(options.body instanceof FormData
        ? {}
        : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
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

async function publicRequest<T>(
  options: RequestInit,
): Promise<T> {
  const response = await fetch('/api/public/requests', options)
  if (!response.ok) {
    throw new Error('Не удалось отправить заявку')
  }
  return response.json() as Promise<T>
}

export function createPublicWarehouseRequest(
  input: PublicWarehouseRequestInput,
): Promise<WorkRequest> {
  return publicRequest<WorkRequest>({
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(input),
  })
}

export function createPublicRepairRequest(
  input: PublicRepairRequestInput,
  photos: File[],
): Promise<WorkRequest> {
  const body = new FormData()
  for (const [key, value] of Object.entries(input)) {
    body.append(key, value)
  }
  for (const photo of photos) {
    body.append('photos', photo)
  }
  return publicRequest<WorkRequest>({
    method: 'POST',
    headers: { Accept: 'application/json' },
    body,
  })
}

export function getWorkRequests(): Promise<WorkRequest[]> {
  return authorizedRequest<WorkRequest[]>('/requests')
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
