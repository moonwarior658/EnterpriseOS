import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  archiveSupplySupplier,
  confirmSupplySupplierIikoMapping,
  createSupplySupplier,
  getIikoSupplierReferences,
  getSupplySupplier,
  getSupplySupplierIikoMapping,
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
  minimum_order_amount: '10000.00',
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
  const form = readFileSync(
    new URL('../src/pages/SupplySupplierForm.tsx', import.meta.url),
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
  assert.match(form, /Минимальная сумма заказа/)
  assert.match(form, /minimumOrderAmountError/)
})

test('карточка поставщика покрывает empty, search, confirm, remap, deleted warning и readiness', () => {
  const form = readFileSync(
    new URL('../src/pages/SupplySupplierForm.tsx', import.meta.url), 'utf8',
  )
  const panel = readFileSync(
    new URL('../src/components/SupplierIikoMappingPanel.tsx', import.meta.url),
    'utf8',
  )
  assert.match(form, /SupplierIikoMappingPanel/)
  assert.match(panel, /Поставщик ещё не сопоставлен/)
  assert.match(panel, /getIikoSupplierReferences/)
  assert.match(panel, /setSelected\(item\)/)
  assert.match(panel, /confirmSupplySupplierIikoMapping/)
  assert.match(panel, /Изменить сопоставление/)
  assert.match(panel, /window\.confirm/)
  assert.match(panel, /item\.is_deleted \|\| !item\.is_active/)
  assert.match(panel, /Удалён в iiko/)
  assert.match(panel, /iiko_receipt_ready_supplier_mapping/)
  assert.doesNotMatch(panel, />GUID</)
})

test('API-клиент использует supplier mapping read, search и explicit confirm endpoints', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'token', setItem: () => undefined, removeItem: () => undefined },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify({
      items: [], total: 0, mapping: null, history: [],
      iiko_receipt_ready_supplier_mapping: false, warning: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try {
    await getSupplySupplierIikoMapping('supplier')
    await getIikoSupplierReferences('supplier', ' Альфа ', true)
    await confirmSupplySupplierIikoMapping('supplier', 'iiko-supplier')
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.equal(calls[0].url, '/api/supply/suppliers/supplier/iiko-mapping')
  assert.match(calls[1].url, /\/api\/supply\/iiko\/suppliers\?/)
  assert.match(calls[1].url, /supplier_id=supplier/)
  assert.match(calls[1].url, /search=%D0%90%D0%BB%D1%8C%D1%84%D0%B0/)
  assert.match(calls[1].url, /include_deleted=true/)
  assert.equal(calls[2].options.method, 'POST')
  assert.deepEqual(JSON.parse(String(calls[2].options.body)), {
    iiko_supplier_id: 'iiko-supplier',
  })
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
    minimum_order_amount: '10000.00',
  })

  const invalid = buildSupplierPayload(EMPTY_SUPPLIER_FORM)
  assert.equal(invalid.status, 'validation')
  assert.equal(
    invalid.status === 'validation' ? invalid.errors.displayName : '',
    'Укажите отображаемое название',
  )
})

test('минимальную сумму можно изменить, очистить и нельзя сделать отрицательной', () => {
  const values = supplierToFormValues(SUPPLIER)
  assert.equal(values.minimumOrderAmount, '10000.00')

  const updated = buildSupplierPayload({
    ...values,
    minimumOrderAmount: '12 500 ₽',
  })
  assert.equal(updated.status, 'success')
  assert.equal(
    updated.status === 'success' ? updated.payload.minimum_order_amount : null,
    '12500',
  )

  const decimal = buildSupplierPayload({
    ...values,
    minimumOrderAmount: '12500,50',
  })
  assert.equal(decimal.status, 'success')
  assert.equal(
    decimal.status === 'success' ? decimal.payload.minimum_order_amount : null,
    '12500.50',
  )

  const cleared = buildSupplierPayload({ ...values, minimumOrderAmount: '' })
  assert.equal(cleared.status, 'success')
  assert.equal(
    cleared.status === 'success' ? cleared.payload.minimum_order_amount : 'x',
    null,
  )

  const negative = buildSupplierPayload({
    ...values,
    minimumOrderAmount: '-1',
  })
  assert.equal(negative.status, 'validation')
  assert.equal(
    negative.status === 'validation'
      ? negative.errors.minimumOrderAmount
      : '',
    'Укажите неотрицательную сумму с точностью до копеек',
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
