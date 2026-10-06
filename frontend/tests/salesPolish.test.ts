import assert from 'node:assert/strict'
import test from 'node:test'
import { salesPeriodOptions, salesPeriodAnchor, sortSalesProducts, type ProductSortKey } from '../src/pages/salesAnalyticsLogic.ts'
import { dashboardAccess } from '../src/pages/dashboardAccess.ts'

test('period pickers use source dates, Monday weeks and API-compatible anchors', () => {
  const months = salesPeriodOptions('month', '2026-04-06', '2026-10-06')
  assert.deepEqual(months[1], { value: '2026-09-01', label: 'Сентябрь 2026' })
  assert.equal(months.at(-1)?.value, '2026-05-01')
  const weeks = salesPeriodOptions('week', '2026-04-06', '2026-10-06')
  assert.deepEqual(weeks[0], { value: '2026-10-05', label: '05.10 — 11.10.2026' })
  assert.equal(salesPeriodAnchor('week', '2026-10-04'), '2026-09-28')
  assert.equal(salesPeriodAnchor('month', '2026-09-25'), '2026-09-01')
  assert.equal(salesPeriodOptions('week', '', '').length, 0)
})
test('all product columns sort both directions without mutating the source', () => {
  const rows = [
    { product_name: 'Яблоко', department_name: 'Юг', category: 'Фрукты', quantity: '10', revenue: '-20.5', previous_quantity: '2.5', previous_revenue: '10' },
    { product_name: 'Абрикос', department_name: 'Восток', category: null, quantity: '2', revenue: '9', previous_quantity: '0', previous_revenue: '2' },
  ]
  for (const key of Object.keys(rows[0]) as ProductSortKey[]) {
    const asc = sortSalesProducts(rows, key, 'asc'), desc = sortSalesProducts(rows, key, 'desc')
    assert.deepEqual(desc, [...asc].reverse())
    assert.notEqual(asc, rows)
  }
  assert.equal(sortSalesProducts(rows, 'quantity', 'asc')[0].product_name, 'Абрикос')
  assert.equal(sortSalesProducts(rows, 'revenue', 'asc')[0].product_name, 'Яблоко')
  assert.equal(rows[0].product_name, 'Яблоко')
})
test('ADMIN has the union of dashboard widget permissions', () => {
  const admin = dashboardAccess(['ADMIN'])
  for (const role of ['NETWORK_MANAGER', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'ACCOUNTANT', 'SUPPLY_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER', 'SELLER'] as const) {
    const access = dashboardAccess([role])
    for (const key of ['readRepairs', 'readSupplySummary', 'readOperationalSupply', 'readFinance'] as const) {
      if (access[key]) assert(admin[key], `${role}: ${key}`)
    }
  }
})

test('Statistics controls preserve requests, sort locally and enforce target edit visibility', async () => {
  const React = await import('react')
  const { act } = React
  const { createRoot } = await import('react-dom/client')
  const { MemoryRouter, Routes, Route } = await import('react-router-dom')
  const { createServer } = await import('vite')
  const { JSDOM } = await import('jsdom')
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const names = ['window', 'document', 'sessionStorage', 'IS_REACT_ACT_ENVIRONMENT']
  const previous = names.map(name => Object.getOwnPropertyDescriptor(globalThis, name))
  const originalFetch = globalThis.fetch
  let root: ReturnType<typeof createRoot> | undefined
  try {
    const { default: Page } = await server.ssrLoadModule('/src/pages/StatisticsPage.tsx')
    const { AuthProvider } = await server.ssrLoadModule('/src/contexts/AuthContext.tsx')
    for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document, sessionStorage: dom.window.sessionStorage, IS_REACT_ACT_ENVIRONMENT: true })) Object.defineProperty(globalThis, name, { configurable: true, value })
    sessionStorage.setItem('eos_access_token', 'test')
    const calls: string[] = []
    let role = 'ADMIN'
    const period = { kind: 'month', start: '2026-09-01', end: '2026-09-30', previous_start: '2026-08-02', previous_end: '2026-08-31' }
    const products = ['Яблоко', 'Абрикос'].map((name, index) => ({ iiko_product_id: String(index), department_id: 'point', department_name: 'Точка', product_name: name, category: 'Фрукты', quantity: index ? '2' : '10', revenue: '100', previous_quantity: '1', previous_revenue: '50', check_count: 1, dynamics: [] }))
    const workspace = { completeness: { warning: false }, status: { today: '2026-10-06', history_from: '2026-04-06', last_success_at: null }, points: [], sellers: [], products: { period, products, summaries: products, categories: ['Фрукты'], dynamics: [] } }
    globalThis.fetch = async input => {
      const url = String(input); calls.push(url)
      if (url === '/api/auth/me') return Response.json({ id: 1 })
      if (url.includes('action-context')) return Response.json({ roles: [role] })
      if (url.includes('/targets')) return Response.json([])
      assert(url.includes('/workspace'))
      return Response.json(workspace)
    }
    root = createRoot(document.getElementById('root')!)
    const render = () => React.createElement(AuthProvider, { key: role }, React.createElement(MemoryRouter, { initialEntries: ['/statistics/products?period=month&anchor=2026-09-25'] }, React.createElement(Routes, null, React.createElement(Route, { path: '/statistics/:view', element: React.createElement(Page) }))))
    await act(async () => { root!.render(render()) })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 200)) })
    assert(document.querySelector('.page-shell.statistics-page'))
    assert.equal(document.querySelector<HTMLSelectElement>('label:nth-child(2) select')?.selectedOptions[0].textContent, 'Сентябрь 2026')
    assert.equal(document.querySelector('.statistics-filters .statistics-export button')?.textContent, 'Выгрузить ⌄')
    assert(!document.body.textContent?.includes('Открыть продукцию и категории'))
    assert.equal(document.querySelectorAll('.statistics-tabs').length, 1)
    assert(!document.querySelector('.statistics-target-form'), 'ADMIN cannot edit targets')
    const heading = Array.from(document.querySelectorAll<HTMLButtonElement>('.statistics-sort-heading')).find(button => button.textContent?.startsWith('Количество'))!
    const before = calls.length
    await act(async () => heading.click())
    assert.equal(heading.closest('th')?.getAttribute('aria-sort'), 'ascending')
    assert.equal(document.querySelector('tbody tr td')?.textContent, 'Абрикос')
    await act(async () => heading.click())
    assert.equal(heading.closest('th')?.getAttribute('aria-sort'), 'descending')
    assert.equal(document.querySelector('tbody tr td')?.textContent, 'Яблоко')
    assert.equal(calls.length, before, 'sort does not fetch or rebuild snapshots')
    const exportButton = document.querySelector<HTMLButtonElement>('.statistics-export button')!
    await act(async () => exportButton.click())
    assert.equal(exportButton.getAttribute('aria-expanded'), 'true')
    assert.deepEqual(Array.from(document.querySelectorAll('.statistics-export .statistics-menu-options button')).map(button => button.textContent), ['Excel', 'PDF'])
    await act(async () => document.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    assert.equal(exportButton.getAttribute('aria-expanded'), 'false')
    assert.equal(document.activeElement, exportButton)
    role = 'DEPUTY_DIRECTOR'
    await act(async () => { root!.render(render()) })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 200)) })
    assert(document.querySelector('.statistics-target-form'))
    const selects = document.querySelectorAll<HTMLSelectElement>('.statistics-filters select')
    await act(async () => { selects[0].value = 'week'; selects[0].dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 200)) })
    assert.equal(document.querySelectorAll<HTMLSelectElement>('.statistics-filters select')[1].selectedOptions[0].textContent, '05.10 — 11.10.2026')
    assert(calls.at(-1)?.includes('period=week'))
    const periodSelect = document.querySelector<HTMLSelectElement>('.statistics-filters select')!
    await act(async () => { periodSelect.value = 'custom'; periodSelect.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 200)) })
    assert.equal(document.querySelectorAll('.statistics-filters input[type="date"]').length, 2)
    assert(calls.at(-1)?.includes('start=2026-10-06&end=2026-10-06'))
  } finally {
    if (root) await act(async () => root!.unmount())
    globalThis.fetch = originalFetch
    names.forEach((name, index) => { if (previous[index]) Object.defineProperty(globalThis, name, previous[index]!); else Reflect.deleteProperty(globalThis, name) })
    dom.window.close(); await server.close()
  }
})
