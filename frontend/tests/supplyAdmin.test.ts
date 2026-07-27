import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  getSupplyRequests,
  getSupplyDebts,
  fulfillSupplyAsPlanned,
  matchSupplyLine,
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
  suggestSupplyWorkingName,
  updateSupplyLineMappingDraft,
  updateSupplyLineWorkingDraft,
  type SupplyLineMappingState,
  type SupplyLineWorkingState,
} from '../src/pages/supplyRequestDetailLogic.ts'

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

test('карточка поддерживает факт, долги и readonly исполненной заявки', () => {
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
  assert.match(debts, /Долги подразделений/)
  assert.match(debts, /Закрыть частично или полностью/)
  assert.match(debts, /Отменить долг/)
  assert.match(debts, /История/)
})

test('несопоставленная позиция остаётся рабочей для плана и факта', () => {
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
  assert.match(detail, /Позиция не сопоставлена/)
  assert.match(detail, /Планирование и факт доступны по рабочему наименованию/)
  assert.match(detail, /'MATCHED', 'NEEDS_REVIEW'/)
  assert.match(registry, /Не сопоставлено:/)
  assert.match(debts, /debt\.working_name/)
})

test('ручные значения двух неизвестных строк изолированы', () => {
  const detail = readFileSync(
    new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(detail, /Уточните строку/)
  assert.match(detail, /Сохранить строку/)
  assert.match(detail, /Строка готова к планированию/)
  assert.match(detail, /Сопоставить с iiko позже/)
  assert.match(detail, /item\.id === line\.id \? updated\.line : item/)
  assert.match(
    detail,
    /clearSupplyLineWorkingDraft\(current, line\.id\)/,
  )
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

test('editable state сопоставления изолирован по двум line.id', () => {
  const detail = readFileSync(
    new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  assert.doesNotMatch(detail, /productSearch/)
  assert.match(detail, /value=\{draft\.searchQuery\}/)
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
  assert.match(source, /inFlight/)
  assert.match(source, /Требует сопоставления/)
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
    await getSupplyDebts(new URLSearchParams({ severity: 'CRITICAL' }))
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.match(calls[0].url, /has_needs_review=true/)
  assert.equal(JSON.parse(String(calls[1].options.body)).save_alias, true)
  const workingBody = JSON.parse(String(calls[2].options.body))
  assert.equal(workingBody.request_version, 5)
  assert.equal(workingBody.requested_quantity, '3')
  assert.equal(calls[2].options.method, 'PATCH')
  const allocationBody = JSON.parse(String(calls[3].options.body))
  assert.equal(allocationBody.expected_version, 6)
  assert.deepEqual(
    allocationBody.allocations.map((item: { action: string }) => item.action),
    ['TRANSFER', 'PURCHASE'],
  )
  assert.equal(JSON.parse(String(calls[4].options.body)).expected_version, 7)
  assert.equal(JSON.parse(String(calls[5].options.body)).expected_version, 8)
  assert.match(calls[6].url, /severity=CRITICAL/)
})
