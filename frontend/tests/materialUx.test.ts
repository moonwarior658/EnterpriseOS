import test from 'node:test'
import assert from 'node:assert/strict'
import React, {act} from 'react'
import {MemoryRouter, Routes, Route} from 'react-router-dom'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'

const metric={id:'snapshot',status:'READY',amount:'275.34615384615384615',unit:'кг',receipt_at:'2026-10-14T04:00:00Z',date_from:'2026-04-01',date_to:'2026-10-21'}
const usage={status:'READY',quantity:'1078.799155418',unit:'кг',date_from:'2026-09-01',date_to:'2026-10-01'}
const product=()=>({id:'supply-id',name:'Сливки',kind:'RAW_MATERIAL',archived:false,supply_active:true,version:1,unit:'кг',unit_id:'kg',unit_weight_kg:'1.0788',photo_hash:null,primary_supplier:null,backup_supplier:null,backup_ambiguous:false,suppliers:[],purchase_access:true,allowed_actions:['EDIT','PHOTO','ARCHIVE','CONFIRM','METRICS_REFRESH'],current:null as unknown,latest:null as unknown,last_purchase_price:metric,six_month_average:{...metric,date_to:'2026-10-01'},monthly_consumption:usage})
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
   const {default:Page}=await server.ssrLoadModule('/src/pages/RawMaterialsPage.tsx')
   await render(React.createElement(MemoryRouter,{initialEntries:[path]},React.createElement(Routes,null,React.createElement(Route,{path:'/raw-materials',element:React.createElement(Page)}),React.createElement(Route,{path:'/raw-materials/:productId',element:React.createElement(Page)}))))
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

test('display decimals preserve exact source strings, unknown values and half-open periods',async()=>{
 const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
 try {
  const {materialNumber:n,materialPeriod:p}=await server.ssrLoadModule('/src/components/materialPresentation.ts')
  assert.equal(n('1078.799155418'),'1 078,80');assert.equal(n('275.346153846153846'),'275,35')
  assert.equal(n('999.999'),'1 000,00');assert.equal(n('9007199254740993.12'),'9 007 199 254 740 993,12')
  assert.equal(n('1E-9'),'0,00');assert.equal(n('1.0788e3'),'1 078,80');assert.equal(n('0'),'0,00');assert.equal(n('-5.555'),'-5,56');assert.equal(n(null),'Нет данных')
  assert.equal(p('2026-04-01','2026-10-01'),'01.04.2026 — 30.09.2026')
 }finally{await server.close()}
})

test('dialog guards unsaved close and Escape, traps focus, restores trigger, blocks close while busy',async()=>harness(async({dom,server,render,click})=>{
 const {MaterialDialog}=await server.ssrLoadModule('/src/components/MaterialDialog.tsx');let closed=0
 const trigger=document.getElementById('trigger')!;trigger.focus()
 await render(React.createElement(MaterialDialog,{title:'Правка',dirty:true,onClose:()=>closed++},React.createElement('input',{value:'Черновик',readOnly:true})))
 await act(async()=>{dom.window.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape'}))})
 assert.equal(closed,0);assert.ok(document.querySelector('[role="alertdialog"]'))
 await click('Продолжить редактирование');assert.equal(document.querySelector('[role="alertdialog"]'),null)
 const close=document.querySelector<HTMLButtonElement>('[aria-label="Закрыть окно"]')!;close.focus()
 await act(async()=>document.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true})))
 assert.equal(document.activeElement?.tagName,'INPUT')
 await click('Закрыть окно');await click('Закрыть без сохранения');assert.equal(closed,1)
 await render(null);assert.equal(document.activeElement,trigger)
 await render(React.createElement(MaterialDialog,{title:'Сохранение',busy:true,onClose:()=>closed++},'Ожидаем'))
 await act(async()=>dom.window.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape'})))
 assert.equal(closed,1);assert.equal(document.querySelector<HTMLButtonElement>('[aria-label="Закрыть окно"]')!.disabled,true)
}))

test('registry formats compact values, sends global sorts and filters, enrolls only from guarded modal',async()=>harness(async({dom,page,click,change})=>{
 const paths:string[]=[],posts:unknown[]=[]
 globalThis.fetch=async(url,init)=>{const path=String(url);paths.push(path)
  if(init?.method==='POST'){posts.push(JSON.parse(String(init.body)));return Response.json(product())}
  if(path.includes('/candidates'))return Response.json({items:[{id:'existing-id',name:'Товар Supply'}]})
  return Response.json({items:[product()],total:1,can_enroll:true,purchase_access:true,categories:[],suppliers:[]})
 }
 await page('/raw-materials')
 const table=document.querySelector('table')!;assert.match(table.textContent!,/1 078,80 кг/);assert.match(table.textContent!,/275,35 ₽\/кг/)
 assert.doesNotMatch(table.textContent!,/2026|14\.10|01\.09|с НДС/)
 await click('Вес условной единицы ↕');await act(delay);assert.ok(paths.at(-1)!.includes('sort=unit_weight_kg&direction=asc'))
 await click('Вес условной единицы ↑');await act(delay);assert.ok(paths.at(-1)!.includes('direction=desc'))
 await click('Без поставщика');await act(delay);assert.equal([...document.querySelectorAll('button')].find(b=>b.textContent==='Без поставщика')!.getAttribute('aria-pressed'),'true')
 await click('Архив карточек');await act(delay);assert.ok(paths.at(-1)!.includes('archived=true'))
 await click('Сбросить фильтры');await act(delay);assert.ok(!paths.at(-1)!.includes('archived'))
 await click('Включить существующий товар Supply');await act(delay)
 const dialog=document.querySelector('[role="dialog"]')!;assert.ok(dialog);assert.equal(document.querySelector('.material-page form'),null)
 await change(dialog.querySelector('select')!,'existing-id')
 await change(dialog.querySelector('input[minlength="3"]')!,'Согласовано владельцем')
 await act(async()=>dialog.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click())
 await act(async()=>dialog.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})))
 assert.deepEqual(posts,[{product_id:'existing-id',kind:'RAW_MATERIAL',reason:'Согласовано владельцем'}]);assert.equal(document.querySelector('[role="dialog"]'),null)
}))

test('card is read-only; draft save then confirm binds exact saved version, history opens separately',async()=>harness(async({dom,page,click,change})=>{
 let current=product();const calls:string[]=[],posts:{path:string;body:Record<string,unknown>}[]=[]
 globalThis.fetch=async(url,init)=>{const path=String(url);calls.push(path)
  if(init?.method==='PATCH'){
   const body=JSON.parse(String(init.body));posts.push({path,body});current={...current,version:2,latest:{id:'spec',revision:1,status:'DRAFT',content_hash:'a'.repeat(64),knowledge:body.knowledge,created_at:'2026-10-20T04:00:00Z',author:'Снабженец'}};return Response.json(current)
  }
  if(init?.method==='POST'){
   const body=JSON.parse(String(init.body));posts.push({path,body});const spec={...(current.latest as object),status:'CONFIRMED'};current={...current,version:3,latest:spec,current:spec};return Response.json(current)
  }
  if(path.includes('/standards/options'))return Response.json({products:[],suppliers:[],units:[]})
  if(path.includes('/history'))return Response.json({versions:[],total:0,events:[{id:'audit',operation:'DRAFT_SAVED',author:'Снабженец',occurred_at:'2026-10-20T04:00:00Z',reason:'Проверена этикетка',before:{},after:{revision:1}}],event_total:1})
  if(path.includes('/metrics'))return Response.json({current:metric,items:[metric],refresh:null})
  return Response.json(current)
 }
 await page('/raw-materials/supply-id')
 assert.equal(document.querySelector('form'),null);assert.equal(document.querySelector('details'),null)
 assert.doesNotMatch(document.body.textContent!,/SupplyProduct:|Назначения поставщиков из Supply/)
 assert.ok(!calls.some(p=>p.includes('/history')||p.includes('/usage')))
 await click('История изменений');assert.match(document.querySelector('[role="dialog"]')!.textContent!,/Снабженец.*Проверена этикетка.*Версия 1/)
 await click('Закрыть окно');await click('Изменить спецификацию');await act(delay)
 const form=document.querySelector('form')!;await change(form.querySelector('input[minlength="3"]')!,'Проверена этикетка')
 await change(form.querySelector('textarea')!,'Для кремов')
 assert.match(document.body.textContent!,/Сначала сохраните черновик/)
 await act(async()=>dom.window.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape'})))
 assert.ok(document.querySelector('[role="alertdialog"]'));await click('Продолжить редактирование')
 await act(async()=>form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await act(delay)
 assert.equal(posts.length,1);assert.equal(posts[0].body.expected_version,1)
 assert.match(document.querySelector('[role="dialog"]')!.textContent!,/Сохранённый черновик: версия 1/)
 await act(async()=>document.querySelector<HTMLInputElement>('.material-confirm input[type="checkbox"]')!.click())
 const confirm=[...document.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='Подтвердить версию 1')!;assert.equal(confirm.disabled,false)
 await act(async()=>confirm.click());await act(delay)
 assert.equal(posts.length,2);assert.equal(posts[1].body.expected_version,2);assert.equal(posts[1].body.specification_id,'spec');assert.equal(posts[1].body.content_hash,'a'.repeat(64));assert.equal(posts[1].body.primary_product_id,'supply-id')
 assert.match(document.querySelector('[role="dialog"]')!.textContent!,/Действующая подтверждённая версия: 1/)
}))

test('photo upload sends file and concurrency version once, disables duplicate action, renders saved photo',async()=>harness(async({dom,page,click,change})=>{
 let current=product(),uploads=0,release:()=>void=()=>{}
 globalThis.fetch=async(url,init)=>{
  if(init?.method==='PUT'){
   uploads++;const body=init.body as FormData;assert.equal(body.get('expected_version'),'1');assert.equal(body.get('reason'),'Фото этикетки');assert.equal((body.get('file') as File).name,'label.png')
   await new Promise<void>(r=>{release=r});current={...current,version:2,photo_hash:'saved-photo' as never};return Response.json(current)
  }
  if(String(url).includes('/photo?'))return new Response(new Blob(['fixture'],{type:'image/png'}))
  if(String(url).includes('/metrics'))return Response.json({items:[],refresh:null})
  return Response.json(current)
 }
 await page('/raw-materials/supply-id');await click('Изменить фотографию')
 const input=document.querySelector<HTMLInputElement>('input[type="file"]')!
 Object.defineProperty(input,'files',{value:[new File(['fixture'],'label.png',{type:'image/png'})],configurable:true})
 await act(async()=>input.dispatchEvent(new dom.window.Event('change',{bubbles:true})))
 await change(document.querySelector('input[minlength="3"]')!,'Фото этикетки')
 const form=document.querySelector('form')!
 await act(async()=>{form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}))})
 assert.equal(uploads,1);assert.equal(document.querySelector<HTMLButtonElement>('[aria-label="Закрыть окно"]')!.disabled,true)
 await act(async()=>release());await act(delay)
 assert.equal(document.querySelector('[role="dialog"]'),null);assert.ok(document.querySelector('img[src^="blob:"]'))
}))

test('technical reader has no financial calls or edit actions; usage history stays accessible',async()=>harness(async({page,click})=>{
 const paths:string[]=[];const p={...product(),purchase_access:false,allowed_actions:[],last_purchase_price:undefined,six_month_average:undefined}
 globalThis.fetch=async url=>{const path=String(url);paths.push(path);return Response.json(path.includes('/usage')?{items:[usage]}:p)}
 await page('/raw-materials/supply-id');assert.equal(document.querySelector('form'),null)
 assert.equal([...document.querySelectorAll('button')].some(b=>b.textContent==='Изменить спецификацию'),false)
 await click('История расхода');assert.match(document.body.textContent!,/1 078,80 кг/)
 assert.ok(paths.some(p=>p.includes('/usage')));assert.ok(!paths.some(p=>p.includes('/metrics')||p.includes('/document-admissions')))
 assert.doesNotMatch(document.body.textContent!,/₽|275,35/)
}))

test('specification editing retains exact weights and coefficients; manufacturer list accepts commas',async()=>harness(async({dom,server,render,change})=>{
 const {MaterialEditor}=await server.ssrLoadModule('/src/components/MaterialEditor.tsx')
 const coefficient={from_unit_id:'pcs',to_unit_id:'kg',supplier_iiko_id:'supplier',container_id:null,factor:'0.123456789012',valid_from:'2026-04-01',valid_to:'2026-10-01',packaging:'Проверенная упаковка',evidence:'Первичная маркировка'}
 const knowledge={purpose:'Крем',composition:'',allergens:'',characteristics:'',receiving_requirements:'',storage:'',shelf_life:'',manufacturer:'БМК',unit_weight_kg:'0.123456789',weight_evidence:'Первичная маркировка',conversions:[coefficient],allowed_manufacturers:['БМК']}
 let sent:Record<string,unknown>|undefined
 globalThis.fetch=async(url,init)=>{
  if(init?.method==='PATCH'){sent=JSON.parse(String(init.body));return Response.json({})}
  assert.match(String(url),/standards\/options/)
  return Response.json({products:[],suppliers:[{id:'supplier',name:'Поставщик'}],units:[{id:'pcs',name:'шт'},{id:'kg',name:'кг'}]})
 }
 await render(React.createElement(MaterialEditor,{material:{...product(),latest:{id:'spec',status:'DRAFT',revision:1,knowledge}},onClose:()=>{},onSaved:()=>{}}))
 await act(delay)
 const labels=Array.from(document.querySelectorAll('label'))
 const factor=labels.find(l=>l.textContent?.startsWith('Коэффициент'))!.querySelector('input')!
 const weight=labels.find(l=>l.textContent?.startsWith('Вес условной единицы'))!.querySelector('input')!
 assert.equal(factor.value,'0.123456789012');assert.equal(weight.value,'0.123456789')
 const manufacturers=labels.find(l=>l.textContent?.startsWith('Разрешённые производители'))!.querySelector('input')!
 await change(manufacturers,'БМК, ');assert.equal(manufacturers.value,'БМК, ')
 await change(manufacturers,'БМК, Ларица')
 await change(document.querySelector('input[minlength="3"]')!,'Уточнение по маркировке')
 await act(async()=>document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})))
 const saved=sent!.knowledge as typeof knowledge
 assert.equal(saved.unit_weight_kg,'0.123456789');assert.equal(saved.conversions[0].factor,'0.123456789012');assert.deepEqual(saved.allowed_manufacturers,['БМК','Ларица'])
}))
