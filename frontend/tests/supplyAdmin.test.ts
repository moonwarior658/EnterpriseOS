import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  getSupplyRequests,
  getSupplyDebts,
  getSupplyProducts,
  fulfillSupplyAsPlanned,
  matchSupplyLine,
  planSupplyRequest,
  recognizeSupplyRequest,
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
  isSupplyLineMatchReady,
  nextSupplyLineToMatch,
  requiresSupplyLineMatch,
  saveDirtySupplyLines,
  supplyLineWorkingBaseline,
  supplyExpectedDebtMillis,
  supplySendExcessMillis,
  supplyMatchProgress,
  supplyPrintStatusLabel,
  suggestSupplyWorkingName,
  formatSupplyQuantityMillis,
  supplyQuantityMillis,
  updateSupplyLineMappingDraft,
  updateSupplyLineWorkingDraft,
  type SupplyLineMappingState,
  type SupplyLineWorkingState,
} from '../src/pages/supplyRequestDetailLogic.ts'
import type { SupplyLine, SupplyUnit } from '../src/services/supplyAdmin.ts'

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

test('статусы print job отображаются безопасными русскими подписями', () => {
  assert.equal(supplyPrintStatusLabel('QUEUED_FOR_PRINT'), 'В очереди')
  assert.equal(supplyPrintStatusLabel('PRINTING'), 'Печатается')
  assert.equal(supplyPrintStatusLabel('PRINTED'), 'Напечатано')
  assert.equal(supplyPrintStatusLabel('PRINT_FAILED'), 'Ошибка печати')
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
  assert.match(detail, /getSupplyProducts\(query, controller\.signal\)/)
  assert.match(detail, /new AbortController\(\)/)
  assert.match(detail, /}, 300\)/)
  assert.doesNotMatch(detail, /getSupplyProducts\('', controller\.signal\)/)
  assert.doesNotMatch(detail, /products\.filter/)
  assert.match(detail, /value=\{draft\.searchQuery\}/)
  assert.match(
    detail,
    /clearSupplyLineMappingDraft\(current, line\.id\)/,
  )

  const first = createSupplyLineMappingDraft('Картофель')
  const second = createSupplyLineMappingDraft('Молоко')
  let state: SupplyLineMappingState = {}

  state = updateSupplyLineMappingDraft(state, 'line-1', first, {
    searchQuery: 'Картофель',
  })
  assert.equal(
    getSupplyLineMappingDraft(
      state, 'line-1', 'Картофель',
    ).searchQuery,
    'Картофель',
  )
  assert.equal(
    getSupplyLineMappingDraft(
      state, 'line-2', 'Молоко',
    ).searchQuery,
    'Молоко',
  )

  state = updateSupplyLineMappingDraft(state, 'line-1', first, {
    productId: 'product-1',
    status: 'loading',
  })
  assert.deepEqual(
    {
      productId: state['line-1'].productId,
      status: state['line-1'].status,
    },
    {
      productId: 'product-1',
      status: 'loading',
    },
  )
  assert.deepEqual(
    getSupplyLineMappingDraft(
      state, 'line-2', 'Молоко',
    ),
    second,
  )

  state = updateSupplyLineMappingDraft(state, 'line-2', second, {
    searchQuery: 'Молоко',
    productId: 'product-2',
    status: 'error',
    error: 'Ошибка второй строки',
  })
  state = clearSupplyLineMappingDraft(state, 'line-1')
  assert.equal(state['line-1'], undefined)
  assert.equal(state['line-2'].searchQuery, 'Молоко')
  assert.equal(state['line-2'].productId, 'product-2')
  assert.equal(state['line-2'].error, 'Ошибка второй строки')
})

test('MATCH сразу валидирует актуальные quantity и unit основной строки', () => {
  const mapping = {
    ...createSupplyLineMappingDraft('Контейнеры'),
    productId: 'product-1',
  }
  const pieceUnit: SupplyUnit = {
    id: 'unit-pcs',
    code: 'PCS',
    name_ru: 'Штука',
    short_name_ru: 'шт',
    allows_fraction: false,
    is_active: true,
  }
  const empty = createSupplyLineWorkingDraft('Контейнеры', '', '')
  assert.equal(isSupplyLineMatchReady(mapping, empty, [pieceUnit]), false)
  const corrected = { ...empty, quantity: '200', unitId: pieceUnit.id }
  assert.equal(isSupplyLineMatchReady(mapping, corrected, [pieceUnit]), true)
  assert.equal(isSupplyLineMatchReady(
    mapping,
    { ...corrected, quantity: '2.5' },
    [pieceUnit],
  ), false)
})

test('рабочее место показывает нужные строки, прогресс и следующий фокус', () => {
  const detail = readFileSync(
    new URL('../src/pages/SupplyRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(detail, /requiresSupplyLineMatch\(line\)/)
  assert.match(detail, /Сопоставить с товаром EOS/)
  assert.match(detail, /Перераспознать строку/)
  assert.match(detail, /Выбран товар EOS/)
  assert.match(detail, /nextSupplyLineToMatch/)
  assert.match(detail, /scrollIntoView/)
  assert.match(detail, /recognizeSupplyRequest/)
  assert.doesNotMatch(detail, /Сопоставить с iiko/)

  const lines = [
    { id: 'one', match_status: 'MATCHED' },
    { id: 'two', match_status: 'UNPROCESSED' },
    { id: 'three', match_status: 'NEEDS_REVIEW' },
    { id: 'four', match_status: 'REJECTED' },
  ] as SupplyLine[]
  assert.equal(requiresSupplyLineMatch(lines[1]), true)
  assert.equal(requiresSupplyLineMatch(lines[2]), true)
  assert.deepEqual(supplyMatchProgress(lines), {
    matched: 1,
    total: 4,
    needsReview: 2,
  })
  assert.equal(nextSupplyLineToMatch(lines, 'two'), 'three')
  assert.equal(nextSupplyLineToMatch(lines, 'three'), 'two')
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
  assert.doesNotMatch(
    debts,
    /if \(!query\.has\('status'\)\) query\.set\('status', 'ACTIVE'\)/,
  )
  assert.match(debts, /searchParams\.get\('status'\) \?\? ''/)
})

test('пагинация EOS использует page size 25 и сохраняет URL-фильтры', () => {
  const registry = readFileSync(
    new URL('../src/pages/SupplyRequestListPage.tsx', import.meta.url),
    'utf8',
  )
  const controls = readFileSync(
    new URL('../src/components/EosFormControls.tsx', import.meta.url),
    'utf8',
  )
  const styles = readFileSync(
    new URL('../src/App.css', import.meta.url),
    'utf8',
  )
  assert.match(registry, /SUPPLY_REQUEST_PAGE_SIZE = 25/)
  assert.match(registry, /<EosPagination/)
  assert.match(registry, /if \(search\.trim\(\)\) next\.set\('search'/)
  assert.match(controls, /aria-label="Предыдущая страница"/)
  assert.match(controls, /aria-label="Следующая страница"/)
  assert.match(controls, /offset \+ itemCount >= total/)
  assert.doesNotMatch(registry, /page size|Количество записей/i)
  assert.match(styles, /\.eos-pagination/)
})

test('фильтры реестра выделяют ширину подразделению и направлению', () => {
  const styles = readFileSync(
    new URL('../src/App.css', import.meta.url),
    'utf8',
  )
  assert.match(styles, /minmax\(13\.5rem, 1\.15fr\)/)
  assert.match(styles, /minmax\(12\.5rem, 1\.1fr\)/)
  assert.match(styles, /@media \(max-width: 900px\)/)
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
    await getSupplyProducts('Молоко')
    await recognizeSupplyRequest('request', 10)
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.match(calls[0].url, /has_needs_review=true/)
  assert.match(calls[0].url, /_ts=/)
  assert.deepEqual(JSON.parse(String(calls[1].options.body)), {
    expected_version: 4,
    product_id: 'product',
    unit_id: 'unit',
    quantity: '2',
    action: 'MATCH',
  })
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
  assert.match(calls[8].url, /active=true/)
  assert.match(calls[8].url, /search=%D0%9C%D0%BE%D0%BB%D0%BE%D0%BA%D0%BE/)
  assert.match(calls[8].url, /limit=20/)
  assert.match(calls[8].url, /offset=0/)
  assert.equal(JSON.parse(String(calls[9].options.body)).expected_version, 10)
  assert.equal(Object.hasOwn(JSON.parse(String(calls[9].options.body)), 'force'), false)
})
