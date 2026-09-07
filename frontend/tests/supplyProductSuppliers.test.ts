import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  archiveSupplyProductSupplier,
  createSupplyProductSupplier,
  getSupplyProductSuppliers,
  makePrimarySupplyProductSupplier,
  restoreSupplyProductSupplier,
  updateSupplyProductSupplier,
} from '../src/services/supplyAdmin.ts'

test('управление поставщиками встроено в карточку товара mapping', () => {
  const mappingPage = readFileSync(
    new URL('../src/pages/IikoMappingPage.tsx', import.meta.url), 'utf8',
  )
  const panel = readFileSync(
    new URL('../src/pages/SupplyProductSuppliersPanel.tsx', import.meta.url),
    'utf8',
  )
  assert.match(mappingPage, /SupplyProductSuppliersPanel/)
  assert.match(mappingPage, />\s*Поставщики\s*</)
  assert.match(panel, /Добавить поставщика/)
  assert.match(panel, /Назначить основным/)
  assert.match(panel, /Архивировать/)
  assert.match(panel, /Восстановить/)
  assert.match(panel, /Цена упаковки/)
  assert.match(panel, /За базовую единицу/)
  assert.match(panel, /getSupplySuppliers\(true/)
  assert.doesNotMatch(panel, />UUID</)
})

test('API-клиент использует nested relation endpoints и атомарный make-primary', async () => {
  const calls: Array<{ url: string; options: RequestInit }> = []
  const originalFetch = globalThis.fetch
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: {
      getItem: () => 'token', setItem: () => undefined,
      removeItem: () => undefined,
    },
  })
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getSupplyProductSuppliers('product', true)
    await createSupplyProductSupplier('product', {
      supplier_id: 'supplier', package_quantity: '12',
      package_unit_id: 'box',
    })
    await updateSupplyProductSupplier('product', 'relation', { priority: 20 })
    await archiveSupplyProductSupplier('product', 'relation')
    await restoreSupplyProductSupplier('product', 'relation')
    await makePrimarySupplyProductSupplier('product', 'relation')
  } finally {
    globalThis.fetch = originalFetch
  }
  assert.equal(calls[0].url, '/api/supply/products/product/suppliers?active=true')
  assert.equal(calls[1].options.method, 'POST')
  assert.equal(calls[2].options.method, 'PATCH')
  assert.match(calls[3].url, /\/archive$/)
  assert.match(calls[4].url, /\/restore$/)
  assert.match(calls[5].url, /\/make-primary$/)
  assert.equal(calls[5].options.method, 'POST')
})
