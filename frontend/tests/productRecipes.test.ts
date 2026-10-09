import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'

test('exact recipe decimals, zero, missing values and safe errors', async () => {
  const server = await createServer({ server: { middlewareMode: true, ws: false }, appType: 'custom' })
  try {
  const { recipeNorm, RecipeApiError } = await server.ssrLoadModule('/src/services/productRecipes.ts')
  assert.equal(recipeNorm('0.00000000123456789'), '0,00000000123456789')
  assert.equal(recipeNorm('0'), '0'); assert.equal(recipeNorm(null), 'Нет данных')
  assert.match(new RecipeApiError(403).message, /Нет доступа/)
  } finally { await server.close() }
})

test('recipe UI: nested/source/prepared/history, confirmation and manual update with Core progress', async () => {
  const server = await createServer({ server: { middlewareMode: true, ws: false }, appType: 'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const values = { window: dom.window, document: dom.window.document, getComputedStyle: dom.window.getComputedStyle, IS_REACT_ACT_ENVIRONMENT: true, sessionStorage: dom.window.sessionStorage }
  const previous = Object.keys(values).map(name => Object.getOwnPropertyDescriptor(globalThis, name)), originalFetch = globalThis.fetch
  let root: ReturnType<typeof import('react-dom/client').createRoot> | undefined
  const row = { product_id: 'child', name: 'Крем', unit: 'кг', gross: '0.00000000123456789', net: '0', output: null, writeoff: null, scope_note: null }
  const chart = { version_id: 'source-version', chart_id: 'source-chart', product_id: 'root', kind: 'SOURCE', roles: ['ASSEMBLED','TREE','HISTORY'], name: 'Эклер', unit: 'шт', valid_from: '2026-06-01', valid_to: null, base_amount: '1', technology: '<script>Исходный текст</script>', writeoff_strategy: 'Через приготовление', size_strategy: 'Общая рецептура', store_note: 'Производственный склад не подтверждён', items: [row] }
  const nested = { ...chart, version_id: 'nested-version', product_id: 'child', name: 'Крем', roles: ['TREE'], items: [{ ...row, product_id: 'goods', name: 'Молоко', gross: '0.15', net: '0.15', output: '0.1' }] }
  const prepared = { ...chart, version_id: 'writeoff-version', kind: 'PREPARED', roles: ['PREPARED'], technology: null, items: [{ ...row, product_id: 'goods', name: 'Молоко', gross: null, net: null, output: null, writeoff: '0.15' }] }
  const approval = { author: 'Шеф', employee_id: 'employee', confirmed_at: '2026-10-09T10:00:00Z', evidence: 'Сверено в iikoOffice', version_ids: ['source-version','nested-version'] }
  const observation = { id: 'observation', manifest_hash: 'a'.repeat(64), root_product_id: 'root', effective_on: '2026-10-09', observed_at: '2026-10-09T09:00:00Z', status: 'UNCONFIRMED', status_label: 'Требует проверки', is_current: true, ready_for_production: false, issues: ['Производственный склад не подтверждён'], charts: [chart,nested,prepared], confirmation: null as typeof approval | null }
  const data = { contexts: [{ key: 'c'.repeat(64), label: 'Производство', warehouse_label: 'Склад не подтверждён', size_label: 'Размер не подтверждён' }], context_key: 'c'.repeat(64), observation, last_updated_at: observation.observed_at, history: [{ id: 'old-observation', effective_on: '2026-05-31', observed_at: '2026-10-09T08:00:00Z', status: 'INCOMPLETE', status_label: 'Неполные данные', is_current: false, confirmation: null, version_ids: ['old-version'] }], total: 1, offset: 0, limit: 20, allowed_actions: ['CONFIRM','REFRESH'], refresh: null as { state: string; label: string; active: boolean; requested_at: string; finished_at: string | null } | null }
  const posts: { url: string; body: Record<string,string> }[] = []
  let mode = 'normal', release: (() => void) | undefined
  try {
    Object.entries(values).forEach(([name, value]) => Object.defineProperty(globalThis, name, { configurable: true, value }))
    globalThis.fetch = async (input, init) => {
      const url = new URL(String(input), 'http://localhost')
      if (init?.method === 'POST') {
        posts.push({ url: url.pathname, body: JSON.parse(String(init.body)) })
        if (url.pathname.endsWith('/confirm')) { observation.confirmation = approval; data.allowed_actions = ['REFRESH']; return Response.json(data) }
        await new Promise<void>(resolve => { release = resolve })
        data.refresh = { state: 'pending', label: 'Ожидает обновления', active: true, requested_at: observation.observed_at, finished_at: null }
        return Response.json({ refresh: data.refresh }, { status: 202 })
      }
      if (mode === 'error') return new Response('{"detail":"private stack"}', { status: 503 })
      if (url.searchParams.get('observation_id')) return Response.json({ ...data, observation: { ...observation, id: 'old-observation', is_current: false, status: 'INCOMPLETE', status_label: 'Неполные данные', confirmation: null }, allowed_actions: ['REFRESH'] })
      return Response.json(data)
    }
    const { createRoot } = await import('react-dom/client'), { ProductRecipes } = await server.ssrLoadModule('/src/pages/productKnowledge/ProductRecipes.tsx')
    root = createRoot(document.getElementById('root')!)
    await act(async () => { root!.render(React.createElement(ProductRecipes, { productId: 'product' })) })
    const body = () => document.body.textContent!
    const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === label)!
    assert.match(body(), /Требует проверки/); assert.match(body(), /0,00000000123456789/); assert.match(body(), /Нет данных/)
    assert.match(body(), /Рецептура полуфабриката/); assert.match(body(), /Проекция списания iiko/); assert.match(body(), /Версии из истории iiko/)
    assert.equal(document.querySelector('script'), null); assert.match(body(), /Готовность к производству не подтверждена/)
    assert.equal(button('Подтвердить версию').disabled, true)
    await act(async () => document.querySelector<HTMLInputElement>('input[type=checkbox]')!.click())
    const textarea = document.querySelector('textarea')!
    await act(async () => { Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, 'Office: нормы и вложенные версии сверены'); textarea.dispatchEvent(new dom.window.Event('input', { bubbles: true })); textarea.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    assert.equal(button('Подтвердить версию').disabled, false)
    await act(async () => button('Подтвердить версию').click())
    assert.equal(posts[0].body.observation_id, 'observation'); assert.equal(posts[0].body.manifest_hash, 'a'.repeat(64))
    assert.match(body(), /Сверка исходной версии подтверждена/); assert.match(body(), /Шеф/)
    assert.match(body(), /Готовность к производству не подтверждена/); assert.doesNotMatch(body(), /execution_id|raw_payload|private stack/)
    await act(async () => { button('Обновить из iiko').click(); button('Обновить из iiko').click() })
    assert.equal(posts.length, 2); assert.deepEqual(Object.keys(posts[1].body).sort(), ['context_key','effective_on','request_id'])
    await act(async () => release!())
    assert.match(body(), /Ожидает обновления/); assert.equal(button('Обновить из iiko').disabled, true)
    observation.id = 'new-observation'; observation.confirmation = null
    data.refresh = { ...data.refresh!, state: 'succeeded', label: 'Обновление завершено', active: false, finished_at: '2026-10-09T10:05:00Z' }; data.allowed_actions = ['CONFIRM','REFRESH']
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 2650)) })
    assert.match(body(), /Обновление завершено/); assert.equal(button('Подтвердить версию').disabled, true)
    await act(async () => document.querySelector<HTMLButtonElement>('.recipe-history button')!.click())
    assert.match(body(), /Историческое наблюдение/); assert.match(body(), /Неполные данные/); assert.equal(button('Подтвердить версию'), undefined)
    mode = 'error'; await act(async () => button('К последнему наблюдению').click())
    assert.match(body(), /Не удалось получить результат/); assert.doesNotMatch(body(), /private stack/)
    mode = 'normal'; await act(async () => button('Повторить загрузку').click()); assert.match(body(), /Требует проверки/)
  } finally {
    if (root) await act(async () => root!.unmount())
    globalThis.fetch = originalFetch
    Object.keys(values).forEach((name, index) => { if (previous[index]) Object.defineProperty(globalThis, name, previous[index]!); else Reflect.deleteProperty(globalThis, name) })
    await server.close(); dom.window.close()
  }
})
