import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  getSupplyRequests,
  getSupplyDebts,
  fulfillSupplyAsPlanned,
  matchSupplyLine,
  planSupplyRequest,
  saveSupplyAllocations,
  saveSupplyFulfillment,
  saveSupplyLineWorkingValues,
} from '../src/services/supplyAdmin.ts'
import {
  clearSupplyLineWorkingDraft,
  createSupplyLineWorkingDraft,
  clearSupplyLineMappingDraft,
  createSupplyLineMappingDraft,
  getSupplyLineMappingDraft,
  getSupplyLineWorkingDraft,
  isSupplyLineWorkingDraftDirty,
  saveDirtySupplyLines,
  supplyLineWorkingBaseline,
  supplyExpectedDebtMillis,
  supplySendExcessMillis,
  suggestSupplyWorkingName,
  formatSupplyQuantityMillis,
  supplyQuantityMillis,
  updateSupplyLineMappingDraft,
  updateSupplyLineWorkingDraft,
  type SupplyLineMappingState,
  type SupplyLineWorkingState,
} from '../src/pages/supplyRequestDetailLogic.ts'
import type { SupplyLine } from '../src/services/supplyAdmin.ts'

test('подключает защищённые маршруты реестра и карточки', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(
    new URL('../src/layouts/AppLayout.tsx', import.meta.url), 'utf8',
  )
  assert.match(app, /path="\/supply\/requests"/)
  assert.match(app, /path="\/supply\/requests\/:requestId"/)
  assert.match(app, /path="\/supply\/debts"/)
  assert.match(app, /ProtectedRoute adminOnly/)
  assert.match(layout, /Заявки снабжения/)
  assert.match(layout, /Долги подразделений/)
})

test('карточка сохраняет факт и readonly исполненной заявки', () => {
  const detail = readFileSync(
    new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  const debts = readFileSync(
    new URL('../src/pages/SupplyDebtListPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(detail, /Отправить как запланировано/)
  assert.match(detail, /Сохранить факт/)
  assert.match(detail, /Подтвердить включение/)
  assert.match(detail, /request\.status === 'FULFILLED'/)
  assert.match(detail, /Утверждено/)
  assert.match(debts, /Долги подразделений/)
  assert.match(debts, /Закрыть частично или полностью/)
  assert.match(debts, /Отменить долг/)
  assert.match(debts, /История/)
})

test('основной экран компактный и не требует ручного распределения', () => {
  const detail = readFileSync(
    new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  const registry = readFileSync(
    new URL('../src/pages/SupplyRequestListPage.tsx', import.meta.url),
    'utf8',
  )
  const debts = readFileSync(
    new URL('../src/pages/SupplyDebtListPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(detail, /supply-simple-table/)
  assert.match(detail, /Название/)
  assert.match(detail, /Отправить/)
  assert.match(detail, /Фасовка \/ единица/)
  assert.match(detail, /Не сопоставлено/)
  assert.match(detail, /Сохранить изменения/)
  assert.match(detail, /Отправить в работу/)
  assert.doesNotMatch(detail, /AllocationEditor/)
  assert.doesNotMatch(detail, /Сохранить решение/)
  assert.match(registry, /Требуется сопоставить/)
  assert.doesNotMatch(registry, /Количество на странице/)
  assert.doesNotMatch(registry, /· v\{item\.version\}/)
  assert.match(registry, /EosSelect/)
  assert.match(registry, /EosCheckbox/)
  assert.match(debts, /debt\.working_name/)
})

test('dirty state двух строк изолирован по line.id', () => {
  const detail = readFileSync(
    new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(detail, /dirtySet\.has\(line\.id\)/)
  assert.match(detail, /saveDirtySupplyLines/)
  assert.match(detail, /supply-sticky-actions/)
  assert.match(detail, /event\.key === 'Enter'/)
  assert.match(
    detail,
    /Заявка изменилась\. Обновите карточку и повторите\./,
  )
  assert.equal(
    suggestSupplyWorkingName(null, 'мусорные пакеты 30л 3 рулона'),
    'мусорные пакеты 30л',
  )

  const first = createSupplyLineWorkingDraft('Первая', '', '')
  const second = createSupplyLineWorkingDraft('Вторая', '', '')
  let state: SupplyLineWorkingState = {}
  state = updateSupplyLineWorkingDraft(state, 'line-1', first, {
    workingName: 'Мусорные пакеты 30 л',
    quantity: '3',
    unitId: 'roll',
  })
  state = updateSupplyLineWorkingDraft(state, 'line-2', second, {
    workingName: 'Вторая строка',
    quantity: '7',
    unitId: 'piece',
  })
  state = clearSupplyLineWorkingDraft(state, 'line-1')

  assert.equal(state['line-1'], undefined)
  assert.deepEqual(
    getSupplyLineWorkingDraft(state, 'line-2', second),
    {
      workingName: 'Вторая строка',
      quantity: '7',
      unitId: 'piece',
      status: 'idle',
      error: '',
    },
  )
})

test('batch-save очищает успешную строку и оставляет ошибочную dirty', async () => {
  const lines = [
    {
      id: 'line-1',
      working_name: 'Первая',
      quantity: '10.000',
      send_quantity: null,
      parsed_quantity: '10.000',
      requested_unit: { id: 'kg' },
      parsed_unit: null,
    },
    {
      id: 'line-2',
      working_name: 'Вторая',
      quantity: '20.000',
      send_quantity: null,
      parsed_quantity: '20.000',
      requested_unit: { id: 'kg' },
      parsed_unit: null,
    },
  ] as SupplyLine[]
  const state: SupplyLineWorkingState = {
    'line-1': createSupplyLineWorkingDraft('Первая', '8', 'kg'),
    'line-2': createSupplyLineWorkingDraft('Вторая', '18', 'kg'),
  }
  assert.equal(supplyLineWorkingBaseline(lines[0]).quantity, '10.000')
  assert.equal(
    isSupplyLineWorkingDraftDirty(
      state['line-1'],
      supplyLineWorkingBaseline(lines[0]),
    ),
    true,
  )

  const result = await saveDirtySupplyLines(
    'request',
    7,
    lines,
    state,
    async (_requestId, lineId, input) => {
      if (lineId === 'line-2') throw new Error('validation')
      assert.equal(input.requested_quantity, '10.000')
      assert.equal(input.send_quantity, '8')
      return {
        request_version: input.request_version + 1,
        line: { ...lines[0], send_quantity: input.send_quantity },
      }
    },
  )

  assert.equal(result.requestVersion, 8)
  assert.equal(result.savedLines['line-1'].quantity, '10.000')
  assert.equal(result.savedLines['line-1'].send_quantity, '8')
  assert.equal(result.remaining['line-1'], undefined)
  assert.equal(result.remaining['line-2'].quantity, '18')
  assert.ok(result.errors['line-2'])
  assert.equal(supplyExpectedDebtMillis('10', '8'), 2000)
  assert.equal(supplyExpectedDebtMillis('10', '12'), 0)
  assert.equal(supplySendExcessMillis('10', '8'), 0)
  assert.equal(supplySendExcessMillis('10', '10'), 0)
  assert.equal(supplySendExcessMillis('10', '12'), 2000)
  assert.equal(
    isSupplyLineWorkingDraftDirty(
      supplyLineWorkingBaseline(lines[0]),
      supplyLineWorkingBaseline(lines[0]),
    ),
    false,
  )
})

test('editable state сопоставления изолирован по двум line.id', () => {
  const detail = readFileSync(
    new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  assert.doesNotMatch(detail, /productSearch/)
  assert.match(detail, /value=\{mappingDraft\.searchQuery\}/)
  assert.match(
    detail,
    /clearSupplyLineMappingDraft\(current, line\.id\)/,
  )

  const first = createSupplyLineMappingDraft('unit-1', '1')
  const second = createSupplyLineMappingDraft('unit-2', '2')
  let state: SupplyLineMappingState = {}

  state = updateSupplyLineMappingDraft(state, 'line-1', first, {
    searchQuery: 'Картофель',
  })
  assert.equal(
    getSupplyLineMappingDraft(state, 'line-1', 'unit-1', '1').searchQuery,
    'Картофель',
  )
  assert.equal(
    getSupplyLineMappingDraft(state, 'line-2', 'unit-2', '2').searchQuery,
    '',
  )

  state = updateSupplyLineMappingDraft(state, 'line-1', first, {
    productId: 'product-1',
    quantity: '3.5',
    saveAlias: true,
    status: 'loading',
  })
  assert.deepEqual(
    {
      productId: state['line-1'].productId,
      quantity: state['line-1'].quantity,
      saveAlias: state['line-1'].saveAlias,
      status: state['line-1'].status,
    },
    {
      productId: 'product-1',
      quantity: '3.5',
      saveAlias: true,
      status: 'loading',
    },
  )
  assert.deepEqual(
    getSupplyLineMappingDraft(state, 'line-2', 'unit-2', '2'),
    second,
  )

  state = updateSupplyLineMappingDraft(state, 'line-2', second, {
    searchQuery: 'Молоко',
    productId: 'product-2',
    quantity: '7',
    status: 'error',
    error: 'Ошибка второй строки',
  })
  state = clearSupplyLineMappingDraft(state, 'line-1')
  assert.equal(state['line-1'], undefined)
  assert.equal(state['line-2'].searchQuery, 'Молоко')
  assert.equal(state['line-2'].productId, 'product-2')
  assert.equal(state['line-2'].quantity, '7')
  assert.equal(state['line-2'].error, 'Ошибка второй строки')
})

test('реестр обновляется раз в 10 секунд и при возврате на вкладку', () => {
  const source = readFileSync(
    new URL('../src/pages/SupplyRequestListPage.tsx', import.meta.url), 'utf8',
  )
  assert.match(source, /10_000/)
  assert.match(source, /visibilitychange/)
  assert.match(source, /activeRequest/)
  assert.match(source, /requestSequence/)
  assert.match(source, /Требует сопоставления/)
})

test('долги перезагружаются при route navigation и возврате на вкладку', () => {
  const debts = readFileSync(
    new URL('../src/pages/SupplyDebtListPage.tsx', import.meta.url),
    'utf8',
  )
  const registry = readFileSync(
    new URL('../src/pages/SupplyRequestListPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(debts, /visibilitychange/)
  assert.match(debts, /10_000/)
  assert.match(debts, /activeRequest\.current\?\.abort\(\)/)
  assert.match(debts, /setState\('loading'\)/)
  assert.match(debts, /next\.set\('open', debtId\)/)
  assert.match(debts, /searchKey/)
  assert.match(registry, /routeParams\.get\('status'\)/)
  assert.match(registry, /routeParams\.get\('has_needs_review'\)/)
  assert.match(registry, /controller\.signal/)
})

test('количества Supply сравниваются без float-ошибки', () => {
  assert.equal(supplyQuantityMillis('0.1'), 100)
  assert.equal(supplyQuantityMillis('0.2'), 200)
  assert.equal(supplyQuantityMillis('0.3'), 300)
  assert.equal(
    (supplyQuantityMillis('0.1') ?? 0)
      + (supplyQuantityMillis('0.2') ?? 0),
    supplyQuantityMillis('0.3'),
  )
  assert.equal(supplyQuantityMillis('1.2345'), null)
  assert.equal(formatSupplyQuantityMillis(300), '0.300')
})

test('API-клиент передаёт фильтры, expected_version, алиас и allocations', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  const storage = new Map([['eos_access_token', 'token']])
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify([]), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getSupplyRequests(new URLSearchParams({ has_needs_review: 'true' }))
    await matchSupplyLine('request', 'line', {
      expected_version: 4,
      product_id: 'product',
      unit_id: 'unit',
      quantity: '2',
      save_alias: true,
    })
    await saveSupplyLineWorkingValues('request', 'line', {
      request_version: 5,
      working_name: 'Мусорные пакеты 30 л',
      requested_quantity: '3',
      send_quantity: '2',
      requested_unit_id: 'roll',
    })
    await saveSupplyAllocations(
      'request', 'line', 6,
      { transfer: '1', purchase: '1', cancel: '0', comment: 'решение' },
      'unit',
    )
    await saveSupplyFulfillment('request', 'line', 7, [{
      allocation_id: 'allocation',
      fulfilled_quantity: '1.5',
      comment: 'факт',
    }])
    await fulfillSupplyAsPlanned('request', 8)
    await planSupplyRequest('request', 9, true)
    await getSupplyDebts(new URLSearchParams({ severity: 'CRITICAL' }))
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.match(calls[0].url, /has_needs_review=true/)
  assert.match(calls[0].url, /_ts=/)
  assert.equal(JSON.parse(String(calls[1].options.body)).save_alias, true)
  const workingBody = JSON.parse(String(calls[2].options.body))
  assert.equal(workingBody.request_version, 5)
  assert.equal(workingBody.requested_quantity, '3')
  assert.equal(workingBody.send_quantity, '2')
  assert.equal(calls[2].options.method, 'PATCH')
  const allocationBody = JSON.parse(String(calls[3].options.body))
  assert.equal(allocationBody.expected_version, 6)
  assert.deepEqual(
    allocationBody.allocations.map((item: { action: string }) => item.action),
    ['TRANSFER', 'PURCHASE'],
  )
  assert.equal(JSON.parse(String(calls[4].options.body)).expected_version, 7)
  assert.equal(JSON.parse(String(calls[5].options.body)).expected_version, 8)
  const planBody = JSON.parse(String(calls[6].options.body))
  assert.equal(planBody.expected_version, 9)
  assert.equal(planBody.simple_mode, true)
  assert.match(calls[7].url, /severity=CRITICAL/)
  assert.match(calls[7].url, /_ts=/)
})
