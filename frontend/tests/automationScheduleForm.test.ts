import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AutomationSchedule,
  AutomationScheduleCreateInput,
  AutomationScheduleUpdateInput,
} from '../src/services/automation.ts'
import {
  buildSupplyScheduleSummary,
  createSubmissionGuard,
  DEFAULT_SCHEDULE_FORM_VALUES,
  scheduleToFormValues,
  submitScheduleForm,
  type ScheduleFormApi,
  type ScheduleFormValues,
} from '../src/pages/automationScheduleFormLogic.ts'

const SCHEDULE: AutomationSchedule = {
  id: 42,
  name: 'Ежедневный отчёт',
  automation_type: 'smoke_test',
  contract_version: '1.0',
  tenant_id: 'eclair',
  scope_type: 'company',
  scope_id: null,
  schedule_config: { type: 'daily', time: '09:00' },
  payload: {},
  recipients: [],
  timezone: 'Asia/Yekaterinburg',
  is_enabled: true,
  next_run_at: '2026-07-23T04:00:00Z',
  created_by_user_id: 7,
  created_at: '2026-07-22T04:00:00Z',
  updated_at: '2026-07-22T04:00:00Z',
}

const VALID_VALUES: ScheduleFormValues = {
  ...DEFAULT_SCHEDULE_FORM_VALUES,
  name: 'Ежедневный отчёт',
  automationType: 'smoke_test',
  isEnabled: true,
}

function unusedApiMethod(): never {
  throw new Error('Unexpected API call')
}

test('успешно создаёт регламент с поддерживаемым backend payload', async () => {
  let received: AutomationScheduleCreateInput | undefined
  const api: ScheduleFormApi = {
    async create(input) {
      received = input
      return SCHEDULE
    },
    update: unusedApiMethod,
  }

  const result = await submitScheduleForm(
    { type: 'create' },
    VALID_VALUES,
    api,
    createSubmissionGuard(),
    new Set(['smoke_test']),
  )

  assert.equal(result.status, 'success')
  assert.deepEqual(received, {
    name: 'Ежедневный отчёт',
    automation_type: 'smoke_test',
    scope_type: 'company',
    scope_id: null,
    schedule_config: { type: 'daily', time: '09:00' },
    payload: {},
    recipients: [],
    timezone: 'Asia/Yekaterinburg',
    is_enabled: true,
  })
})

test('возвращает понятную ошибку валидации до вызова API', async () => {
  let calls = 0
  const api: ScheduleFormApi = {
    async create() {
      calls += 1
      return SCHEDULE
    },
    update: unusedApiMethod,
  }

  const result = await submitScheduleForm(
    { type: 'create' },
    { ...VALID_VALUES, name: '   ' },
    api,
    createSubmissionGuard(),
  )

  assert.equal(result.status, 'validation')
  assert.equal(calls, 0)
  assert.equal(
    result.status === 'validation' ? result.errors.name : undefined,
    'Укажите название регламента',
  )
})

test('успешно редактирует регламент через PATCH-compatible input', async () => {
  let receivedId: number | undefined
  let received: AutomationScheduleUpdateInput | undefined
  const updatedSchedule = { ...SCHEDULE, name: 'Обновлённый отчёт' }
  const api: ScheduleFormApi = {
    create: unusedApiMethod,
    async update(scheduleId, input) {
      receivedId = scheduleId
      received = input
      return updatedSchedule
    },
  }

  const result = await submitScheduleForm(
    { type: 'edit', scheduleId: 42 },
    { ...VALID_VALUES, name: '  Обновлённый отчёт  ' },
    api,
    createSubmissionGuard(),
    new Set(['smoke_test']),
  )

  assert.equal(result.status, 'success')
  assert.equal(receivedId, 42)
  assert.equal(received?.name, 'Обновлённый отчёт')
  assert.equal('payload' in (received ?? {}), false)
  assert.equal('recipients' in (received ?? {}), false)
})

test('edit сохраняет выбранный key типа автоматизации', () => {
  const values = scheduleToFormValues(SCHEDULE)

  assert.equal(values.automationType, 'smoke_test')
})

test('не отправляет неизвестный legacy key вместо каталожного типа', async () => {
  let calls = 0
  const api: ScheduleFormApi = {
    create: unusedApiMethod,
    async update() {
      calls += 1
      return SCHEDULE
    },
  }

  const result = await submitScheduleForm(
    { type: 'edit', scheduleId: 42 },
    { ...VALID_VALUES, automationType: 'legacy_unknown' },
    api,
    createSubmissionGuard(),
    new Set(['smoke_test']),
  )

  assert.equal(result.status, 'validation')
  assert.equal(calls, 0)
  assert.equal(
    result.status === 'validation'
      ? result.errors.automationType
      : undefined,
    'Выберите поддерживаемый тип автоматизации',
  )
})

test('переводит backend-ошибку без показа технического сообщения', async () => {
  const api: ScheduleFormApi = {
    async create() {
      throw new Error('Unknown timezone')
    },
    update: unusedApiMethod,
  }

  const result = await submitScheduleForm(
    { type: 'create' },
    VALID_VALUES,
    api,
    createSubmissionGuard(),
  )

  assert.deepEqual(result, {
    status: 'error',
    message: 'Указан неизвестный часовой пояс',
  })
})

test('не отправляет повторный запрос, пока первый не завершён', async () => {
  let calls = 0
  let resolveRequest: ((schedule: AutomationSchedule) => void) | undefined
  const pendingRequest = new Promise<AutomationSchedule>((resolve) => {
    resolveRequest = resolve
  })
  const api: ScheduleFormApi = {
    async create() {
      calls += 1
      return pendingRequest
    },
    update: unusedApiMethod,
  }
  const guard = createSubmissionGuard()

  const first = submitScheduleForm(
    { type: 'create' },
    VALID_VALUES,
    api,
    guard,
  )
  const second = await submitScheduleForm(
    { type: 'create' },
    VALID_VALUES,
    api,
    guard,
  )

  assert.deepEqual(second, { status: 'busy' })
  assert.equal(calls, 1)

  assert.ok(resolveRequest)
  resolveRequest(SCHEDULE)
  assert.equal((await first).status, 'success')
})

test('создаёт weekly Supply action с direction code и typed payload', async () => {
  let received: AutomationScheduleCreateInput | undefined
  const api: ScheduleFormApi = {
    async create(input) {
      received = input
      return {
        ...SCHEDULE,
        automation_type: 'supply.ensure_request_cycle',
        schedule_config: {
          type: 'weekly',
          weekdays: [1, 4],
          time: '00:00',
        },
        payload: input.payload,
      }
    },
    update: unusedApiMethod,
  }
  const values: ScheduleFormValues = {
    ...VALID_VALUES,
    automationType: 'supply.ensure_request_cycle',
    scheduleType: 'weekly',
    weekdays: [4, 1],
    time: '00:00',
    directionCode: 'MAIN',
    cycleDateOffsetDays: '0',
    opensTime: '00:00',
    closesTime: '23:59',
    hardClosesTime: '00:10',
    hardCloseNextDay: true,
  }

  const result = await submitScheduleForm(
    { type: 'create' },
    values,
    api,
    createSubmissionGuard(),
    new Set(['supply.ensure_request_cycle']),
  )

  assert.equal(result.status, 'success')
  assert.deepEqual(received?.schedule_config, {
    type: 'weekly',
    weekdays: [1, 4],
    time: '00:00',
  })
  assert.deepEqual(received?.payload, {
    direction_code: 'MAIN',
    cycle_date_offset_days: 0,
    opens_time: '00:00',
    closes_time: '23:59',
    hard_closes_time: '00:10',
    hard_close_next_day: true,
    timezone: 'Asia/Yekaterinburg',
    initial_status: 'OPEN',
  })
  assert.equal('tenant_id' in (received?.payload ?? {}), false)
})

test('Supply action требует день недели и валидный период', async () => {
  let calls = 0
  const api: ScheduleFormApi = {
    async create() {
      calls += 1
      return SCHEDULE
    },
    update: unusedApiMethod,
  }
  const result = await submitScheduleForm(
    { type: 'create' },
    {
      ...VALID_VALUES,
      automationType: 'supply.ensure_request_cycle',
      scheduleType: 'weekly',
      weekdays: [],
      directionCode: 'MAIN',
      opensTime: '12:00',
      closesTime: '11:00',
      hardCloseNextDay: false,
      hardClosesTime: '10:00',
    },
    api,
    createSubmissionGuard(),
    new Set(['supply.ensure_request_cycle']),
  )

  assert.equal(result.status, 'validation')
  assert.equal(calls, 0)
  if (result.status === 'validation') {
    assert.equal(result.errors.weekdays, 'Выберите хотя бы один день недели')
    assert.equal(
      result.errors.closesTime,
      'Обычное закрытие должно быть позже открытия',
    )
    assert.equal(
      result.errors.hardClosesTime,
      'Окончательное закрытие должно быть позже обычного',
    )
  }
})

test('редактирование Supply action не теряет weekdays и payload', async () => {
  const supplySchedule: AutomationSchedule = {
    ...SCHEDULE,
    automation_type: 'supply.ensure_request_cycle',
    schedule_config: {
      type: 'weekly',
      weekdays: [1, 4],
      time: '00:00',
    },
    payload: {
      direction_code: 'HOUSEHOLD',
      cycle_date_offset_days: 1,
      opens_time: '01:00',
      closes_time: '22:00',
      hard_closes_time: '00:20',
      hard_close_next_day: true,
      timezone: 'Asia/Yekaterinburg',
      initial_status: 'OPEN',
    },
  }
  const values = scheduleToFormValues(supplySchedule)
  let received: AutomationScheduleUpdateInput | undefined
  const api: ScheduleFormApi = {
    create: unusedApiMethod,
    async update(_id, input) {
      received = input
      return supplySchedule
    },
  }

  assert.deepEqual(values.weekdays, [1, 4])
  assert.equal(values.directionCode, 'HOUSEHOLD')
  assert.equal(values.cycleDateOffsetDays, '1')
  const result = await submitScheduleForm(
    { type: 'edit', scheduleId: 42 },
    values,
    api,
    createSubmissionGuard(),
    new Set(['supply.ensure_request_cycle']),
  )
  assert.equal(result.status, 'success')
  assert.deepEqual(received?.schedule_config, supplySchedule.schedule_config)
  assert.deepEqual(received?.payload, supplySchedule.payload)
})

test('строит русское summary из выбранных администратором значений', () => {
  const summary = buildSupplyScheduleSummary(
    {
      ...VALID_VALUES,
      automationType: 'supply.ensure_request_cycle',
      scheduleType: 'weekly',
      weekdays: [1, 4],
      time: '00:00',
      directionCode: 'MAIN',
    },
    'Основное',
  )

  assert.equal(
    summary,
    'Каждый вторник и пятницу в 00:00 система создаёт цикл направления «Основное» на день запуска. Приём заявок до 23:59, окончательное закрытие в 00:10 следующего дня. Часовой пояс: Екатеринбург.',
  )
})
