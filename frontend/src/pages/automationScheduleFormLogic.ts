import type {
  AutomationSchedule,
  AutomationScheduleCreateInput,
  AutomationScheduleUpdateInput,
  AutomationScopeType,
  ScheduleConfig,
} from '../services/automation.ts'

export type ScheduleFormValues = {
  name: string
  automationType: string
  scopeType: AutomationScopeType
  scopeId: string
  scheduleType: ScheduleConfig['type']
  time: string
  weekdays: number[]
  intervalMinutes: string
  timezone: string
  isEnabled: boolean
}

export type ScheduleFormErrors = Partial<
  Record<keyof ScheduleFormValues, string>
>

export type ScheduleFormMode =
  | { type: 'create' }
  | { type: 'edit'; scheduleId: number }

export type ScheduleFormApi = {
  create: (
    input: AutomationScheduleCreateInput,
  ) => Promise<AutomationSchedule>
  update: (
    scheduleId: number,
    input: AutomationScheduleUpdateInput,
  ) => Promise<AutomationSchedule>
}

export type SubmissionGuard = {
  tryStart: () => boolean
  finish: () => void
}

export type ScheduleFormSubmitResult =
  | { status: 'success'; schedule: AutomationSchedule }
  | { status: 'validation'; errors: ScheduleFormErrors }
  | { status: 'error'; message: string }
  | { status: 'busy' }

const TIME_PATTERN = /^(?:[01]\d|2[0-3]):[0-5]\d$/

export const DEFAULT_SCHEDULE_FORM_VALUES: ScheduleFormValues = {
  name: '',
  automationType: '',
  scopeType: 'company',
  scopeId: '',
  scheduleType: 'daily',
  time: '09:00',
  weekdays: [0, 1, 2, 3, 4],
  intervalMinutes: '60',
  timezone: 'Asia/Yekaterinburg',
  isEnabled: false,
}

export function scheduleToFormValues(
  schedule: AutomationSchedule,
): ScheduleFormValues {
  const config = schedule.schedule_config

  return {
    name: schedule.name,
    automationType: schedule.automation_type,
    scopeType: schedule.scope_type,
    scopeId: schedule.scope_id ?? '',
    scheduleType: config.type,
    time: config.type === 'interval' ? '09:00' : config.time,
    weekdays: config.type === 'weekly' ? config.weekdays : [0, 1, 2, 3, 4],
    intervalMinutes:
      config.type === 'interval' ? String(config.minutes) : '60',
    timezone: schedule.timezone,
    isEnabled: schedule.is_enabled,
  }
}

export function validateScheduleForm(
  values: ScheduleFormValues,
): ScheduleFormErrors {
  const errors: ScheduleFormErrors = {}
  const name = values.name.trim()
  const automationType = values.automationType.trim()
  const scopeId = values.scopeId.trim()
  const timezone = values.timezone.trim()

  if (!name) {
    errors.name = 'Укажите название регламента'
  } else if (name.length > 160) {
    errors.name = 'Название должно быть не длиннее 160 символов'
  }

  if (!automationType) {
    errors.automationType = 'Укажите тип автоматизации'
  } else if (automationType.length > 100) {
    errors.automationType = 'Тип должен быть не длиннее 100 символов'
  }

  if (values.scopeType !== 'company' && !scopeId) {
    errors.scopeId = 'Укажите идентификатор выбранной области'
  } else if (scopeId.length > 64) {
    errors.scopeId = 'Идентификатор должен быть не длиннее 64 символов'
  }

  if (!timezone) {
    errors.timezone = 'Укажите часовой пояс'
  } else if (timezone.length > 64) {
    errors.timezone = 'Часовой пояс должен быть не длиннее 64 символов'
  }

  if (
    (values.scheduleType === 'daily' ||
      values.scheduleType === 'weekly') &&
    !TIME_PATTERN.test(values.time)
  ) {
    errors.time = 'Укажите время в формате ЧЧ:ММ'
  }

  if (values.scheduleType === 'weekly' && values.weekdays.length === 0) {
    errors.weekdays = 'Выберите хотя бы один день недели'
  }

  if (values.scheduleType === 'interval') {
    const minutes = Number(values.intervalMinutes)

    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 10080) {
      errors.intervalMinutes = 'Укажите целое число от 1 до 10 080 минут'
    }
  }

  return errors
}

function buildScheduleConfig(values: ScheduleFormValues): ScheduleConfig {
  if (values.scheduleType === 'daily') {
    return { type: 'daily', time: values.time }
  }

  if (values.scheduleType === 'weekly') {
    return {
      type: 'weekly',
      weekdays: [...values.weekdays].sort((left, right) => left - right),
      time: values.time,
    }
  }

  return {
    type: 'interval',
    minutes: Number(values.intervalMinutes),
  }
}

function buildEditableInput(
  values: ScheduleFormValues,
): AutomationScheduleUpdateInput {
  return {
    name: values.name.trim(),
    automation_type: values.automationType.trim(),
    scope_type: values.scopeType,
    scope_id:
      values.scopeType === 'company' ? null : values.scopeId.trim(),
    schedule_config: buildScheduleConfig(values),
    timezone: values.timezone.trim(),
    is_enabled: values.isEnabled,
  }
}

export function buildCreateInput(
  values: ScheduleFormValues,
): AutomationScheduleCreateInput {
  return {
    ...buildEditableInput(values),
    name: values.name.trim(),
    automation_type: values.automationType.trim(),
    scope_type: values.scopeType,
    scope_id:
      values.scopeType === 'company' ? null : values.scopeId.trim(),
    schedule_config: buildScheduleConfig(values),
    payload: {},
    recipients: [],
    timezone: values.timezone.trim(),
    is_enabled: values.isEnabled,
  }
}

export function createSubmissionGuard(): SubmissionGuard {
  let isSubmitting = false

  return {
    tryStart() {
      if (isSubmitting) {
        return false
      }

      isSubmitting = true
      return true
    },
    finish() {
      isSubmitting = false
    },
  }
}

export function translateScheduleApiError(error: unknown): string {
  const message = error instanceof Error ? error.message : ''

  if (/unknown timezone/i.test(message)) {
    return 'Указан неизвестный часовой пояс'
  }

  if (/scope_id|invalid schedule scope|scope requires/i.test(message)) {
    return 'Проверьте область действия и её идентификатор'
  }

  if (/weekdays|schedule_config|invalid schedule/i.test(message)) {
    return 'Проверьте выбранное расписание'
  }

  if (/field required|value must not be empty|string_too_short/i.test(message)) {
    return 'Заполните обязательные поля формы'
  }

  if (/automation schedule not found/i.test(message)) {
    return 'Регламент не найден. Возможно, он уже был удалён'
  }

  if (/сессия не найдена/i.test(message)) {
    return 'Сессия завершена. Войдите в систему снова'
  }

  return 'Не удалось сохранить регламент. Попробуйте ещё раз'
}

export async function submitScheduleForm(
  mode: ScheduleFormMode,
  values: ScheduleFormValues,
  api: ScheduleFormApi,
  guard: SubmissionGuard,
): Promise<ScheduleFormSubmitResult> {
  const errors = validateScheduleForm(values)

  if (Object.keys(errors).length > 0) {
    return { status: 'validation', errors }
  }

  if (!guard.tryStart()) {
    return { status: 'busy' }
  }

  try {
    const schedule =
      mode.type === 'create'
        ? await api.create(buildCreateInput(values))
        : await api.update(mode.scheduleId, buildEditableInput(values))

    return { status: 'success', schedule }
  } catch (error) {
    return { status: 'error', message: translateScheduleApiError(error) }
  } finally {
    guard.finish()
  }
}
