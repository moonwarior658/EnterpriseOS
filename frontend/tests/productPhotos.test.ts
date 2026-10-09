import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'

test('photo: private fetch, placeholder, revoked blob, manager upload/delete, conflict and duplicate submission', async () => {
  const server = await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const dom = new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
  const values = {window:dom.window, document:dom.window.document, getComputedStyle:dom.window.getComputedStyle, IS_REACT_ACT_ENVIRONMENT:true, sessionStorage:dom.window.sessionStorage}
  const previous = Object.keys(values).map(name=>Object.getOwnPropertyDescriptor(globalThis,name))
  const originalFetch=globalThis.fetch, originalCreate=URL.createObjectURL, originalRevoke=URL.revokeObjectURL
  let root: ReturnType<typeof import('react-dom/client').createRoot> | undefined
  const requests: {path:string; init?:RequestInit}[] = [], revoked:string[]=[]
  let saved=0, status=200, release:(()=>void)|undefined, held=false
  const product={id:'11111111-1111-4111-8111-111111111111',name:'Эклер',photo:'a'.repeat(64),version:3,allowed_actions:['EDIT']}
  try {
    Object.entries(values).forEach(([name,value])=>Object.defineProperty(globalThis,name,{configurable:true,value}))
    URL.createObjectURL=()=> 'blob:private-photo';URL.revokeObjectURL=url=>revoked.push(url)
    globalThis.fetch=async(input,init)=>{
      requests.push({path:String(input),init})
      if(held)await new Promise<void>(resolve=>{release=resolve})
      return new Response(init?.method ? '{}' : 'image', {status})
    }
    const {createRoot}=await import('react-dom/client')
    const {ProductPhoto,ProductPhotoEditor}=await server.ssrLoadModule('/src/pages/productKnowledge/ProductPhoto.tsx')
    root=createRoot(document.getElementById('root')!)
    let key=0
    const render=async(component:React.ComponentType, props:object)=>act(async()=>root!.render(React.createElement(component,{key:++key,...props})))
    await render(ProductPhoto,{product:{...product,photo:null}})
    assert.match(document.body.textContent!,/Нет фото/);assert.equal(requests.length,0)
    await render(ProductPhoto,{product})
    assert.equal(document.querySelector('img')!.alt,'Эклер')
    assert.equal(requests[0].init!.cache,'no-store')
    assert.match(String((requests[0].init!.headers as Record<string,string>).Authorization),/^Bearer /)
    await render(ProductPhoto,{product:{...product,photo:null}})
    assert.deepEqual(revoked,['blob:private-photo'])
    status=404;await render(ProductPhoto,{product});assert.match(document.body.textContent!,/Фото недоступно/)
    await render(ProductPhotoEditor,{product:{...product,allowed_actions:[]},onSaved:()=>saved++})
    assert.equal(document.querySelector('form'),null)
    await render(ProductPhotoEditor,{product,onSaved:()=>saved++})
    const input=document.querySelector<HTMLInputElement>('input:not([type="file"])')!
    await act(async()=>{const setter=Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value')!.set!;setter.call(input,'Новая фотография');input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));input.dispatchEvent(new dom.window.Event('change',{bubbles:true}))})
    const fileInput=document.querySelector<HTMLInputElement>('input[type="file"]')!
    Object.defineProperty(fileInput,'files',{configurable:true,value:[new File(['photo'],'eclair.png',{type:'image/png'})]})
    await act(async()=>fileInput.dispatchEvent(new dom.window.Event('change',{bubbles:true})))
    status=200;held=true
    await act(async()=>{for(let i=0;i<2;i++)document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}))})
    assert.equal(requests.filter(r=>r.init?.method==='PUT').length,1)
    assert(document.querySelector('fieldset')!.disabled)
    const form=requests.at(-1)!.init!.body as FormData
    assert.equal(form.get('expected_version'),'3');assert.equal(form.get('reason'),'Новая фотография');assert(form.get('file') instanceof File)
    held=false;await act(async()=>release!());assert.equal(saved,1)
    status=409
    await act(async()=>Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Удалить фотографию')!.click())
    assert.match(document.querySelector('[role="alert"]')!.textContent!,/Данные изменились/)
    assert.equal(requests.at(-1)!.init!.method,'DELETE')
  } finally {
    if(root)await act(async()=>root!.unmount())
    globalThis.fetch=originalFetch;URL.createObjectURL=originalCreate;URL.revokeObjectURL=originalRevoke
    Object.keys(values).forEach((name,i)=>{const d=previous[i];if(d)Object.defineProperty(globalThis,name,d);else Reflect.deleteProperty(globalThis,name)})
    dom.window.close();await server.close()
  }
})
