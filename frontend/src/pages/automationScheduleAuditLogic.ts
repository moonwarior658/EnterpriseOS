import type {
  AutomationScheduleAuditItem,
  AutomationScheduleAuditPage,
} from '../services/automation'

export type AuditLoader = (
  scheduleId: number,
  limit: number,
  offset: number,
) => Promise<AutomationScheduleAuditPage>

const EVENT_LABELS: Record<AutomationScheduleAuditItem['event_type'], string> = {
  automation_schedule_created: 'Регламент создан',
  automation_schedule_updated: 'Регламент изменён',
  automation_schedule_enabled: 'Регламент включён',
  automation_schedule_disabled: 'Регламент отключён',
  automation_schedule_run_requested: 'Запрошен ручной запуск',
}

const FIELD_LABELS: Record<string, string> = {
  name: 'название',
  automation_type: 'тип автоматизации',
  scope_type: 'область действия',
  scope_id: 'объект области действия',
  schedule_config: 'расписание',
  timezone: 'часовой пояс',
  is_enabled: 'состояние',
}

export async function loadScheduleAudit(
  scheduleId: number,
  pageNumber: number,
  pageSize: number,
  loader: AuditLoader,
): Promise<
  | { status: 'success'; page: AutomationScheduleAuditPage }
  | { status: 'error'; message: string }
> {
  try {
    const page = await loader(
      scheduleId,
      pageSize,
      (pageNumber - 1) * pageSize,
    )
    return { status: 'success', page }
  } catch {
    return {
      status: 'error',
      message: 'Не удалось загрузить журнал действий. Попробуйте ещё раз',
    }
  }
}

export function auditEventLabel(
  eventType: AutomationScheduleAuditItem['event_type'],
): string {
  return EVENT_LABELS[eventType]
}

export function auditEventDescription(
  event: AutomationScheduleAuditItem,
): string {
  if (event.event_type === 'automation_schedule_created') {
    return 'Создан регламент и сохранены его безопасные параметры'
  }

  if (event.event_type === 'automation_schedule_enabled') {
    return 'Регламент переведён в активное состояние'
  }

  if (event.event_type === 'automation_schedule_disabled') {
    return 'Регламент остановлен для последующих запусков'
  }

  if (event.event_type === 'automation_schedule_run_requested') {
    return 'Регламент поставлен в очередь на выполнение'
  }

  const changes = event.metadata.changes
  if (typeof changes !== 'object' || changes === null) {
    return 'Изменены безопасные параметры регламента'
  }

  const fields = Object.keys(changes)
    .filter((field) => FIELD_LABELS[field])
    .map((field) => FIELD_LABELS[field])

  return fields.length > 0
    ? `Изменены: ${fields.join(', ')}`
    : 'Изменены безопасные параметры регламента'
}
