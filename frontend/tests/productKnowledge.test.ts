import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'
import { demoProducts, filterCatalog, resolveDemoPrice } from '../src/pages/productKnowledge/demoCatalog.ts'

test('demo catalog keeps distinct identities and resolves filters and prices without fallback', () => {
  assert.equal(demoProducts.length, 14)
  assert.equal(new Set(demoProducts.map(p => p.id)).size, 14)
  const all = { query: '', status: '', category: '', mode: '' }
  const twins = filterCatalog(demoProducts, { ...all, query: 'ПРАГА' })
  assert.equal(twins.length, 2)
  assert.notEqual(twins[0].id, twins[1].id)
  assert.equal(filterCatalog(demoProducts, { ...all, query: 'demo-001' })[0].name, 'Чизкейк с ягодами')
  assert.equal(filterCatalog(demoProducts, { ...all, status: 'OFF_SALE', category: 'Выпечка', mode: 'PORTION' }).length, 1)
  assert.equal(filterCatalog(demoProducts, { ...all, mode: 'UNKNOWN' })[0].weight, null)
  const p = demoProducts[0]
  assert.equal(resolveDemoPrice(p, '', '2026-10-08'), 'Выберите точку')
  assert.equal(resolveDemoPrice(p, 'Демо · Центральная', '2026-09-01'), '220 ₽ / порция')
  assert.equal(resolveDemoPrice(p, 'Демо · Парковая', '2026-10-08'), '240 ₽ / порция')
  assert.equal(resolveDemoPrice(p, 'Демо · Центральная', '2026-11-01'), 'Нет данных')
  assert.equal(resolveDemoPrice(p, 'Unknown', '2026-10-08'), 'Нет данных')
})

test('portal: pagination, filters, card, management, empty/loading/error/stale; no network', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost', pretendToBeVisual: true })
  const values = { window: dom.window, document: dom.window.document, getComputedStyle: dom.window.getComputedStyle, IS_REACT_ACT_ENVIRONMENT: true }
  const previous = Object.keys(values).map(name => Object.getOwnPropertyDescriptor(globalThis, name))
  const originalFetch = globalThis.fetch
  let calls = 0
  let root: ReturnType<typeof import('react-dom/client').createRoot> | undefined
  try {
    dom.window.scrollTo = () => {}
    Object.entries(values).forEach(([name, value]) => Object.defineProperty(globalThis, name, { configurable: true, value }))
    globalThis.fetch = async () => { calls++; throw new Error('No K0 network') }
    const { createRoot } = await import('react-dom/client')
    const { default: Page } = await server.ssrLoadModule('/src/pages/ProductKnowledgeDemoPage.tsx')
    root = createRoot(document.getElementById('root')!)
    let key = 0
    const render = async (url: string) => {
      await act(async () => root!.render(React.createElement(MemoryRouter, { key: ++key, initialEntries: [url] }, React.createElement(Routes, null,
        React.createElement(Route, { path: '/products', element: React.createElement(Page) }),
        React.createElement(Route, { path: '/products/:productId', element: React.createElement(Page) }),
      ))))
    }
    const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 300)) })
    const button = (text: string) => Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(b => b.textContent === text)!
    await render('/products')
    assert.match(document.body.textContent!, /Загружаем продукцию/)
    await settle()
    assert.deepEqual(Array.from(document.querySelectorAll('th')).map(el => el.textContent), ['Фото', 'Название', 'Вес', 'Порционный / весовой товар', 'Цена', 'Себестоимость', 'Статус'])
    assert.equal(document.querySelectorAll('tbody tr').length, 6)
    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="Следующая страница"]')!.click())
    assert.match(document.querySelector('.eos-pagination-range')!.textContent!, /7–12 из 14/)
    const point = document.querySelector<HTMLSelectElement>('select[aria-label="Точка цены"]')!
    await act(async () => { point.value = 'Демо · Парковая'; point.dispatchEvent(new dom.window.Event('change', { bubbles: true })) })
    assert.match(document.querySelector('.eos-pagination-range')!.textContent!, /1–6 из 14/)
    assert.match(document.querySelector('tbody')!.textContent!, /240 ₽/)
    await act(async () => button('Добавить изделие').click())
    assert(document.querySelector('[role="dialog"]'))
    assert(button('Сохранение недоступно').disabled)
    await act(async () => button('Закрыть').click())
    await render('/products?q=Прага&category=Торты&mode=WEIGHT'); await settle()
    assert.equal(document.querySelectorAll('tbody tr').length, 2)
    await act(async () => document.querySelector<HTMLAnchorElement>('tbody a')!.click())
    assert.equal(document.querySelectorAll('.product-knowledge-section').length, 9)
    assert.match(document.querySelector('h1')!.textContent!, /Прага/)
    await act(async () => button('Изменить статус').click())
    assert.equal(document.querySelector('[role="dialog"] select')?.children.length, 2)
    assert(button('Сохранение недоступно').disabled)
    await act(async () => button('Закрыть').click())
    assert.match(document.querySelector('.product-status')!.textContent!, /В продаже/)
    await act(async () => button('Фотографии').click())
    assert(document.querySelector<HTMLInputElement>('input[type="file"]')!.disabled)
    assert(button('Удалить фото').disabled)
    await act(async () => button('Закрыть').click())
    await act(async () => button('Редактировать').click())
    assert.equal(document.querySelectorAll('[role="dialog"] textarea').length, 5)
    await act(async () => button('Закрыть').click())
    for (const [url, text] of [ ['/products?scenario=empty', 'Каталог пока пуст'], ['/products?q=неттакого', 'Ничего не найдено'], ['/products?scenario=error', 'Не удалось загрузить продукцию'], ['/products?scenario=loading', 'Загружаем продукцию'], ['/products?scenario=stale', 'Данные устарели'], ['/products/not-found', 'Изделие не найдено'] ]) {
      await render(url); await settle(); assert(document.body.textContent!.includes(text), text)
    }
    await render('/products?scenario=error'); await settle()
    await act(async () => button('Повторить').click())
    assert.equal(document.querySelectorAll('tbody tr').length, 6)
    assert.equal(calls, 0)
  } finally {
    if (root) await act(async () => root!.unmount())
    globalThis.fetch = originalFetch
    Object.keys(values).forEach((name, i) => { if (previous[i]) Object.defineProperty(globalThis, name, previous[i]!); else Reflect.deleteProperty(globalThis, name) })
    dom.window.close(); await server.close()
  }
})
