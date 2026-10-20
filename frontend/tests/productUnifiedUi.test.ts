import test from 'node:test'
import assert from 'node:assert/strict'
import React, {act} from 'react'
import {MemoryRouter, Routes, Route} from 'react-router-dom'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'

const delay=()=>new Promise(r=>setTimeout(r,280))
async function harness(run:(h:{dom:JSDOM;server:Awaited<ReturnType<typeof createServer>>;render:(element:React.ReactNode)=>Promise<void>;page:(path:string)=>Promise<void>;click:(label:string)=>Promise<void>;change:(element:HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement,value:string)=>Promise<void>})=>Promise<void>) {
 const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
 const dom=new JSDOM('<button id="trigger">Открыть</button><div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
 dom.window.scrollTo=()=>{}
 const values={window:dom.window,document:dom.window.document,getComputedStyle:dom.window.getComputedStyle,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true}
 const old=Object.keys(values).map(k=>Object.getOwnPropertyDescriptor(globalThis,k)),oldFetch=globalThis.fetch
 let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
 try {
  Object.entries(values).forEach(([k,v])=>Object.defineProperty(globalThis,k,{value:v,configurable:true}))
  const {createRoot}=await import('react-dom/client');root=createRoot(document.getElementById('root')!)
  const render=async(element:React.ReactNode)=>{await act(async()=>{root!.render(element)})}
  const page=async(path:string)=>{
   const {default:Page}=await server.ssrLoadModule('/src/pages/ProductKnowledgePage.tsx')
   await render(React.createElement(MemoryRouter,{initialEntries:[path]},React.createElement(Routes,null,React.createElement(Route,{path:'/products',element:React.createElement(Page)}),React.createElement(Route,{path:'/products/:productId',element:React.createElement(Page)}))))
   await act(delay)
  }
  const click=async(label:string)=>{const el=[...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent===label||b.getAttribute('aria-label')===label);assert.ok(el,'button '+label);await act(async()=>el.click())}
  const change=async(el:HTMLInputElement|HTMLTextAreaElement|HTMLSelectElement,value:string)=>{
   assert.ok(el,'form field');const proto=el.tagName==='TEXTAREA'?dom.window.HTMLTextAreaElement.prototype:el.tagName==='SELECT'?dom.window.HTMLSelectElement.prototype:dom.window.HTMLInputElement.prototype
   await act(async()=>{Object.getOwnPropertyDescriptor(proto,'value')!.set!.call(el,value);el.dispatchEvent(new dom.window.Event(el.tagName==='SELECT'?'change':'input',{bubbles:true}))})
  }
  await run({dom,server,render,page,click,change})
 } finally {
  if(root)await act(async()=>root!.unmount());globalThis.fetch=oldFetch
  Object.keys(values).forEach((k,i)=>{if(old[i])Object.defineProperty(globalThis,k,old[i]!);else Reflect.deleteProperty(globalThis,k)})
  dom.window.close();await server.close()
 }
}

const makeProduct=()=>({id:'product',name:'Эклер',sku:'001',unit_name:'шт',unit_weight_kg:'0.055',sale_mode:'PORTION',sale_status:'ON_SALE',category_id:null,category_name:null,description:'Для витрины',description_source:'EOS',characteristics:'Форма',composition:'Мука',allergens:'Молоко',storage:'Холод',training:'Материалы',observed_at:'2026-10-20T04:00:00Z',source_deleted:false,version:3,deleted_at:null,verified_at:null,verified_by_name:null,photo:null,price:{department_id:'point',department_name:'Центр',amount:'1078.799',currency:'RUB',price_unit:'шт',valid_from:'2026-10-20',valid_to:'2026-10-21',observed_at:'2026-10-20T04:00:00Z'},prices:[],price_conflict_points:[],cost_access:true,cost:{status:'UNVERIFIED',amount:null,note:'Нет подтверждённой себестоимости'},recipe_access:true,allowed_actions:['EDIT','STATUS','DELETE','VERIFY']})
const catalog=(p:ReturnType<typeof makeProduct>)=>({items:[p],points:[{id:'point',name:'Центр'}],categories:[],total:26,active_count:26,verified_count:0,allowed_actions:['ADD'],cost_access:p.cost_access})

test('products and raw materials share the exact dialog and decimal implementation',async()=>harness(async({server})=>{
 const raw=await server.ssrLoadModule('/src/components/MaterialDialog.tsx'),common=await server.ssrLoadModule('/src/components/KnowledgeDialog.tsx')
 assert.equal(raw.MaterialDialog,common.KnowledgeDialog)
 const a=await server.ssrLoadModule('/src/components/materialPresentation.ts'),b=await server.ssrLoadModule('/src/components/knowledgePresentation.ts')
 assert.equal(a.materialNumber,b.knowledgeNumber);assert.equal(b.knowledgeNumber('1078.799'),'1 078,80')
}))

test('registry keeps product columns and price context, global sort resets page and toggles preserve filters',async()=>harness(async({page,click})=>{
 const paths:URL[]=[];let p=makeProduct()
 globalThis.fetch=async url=>{const u=new URL(String(url),'http://localhost');paths.push(u);return Response.json(catalog(p))}
 await page('/products?page=2&point=point&date=2026-10-20&q=Эклер')
 assert.equal(document.querySelectorAll('th').length,7);assert.match(document.querySelector('tbody')!.textContent!,/1 078,80 ₽\/шт/)
 await click('Цена ↕');await act(delay)
 const q=paths.at(-1)!.searchParams;assert.equal(q.get('sort'),'price');assert.equal(q.get('direction'),'asc');assert.equal(q.get('offset'),'0');assert.equal(q.get('department_id'),'point');assert.equal(q.get('price_at'),'2026-10-20');assert.equal(q.get('q'),'Эклер')
 await click('Цена ↑');await act(delay);assert.equal(paths.at(-1)!.searchParams.get('direction'),'desc')
 await click('Только непроверенные');await act(delay);assert.equal(paths.at(-1)!.searchParams.get('unverified'),'true')
 await click('Удалённые из EOS');await act(delay);assert.equal(paths.at(-1)!.searchParams.get('deleted'),'true')
 await click('Сбросить фильтры');await act(delay);assert.equal(paths.at(-1)!.searchParams.get('department_id'),'point');assert.equal(paths.at(-1)!.searchParams.get('q'),null)
 p={...p,cost_access:false};await click('Только непроверенные');await act(delay);assert.doesNotMatch(document.querySelector('thead')!.textContent!,/Себестоимость/)
}))

test('read-only card keeps history, source prices, management and cancel/save with concurrency guard',async()=>harness(async({dom,page,click,change})=>{
 let p=makeProduct();const requests:string[]=[],commands:Record<string,unknown>[]=[]
 globalThis.fetch=async(url,init)=>{const path=String(url);requests.push(path)
  if(init?.method==='PATCH'){const body=JSON.parse(String(init.body));commands.push(body);p={...p,...body,version:4};return Response.json(p)}
  if(path.includes('/history'))return Response.json([{id:'event',operation:'EDIT',actor_name:'Технолог',occurred_at:p.observed_at,reason:'Проверена маркировка',before:{name:'Источник'},after:{name:'Эклер'}}])
  if(path.startsWith('/api/products/product?'))return Response.json({...p,prices:[p.price]})
  return Response.json(catalog(p))
 }
 await page('/products/product?point=point&date=2026-10-20')
 assert.equal(document.querySelector('form'),null);assert.equal(document.querySelector('details'),null)
 assert.ok(!requests.some(p=>/\/history|\/costs|\/recipes/.test(p)))
 await click('История изменений');assert.match(document.querySelector('[role="dialog"]')!.textContent!,/Технолог.*Проверена маркировка/)
 await click('Закрыть окно');await click('Цены по точкам и источники');assert.match(document.querySelector('[role="dialog"]')!.textContent!,/Центр.*1 078,80/)
 await click('Закрыть окно');await click('Изменение карточки')
 assert.equal(document.querySelectorAll('[role="dialog"] textarea').length,6)
 await change(document.querySelector('[role="dialog"] input')!,'Новое название')
 await click('Отмена');assert.ok(document.querySelector('[role="alertdialog"]'));await click('Продолжить редактирование');assert.equal(document.querySelector<HTMLInputElement>('[role="dialog"] input')!.value,'Новое название')
 const reason=[...document.querySelectorAll('label')].find(l=>l.textContent==='Причина / комментарий')!.querySelector('input')!
 await change(reason,'Уточнение по этикетке')
 const form=document.querySelector('form')!
 await act(async()=>{form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}))});await act(delay)
 assert.equal(commands.length,1);assert.equal(commands[0].expected_version,3);assert.equal(commands[0].name,'Новое название');assert.equal(commands[0].composition,'Мука');assert.equal(document.querySelector('[role="dialog"]'),null)
 assert.match(document.querySelector('h1')!.textContent!,/Новое название/)
 await click('Изменение карточки');await change(document.querySelector('[role="dialog"] input')!,'Отменённое имя');await click('Отмена');await click('Закрыть без сохранения')
 await click('Изменение карточки');assert.equal(document.querySelector<HTMLInputElement>('[role="dialog"] input')!.value,'Новое название')
}))

test('cost review keeps its domain confirmations and guards modal close without a production mutation',async()=>harness(async({dom,page,click,change})=>{
 const p=makeProduct(),sent:Record<string,unknown>[]=[]
 const portal={contexts:[],selected_context:null,current:p.cost,history:[],total:0,offset:0,limit:25,note:null,can_review:true,review:{observation_id:'observation',content_hash:'a'.repeat(64),context:'Цех',warehouse:'Подтверждённый склад',quality:'REQUIRES_REVIEW',issues:[],candidate_amount:'10',components:[],can_confirm:true}}
 globalThis.fetch=async(url,init)=>{
  const path=String(url)
  if(init?.method==='POST'){sent.push(JSON.parse(String(init.body)));return new Response(null,{status:204})}
  if(path.includes('/costs'))return Response.json(portal)
  return Response.json(path.startsWith('/api/products/product?')?p:catalog(p))
 }
 await page('/products/product?point=point');await click('Себестоимость · ССН');await click('Проверить расчёт')
 const form=document.querySelector('form')!;await change(form.querySelector('input[inputmode="decimal"]')!,'10,00')
 await click('Закрыть окно');assert.ok(document.querySelector('[role="alertdialog"]'));await click('Продолжить редактирование')
 await change(form.querySelector('select')!,'no');await change(form.querySelector('textarea')!,'Проверено по первичному экспорту iikoOffice')
 await act(async()=>form.querySelectorAll<HTMLInputElement>('input[type="checkbox"]').forEach(x=>x.click()))
 await act(async()=>form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})))
 assert.equal(sent.length,1);assert.equal(sent[0].office_ssn,'10.00');assert.equal(sent[0].allow_updates,false);assert.equal(sent[0].warehouse_confirmed,true);assert.equal(sent[0].context_confirmed,true)
}))
