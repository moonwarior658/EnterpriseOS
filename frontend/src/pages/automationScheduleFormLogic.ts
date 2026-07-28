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
  directionCode: string
  cycleDateOffsetDays: string
  opensTime: string
  closesTime: string
  hardClosesTime: string
  hardCloseNextDay: boolean
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
export const SUPPLY_ENSURE_REQUEST_CYCLE =
  'supply.ensure_request_cycle'
export const SUPPLY_CLOSE_EXPIRED_REQUEST_CYCLES =
  'supply.close_expired_request_cycles'

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
  directionCode: '',
  cycleDateOffsetDays: '0',
  opensTime: '00:00',
  closesTime: '23:59',
  hardClosesTime: '00:10',
  hardCloseNextDay: true,
  isEnabled: false,
}

function payloadString(
  payload: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  return typeof payload[key] === 'string'
    ? payload[key]
    : fallback
}

function payloadBoolean(
  payload: Record<string, unknown>,
  key: string,
  fallback: boolean,
): boolean {
  return typeof payload[key] === 'boolean'
    ? payload[key]
    : fallback
}

function payloadIntegerString(
  payload: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const value = payload[key]
  return typeof value === 'number' && Number.isInteger(value)
    ? String(value)
    : fallback
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
    directionCode: payloadString(
      schedule.payload,
      'direction_code',
      '',
    ),
    cycleDateOffsetDays: payloadIntegerString(
      schedule.payload,
      'cycle_date_offset_days',
      '0',
    ),
    opensTime: payloadString(
      schedule.payload,
      'opens_time',
      '00:00',
    ),
    closesTime: payloadString(
      schedule.payload,
      'closes_time',
      '23:59',
    ),
    hardClosesTime: payloadString(
      schedule.payload,
      'hard_closes_time',
      '00:10',
    ),
    hardCloseNextDay: payloadBoolean(
      schedule.payload,
      'hard_close_next_day',
      true,
    ),
    isEnabled: schedule.is_enabled,
  }
}

export function validateScheduleForm(
  values: ScheduleFormValues,
  availableAutomationTypes?: ReadonlySet<string>,
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
  } else if (
    availableAutomationTypes &&
    !availableAutomationTypes.has(automationType)
  ) {
    errors.automationType = 'Выберите поддерживаемый тип автоматизации'
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

  if (automationType === SUPPLY_ENSURE_REQUEST_CYCLE) {
    if (values.scheduleType !== 'weekly') {
      errors.scheduleType =
        'Открытие циклов запускается по выбранным дням недели'
    }
    if (!values.directionCode.trim()) {
      errors.directionCode = 'Выберите направление'
    }

    const offset = Number(values.cycleDateOffsetDays)
    if (!Number.isInteger(offset) || offset < 0 || offset > 31) {
      errors.cycleDateOffsetDays =
        'Укажите целое смещение от 0 до 31 дня'
    }

    for (const [field, value] of [
      ['opensTime', values.opensTime],
      ['closesTime', values.closesTime],
      ['hardClosesTime', values.hardClosesTime],
    ] as const) {
      if (!TIME_PATTERN.test(value)) {
        errors[field] = 'Укажите время в формате ЧЧ:ММ'
      }
    }

    if (
      TIME_PATTERN.test(values.opensTime) &&
      TIME_PATTERN.test(values.closesTime) &&
      values.closesTime <= values.opensTime
    ) {
      errors.closesTime =
        'Обычное закрытие должно быть позже открытия'
    }
    if (
      !values.hardCloseNextDay &&
      TIME_PATTERN.test(values.closesTime) &&
      TIME_PATTERN.test(values.hardClosesTime) &&
      values.hardClosesTime <= values.closesTime
    ) {
      errors.hardClosesTime =
        'Окончательное закрытие должно быть позже обычного'
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
  const input: AutomationScheduleUpdateInput = {
    name: values.name.trim(),
    automation_type: values.automationType.trim(),
    scope_type: values.scopeType,
    scope_id:
      values.scopeType === 'company' ? null : values.scopeId.trim(),
    schedule_config: buildScheduleConfig(values),
    timezone: values.timezone.trim(),
    is_enabled: values.isEnabled,
  }
  const actionPayload = buildActionPayload(values)
  if (actionPayload !== null) {
    input.payload = actionPayload
  }
  return input
}

function buildActionPayload(
  values: ScheduleFormValues,
): Record<string, unknown> | null {
  if (values.automationType === SUPPLY_ENSURE_REQUEST_CYCLE) {
    return {
      direction_code: values.directionCode.trim(),
      cycle_date_offset_days: Number(values.cycleDateOffsetDays),
      opens_time: values.opensTime,
      closes_time: values.closesTime,
      hard_closes_time: values.hardClosesTime,
      hard_close_next_day: values.hardCloseNextDay,
      timezone: values.timezone.trim(),
      initial_status: 'OPEN',
    }
  }
  if (
    values.automationType === SUPPLY_CLOSE_EXPIRED_REQUEST_CYCLES
  ) {
    return { timezone: values.timezone.trim() }
  }
  return null
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
    payload: buildActionPayload(values) ?? {},
    recipients: [],
    timezone: values.timezone.trim(),
    is_enabled: values.isEnabled,
  }
}

const WEEKDAY_SUMMARY_LABELS = [
  'понедельник',
  'вторник',
  'среду',
  'четверг',
  'пятницу',
  'субботу',
  'воскресенье',
]

function joinRussian(items: string[]): string {
  if (items.length <= 1) {
    return items[0] ?? ''
  }
  return `${items.slice(0, -1).join(', ')} и ${items.at(-1)}`
}

export function buildSupplyScheduleSummary(
  values: ScheduleFormValues,
  directionName?: string,
): string {
  const timezoneLabel =
    values.timezone.trim() === 'Asia/Yekaterinburg'
      ? 'Екатеринбург'
      : values.timezone.trim()

  if (
    values.automationType === SUPPLY_CLOSE_EXPIRED_REQUEST_CYCLES
  ) {
    return `Система закрывает истёкшие циклы по настроенному расписанию. Часовой пояс: ${timezoneLabel}.`
  }
  if (values.automationType !== SUPPLY_ENSURE_REQUEST_CYCLE) {
    return ''
  }

  const weekdays = values.weekdays
    .map((weekday) => WEEKDAY_SUMMARY_LABELS[weekday])
    .filter((weekday): weekday is string => Boolean(weekday))
  const cycleDate =
    values.cycleDateOffsetDays === '0'
      ? 'на день запуска'
      : `со смещением на ${values.cycleDateOffsetDays} дн.`
  const hardClose = values.hardCloseNextDay
    ? `${values.hardClosesTime} следующего дня`
    : values.hardClosesTime

  return `Каждый ${joinRussian(weekdays)} в ${values.time} система создаёт цикл направления «${directionName ?? values.directionCode}» ${cycleDate}. Приём заявок до ${values.closesTime}, окончательное закрытие в ${hardClose}. Часовой пояс: ${timezoneLabel}.`
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

  if (/unsupported automation type/i.test(message)) {
    return 'Выберите поддерживаемый тип автоматизации'
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
  availableAutomationTypes?: ReadonlySet<string>,
): Promise<ScheduleFormSubmitResult> {
  const errors = validateScheduleForm(values, availableAutomationTypes)

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
