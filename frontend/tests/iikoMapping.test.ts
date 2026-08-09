import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  acquireIikoStockSnapshotGuard,
  deduplicateIikoWarehouseMappings,
  iikoMappingStatusLabel,
  iikoLegalContourLabel,
  iikoStockSnapshotStatusLabel,
  iikoWarehouseDestinationTypeLabel,
  iikoWarehouseRoleLabel,
  mappingActionLabel,
} from '../src/pages/iikoMappingLogic.ts'
import {
  bootstrapIikoProductCatalog,
  confirmWarehouseMapping,
  generateMappingCandidates,
  getConfirmedSourceWarehouseMappings,
  IikoMappingApiError,
  mappingQuery,
  syncIikoReferenceData,
  takeIikoStockBalanceSnapshot,
  type IikoWarehouseMapping,
} from '../src/services/iikoMapping.ts'


test('показывает безопасные русские статусы и роли mapping', () => {
  assert.equal(iikoMappingStatusLabel('SUGGESTED'), 'Предложено')
  assert.equal(iikoMappingStatusLabel('CONFLICT'), 'Конфликт')
  assert.equal(iikoWarehouseRoleLabel('FIXED_ASSETS'), 'Основные средства')
  assert.equal(
    iikoWarehouseDestinationTypeLabel('SOURCE'),
    'Источник снабжения',
  )
  assert.equal(iikoLegalContourLabel('OOO'), 'ООО')
  assert.equal(iikoStockSnapshotStatusLabel('SUCCEEDED'), 'Остатки сняты')
  assert.equal(
    iikoStockSnapshotStatusLabel('PARTIALLY_SUCCEEDED'),
    'Остатки сняты частично',
  )
  assert.equal(iikoStockSnapshotStatusLabel('FAILED'), 'Остатки не сняты')
  assert.equal(mappingActionLabel('CONFIRMED'), 'Заменить связь')
})

test('формирует фильтры статуса, поиска, удалённых и конфликтов', () => {
  const query = mappingQuery({
    status: 'CONFLICT',
    search: '  молоко ',
    includeDeleted: true,
    conflictsOnly: true,
    limit: 100,
    offset: 200,
  })
  assert.equal(query.get('status'), 'CONFLICT')
  assert.equal(query.get('search'), 'молоко')
  assert.equal(query.get('include_deleted'), 'true')
  assert.equal(query.get('conflicts_only'), 'true')
  assert.equal(query.get('offset'), '200')
})

test('admin UI содержит три mapping-раздела и все явные действия', () => {
  const page = readFileSync(
    new URL('../src/pages/IikoMappingPage.tsx', import.meta.url),
    'utf8',
  )
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(page, /Товары/)
  assert.match(page, /Единицы/)
  assert.match(page, /Склады/)
  assert.match(page, /iikoWarehouseDestinationTypeLabel/)
  assert.match(page, /Контур источника/)
  assert.match(page, /Сформировать предложения/)
  assert.match(page, /Создать каталог EOS из iiko/)
  assert.match(page, /bootstrapResult\.created/)
  assert.match(page, /bootstrapResult\.linked/)
  assert.match(page, /bootstrapResult\.existing/)
  assert.match(page, /bootstrapResult\.conflicts/)
  assert.match(page, /bootstrapResult\.skipped/)
  assert.match(
    page,
    /await bootstrapIikoProductCatalog\(\)[\s\S]*?await getSupplyProducts\(\)[\s\S]*?setProducts\(productPage\.items\)[\s\S]*?await load\(\)/,
  )
  assert.match(page, /Игнорировать/)
  assert.match(page, /Снять связь/)
  assert.match(page, /Снять остатки/)
  assert.match(page, /Подразделение для снимка остатков/)
  assert.match(page, /getConfirmedSourceWarehouseMappings/)
  assert.match(page, /void getSupplyDepartments\(\)\.then/)
  assert.match(page, /stockSnapshotInFlight = useRef\(false\)/)
  assert.match(page, /source\.legal_contour === department\.legal_contour/)
  assert.match(page, /takeIikoStockBalanceSnapshot/)
  assert.match(page, /records_created/)
  assert.match(page, /failed_source_warehouse_mapping_ids/)
  assert.match(page, /Частичный снимок сохранён для аудита/)
  assert.match(page, /Показывать удалённые/)
  assert.match(page, /Только конфликты/)
  assert.match(app, /ProtectedRoute adminOnly><IikoMappingPage/)
})

test('snapshot deduplicate SOURCE и синхронно блокирует второй запуск', () => {
  const source = {
    id: 'source-ip',
    source_name: 'Центральный склад',
    source_code: null,
    is_deleted: false,
    status: 'CONFIRMED',
    confidence: null,
    reasons: [],
    decided_at: null,
    iiko_warehouse_id: 'warehouse-ip',
    eos_department_id: null,
    eos_department_name: null,
    destination_type: 'SOURCE',
    role: 'MAIN',
    legal_contour: 'IP',
  } satisfies IikoWarehouseMapping
  assert.deepEqual(
    deduplicateIikoWarehouseMappings([source, source]).map((item) => item.id),
    ['source-ip'],
  )

  const guard = { current: false }
  assert.equal(acquireIikoStockSnapshotGuard(guard), true)
  assert.equal(acquireIikoStockSnapshotGuard(guard), false)
  guard.current = false
  assert.equal(acquireIikoStockSnapshotGuard(guard), true)
})

test('snapshot берёт CONFIRMED SOURCE и текущую admin-сессию', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  const calls: Array<{ url: string; options: RequestInit }> = []
  globalThis.fetch = async (input, options = {}) => {
    const url = String(input)
    calls.push({ url, options })
    if (url.includes('/mappings/warehouses?')) {
      return new Response(JSON.stringify({
        items: [
          {
            id: 'source-ip',
            source_name: 'Центральный склад',
            source_code: null,
            is_deleted: false,
            status: 'CONFIRMED',
            confidence: null,
            reasons: [],
            decided_at: null,
            iiko_warehouse_id: 'warehouse-ip',
            eos_department_id: null,
            eos_department_name: null,
            destination_type: 'SOURCE',
            role: 'MAIN',
            legal_contour: 'IP',
          },
          {
            id: 'destination-ip',
            source_name: 'М15',
            source_code: null,
            is_deleted: false,
            status: 'CONFIRMED',
            confidence: null,
            reasons: [],
            decided_at: null,
            iiko_warehouse_id: 'warehouse-m15',
            eos_department_id: 'department-ip',
            eos_department_name: 'М15',
            destination_type: 'DESTINATION',
            role: 'MAIN',
            legal_contour: 'IP',
          },
        ],
        total: 2,
        limit: 200,
        offset: 0,
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({
      status: 'SUCCEEDED',
      records_created: 17,
      records_failed: 0,
      error_message: null,
      parameters: {
        snapshot_at: '2026-08-09T12:30:00.000Z',
        department_id: 'department-ip',
        source_warehouse_mapping_ids: ['source-ip'],
        completed_source_warehouse_mapping_ids: ['source-ip'],
        failed_source_warehouse_mapping_ids: [],
      },
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const sources = await getConfirmedSourceWarehouseMappings()
    assert.deepEqual(sources.map((source) => source.id), ['source-ip'])
    const run = await takeIikoStockBalanceSnapshot(
      'department-ip',
      sources.map((source) => source.id),
      new Date('2026-08-09T12:30:00+00:00'),
    )
    assert.equal(run.status, 'SUCCEEDED')
    assert.equal(run.records_created, 17)
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
  assert.match(calls[0].url, /status=CONFIRMED/)
  assert.equal(calls[1].url, '/api/integrations/iiko/sync/stock-balance-snapshot')
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(
    new Headers(calls[1].options.headers).get('Authorization'),
    'Bearer test-token',
  )
  assert.deepEqual(JSON.parse(String(calls[1].options.body)), {
    snapshot_at: '2026-08-09T12:30:00.000Z',
    department_id: 'department-ip',
    source_warehouse_mapping_ids: ['source-ip'],
  })
})

test('bootstrap каталога вызывает отдельный endpoint и возвращает счётчики', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  let requestedPath = ''
  let requestedMethod = ''
  globalThis.fetch = async (input, options = {}) => {
    requestedPath = String(input)
    requestedMethod = options.method ?? 'GET'
    return new Response(JSON.stringify({
      created: 2,
      linked: 2,
      existing: 3,
      conflicts: 1,
      skipped: 4,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const result = await bootstrapIikoProductCatalog()
    assert.equal(result.created, 2)
    assert.equal(result.conflicts, 1)
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
  assert.match(requestedPath, /\/products\/bootstrap-catalog$/)
  assert.equal(requestedMethod, 'POST')
})

test('SOURCE отправляется с контуром и ролью без подразделения', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  let requestBody: Record<string, unknown> = {}
  globalThis.fetch = async (_input, options = {}) => {
    requestBody = JSON.parse(String(options.body)) as Record<string, unknown>
    return new Response(JSON.stringify({
      id: 'mapping-1',
      destination_type: 'SOURCE',
      legal_contour: 'IP',
      role: 'PACKAGING',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await confirmWarehouseMapping(
      'mapping-1',
      {
        destination_type: 'SOURCE',
        legal_contour: 'IP',
        role: 'PACKAGING',
      },
      false,
    )
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
  assert.deepEqual(requestBody, {
    destination_type: 'SOURCE',
    legal_contour: 'IP',
    role: 'PACKAGING',
  })
  assert.equal('eos_department_id' in requestBody, false)
  assert.equal(requestBody.role, 'PACKAGING')
})

test('обновляет reference snapshot, показывает totals и не запрашивает остатки', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  const calls: Array<{ url: string; options: RequestInit }> = []
  globalThis.fetch = async (input, options = {}) => {
    const url = String(input)
    calls.push({ url, options })
    const body = url.endsWith('/sync/reference-snapshot')
      ? { status: 'SUCCEEDED' }
      : { items: [], total: url.includes('/products') ? 12 : url.includes('/units') ? 3 : 5, limit: 1, offset: 0 }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    assert.deepEqual(await syncIikoReferenceData(), {
      products: 12,
      units: 3,
      warehouses: 5,
      warning: null,
    })
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
  assert.equal(
    calls[0].url,
    '/api/integrations/iiko/sync/reference-snapshot',
  )
  assert.equal(calls[0].options.method, 'POST')
  assert.deepEqual(
    calls.slice(1).map((call) => call.url).sort(),
    [
      '/api/integrations/iiko/products?limit=1&offset=0',
      '/api/integrations/iiko/units?limit=1&offset=0',
      '/api/integrations/iiko/warehouses?limit=1&offset=0',
    ],
  )
  assert.ok(calls.every((call) => !call.url.includes('stock-balances')))
  assert.ok(calls.every((call) => (
    new Headers(call.options.headers).get('Authorization')
      === 'Bearer test-token'
  )))
})

test('PARTIALLY_SUCCEEDED показывает предупреждение и загружает totals', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  const calls: string[] = []
  globalThis.fetch = async (input) => {
    const url = String(input)
    calls.push(url)
    const body = url.endsWith('/sync/reference-snapshot')
      ? {
          status: 'PARTIALLY_SUCCEEDED',
          error_message: 'Часть справочников iiko недоступна текущим правам',
        }
      : {
          items: [],
          total: url.includes('/products')
            ? 12
            : url.includes('/units') ? 3 : 5,
          limit: 1,
          offset: 0,
        }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    assert.deepEqual(await syncIikoReferenceData(), {
      products: 12,
      units: 3,
      warehouses: 5,
      warning: 'Часть справочников iiko недоступна текущим правам',
    })
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
  assert.equal(calls.length, 4)
  assert.ok(calls.some((url) => url.includes('/products?')))
  assert.ok(calls.some((url) => url.includes('/units?')))
  assert.ok(calls.some((url) => url.includes('/warehouses?')))
})

test('ошибка синхронизации не показывает технические детали', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: 'https://iiko.internal/resto/api: token expired',
  }), {
    status: 502,
    headers: { 'Content-Type': 'application/json' },
  })
  try {
    await assert.rejects(
      syncIikoReferenceData(),
      (error: unknown) => (
        error instanceof IikoMappingApiError
        && error.message === 'Не удалось обновить данные iiko'
      ),
    )
    globalThis.fetch = async () => new Response(JSON.stringify({
      status: 'FAILED',
      error_message: 'IIKO_INTERNAL_ERROR at internal endpoint',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
    await assert.rejects(
      syncIikoReferenceData(),
      (error: unknown) => (
        error instanceof IikoMappingApiError
        && error.message === 'Не удалось обновить данные iiko'
      ),
    )
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
})

test('кнопка предложений доступна только после обновления данных iiko', () => {
  const page = readFileSync(
    new URL('../src/pages/IikoMappingPage.tsx', import.meta.url),
    'utf8',
  )
  assert.match(page, /Обновить данные iiko/)
  assert.match(page, /Данные iiko обновлены: товары/)
  assert.match(page, /syncResult\.warning/)
  assert.match(page, /disabled=\{busyId !== null \|\| !referenceReady\}/)
  assert.match(page, /Формируем предложения…/)
  assert.match(page, /setReferenceReady\(true\)[\s\S]*?await load\(\)/)
  assert.match(page, /await generateMappingCandidates\(\)[\s\S]*?await load\(\)/)
  assert.doesNotMatch(page, /sync\/stock-balances/)
  assert.doesNotMatch(page, /Обновить остатки/)
})

test('долгая генерация остаётся pending без клиентского timeout', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  let resolveResponse: ((response: Response) => void) | undefined
  let callCount = 0
  globalThis.fetch = async () => {
    callCount += 1
    return await new Promise<Response>((resolve) => {
      resolveResponse = resolve
    })
  }
  let settled = false
  try {
    const generation = generateMappingCandidates().finally(() => {
      settled = true
    })
    await Promise.resolve()
    assert.equal(callCount, 1)
    assert.equal(settled, false)
    resolveResponse?.(new Response(JSON.stringify({
      products_created: 1,
      products_updated: 0,
      units_created: 0,
      units_updated: 0,
      warehouses_created: 0,
      warehouses_updated: 0,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    await generation
    assert.equal(settled, true)
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
})

test('gateway timeout переключается на статус того же запуска', async () => {
  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  let generationId = ''
  let callCount = 0
  globalThis.fetch = async (input, options = {}) => {
    callCount += 1
    if (callCount === 1) {
      generationId = new Headers(options.headers).get(
        'X-EOS-Generation-ID',
      ) ?? ''
      return new Response('gateway timeout', { status: 504 })
    }
    assert.match(
      String(input),
      new RegExp(`generation_id=${generationId}`),
    )
    return new Response(JSON.stringify({
      generation_id: generationId,
      status: 'SUCCEEDED',
      result: {
        products_created: 1,
        products_updated: 0,
        units_created: 0,
        units_updated: 0,
        warehouses_created: 0,
        warehouses_updated: 0,
      },
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const result = await generateMappingCandidates()
    assert.equal(result.products_created, 1)
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
  assert.equal(callCount, 2)
  assert.match(generationId, /^[0-9a-f-]{36}$/)
})

test('карточки mapping компактны на desktop и складываются на mobile', () => {
  const styles = readFileSync(
    new URL('../src/App.css', import.meta.url),
    'utf8',
  )
  assert.match(styles, /\.iiko-mapping-row[\s\S]*?min-height: 80px/)
  assert.match(styles, /\.iiko-mapping-actions[\s\S]*?flex-wrap: nowrap/)
  assert.match(
    styles,
    /\.iiko-mapping-actions \.primary-action,[\s\S]*?font-size: 0\.78rem/,
  )
  assert.match(
    styles,
    /@media \(max-width: 900px\)[\s\S]*?grid-template-columns: 1fr/,
  )
})
