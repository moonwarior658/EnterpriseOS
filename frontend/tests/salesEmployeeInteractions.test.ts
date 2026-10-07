import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'

test('Employee role submit displays failure inside dialog, preserves reason, guards duplicate and refreshes success', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const names = ['window', 'document', 'sessionStorage', 'getComputedStyle', 'IS_REACT_ACT_ENVIRONMENT']
  const previous = names.map(name => Object.getOwnPropertyDescriptor(globalThis, name))
  const originalFetch = globalThis.fetch
  let root: ReturnType<typeof import('react-dom/client').createRoot> | undefined
  try {
    dom.window.scrollTo = () => {}
    for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document, sessionStorage: dom.window.sessionStorage, getComputedStyle: dom.window.getComputedStyle, IS_REACT_ACT_ENVIRONMENT: true })) Object.defineProperty(globalThis, name, { configurable: true, value })
    const { createRoot } = await import('react-dom/client')
    const { default: Page } = await server.ssrLoadModule('/src/pages/EmployeeDetailPage.tsx')
    const { AuthProvider } = await server.ssrLoadModule('/src/contexts/AuthContext.tsx')
    sessionStorage.setItem('eos_access_token', 'test')
    const employee = { profile_level: 'FULL', id: 'employee', full_name: 'Test Employee', phone: '', residence_address: '', birth_date: '1990-01-01', photo_url: null, status: 'ACTIVE', allowed_actions: [], role_assignments: [] as object[], department_assignments: [], lifecycle_events: [], linked_user_id: null }
    const posts: object[] = []
    let succeed = false, failSearch = false
    globalThis.fetch = async (input, options = {}) => {
      const url = String(input)
      if (url === '/api/auth/me') return Response.json({ id: 1 })
      if (url.includes('action-context')) return Response.json({ roles: ['ADMIN'], employee_id: 'admin' })
      if (url.endsWith('/roles') && options.method === 'POST') {
        const payload = JSON.parse(String(options.body)); posts.push(payload)
        if (!succeed) return Response.json({ detail: 'Для роли требуется одно основное подразделение допустимой категории' }, { status: 409 })
        const assignment = { id: 'role-1', role: payload.role, valid_from: payload.valid_from, valid_to: null, reason: payload.reason }
        employee.role_assignments.push(assignment)
        return Response.json(assignment, { status: 201 })
      }
      if (url.endsWith('/iiko/candidates')) return failSearch ? Response.json({ detail: 'IIKO_CONNECTION_ERROR' }, { status: 502 }) : Response.json([{ iiko_user_id: 'stable', display_name: 'Test Employee', is_deleted: false }])
      if (url.endsWith('/iiko/link') || url.endsWith('/shifts/active')) return Response.json(null)
      if (url === '/api/employees/employee') return Response.json(employee)
      if (url === '/api/employees') return Response.json([employee])
      return Response.json([])
    }
    root = createRoot(document.getElementById('root')!)
    await act(async () => root!.render(React.createElement(AuthProvider, null, React.createElement(MemoryRouter, { initialEntries: ['/employees/employee'] }, React.createElement(Routes, null, React.createElement(Route, { path: '/employees/:employeeId', element: React.createElement(Page) }))))))
    const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 40)) })
    await settle(); await settle()
    const button = (text: string) => Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(b => b.textContent === text)!
    await act(async () => button('Изменить').click())
    await act(async () => button('Роли').click())
    let form = document.querySelector<HTMLFormElement>('.employee-role-assignment-form')!
    assert(form)
    const reason = form.querySelector<HTMLInputElement>('input:not([type="datetime-local"])')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value')!.set!.call(reason, 'Назначение по решению')
      reason.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
      reason.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
    })
    await act(async () => form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true })))
    assert.equal(posts.length, 1)
    assert(document.querySelector('[role="dialog"] [role="alert"]')?.textContent?.includes('основное подразделение'))
    assert.equal(reason.value, 'Назначение по решению')
    succeed = true
    await act(async () => {
      form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))
      form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))
    })
    await settle()
    assert.equal(posts.length, 2, 'double submission sends only one successful request')
    assert.equal(employee.role_assignments.length, 1)
    form = document.querySelector<HTMLFormElement>('.employee-role-assignment-form')!
    assert(form.closest('[role="dialog"]')?.textContent?.includes('Назначение по решению'))
    assert.equal(form.querySelector<HTMLInputElement>('input:not([type="datetime-local"])')!.value, '')
    assert.match((posts[1] as { valid_from: string }).valid_from, /Z$/)
    await act(async () => button('iiko').click())
    assert(document.querySelector('option[value="stable"]'))
    failSearch = true
    await act(async () => button('Найти сотрудника iiko').click())
    assert(document.querySelector('[role="dialog"] [role="alert"]')?.textContent?.includes('Не удалось'))
    assert(!document.querySelector('[role="dialog"]')?.textContent?.includes('Кандидаты по ФИО не найдены'))

  } finally {
    if (root) await act(async () => root!.unmount())
    globalThis.fetch = originalFetch
    names.forEach((name, i) => { if (previous[i]) Object.defineProperty(globalThis, name, previous[i]!); else Reflect.deleteProperty(globalThis, name) })
    dom.window.close(); await server.close()
  }
})

test('Seller master-detail synchronizes row and selector, replaces one mix, sorts columns and preserves filters', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const names = ['window', 'document', 'sessionStorage', 'getComputedStyle', 'IS_REACT_ACT_ENVIRONMENT']
  const previous = names.map(name => Object.getOwnPropertyDescriptor(globalThis, name))
  const originalFetch = globalThis.fetch
  let root: ReturnType<typeof import('react-dom/client').createRoot> | undefined
  try {
    dom.window.scrollTo = () => {}
    for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document, sessionStorage: dom.window.sessionStorage, getComputedStyle: dom.window.getComputedStyle, IS_REACT_ACT_ENVIRONMENT: true })) Object.defineProperty(globalThis, name, { configurable: true, value })
    const { createRoot } = await import('react-dom/client')
    const { AuthProvider } = await server.ssrLoadModule('/src/contexts/AuthContext.tsx')
    const button = (text: string) => Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(b => b.textContent === text)!
    sessionStorage.setItem('eos_access_token', 'test')
    root = createRoot(document.getElementById('root')!)
    const { default: Statistics } = await server.ssrLoadModule('/src/pages/StatisticsPage.tsx')
    const calls: string[] = []
    const period = { kind: 'month', start: '2026-09-01', end: '2026-09-30', previous_start: '2026-08-02', previous_end: '2026-08-31' }
    const emptyMetric = { fact: '100', completion_percent: null, status: 'no_target' }
    const metrics = Object.fromEntries(['revenue', 'check_count', 'average_check', 'fullness'].map(key => [key, emptyMetric]))
    let failMix = false, deferMix = false
    const pending: { resolve: (value: Response) => void; response: Response }[] = []
    globalThis.fetch = async input => {
      const url = String(input); calls.push(url)
      if (url === '/api/auth/me') return Response.json({ id: 1 })
      if (url.includes('action-context')) return Response.json({ roles: ['ADMIN'] })
      const query = new URL(url, 'http://localhost').searchParams
      const id = query.get('employee_id') || 'employee'
      if (query.get('view') === 'seller-products' && failMix) return Response.json({}, { status: 503 })
      const response = Response.json({ status: { today: '2026-10-07', history_from: '2026-04-01' }, completeness: { warning: false },
        points: [{ department_id: 'point', department_name: 'Точка' }],
        sellers: [{ employee_id: 'employee', employee_name: 'Test Employee', metrics }, { employee_id: 'second', employee_name: 'Second Employee', metrics }].filter(s => !query.get('employee_id') || s.employee_id === query.get('employee_id')),
        ...(query.get('view') === 'seller-products' ? { seller_mix: { employee_id: id, employee_name: id === 'employee' ? 'Test Employee' : 'Second Employee', period, completeness: { warning: false }, categories: ['Dessert'], dynamics: [], products: [{ iiko_product_id: 'cake', product_name: id === 'employee' ? 'Cake' : 'Second Cake', category: 'Dessert', quantity: '2', revenue: '100', share_percent: '50', previous_quantity: '1', previous_revenue: '40', quantity_change: '1', revenue_change: '60' }, { iiko_product_id: 'z-cake', product_name: 'Z Cake', category: 'Dessert Z', quantity: '10', revenue: '200', share_percent: '70', previous_quantity: '3', previous_revenue: '90', quantity_change: '7', revenue_change: '110' }] } } : {}) })
      if (query.get('view') === 'seller-products' && deferMix) {
        deferMix = false
        return new Promise<Response>(resolve => pending.push({ resolve, response }))
      }
      return response
    }
    await act(async () => root!.render(React.createElement(AuthProvider, { key: 'statistics' }, React.createElement(MemoryRouter, { initialEntries: ['/statistics/sellers?period=month&anchor=2026-09-01&department_id=point&staff=all'] }, React.createElement(Routes, null, React.createElement(Route, { path: '/statistics/:view', element: React.createElement(Statistics) }))))))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 220)) })
    assert(!document.querySelector('.statistics-seller-mix'))
    assert(!Array.from(document.querySelectorAll('a')).some(a => a.href.includes('/statistics/seller-products')))
    assert(!Array.from(document.querySelectorAll('.statistics-seller-row a')).some(a => a.textContent === 'Продукция'))
    const sellerSelector = () => Array.from(document.querySelectorAll<HTMLSelectElement>('.statistics-filters select')).find(s => s.closest('label')?.textContent?.startsWith('Продавец'))!
    const selectSeller = async (id: string) => act(async () => {
      const selector = sellerSelector(); selector.value = id
      selector.dispatchEvent(new dom.window.Event('change', { bubbles: true }))
    })
    // Row/name selection updates the same selector and detail while keeping every master row.
    await act(async () => button('Test Employee').click())
    assert.equal(sellerSelector().value, 'employee')
    assert.equal(document.querySelectorAll('.statistics-seller-row').length, 2)
    let mix = document.querySelector('.statistics-seller-mix')!
    assert(mix.querySelector('h2')?.textContent === 'Продукция продавца: Test Employee')
    assert(mix.textContent?.includes('Cake'))
    assert(button('Test Employee').closest('tr')?.classList.contains('is-active'))
    assert.equal(button('Test Employee').getAttribute('aria-pressed'), 'true')
    assert.equal(button('Test Employee').closest('section')?.nextElementSibling, mix)
    const mixCall = calls.findLast(url => url.includes('view=seller-products'))!
    for (const filter of ['anchor=2026-09-01', 'department_id=point', 'staff=all', 'employee_id=employee']) assert(mixCall.includes(filter), filter)
    assert.equal(document.querySelector('.statistics-tabs a[aria-current="page"]')?.textContent, 'Продавцы')
    await act(async () => button('Second Employee').closest('tr')!.querySelectorAll('td')[1].click())
    mix = document.querySelector('.statistics-seller-mix')!
    assert.equal(mix.querySelector('h2')?.textContent, 'Продукция продавца: Second Employee')
    assert(mix.textContent?.includes('Second Cake'))
    assert.equal(sellerSelector().value, 'second')
    assert.equal(document.querySelectorAll('.statistics-seller-mix').length, 1)
    assert.equal(document.querySelectorAll('.statistics-seller-row').length, 2)
    assert(!button('Test Employee').closest('tr')?.classList.contains('is-active'))
    assert(button('Second Employee').closest('tr')?.classList.contains('is-active'))
    // Selecting through the upper control updates both active row and the existing detail block.
    const detailBlock = mix
    await selectSeller('employee')
    assert.equal(document.querySelector('.statistics-seller-mix'), detailBlock)
    assert.equal(document.querySelector('.statistics-seller-mix h2')?.textContent, 'Продукция продавца: Test Employee')
    assert(button('Test Employee').closest('tr')?.classList.contains('is-active'))
    assert(!button('Second Employee').closest('tr')?.classList.contains('is-active'))
    await selectSeller('second')
    assert.equal(document.querySelector('.statistics-seller-mix'), detailBlock)
    assert(button('Second Employee').closest('tr')?.classList.contains('is-active'))
    assert.equal(document.querySelectorAll('.statistics-seller-mix').length, 1)
    // Text and decimal-number columns toggle ascending/descending and announce direction.
    const productNames = () => Array.from(detailBlock.querySelectorAll('tbody tr')).map(row => row.querySelector('td')?.textContent)
    const sortHeading = (column: number) => detailBlock.querySelectorAll<HTMLButtonElement>('thead button')[column]
    const requestCount = calls.length
    for (const column of [0, 1, 2, 3, 4, 5, 6, 7, 8]) {
      await act(async () => sortHeading(column).click())
      assert.deepEqual(productNames(), ['Second Cake', 'Z Cake'])
      assert.equal(sortHeading(column).closest('th')?.getAttribute('aria-sort'), 'ascending')
      assert(sortHeading(column).textContent?.includes('↑'))
      await act(async () => sortHeading(column).click())
      assert.deepEqual(productNames(), ['Z Cake', 'Second Cake'])
      assert.equal(sortHeading(column).closest('th')?.getAttribute('aria-sort'), 'descending')
      assert(sortHeading(column).textContent?.includes('↓'))
    }
    assert.equal(calls.length, requestCount, 'sorting is local and preserves context')
    assert(calls.filter(url => new URL(url, 'http://localhost').searchParams.get('view') === 'sellers').every(url => !url.includes('employee_id=')), 'the master table request must include all sellers')
    const categorySelector = detailBlock.querySelector<HTMLSelectElement>('select')!
    await act(async () => { categorySelector.value = 'Dessert'; categorySelector.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)) })
    assert(calls.findLast(url => url.includes('view=seller-products'))?.includes('category=Dessert'))
    assert.equal(sellerSelector().value, 'second')
    await act(async () => button('Second Cake').click())
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)) })
    assert(calls.findLast(url => url.includes('view=seller-products'))?.includes('employee_id=second'))
    assert(calls.findLast(url => url.includes('view=seller-products'))?.includes('iiko_product_id=cake'))
    const point = Array.from(document.querySelectorAll<HTMLSelectElement>('.statistics-filters select')).find(s => s.closest('label')?.textContent?.startsWith('Точка'))!
    await act(async () => { point.value = ''; point.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)) })
    assert(!calls.findLast(url => url.includes('view=seller-products'))?.includes('department_id='))
    assert(calls.findLast(url => url.includes('view=seller-products'))?.includes('employee_id=second'))
    failMix = true
    await act(async () => button('Test Employee').click())
    assert(document.querySelector('.statistics-seller-mix [role="alert"]'))
    assert(!document.querySelector('.statistics-seller-mix')?.textContent?.includes('Second Cake'))
    failMix = false
    await act(async () => button('Повторить').click())
    assert(document.querySelector('.statistics-seller-mix')?.textContent?.includes('Cake'))
    deferMix = true
    await act(async () => button('Second Employee').click())
    assert(document.querySelector('.statistics-seller-mix [role="status"]')?.textContent?.includes('Загружаем'))
    assert(!document.querySelector('.statistics-seller-mix')?.textContent?.includes('Cake'))
    await act(async () => button('Test Employee').click())
    await act(async () => { const stale = pending.pop()!; stale.resolve(stale.response) })
    assert.equal(document.querySelector('.statistics-seller-mix h2')?.textContent, 'Продукция продавца: Test Employee')
    assert(!document.querySelector('.statistics-seller-mix')?.textContent?.includes('Second Cake'))
    await selectSeller('')
    assert.equal(sellerSelector().value, '')
    assert(!document.querySelector('.statistics-seller-mix'))
    assert(!document.querySelector('.statistics-seller-row.is-active'))
    assert(document.querySelector('.statistics-seller-row'))

  } finally {
    if (root) await act(async () => root!.unmount())
    globalThis.fetch = originalFetch
    names.forEach((name, i) => { if (previous[i]) Object.defineProperty(globalThis, name, previous[i]!); else Reflect.deleteProperty(globalThis, name) })
    dom.window.close(); await server.close()
  }
})

test('chart fills measured width, crops future dates and exposes floating delta on keyboard focus', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const names = ['window', 'document', 'ResizeObserver', 'IS_REACT_ACT_ENVIRONMENT']
  const previous = names.map(name => Object.getOwnPropertyDescriptor(globalThis, name))
  let root: ReturnType<typeof import('react-dom/client').createRoot> | undefined
  try {
    class Observer {
      callback: (entries: { contentRect: { width: number } }[]) => void
      constructor(callback: Observer['callback']) { this.callback = callback }
      observe() { this.callback([{ contentRect: { width: 1200 } }]) }
      disconnect() {}
    }
    for (const [name, value] of Object.entries({ window: dom.window, document: dom.window.document, ResizeObserver: Observer, IS_REACT_ACT_ENVIRONMENT: true })) Object.defineProperty(globalThis, name, { configurable: true, value })
    const { createRoot } = await import('react-dom/client')
    const { default: Chart } = await server.ssrLoadModule('/src/pages/SalesTrendChart.tsx')
    root = createRoot(document.getElementById('root')!)
    const rows = [{ date: '2026-10-01', value: 10 }, { date: '2026-10-02', value: 15 }, { date: '2026-10-31', value: null }]
    await act(async () => root!.render(React.createElement(Chart, { rows, through: '2026-10-02' })))
    assert.equal(document.querySelector('svg')?.getAttribute('viewBox'), '0 0 1200 240')
    assert(document.body.textContent?.includes('01.10 · Чт'))
    assert(!document.body.textContent?.includes('31.10'))
    assert(!Array.from(document.querySelectorAll('svg text')).some(t => ['Дата', 'Сумма, ₽'].includes(t.textContent || '')))
    const points = document.querySelectorAll<SVGCircleElement>('circle')
    assert.equal(points.length, 2)
    assert.equal(points[1].getAttribute('cx'), '1175')
    await act(async () => points[1].dispatchEvent(new dom.window.FocusEvent('focusin', { bubbles: true })))
    const tooltip = document.querySelector<HTMLElement>('.statistics-chart-tooltip')!
    assert(tooltip.textContent?.includes('+5'))
    assert(tooltip.style.left && tooltip.style.top && tooltip.style.transform.includes('-100%'))
    assert.equal(points[1].getAttribute('tabindex'), '0')
    await act(async () => root!.render(React.createElement(Chart, { rows, through: '2026-11-01' })))
    assert(document.body.textContent?.includes('31.10'))
  } finally {
    if (root) await act(async () => root!.unmount())
    names.forEach((name, i) => { if (previous[i]) Object.defineProperty(globalThis, name, previous[i]!); else Reflect.deleteProperty(globalThis, name) })
    dom.window.close(); await server.close()
  }
})
