import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'
import { dashboardSalesKind, dashboardSalesDestination } from '../src/pages/dashboardSalesLogic.ts'
import { layoutDashboardWidgets } from '../src/pages/dashboardWidgetLogic.ts'

const metric = (fact = '600', target: string | null = '700') => ({ fact, target, completion_percent: '85.7', status: 'warning', previous: null, change: null, change_percent: null })
const analytics = { period: { kind: 'month', start: '2026-10-01', end: '2026-10-06' }, metrics: { revenue: metric('10000', '50000'), check_count: metric('15', null), average_check: metric(), fullness: metric('2.5', '3') }, completeness: { warning: false } }
const status = { last_success_at: '2026-10-06T10:00:00Z', source_timezone: 'Asia/Yekaterinburg', stale: false, update_failed: false }
const seller = (id: string) => ({ employee_id: id, employee_name: `Продавец ${id}`, metrics: analytics.metrics })

test('role visibility, precedence, navigation and vertical grid size', () => {
  for (const role of ['CHEF_CONFECTIONER', 'HEAD_OF_PRODUCTION', 'ACCOUNTANT', 'SUPPLY_MANAGER', 'DRIVER', 'HANDYMAN', 'BAKER', 'CONFECTIONER', 'UNKNOWN']) assert.equal(dashboardSalesKind([role]), null)
  assert.equal(dashboardSalesKind([]), null)
  for (const [role, kind, size] of [['ADMIN', 'executive', '1x2'], ['SELLER', 'personal', '1x1'], ['NETWORK_MANAGER', 'network', '1x2'], ['DIRECTOR', 'executive', '1x2'], ['DEPUTY_DIRECTOR', 'executive', '1x2']] as const) {
    assert.equal(dashboardSalesKind([role]), kind)
    assert.equal(dashboardSalesDestination(kind), `/statistics/${kind === 'personal' ? 'me' : 'overview'}?period=month`)
    const [layout] = layoutDashboardWidgets([{ id: 'sales', size }])
    assert.equal(layout.columnSpan, 1)
    assert.equal(layout.rowSpan, kind === 'personal' ? 1 : 2)
  }
  assert.equal(dashboardSalesKind(['SELLER', 'NETWORK_MANAGER']), 'network')
  assert.equal(dashboardSalesKind(['SELLER', 'DIRECTOR']), 'executive')
})

test('rendered UI, scoped requests and retained last-successful data', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const originalFetch = globalThis.fetch
  const globals = ['window', 'document', 'sessionStorage', 'IS_REACT_ACT_ENVIRONMENT']
  const previous = globals.map(key => Object.getOwnPropertyDescriptor(globalThis, key))
  let root: ReturnType<typeof createRoot> | undefined
  try {
    const { DashboardSalesContent: Content, default: Widget } = await server.ssrLoadModule('/src/components/dashboard/DashboardSalesWidget.tsx')
    const render = (kind: string, data: unknown, error = '') => renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Content, { kind, data, error })))
    const data = { analytics, status, attention: [seller('1'), seller('2'), seller('3')] }
    const personal = render('personal', data)
    for (const text of ['Мои показатели', 'Средний чек', 'Наполняемость', '15:00']) assert(personal.includes(text))
    assert.doesNotMatch(personal, /Выручка|Чеки:|Продавец|Требуют внимания/)
    assert.match(personal, /href="\/statistics\/me\?period=month"/)
    const network = render('network', data)
    assert.match(network, /Выручка/); assert.match(network, /Чеки:/)
    assert.doesNotMatch(network, /Требуют внимания|<progress/)
    const executive = render('executive', data)
    for (const text of ['факт / план', '<progress', 'Продавец 1', 'Продавец 2']) assert(executive.includes(text))
    assert.doesNotMatch(executive, /Продавец 3|<form|<button/)
    assert.match(executive, /href="\/statistics\/overview\?period=month"/)
    const degraded = render('executive', { ...data, analytics: { ...analytics, completeness: { warning: true } }, status: { ...status, stale: true, update_failed: true }, attention: [] }, 'Не удалось обновить статистику')
    for (const text of ['Неполные данные', 'Данные устарели', 'Обновление не выполнено', 'Недостаточно данных', 'Не удалось обновить статистику']) assert(degraded.includes(text))
    assert.match(render('personal', null), /Загрузка/)
    assert.match(render('personal', null, 'Не удалось обновить статистику'), /Не удалось обновить статистику/)
    const missing = render('personal', { ...data, analytics: { ...analytics, metrics: { ...analytics.metrics, average_check: { ...metric(), fact: null, target: null, status: 'no_data' }, fullness: { ...metric('0', null), status: 'no_target' } } } })
    assert.match(missing, /— \/ —/); assert.match(missing, /0 \/ —/)
    for (const [key, value] of Object.entries({ window: dom.window, document: dom.window.document, sessionStorage: dom.window.sessionStorage, IS_REACT_ACT_ENVIRONMENT: true })) Object.defineProperty(globalThis, key, { configurable: true, value })
    sessionStorage.setItem('eos_access_token', 'test')
    const calls: string[] = []; let failureStatus = 0
    let gate: Promise<void> | null = null
    globalThis.fetch = async (input, options) => {
      calls.push(String(input)); assert.equal(options?.cache, 'no-store')
      if (gate) await gate
      if (failureStatus) return new Response('', { status: failureStatus })
      return Response.json(String(input).includes('/status') ? status : String(input).includes('/attention') ? data.attention.slice(0, 2) : analytics)
    }
    root = createRoot(document.getElementById('root')!)
    await act(async () => { root!.render(React.createElement(MemoryRouter, null, React.createElement(Widget, { kind: 'personal', key: 'seller' }))) })
    assert.deepEqual(calls.sort(), ['/api/sales/analytics/me?period=month', '/api/sales/analytics/status'])
    failureStatus = 503
    await act(async () => { document.dispatchEvent(new dom.window.Event('visibilitychange')) })
    assert(document.body.textContent?.includes('Не удалось обновить статистику'))
    assert(document.body.textContent?.includes('600'))
    failureStatus = 403
    await act(async () => { document.dispatchEvent(new dom.window.Event('visibilitychange')) })
    assert(document.body.textContent?.includes('Нет доступа к выбранной статистике'))
    assert(!document.body.textContent?.includes('600'))
    failureStatus = 0; calls.length = 0
    let release!: () => void
    gate = new Promise<void>(resolve => { release = resolve })
    await act(async () => {
      document.dispatchEvent(new dom.window.Event('visibilitychange'))
      document.dispatchEvent(new dom.window.Event('visibilitychange'))
    })
    assert.equal(calls.length, 2, 'concurrent refresh is skipped')
    await act(async () => { release() }); gate = null
    calls.length = 0
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new dom.window.Event('visibilitychange'))
    assert.equal(calls.length, 0, 'hidden tabs do not request analytics')
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    await act(async () => { root!.render(React.createElement(MemoryRouter, null, React.createElement(Widget, { kind: 'executive', key: 'director' }))) })
    assert.deepEqual(calls.sort(), ['/api/sales/analytics/attention?period=month', '/api/sales/analytics/overview?period=month', '/api/sales/analytics/status'])
    assert(document.body.textContent?.includes('Требуют внимания'))
    await act(async () => { root!.unmount() }); root = undefined
    calls.length = 0; document.dispatchEvent(new dom.window.Event('visibilitychange')); assert.equal(calls.length, 0)
  } finally {
    if (root) await act(async () => { root!.unmount() })
    globalThis.fetch = originalFetch
    globals.forEach((key, i) => { if (previous[i]) Object.defineProperty(globalThis, key, previous[i]!); else Reflect.deleteProperty(globalThis, key) })
    dom.window.close(); await server.close()
  }
})
