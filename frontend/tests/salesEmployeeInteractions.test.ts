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
    const { default: Statistics } = await server.ssrLoadModule('/src/pages/StatisticsPage.tsx')
    const calls: string[] = []
    const period = { kind: 'month', start: '2026-09-01', end: '2026-09-30', previous_start: '2026-08-02', previous_end: '2026-08-31' }
    globalThis.fetch = async input => {
      const url = String(input); calls.push(url)
      if (url === '/api/auth/me') return Response.json({ id: 1 })
      if (url.includes('action-context')) return Response.json({ roles: ['ADMIN'] })
      return Response.json({ status: { today: '2026-10-07', history_from: '2026-04-01' }, completeness: { warning: false },
        points: [{ department_id: 'point', department_name: 'Точка' }], sellers: [],
        seller_mix: { employee_id: 'employee', employee_name: 'Test Employee', period, categories: ['Dessert'], dynamics: [], products: [{ iiko_product_id: 'cake', product_name: 'Cake', category: 'Dessert', quantity: '2', revenue: '100', share_percent: '50', previous_quantity: '1', previous_revenue: '40', quantity_change: '1', revenue_change: '60' }] } })
    }
    await act(async () => root!.render(React.createElement(AuthProvider, { key: 'statistics' }, React.createElement(MemoryRouter, { initialEntries: ['/statistics/seller-products?period=month&anchor=2026-09-01&employee_id=employee&category=Dessert'] }, React.createElement(Routes, null, React.createElement(Route, { path: '/statistics/:view', element: React.createElement(Statistics) }))))))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 220)) })
    const productLink = Array.from(document.querySelectorAll<HTMLAnchorElement>('a')).find(a => a.textContent === 'Cake')!
    assert(productLink.href.includes('employee_id=employee') && productLink.href.includes('category=Dessert') && productLink.href.includes('iiko_product_id=cake'))
    const point = Array.from(document.querySelectorAll<HTMLSelectElement>('.statistics-filters select')).find(s => s.closest('label')?.textContent?.startsWith('Точка'))!
    await act(async () => { point.value = 'point'; point.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)) })
    assert(calls.at(-1)?.includes('department_id=point') && calls.at(-1)?.includes('employee_id=employee'))
    await act(async () => button('Сбросить фильтры').click())
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 180)) })
    assert(calls.at(-1)?.includes('employee_id=employee'))
    assert(!calls.at(-1)?.includes('department_id='))
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
