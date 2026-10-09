import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'

test('cost labels fail closed, preserve zero and mark estimated SSN', async () => {
  const server = await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  try {
    const {costLabel,exactCostNumber,CostApiError}=await server.ssrLoadModule('/src/services/productCosts.ts')
    assert.equal(costLabel(null),'Нет подтверждённой себестоимости')
    assert.equal(costLabel({status:'UNVERIFIED',amount:'999.99',note:'Требует сверки'}),'Требует сверки')
    assert.equal(costLabel({status:'VERIFIED',amount:'0.00',estimated:false}),'0,00 ₽')
    assert.equal(costLabel({status:'VERIFIED',amount:'113.08',estimated:true}),'113,08 ₽ *')
    assert.equal(exactCostNumber('0.00000000123456789'),'0,00000000123456789')
    assert.match(new CostApiError(403).message,/Нет доступа/)
  } finally {await server.close()}
})

test('cost card hides unconfirmed amounts and renders verified ingredient/history details safely', async () => {
  const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
  const values={window:dom.window,document:dom.window.document,getComputedStyle:dom.window.getComputedStyle,IS_REACT_ACT_ENVIRONMENT:true,sessionStorage:dom.window.sessionStorage}
  const previous=Object.keys(values).map(name=>Object.getOwnPropertyDescriptor(globalThis,name)),oldFetch=globalThis.fetch
  let root: ReturnType<typeof import('react-dom/client').createRoot> | undefined
  let mode='unverified'
  const current={status:'UNVERIFIED',amount:'999.99',note:'Требует сверки с iikoOffice',unit:'шт',context:'Цех',warehouse:'Все склады источника',method:'Расчёт EOS по ТТК',source:'iiko',stock_at:'2026-10-09T11:00:00Z',observed_at:'2026-10-09T11:01:00Z',estimated:true,rounding:'Цены до 0,01 ₽',components:[{name:'<script>Молоко</script>',quantity:'0.00000000123456789',unit:'л',unit_cost:'999.99',contribution:'99.99'}],observation_id:'snapshot',content_hash:'secret-hash',context_key:'private-context'}
  try {
    Object.entries(values).forEach(([name,value])=>Object.defineProperty(globalThis,name,{configurable:true,value}))
    globalThis.fetch=async()=>mode==='error'?new Response('{"detail":"private stack"}',{status:503}):Response.json({can_review:mode==='preview',review:mode==='preview'?{candidate_amount:'0.25',components:[],observation_id:'snapshot',content_hash:'secret-hash',quality:'REQUIRES_REVIEW',issues:['Оценочность требует проверки в iikoOffice'],can_confirm:true,context:'Цех',warehouse:'Все склады источника',method:'Расчёт EOS по ТТК'}:null,contexts:[{key:'ctx',label:'Цех',warehouse:'Все склады источника'}],selected_context:'ctx',current:mode==='verified'?{...current,status:'VERIFIED',amount:'113.08'}:current,history:[],total:0,offset:0,limit:25,note:null})
    const {createRoot}=await import('react-dom/client'),{ProductCosts}=await server.ssrLoadModule('/src/pages/productKnowledge/ProductCosts.tsx')
    root=createRoot(document.getElementById('root')!)
    await act(async()=>{root!.render(React.createElement(ProductCosts,{productId:'one'}))})
    assert.match(document.body.textContent!,/Требует сверки/);assert.doesNotMatch(document.body.textContent!,/999|Молоко/)
    mode='verified';await act(async()=>{root!.render(React.createElement(ProductCosts,{productId:'two'}))})
    assert.match(document.body.textContent!,/113,08/);assert.match(document.body.textContent!,/Оценочная ССН/)
    assert.match(document.body.textContent!,/0,00000000123456789/);assert.match(document.body.textContent!,/Количество/)
    assert.match(document.body.textContent!,/Расчёт EOS/);assert.equal(document.querySelector('script'),null)
    assert.doesNotMatch(document.body.textContent!,/secret-hash|private-context|execution_id/)
    mode='preview';await act(async()=>{root!.render(React.createElement(ProductCosts,{productId:'preview'}))})
    const reviewButton=[...document.querySelectorAll('button')].find(button=>button.textContent==='Проверить расчёт')!
    await act(async()=>{reviewButton.click()})
    assert.match(document.body.textContent!,/Неподтверждённый расчёт EOS/);assert.match(document.body.textContent!,/Кандидатная ССН: 0,25/)
    const confirmButton=[...document.querySelectorAll('button')].find(button=>button.textContent==='Подтвердить этот расчёт')!
    assert.equal(confirmButton.disabled,true);assert.equal(document.querySelectorAll('input[type=checkbox]:checked').length,0)
    assert.match(document.body.textContent!,/Звёздочка/);assert.doesNotMatch(document.body.textContent!,/secret-hash|private-context|999/)
    mode='error';await act(async()=>{root!.render(React.createElement(ProductCosts,{productId:'three'}))})
    assert.match(document.body.textContent!,/Не удалось загрузить/);assert.doesNotMatch(document.body.textContent!,/private stack|113,08/)
  } finally {
    if(root)await act(async()=>root!.unmount());globalThis.fetch=oldFetch
    Object.keys(values).forEach((name,index)=>{if(previous[index])Object.defineProperty(globalThis,name,previous[index]!);else Reflect.deleteProperty(globalThis,name)})
    dom.window.close();await server.close()
  }
})


test('confirmation sends explicit snapshot and warehouse proof and hides backend errors', async () => {
  const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const oldFetch=globalThis.fetch,previousStorage=Object.getOwnPropertyDescriptor(globalThis,'sessionStorage')
  Object.defineProperty(globalThis,'sessionStorage',{configurable:true,value:{getItem:()=>null}})
  try {
    const {confirmProductCost}=await server.ssrLoadModule('/src/services/productCosts.ts')
    let received: Record<string,unknown> | undefined
    globalThis.fetch=async(_url,init)=>{received=JSON.parse(String(init?.body));return new Response('{"detail":"private stack"}',{status:409})}
    await assert.rejects(confirmProductCost('id',{observation_id:'snapshot',content_hash:'hash',office_ssn:'0.00',estimated:true,warehouse_confirmed:true,context_confirmed:true,office_evidence:'Independent Office evidence',allow_updates:false}),/Расчёт изменился/)
    assert.equal(received?.allow_updates,false);assert.equal(received?.warehouse_confirmed,true);assert.equal(received?.office_ssn,'0.00')
  } finally {globalThis.fetch=oldFetch;if(previousStorage)Object.defineProperty(globalThis,'sessionStorage',previousStorage);else Reflect.deleteProperty(globalThis,'sessionStorage');await server.close()}
})
