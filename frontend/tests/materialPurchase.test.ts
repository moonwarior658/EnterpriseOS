import test from 'node:test'
import assert from 'node:assert/strict'
import React, {act} from 'react'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'

test('manual purchase update polls completion and opens protected document; failure retains price',async()=>{
 const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
 dom.window.scrollTo=()=>{}
 const values={window:dom.window,document:dom.window.document,getComputedStyle:dom.window.getComputedStyle,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true}
 const previous=Object.keys(values).map(name=>Object.getOwnPropertyDescriptor(globalThis,name)),oldFetch=globalThis.fetch
 let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
 let started=false,complete=false,failed=false,posts=0,reads=0
 const metric={id:'snapshot',status:'READY',amount:'33.333333333333333333333',unit:'кг',currency:'RUB',receipt_at:'2026-10-18T09:00:00+05:00',observed_at:'2026-10-20T09:00:00Z',reasons:[]}
 try{
  Object.entries(values).forEach(([name,value])=>Object.defineProperty(globalThis,name,{configurable:true,value}))
  globalThis.fetch=async(url,init)=>{
   if(init?.method==='POST'){
    posts++;assert.ok(JSON.parse(String(init.body)).request_id)
    if(failed)return new Response('{"detail":"private stack error"}',{status:503})
    started=true;return Response.json({status:'pending',label:'Ожидает обновления',active:true})
   }
   if(String(url).includes('/sources'))return Response.json({metric,warehouse:'Цех Производство ИП',hash:'a'.repeat(64),candidates:[{document_id:'invoice',number:'ПН-42',receipt_at:metric.receipt_at,supplier_name:'Внешний поставщик',numerator:'100',denominator:'3',lines:[{num:'1',actualAmount:'3',sum:'100',vatSum:'16.67'}]}],exclusions:[]})
   if(String(url).includes('/usage'))return Response.json({items:[]})
   reads++
   return Response.json({items:complete?[metric]:[],refresh:started?{status:complete?'succeeded':'running',label:complete?'Обновление завершено':'Получаем данные из iiko',active:!complete}:null})
  }
  const {createRoot}=await import('react-dom/client'),{PurchasePanel}=await server.ssrLoadModule('/src/components/MaterialPurchase.tsx')
  root=createRoot(document.getElementById('root')!)
  const onUpdated=()=>{}
  await act(async()=>{root!.render(React.createElement(PurchasePanel,{material:{id:'product',purchase_access:true,allowed_actions:['METRICS_REFRESH'],last_purchase_price:{status:'NO_DATA',amount:null}},onUpdated}))})
  let button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Обновить показатели')!
  await act(async()=>{button.click()})
  assert.equal(posts,1);assert.ok([...document.querySelectorAll('button')].some(b=>b.textContent==='Обновляем…'&&b.disabled))
  complete=true
  await act(async()=>{await new Promise(r=>setTimeout(r,1700))})
  assert.ok(reads>=2);assert.match(document.body.textContent!,/33,33/);assert.match(document.body.textContent!,/Обновление завершено/)
  await act(async()=>{[...document.querySelectorAll('button')].find(b=>b.textContent==='История показателей и документы')!.click()})
  button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Документ-основание')!
  await act(async()=>{button.click()})
  assert.match(document.body.textContent!,/ПН-42/);assert.match(document.body.textContent!,/Внешний поставщик/);assert.match(document.body.textContent!,/100,00 ₽ \/ 3,00 кг/)
  failed=true
  button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Обновить показатели')!
  await act(async()=>{button.click()})
  assert.match(document.body.textContent!,/история сохранена/);assert.match(document.body.textContent!,/33,33/);assert.doesNotMatch(document.body.textContent!,/private stack/)
 }finally{
  if(root)await act(async()=>root!.unmount())
  globalThis.fetch=oldFetch
  Object.keys(values).forEach((name,i)=>{if(previous[i])Object.defineProperty(globalThis,name,previous[i]!);else Reflect.deleteProperty(globalThis,name)})
  dom.window.close();await server.close()
 }
})
