import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'

test('live catalog: API filters, paging, safe card, errors and empty data without demo fallback', async () => {
  const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
  const values={window:dom.window,document:dom.window.document,getComputedStyle:dom.window.getComputedStyle,IS_REACT_ACT_ENVIRONMENT:true,sessionStorage:dom.window.sessionStorage}
  const previous=Object.keys(values).map(name=>Object.getOwnPropertyDescriptor(globalThis,name)), originalFetch=globalThis.fetch
  let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
  const calls:URL[]=[]
  const product={id:'11111111-1111-4111-8111-111111111111',name:'Реальный эклер',sku:'001',unit_name:'шт',unit_weight_kg:'0.055',sale_mode:'UNKNOWN',sale_status:'ON_SALE',category_id:null,category_name:null,description:null,observed_at:'2026-10-08T09:00:00Z',source_deleted:false,price:null,prices:[],allowed_actions:[]}
  let failure=false,empty=false,costAccess=false
  try {
    Object.entries(values).forEach(([name,value])=>Object.defineProperty(globalThis,name,{configurable:true,value}))
    dom.window.scrollTo=()=>{}
    globalThis.fetch=async input=>{
      const url=new URL(String(input),'http://localhost');calls.push(url)
      if(failure)return new Response('{}',{status:503})
      if(url.pathname.endsWith('/history'))return Response.json([])
      if(url.pathname.includes(product.id))return Response.json(product)
      return Response.json({cost_access:costAccess,items:empty?[]:[{...product,id:url.searchParams.get('offset')==='25'?'22222222-2222-4222-8222-222222222222':product.id}],total:empty?0:26,offset:Number(url.searchParams.get('offset')),limit:25,points:[{id:'point',name:'Подтверждённая точка'}],categories:[],observed_at:product.observed_at})
    }
    const {createRoot}=await import('react-dom/client'),{default:Page}=await server.ssrLoadModule('/src/pages/ProductKnowledgePage.tsx')
    root=createRoot(document.getElementById('root')!)
    let key=0
    const render=async(url:string)=>act(async()=>root!.render(React.createElement(MemoryRouter,{key:++key,initialEntries:[url]},React.createElement(Routes,null,React.createElement(Route,{path:'/products',element:React.createElement(Page)}),React.createElement(Route,{path:'/products/:productId',element:React.createElement(Page)})))))
    const settle=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,300))})
    await render('/products');assert.match(document.body.textContent!,/Загружаем/);await settle()
    assert.match(document.body.textContent!,/Реальный эклер/);assert.doesNotMatch(document.body.textContent!,/Демонстрацион|Чизкейк|Себестоимость/)
    await act(async()=>document.querySelector<HTMLButtonElement>('[aria-label="Следующая страница"]')!.click());await settle()
    assert(calls.some(url=>url.searchParams.get('offset')==='25'))
    await render('/products?q=Эклер&mode=UNKNOWN&status=ON_SALE&point=point&date=2026-10-08');await settle()
    assert.equal(calls.at(-1)!.searchParams.get('q'),'Эклер');assert.equal(calls.at(-1)!.searchParams.get('department_id'),'point')
    await act(async()=>document.querySelector<HTMLAnchorElement>('tbody a')!.click());await settle()
    assert.match(document.querySelector('h1')!.textContent!,/Реальный эклер/);assert.match(document.body.textContent!,/Подтверждённые сведения отсутствуют/)
    const price={department_id:'point',department_name:'Подтверждённая точка',amount:'0',currency:'RUB',price_unit:'шт',valid_from:'2026-10-08',valid_to:'2026-10-09',observed_at:'2026-10-08T09:00:00Z'}
    Object.assign(product,{price,prices:[price],price_health:[{department_id:'point',last_success_at:'2026-10-08T09:00:00Z',stale:true,update_failed:true}]})
    await render('/products?point=point&date=2026-10-08');await settle()
    assert.match(document.querySelector('tbody')!.textContent!,/0 RUB \/ шт/)
    assert.match(document.querySelector('tbody')!.textContent!,/Ценовой снимок устарел/)
    assert.match(document.querySelector('tbody')!.textContent!,/Последнее обновление цен завершилось ошибкой/)
    assert.match(document.querySelector('tbody')!.textContent!,/Последнее успешное получение цен:/)
    await act(async()=>document.querySelector<HTMLAnchorElement>('tbody a')!.click());await settle()
    assert.match(document.body.textContent!,/период с 2026-10-08 до 2026-10-09/)
    assert.match(document.body.textContent!,/Ценовой снимок устарел/)
    Object.assign(product,{price:null,prices:[],price_conflict_points:['point']})
    await render('/products?point=point&date=2026-10-08');await settle()
    assert.match(document.querySelector('tbody')!.textContent!,/Цена требует проверки/)
    costAccess=true;Object.assign(product,{cost:{status:'VERIFIED',amount:'25.88',note:'Сверено с Office',estimated:false}})
    await render('/products');await settle();assert.match(document.querySelector('thead')!.textContent!,/Себестоимость/);assert.match(document.querySelector('tbody')!.textContent!,/25,88 ₽/)
    Object.assign(product,{cost:{status:'UNVERIFIED',amount:'999.99',note:'Требует сверки',estimated:false}})
    await render('/products');await settle();assert.match(document.querySelector('tbody')!.textContent!,/Требует сверки/);assert.doesNotMatch(document.querySelector('tbody')!.textContent!,/999/)
    failure=true;await render('/products');await settle();assert(document.querySelector('[role="alert"]'))
    failure=false;empty=true;await act(async()=>Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Повторить')!.click());await settle()
    assert.match(document.body.textContent!,/Каталог пока пуст/)
  } finally {
    if(root)await act(async()=>root!.unmount());globalThis.fetch=originalFetch
    Object.keys(values).forEach((name,i)=>{const d=previous[i];if(d)Object.defineProperty(globalThis,name,d);else Reflect.deleteProperty(globalThis,name)})
    dom.window.close();await server.close()
  }
})
