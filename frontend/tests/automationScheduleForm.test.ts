import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AutomationSchedule,
  AutomationScheduleCreateInput,
  AutomationScheduleUpdateInput,
} from '../src/services/automation.ts'
import {
  createSubmissionGuard,
  DEFAULT_SCHEDULE_FORM_VALUES,
  submitScheduleForm,
  type ScheduleFormApi,
  type ScheduleFormValues,
} from '../src/pages/automationScheduleFormLogic.ts'

const SCHEDULE: AutomationSchedule = {
  id: 42,
  name: 'Ежедневный отчёт',
  automation_type: 'daily_report',
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
  automationType: 'daily_report',
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
  )

  assert.equal(result.status, 'success')
  assert.deepEqual(received, {
    name: 'Ежедневный отчёт',
    automation_type: 'daily_report',
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
  )

  assert.equal(result.status, 'success')
  assert.equal(receivedId, 42)
  assert.equal(received?.name, 'Обновлённый отчёт')
  assert.equal('payload' in (received ?? {}), false)
  assert.equal('recipients' in (received ?? {}), false)
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
