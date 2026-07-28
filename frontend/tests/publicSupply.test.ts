import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  createPublicSupplyRequest,
  getPublicSupplyCycles,
  getPublicSupplyDepartments,
  getPublicSupplyRequest,
  getPublicSupplySchedule,
  submitPublicSupplyRequest,
  updatePublicSupplyLines,
  type PublicSupplyRequest,
} from '../src/services/publicSupply.ts'
import {
  formatRemainingTime,
  hasBlockingDuplicates,
  hasUnrecognizedLines,
  PUBLIC_SUPPLY_SESSION_KEY,
  publicSupplyFormError,
  remainingSeconds,
  requestLinesAsText,
} from '../src/pages/publicSupplyLogic.ts'

const REQUEST: PublicSupplyRequest = {
  request_number: 'ЗАЯВКА-20260727-М15-MAIN-001',
  department: {
    id: 'department-id',
    code: 'М15',
    name: 'Матросова 15',
    display_order: 10,
  },
  direction: { id: 'direction-id', code: 'MAIN', name: 'Основной' },
  cycle: {
    id: 'cycle-id',
    direction: { id: 'direction-id', code: 'MAIN', name: 'Основной' },
    cycle_date: '2026-07-27',
    opens_at: '2026-07-27T08:00:00Z',
    closes_at: '2026-07-27T10:00:00Z',
    hard_closes_at: '2026-07-27T11:00:00Z',
    effective_closes_at: '2026-07-27T11:00:00Z',
    server_now: '2026-07-27T10:00:00Z',
    seconds_until_close: 3600,
  },
  status: 'DRAFT',
  version: 1,
  author_name: 'Анна',
  lines: [
    {
      id: 'line-id',
      raw_text: 'Картофель 10 кг',
      parsed_name: 'Картофель',
      parsed_quantity: '10',
      parsed_unit: 'кг',
      matched_product_name: 'Картофель',
      requested_quantity: '10',
      requested_unit: 'кг',
      match_status: 'MATCHED',
      duplicate_status: 'NONE',
      public_message: 'Распознано',
    },
  ],
  submitted_at: null,
  expires_at: '2026-07-28T11:00:00Z',
}

test('маршрут Supply-формы подключён отдельно от старых форм', () => {
  const source = readFileSync(
    new URL('../src/App.tsx', import.meta.url),
    'utf8',
  )
  assert.match(source, /path="\/request\/supply"/)
  assert.match(source, /PublicSupplyRequestPage/)
  assert.match(source, /path="\/request\/warehouse"/)
  assert.match(source, /path="\/request\/repair"/)
  const pageSource = readFileSync(
    new URL('../src/pages/PublicSupplyRequestPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(pageSource, /sessionStorage\.getItem\(PUBLIC_SUPPLY_SESSION_KEY\)/)
  assert.match(pageSource, /getPublicSupplyRequest\(storedToken\)/)
  assert.match(pageSource, /Сегодня заявки не принимаем/)
  assert.match(pageSource, /getPublicSupplySchedule/)
  assert.doesNotMatch(pageSource, /Телефон \(необязательно\)/)
  assert.doesNotMatch(pageSource, /Направление и цикл/)
  assert.match(pageSource, /Восстановить сохранённую заявку/)
  assert.match(pageSource, /retryRestore/)
})

test('валидирует первый экран и строки формы', () => {
  assert.equal(
    publicSupplyFormError({
      departmentId: '',
      multilineText: '',
    }),
    'Выберите подразделение',
  )
  assert.equal(
    publicSupplyFormError({
      departmentId: 'department-id',
      multilineText: 'Картофель 10 кг',
    }),
    '',
  )
  assert.equal(PUBLIC_SUPPLY_SESSION_KEY, 'eos_public_supply_token')
})

test('определяет дубли и нераспознанные строки без внутренних терминов', () => {
  assert.equal(hasBlockingDuplicates(REQUEST.lines), false)
  assert.equal(hasUnrecognizedLines(REQUEST.lines), false)
  assert.equal(
    hasBlockingDuplicates([
      { ...REQUEST.lines[0], duplicate_status: 'SUSPECTED' },
    ]),
    true,
  )
  assert.equal(
    hasUnrecognizedLines([
      { ...REQUEST.lines[0], match_status: 'NEEDS_REVIEW' },
    ]),
    true,
  )
  assert.equal(requestLinesAsText(REQUEST), 'Картофель 10 кг')
})

test('считает дедлайн от server_now, а не от локального времени', () => {
  const receivedAt = Date.parse('2026-07-27T05:00:00Z')
  assert.equal(
    remainingSeconds(REQUEST, receivedAt + 30_000, receivedAt),
    3570,
  )
  assert.equal(formatRemainingTime(3570), '59:30')
  assert.equal(formatRemainingTime(0), 'Приём заявок завершён')
})

test('API client использует только /api/public/supply и поддерживает весь сценарий', async () => {
  const originalFetch = globalThis.fetch
  const calls: Array<{ url: string; options: RequestInit }> = []
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    const url = String(input)
    const body = url.endsWith('/departments')
      ? [REQUEST.department]
      : url.endsWith('/schedule')
        ? [{ summary: 'Основной — понедельник и четверг' }]
      : url.includes('/request-cycles')
        ? [REQUEST.cycle]
        : url.endsWith('/requests')
          ? { ...REQUEST, public_token: 'opaque-token' }
          : REQUEST
    return new Response(JSON.stringify(body), {
      status: url.endsWith('/submit') ? 200 : 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getPublicSupplyDepartments()
    await getPublicSupplySchedule()
    await getPublicSupplyCycles('department-id')
    await createPublicSupplyRequest({
      department_id: 'department-id',
      author_name: null,
      multiline_text: 'Картофель 10 кг',
    })
    await getPublicSupplyRequest('opaque-token')
    await updatePublicSupplyLines('opaque-token', {
      expected_version: 1,
      multiline_text: 'Картофель 5 кг',
    })
    await submitPublicSupplyRequest('opaque-token', {
      expected_version: 2,
      confirm_unrecognized: false,
    })
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(calls.length, 7)
  assert.ok(calls.every((call) => call.url.startsWith('/api/public/supply')))
  assert.match(calls[2].url, /department_id=department-id/)
  assert.equal(calls[3].options.method, 'POST')
  assert.equal(
    Object.hasOwn(
      JSON.parse(String(calls[3].options.body)) as object,
      'author_phone',
    ),
    false,
  )
  assert.equal(calls[5].options.method, 'PUT')
  assert.equal(calls[6].options.method, 'POST')
  assert.equal(
    JSON.parse(String(calls[6].options.body)).confirm_unrecognized,
    false,
  )
})
