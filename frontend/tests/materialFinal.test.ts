import test from 'node:test'
import assert from 'node:assert/strict'
import React,{act} from 'react'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'

test('knowledge usage history reads no monetary endpoints and distinguishes unknown from zero',async()=>{
 const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'})
 const values={window:dom.window,document:dom.window.document,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true}
 const previous=Object.keys(values).map(k=>Object.getOwnPropertyDescriptor(globalThis,k)),oldFetch=globalThis.fetch
 let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
 const paths:string[]=[]
 try {
  Object.entries(values).forEach(([k,v])=>Object.defineProperty(globalThis,k,{value:v,configurable:true}))
  globalThis.fetch=async url=>{paths.push(String(url));assert.match(String(url),/\/usage\?/);return Response.json({items:[{id:'blocked',status:'BLOCKED',quantity:null,reasons:['Границы баланса не подтверждены'],categories:{INVENTORY:'-5'},balance:{opening:null,closing:'10',residual:null},documents:[]},{id:'zero',status:'READY',quantity:'0',unit:'кг',categories:{},documents:[]}]})}
  const {createRoot}=await import('react-dom/client'),{UsagePanel}=await server.ssrLoadModule('/src/components/MaterialUsage.tsx')
  root=createRoot(document.getElementById('root')!)
  await act(async()=>{root!.render(React.createElement(UsagePanel,{id:'product'}))})
  const body=document.body.textContent!
  assert.match(body,/Требуется проверка/);assert.match(body,/0,00 кг/);assert.match(body,/Инвентаризации: -5,00/);assert.match(body,/Независимая сверка iikoOffice не выполнена/)
  assert.doesNotMatch(body,/₽|RUB|OFFICE_VERIFIED/);assert.equal(paths.length,1)
 }finally{
  if(root)await act(async()=>root!.unmount());globalThis.fetch=oldFetch
  Object.keys(values).forEach((k,i)=>{if(previous[i])Object.defineProperty(globalThis,k,previous[i]!);else Reflect.deleteProperty(globalThis,k)})
  dom.window.close();await server.close()
 }
})

test('reserve selection submits only an explicitly allowed reserve and never changes Supply',async()=>{
 const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost'})
 const values={window:dom.window,document:dom.window.document,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true}
 const previous=Object.keys(values).map(k=>Object.getOwnPropertyDescriptor(globalThis,k)),oldFetch=globalThis.fetch
 let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
 try{
  Object.entries(values).forEach(([k,v])=>Object.defineProperty(globalThis,k,{value:v,configurable:true}))
  let called=0,saved=0
  globalThis.fetch=async(url,init)=>{called++;assert.equal(String(url),'/api/raw-materials/profile/reserve-selection');assert.equal(init?.method,'POST');const payload=JSON.parse(String(init?.body));assert.equal(payload.target_product_id,'reserve');assert.equal(payload.specification_id,'spec');assert.equal(payload.expected_version,4);return Response.json({})}
  const {createRoot}=await import('react-dom/client'),{ReserveSelection}=await server.ssrLoadModule('/src/components/MaterialStandards.tsx')
  root=createRoot(document.getElementById('root')!)
  await act(async()=>{root!.render(React.createElement(ReserveSelection,{material:{id:'profile',version:4,current:{id:'spec'},allowed_actions:['EDIT'],reserves:[{product_id:'reserve',name:'Разрешённый товар',manufacturer:'БМК'}]},onSaved:()=>saved++}))})
  const select=document.querySelector('select')!;const input=document.querySelector('input')!
  assert.equal(document.querySelectorAll('option').length,2);assert.equal(document.querySelector('button')!.disabled,true)
  await act(async()=>{select.value='reserve';select.dispatchEvent(new dom.window.Event('change',{bubbles:true}));Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value')!.set!.call(input,'Выбор снабжения');input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));input.dispatchEvent(new dom.window.Event('change',{bubbles:true}))})
  // Submit exercises the same form handler after explicit human selection.
  await act(async()=>{document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}))})
  assert.equal(called,1);assert.equal(saved,1)
 }finally{
  if(root)await act(async()=>root!.unmount());globalThis.fetch=oldFetch
  Object.keys(values).forEach((k,i)=>{if(previous[i])Object.defineProperty(globalThis,k,previous[i]!);else Reflect.deleteProperty(globalThis,k)})
  dom.window.close();await server.close()
 }
})
