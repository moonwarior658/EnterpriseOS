import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'
import { salesReportScope, salesExportAllowed, salesExportQuery } from '../src/pages/salesReportsLogic.ts'

test('reports/export permission matrix and scoped current filters', () => {
  for (const role of ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER']) {
    assert.equal(salesReportScope([role]), 'full')
    for (const view of ['overview','points','sellers','products']) assert(salesExportAllowed([role],view))
  }
  for (const role of ['CHEF_CONFECTIONER','HEAD_OF_PRODUCTION']) {
    assert.equal(salesReportScope([role]), 'products')
    assert(salesExportAllowed([role], 'products'))
    for (const view of ['overview','points','sellers','me']) assert(!salesExportAllowed([role],view))
  }
  for (const role of ['SELLER','HANDYMAN','SUPPLY_MANAGER','ACCOUNTANT','DRIVER','BAKER','CONFECTIONER','UNKNOWN']) {
    assert.equal(salesReportScope([role]), null)
    assert(!salesExportAllowed([role], 'products'))
  }
  assert.equal(salesReportScope([]), null)
  const params = new URLSearchParams('period=custom&start=2026-09-01&end=2026-09-30&department_id=point&employee_id=seller&staff=dismissed&category=Торты&iiko_product_id=product')
  const query = new URLSearchParams(salesExportQuery(params,'points','xlsx'))
  for (const name of ['start','end','department_id','employee_id','staff','category','iiko_product_id']) assert.equal(query.get(name),params.get(name))
  const product = new URLSearchParams(salesExportQuery(params,'products','pdf'))
  assert(!product.has('employee_id')); assert(!product.has('staff'))
  assert.equal(product.get('department_id'),'point'); assert.equal(product.get('format'),'pdf')
})

test('report UI hides seller/network data for product-only payload and explains pending periods', async () => {
  const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType:'custom' })
  const dom = new JSDOM('<div id="root"></div>', { url:'http://localhost', pretendToBeVisual:true })
  const names = ['window','document','sessionStorage','IS_REACT_ACT_ENVIRONMENT']
  const previous = names.map(n => Object.getOwnPropertyDescriptor(globalThis,n))
  const originalFetch = globalThis.fetch
  let root: ReturnType<typeof createRoot> | undefined
  try {
    const { default: Reports, SalesReportContent: Content } = await server.ssrLoadModule('/src/pages/SalesReportsPage.tsx')
    const report = { id:'report', start:'2026-09-28', end:'2026-10-04', created_at:'2026-10-05T03:00:00Z', data: { products: { products:[] }, product_changes:{growth:[],decline:[]} } }
    const html = renderToStaticMarkup(React.createElement(Content,{ report }))
    assert(html.includes('Последующие корректировки продаж не меняют'))
    assert(html.includes('Продукция')); assert.doesNotMatch(html,/Продавцы|Сеть · факт/)
    for (const [n,v] of Object.entries({window:dom.window,document:dom.window.document,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true})) Object.defineProperty(globalThis,n,{configurable:true,value:v})
    sessionStorage.setItem('eos_access_token','test')
    const calls: string[]=[]
    globalThis.fetch=async input => { calls.push(String(input)); return Response.json([{id:null,start:'2026-09-28',end:'2026-10-04',reason:'Период ещё не догружен',completeness:{current:{loaded_days:2,expected_days:7},previous:{loaded_days:7,expected_days:7}}}]) }
    root=createRoot(document.getElementById('root')!)
    await act(async()=> { root!.render(React.createElement(MemoryRouter,null,React.createElement(Reports,{roles:['SELLER']}))) })
    assert(document.body.textContent?.includes('Нет доступа')); assert.equal(calls.length,0)
    await act(async()=> { root!.render(React.createElement(MemoryRouter,null,React.createElement(Reports,{roles:['CHEF_CONFECTIONER']}))) })
    assert.deepEqual(calls,['/api/sales/analytics/reports?kind=week&scope=products'])
    assert(document.body.textContent?.includes('Отчёты продукции'))
    assert(document.body.textContent?.includes('Период ещё не догружен'))
    assert(!Array.from(document.querySelectorAll('button')).some(b => ['Excel','PDF'].includes(b.textContent || '')), 'pending report cannot be exported')
  } finally {
    if(root) await act(async()=>root!.unmount())
    globalThis.fetch=originalFetch
    names.forEach((n,i)=>{if(previous[i]) Object.defineProperty(globalThis,n,previous[i]!);else Reflect.deleteProperty(globalThis,n)})
    dom.window.close();await server.close()
  }
})
