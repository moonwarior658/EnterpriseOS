import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  iikoMappingStatusLabel,
  iikoWarehouseRoleLabel,
  mappingActionLabel,
} from '../src/pages/iikoMappingLogic.ts'
import {
  IikoMappingApiError,
  mappingQuery,
  syncIikoReferenceData,
} from '../src/services/iikoMapping.ts'


test('показывает безопасные русские статусы и роли mapping', () => {
  assert.equal(iikoMappingStatusLabel('SUGGESTED'), 'Предложено')
  assert.equal(iikoMappingStatusLabel('CONFLICT'), 'Конфликт')
  assert.equal(iikoWarehouseRoleLabel('FIXED_ASSETS'), 'Основные средства')
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
  assert.match(page, /Сформировать предложения/)
  assert.match(page, /Игнорировать/)
  assert.match(page, /Снять связь/)
  assert.match(page, /Показывать удалённые/)
  assert.match(page, /Только конфликты/)
  assert.match(app, /ProtectedRoute adminOnly><IikoMappingPage/)
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
  assert.match(page, /setReferenceReady\(true\)[\s\S]*?await load\(\)/)
  assert.doesNotMatch(page, /sync\/stock-balances/)
  assert.doesNotMatch(page, /Обновить остатки/)
})
