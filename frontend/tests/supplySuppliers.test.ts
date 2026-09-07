import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  archiveSupplySupplier,
  createSupplySupplier,
  getSupplySupplier,
  getSupplySuppliers,
  restoreSupplySupplier,
  SupplyApiError,
  updateSupplySupplier,
  type SupplySupplier,
} from '../src/services/supplyAdmin.ts'
import {
  buildSupplierPayload,
  EMPTY_SUPPLIER_FORM,
  supplierErrorMessage,
  supplierToFormValues,
} from '../src/pages/supplySupplierLogic.ts'

const SUPPLIER: SupplySupplier = {
  id: 'supplier-id',
  display_name: 'Новопак',
  legal_name: 'ООО Новопак',
  inn: '6671000001',
  kpp: '667101001',
  ogrn: '1026600000001',
  legal_address: 'Екатеринбург',
  actual_address: null,
  bank_name: 'Банк',
  bik: '046577000',
  correspondent_account: '30101810000000000000',
  settlement_account: '40702810000000000000',
  order_email: 'orders@example.test',
  phone: '+7 900 000-00-00',
  comment: 'Упаковка',
  is_active: true,
  archived_at: null,
  archived_by_user_id: null,
  created_at: '2026-09-07T08:00:00Z',
  updated_at: '2026-09-07T08:00:00Z',
}

test('подключает admin-only route и пункт навигации поставщиков', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(
    new URL('../src/layouts/AppLayout.tsx', import.meta.url),
    'utf8',
  )
  const page = readFileSync(
    new URL('../src/pages/SupplySuppliersPage.tsx', import.meta.url),
    'utf8',
  )

  assert.match(app, /path="\/supply\/suppliers"/)
  assert.match(app, /ProtectedRoute adminOnly/)
  assert.match(layout, /to="\/supply\/suppliers"/)
  assert.match(layout, /Поставщики/)
  assert.match(page, /Активные/)
  assert.match(page, /Архив/)
  assert.match(page, /window\.confirm/)
  assert.match(page, /Восстановить/)
  assert.doesNotMatch(page, />ID</)
  assert.doesNotMatch(page, /archived_by_user_id/)
})

test('форма нормализует строки и отправляет все backend-поля', () => {
  const values = supplierToFormValues(SUPPLIER)
  const result = buildSupplierPayload({
    ...values,
    displayName: '  Рестоэксперт  ',
    actualAddress: '   ',
  })

  assert.equal(result.status, 'success')
  assert.deepEqual(result.status === 'success' ? result.payload : null, {
    display_name: 'Рестоэксперт',
    legal_name: 'ООО Новопак',
    inn: '6671000001',
    kpp: '667101001',
    ogrn: '1026600000001',
    legal_address: 'Екатеринбург',
    actual_address: null,
    bank_name: 'Банк',
    bik: '046577000',
    correspondent_account: '30101810000000000000',
    settlement_account: '40702810000000000000',
    order_email: 'orders@example.test',
    phone: '+7 900 000-00-00',
    comment: 'Упаковка',
  })

  const invalid = buildSupplierPayload(EMPTY_SUPPLIER_FORM)
  assert.equal(invalid.status, 'validation')
  assert.equal(
    invalid.status === 'validation' ? invalid.errors.displayName : '',
    'Укажите отображаемое название',
  )
})

test('ошибки Supplier API переводятся в безопасные русские сообщения', () => {
  assert.equal(
    supplierErrorMessage(
      new SupplyApiError('raw', null, null, 409),
      'fallback',
    ),
    'Активный поставщик с таким ИНН уже существует',
  )
  assert.equal(
    supplierErrorMessage(
      new SupplyApiError('raw', null, null, 404),
      'fallback',
    ),
    'Поставщик не найден. Обновите список.',
  )
  assert.equal(
    supplierErrorMessage(
      new SupplyApiError('raw', null, null, 403),
      'fallback',
    ),
    'Недостаточно прав для работы со справочником поставщиков',
  )
  assert.equal(
    supplierErrorMessage(
      new SupplyApiError('raw', null, null, 422),
      'fallback',
    ),
    'Проверьте заполнение полей поставщика',
  )
})

test('API-клиент использует supplier list/detail/create/update/archive/restore', async () => {
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
    return new Response(JSON.stringify(SUPPLIER), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  try {
    await getSupplySuppliers(true, 'Ново', 50, 25)
    await getSupplySupplier('supplier-id')
    await createSupplySupplier({ display_name: 'Новопак' })
    await updateSupplySupplier('supplier-id', { display_name: 'Новопак 2' })
    await archiveSupplySupplier('supplier-id')
    await restoreSupplySupplier('supplier-id')
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.match(calls[0].url, /active=true/)
  assert.match(calls[0].url, /search=%D0%9D%D0%BE%D0%B2%D0%BE/)
  assert.match(calls[0].url, /offset=50/)
  assert.match(calls[0].url, /limit=25/)
  assert.equal(calls[1].url, '/api/supply/suppliers/supplier-id')
  assert.equal(calls[2].options.method, 'POST')
  assert.equal(calls[3].options.method, 'PATCH')
  assert.match(calls[4].url, /\/archive$/)
  assert.match(calls[5].url, /\/restore$/)
})
