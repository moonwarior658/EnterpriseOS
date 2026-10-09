import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'

test('price schedule form loads confirmed K3 configuration and submits its exact payload', async () => {
  const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
  const globals={window:dom.window,document:dom.window.document,getComputedStyle:dom.window.getComputedStyle,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true}
  const previous=Object.keys(globals).map(key=>Object.getOwnPropertyDescriptor(globalThis,key)), originalFetch=globalThis.fetch
  let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
  const policy={source_id:'a'.repeat(64),confirmed_point_ids:['11111111-1111-4111-8111-111111111111'],currency:'RUB',office_evidence:'Office confirmed'}
  let posted:Record<string,unknown>|undefined, saved=false, reject=false
  try {
    Object.entries(globals).forEach(([key,value])=>Object.defineProperty(globalThis,key,{configurable:true,value}))
    sessionStorage.setItem('eos_access_token','test-only')
    globalThis.fetch=async(input,init)=>{
      if(String(input).endsWith('/product-price-configuration'))return Response.json({payload:policy,points:[{id:policy.confirmed_point_ids[0],name:'Подтверждённая точка'}]})
      assert.equal(init?.method,'POST');posted=JSON.parse(String(init?.body))
      if(reject)return Response.json({detail:[{loc:['body'],msg:'Value error, validation error for PriceRefreshPayload: source_id Field required'}]},{status:422})
      return Response.json({...posted,id:3})
    }
    const {createRoot}=await import('react-dom/client'),{default:Form}=await server.ssrLoadModule('/src/pages/AutomationScheduleForm.tsx')
    root=createRoot(document.getElementById('root')!)
    await act(async()=>root!.render(React.createElement(Form,{schedule:null,automationTypes:[{key:'products.sync_iiko_prices',display_name:'Обновить цены продукции',description:'Цены',category:'products',is_system:true,supports_manual_run:false}],automationTypesLoading:false,automationTypesError:'',onCancel(){},onDeleted(){},onSaved(){saved=true}})))
    const name=document.querySelector<HTMLInputElement>('input[maxlength="160"]')!
    await act(async()=>{Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value')!.set!.call(name,'Цены');name.dispatchEvent(new dom.window.Event('input',{bubbles:true}))})
    const type=Array.from(document.querySelectorAll('select')).find(s=>Array.from(s.options).some(o=>o.value==='products.sync_iiko_prices'))!
    await act(async()=>{type.value='products.sync_iiko_prices';type.dispatchEvent(new dom.window.Event('change',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,100))})
    assert.match(document.body.textContent!,/Подтверждённая точка/);assert.match(document.body.textContent!,/Валюта: RUB/)
    reject=true
    await act(async()=>{document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));await new Promise(resolve=>setTimeout(resolve,100))})
    assert.match(document.body.textContent!,/Проверьте подтверждённую конфигурацию цен/)
    assert.doesNotMatch(document.body.textContent!,/Заполните обязательные поля формы/)
    reject=false
    await act(async()=>{document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));await new Promise(resolve=>setTimeout(resolve,100))})
    assert.deepEqual(posted?.payload,policy);assert.deepEqual(posted?.schedule_config,{type:'interval',minutes:60});assert.equal(posted?.scope_type,'company');assert.equal(saved,true)
  } finally {
    if(root)await act(async()=>root!.unmount());globalThis.fetch=originalFetch
    Object.keys(globals).forEach((key,index)=>{const value=previous[index];if(value)Object.defineProperty(globalThis,key,value);else Reflect.deleteProperty(globalThis,key)})
    dom.window.close();await server.close()
  }
})
