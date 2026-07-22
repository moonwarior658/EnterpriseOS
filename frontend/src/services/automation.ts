import { getStoredToken } from './auth'

export type AutomationScopeType =
  | 'company'
  | 'department'
  | 'location'
  | 'user'

export type ScheduleConfig =
  | {
      type: 'daily'
      time: string
    }
  | {
      type: 'weekly'
      weekdays: number[]
      time: string
    }
  | {
      type: 'interval'
      minutes: number
    }

export type AutomationSchedule = {
  id: number
  name: string
  automation_type: string
  contract_version: string
  tenant_id: string
  scope_type: AutomationScopeType
  scope_id: string | null
  schedule_config: ScheduleConfig
  payload: Record<string, unknown>
  recipients: unknown[]
  timezone: string
  is_enabled: boolean
  next_run_at: string | null
  created_by_user_id: number
  created_at: string
  updated_at: string
}

export type AutomationScheduleCreateInput = {
  name: string
  automation_type: string
  scope_type: AutomationScopeType
  scope_id: string | null
  schedule_config: ScheduleConfig
  payload: Record<string, unknown>
  recipients: unknown[]
  timezone: string
  is_enabled: boolean
}

export type AutomationScheduleUpdateInput = Partial<
  AutomationScheduleCreateInput
>

export type AutomationType = {
  key: string
  display_name: string
  description: string
  category: string
  is_system: boolean
  supports_manual_run: boolean
}

export type AutomationExecutionStatus =
  | 'pending'
  | 'dispatching'
  | 'running'
  | 'retrying'
  | 'succeeded'
  | 'failed'
  | 'timed_out'
  | 'cancelled'

export type AutomationExecution = {
  id: number
  execution_id: string
  schedule_id: number | null
  automation_type: string
  scope_type: AutomationScopeType
  scope_id: string | null
  recipients: unknown[]
  status: AutomationExecutionStatus
  provider: string | null
  requested_at: string
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_message: string | null
  attempt_count: number
  max_attempts: number
  created_at: string
  updated_at: string
}

export type AutomationExecutionHistoryItem = {
  status: AutomationExecutionStatus
  requested_at: string
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  user_status: string
  user_message: string
  error_category: string | null
  error_code: string | null
  error_message: string | null
}

export type AutomationLatestExecution = {
  schedule_id: number
  status: AutomationExecutionStatus | null
  requested_at: string | null
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  user_status: string
  user_message: string
  error_category: string | null
  error_code: string | null
}

export type AutomationExecutionHistoryPage = {
  items: AutomationExecutionHistoryItem[]
  total: number
  limit: number
  offset: number
}

export type AutomationScheduleAuditEventType =
  | 'automation_schedule_created'
  | 'automation_schedule_updated'
  | 'automation_schedule_enabled'
  | 'automation_schedule_disabled'
  | 'automation_schedule_run_requested'

export type AutomationScheduleAuditItem = {
  id: number
  event_type: AutomationScheduleAuditEventType
  actor_user_id: number
  actor_display_name: string | null
  occurred_at: string
  metadata: Record<string, unknown>
}

export type AutomationScheduleAuditPage = {
  items: AutomationScheduleAuditItem[]
  total: number
  limit: number
  offset: number
}

export type AutomationRuntimeState =
  | 'known'
  | 'unknown'
  | 'healthy'
  | 'degraded'

export type AutomationDiagnostics = {
  generated_at: string
  worker_state: {
    status: AutomationRuntimeState
    last_heartbeat_at: string | null
    heartbeat_age_seconds: number | null
    worker_id: string | null
    poll_interval_seconds: number | null
  }
  scheduler_state: {
    status: Exclude<AutomationRuntimeState, 'known'>
    last_run_at: string | null
    age_seconds: number | null
    scanned: number
    claimed: number
    created: number
    failed: number
    skipped: number
    poll_interval_seconds: number | null
  }
  n8n_state: {
    configured: boolean
    reachable: boolean | null
    checked_at: string | null
    latency_ms: number | null
    status: 'healthy' | 'degraded' | 'unavailable' | 'unknown'
    safe_message: string
  }
  outbox_summary: {
    pending: number
    processing: number
    retry_scheduled: number
    published: number
    failed: number
    oldest_pending_at: string | null
    oldest_pending_age_seconds: number | null
    stuck_count: number
  }
  execution_summary: {
    pending: number
    running: number
    succeeded: number
    failed: number
    timed_out: number
    cancelled: number
    running_too_long_count: number
    recent_system_errors: Array<{
      error_category: string
      error_code: string
      count: number
      last_occurred_at: string
    }>
  }
  alerts: Array<{
    code: string
    severity: 'warning' | 'critical'
    title: string
    safe_message: string
    count: number
    detected_at: string
  }>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function getApiErrorMessage(errorBody: unknown): string {
  if (!isRecord(errorBody)) {
    return 'Не удалось выполнить запрос'
  }

  if (typeof errorBody.detail === 'string') {
    return errorBody.detail
  }

  if (Array.isArray(errorBody.detail)) {
    const messages = errorBody.detail
      .map((item) =>
        isRecord(item) && typeof item.msg === 'string'
          ? item.msg
          : null,
      )
      .filter((message): message is string => message !== null)

    if (messages.length > 0) {
      return messages.join('. ')
    }
  }

  return 'Не удалось выполнить запрос'
}

async function authorizedRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T | null> {
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
    const errorBody: unknown = await response.json().catch(() => null)
    throw new Error(getApiErrorMessage(errorBody))
  }

  if (response.status === 204) {
    return null
  }

  return response.json() as Promise<T>
}

export async function getAutomationSchedules(): Promise<
  AutomationSchedule[]
> {
  const schedules = await authorizedRequest<AutomationSchedule[]>(
    '/automation/schedules',
  )

  return schedules ?? []
}

export async function getAutomationTypes(): Promise<AutomationType[]> {
  const types = await authorizedRequest<AutomationType[]>(
    '/automation/types',
  )

  return types ?? []
}

export async function getAutomationDiagnostics(): Promise<AutomationDiagnostics> {
  const diagnostics = await authorizedRequest<AutomationDiagnostics>(
    '/automation/diagnostics',
  )

  if (!diagnostics) {
    throw new Error('Не удалось загрузить диагностику автоматизаций')
  }

  return diagnostics
}

export async function createAutomationSchedule(
  input: AutomationScheduleCreateInput,
): Promise<AutomationSchedule> {
  const schedule = await authorizedRequest<AutomationSchedule>(
    '/automation/schedules',
    {
      method: 'POST',
      body: JSON.stringify(input),
    },
  )

  if (!schedule) {
    throw new Error('Не удалось создать регламент')
  }

  return schedule
}

export async function updateAutomationSchedule(
  scheduleId: number,
  input: AutomationScheduleUpdateInput,
): Promise<AutomationSchedule> {
  const schedule = await authorizedRequest<AutomationSchedule>(
    `/automation/schedules/${scheduleId}`,
    {
      method: 'PATCH',
      body: JSON.stringify(input),
    },
  )

  if (!schedule) {
    throw new Error('Не удалось сохранить регламент')
  }

  return schedule
}

export async function getLatestScheduleExecutions(
  scheduleIds?: number[],
): Promise<AutomationLatestExecution[]> {
  const query = scheduleIds?.length
    ? `?${scheduleIds.map((id) => `schedule_id=${encodeURIComponent(id)}`).join('&')}`
    : ''
  const executions = await authorizedRequest<AutomationLatestExecution[]>(
    `/automation/schedules/executions/latest${query}`,
  )

  return executions ?? []
}

export async function getScheduleExecutionHistory(
  scheduleId: number,
  limit: number,
  offset: number,
): Promise<AutomationExecutionHistoryPage> {
  const page = await authorizedRequest<AutomationExecutionHistoryPage>(
    `/automation/schedules/${scheduleId}/executions?limit=${limit}&offset=${offset}`,
  )

  if (!page) {
    throw new Error('Не удалось загрузить историю запусков')
  }

  return page
}

export async function getScheduleAudit(
  scheduleId: number,
  limit: number,
  offset: number,
): Promise<AutomationScheduleAuditPage> {
  const page = await authorizedRequest<AutomationScheduleAuditPage>(
    `/automation/schedules/${scheduleId}/audit?limit=${limit}&offset=${offset}`,
  )

  if (!page) {
    throw new Error('Не удалось загрузить журнал действий')
  }

  return page
}

export async function runAutomationSchedule(
  scheduleId: number,
): Promise<AutomationExecution> {
  const execution = await authorizedRequest<AutomationExecution>(
    `/automation/schedules/${scheduleId}/run`,
    { method: 'POST' },
  )

  if (!execution) {
    throw new Error('Не удалось запустить регламент')
  }

  return execution
}

export async function updateAutomationScheduleEnabled(
  scheduleId: number,
  isEnabled: boolean,
): Promise<AutomationSchedule | null> {
  return updateAutomationSchedule(scheduleId, {
    is_enabled: isEnabled,
  })
}
