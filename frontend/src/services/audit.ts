import { getStoredToken } from './auth.ts'

export type AuditEvent = {
  id: string
  event_type: string
  entity_type: string
  entity_id: string
  operation: string
  occurred_at: string
  actor_employee_id: string | null
  actor_name_snapshot: string | null
  active_roles_snapshot: string[]
  authorized_as: string | null
  primary_department_id: string | null
  primary_department_name_snapshot: string | null
  actual_department_id: string | null
  actual_department_name_snapshot: string | null
  shift_id: string | null
  before: Record<string, unknown>
  after: Record<string, unknown>
  reason: string | null
  source: 'HUMAN' | 'SYSTEM'
  correction_of_event_id: string | null
}

export type AuditFilters = {
  dateFrom?: string
  dateTo?: string
  employeeId?: string
  departmentId?: string
  entityType?: string
  operation?: string
  eventType?: string
}

export async function getAuditEvents(filters: AuditFilters = {}): Promise<AuditEvent[]> {
  const token = getStoredToken()
  if (!token) throw new Error('Сессия не найдена')
  const query = new URLSearchParams({ limit: '100' })
  if (filters.dateFrom) query.set('date_from', `${filters.dateFrom}T00:00:00Z`)
  if (filters.dateTo) query.set('date_to', `${filters.dateTo}T23:59:59Z`)
  if (filters.employeeId) query.set('employee_id', filters.employeeId)
  if (filters.departmentId) query.set('department_id', filters.departmentId)
  if (filters.entityType) query.set('entity_type', filters.entityType)
  if (filters.operation) query.set('operation', filters.operation)
  if (filters.eventType) query.set('event_type', filters.eventType)
  const response = await fetch(`/api/audit/events?${query}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const message = typeof body?.detail?.message === 'string'
      ? body.detail.message
      : 'Не удалось загрузить аудит'
    throw new Error(message)
  }
  return response.json() as Promise<AuditEvent[]>
}
