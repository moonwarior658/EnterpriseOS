import { getStoredToken } from './auth'

export type WorkRequestType = 'warehouse' | 'repair'
export type WorkRequestStatus =
  | 'new'
  | 'in_progress'
  | 'completed'
  | 'cancelled'
export type WarehouseCategory = 'products' | 'household' | 'packaging'
export type RepairPriority = 'routine' | 'important' | 'urgent'

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
  created_by_name: string
}

export type CreateWorkRequestInput = {
  request_type: WorkRequestType
  department: string
  description: string
  warehouse_category?: WarehouseCategory
  repair_category?: string
  priority?: RepairPriority
}

async function authorizedRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getStoredToken()

  if (!token) {
    throw new Error('Сессия не найдена')
  }

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
    throw new Error('Не удалось выполнить запрос')
  }

  return response.json() as Promise<T>
}

export function getWorkRequests(): Promise<WorkRequest[]> {
  return authorizedRequest<WorkRequest[]>('/requests')
}

export function createWorkRequest(
  input: CreateWorkRequestInput,
): Promise<WorkRequest> {
  return authorizedRequest<WorkRequest>('/requests', {
    method: 'POST',
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
