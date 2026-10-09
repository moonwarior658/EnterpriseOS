import assert from 'node:assert/strict'
import test from 'node:test'
import React, { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { createServer } from 'vite'
import { JSDOM } from 'jsdom'

test('K2 controls enforce explicit actions, preserve UUID confirmation and handle conflicts and duplicate submission', async () => {
  const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
  const values={window:dom.window,document:dom.window.document,getComputedStyle:dom.window.getComputedStyle,IS_REACT_ACT_ENVIRONMENT:true,sessionStorage:dom.window.sessionStorage}
  const previous=Object.keys(values).map(name=>Object.getOwnPropertyDescriptor(globalThis,name)),originalFetch=globalThis.fetch
  let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
  const commands:{path:string;method:string;body:Record<string,unknown>}[]=[]
  let fail=false, release:(() => void)|undefined, saved=0
  const product={id:'11111111-1111-4111-8111-111111111111',name:'Эклер EOS',version:3,category_id:null,description:'Локальное описание',characteristics:'Форма',composition:'Мука',allergens:'Глютен',storage:'Холодильник',training:'Материалы',sale_status:'ON_SALE',verified_at:null,allowed_actions:['EDIT','STATUS','DELETE','VERIFY']}
  const candidate={source_id:'a'.repeat(64),iiko_product_id:'22222222-2222-4222-8222-222222222222',name:'Эклер iiko',unit_name:'шт',source_deleted:false,existing_id:null,confirmation_hash:'b'.repeat(64)}
  try {
    Object.entries(values).forEach(([name,value])=>Object.defineProperty(globalThis,name,{configurable:true,value}))
    globalThis.fetch=async(input,init)=>{
      const path=String(input)
      if(path.includes('iiko-candidates'))return Response.json([candidate])
      commands.push({path,method:init!.method!,body:JSON.parse(String(init!.body))})
      if(release)await new Promise<void>(resolve=>{release=resolve})
      return fail?new Response('{}',{status:409}):Response.json(product)
    }
    const {createRoot}=await import('react-dom/client'),{ProductEditor,ManualProductAdd}=await server.ssrLoadModule('/src/pages/productKnowledge/ProductManagement.tsx')
    root=createRoot(document.getElementById('root')!)
    let key=0
    const render=async(element:React.ReactNode)=>act(async()=>root!.render(React.createElement(MemoryRouter,{key:++key},element)))
    const button=(label:string)=>Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(b=>b.textContent===label)!
    await render(React.createElement(ProductEditor,{product:{...product,allowed_actions:[]},categories:[],onSaved:()=>saved++}))
    assert.equal(document.querySelectorAll('button').length,0)
    await render(React.createElement(ProductEditor,{product,categories:[],onSaved:()=>saved++}))
    await act(async()=>button('Изменение карточки').click())
    assert.equal(document.querySelectorAll('textarea').length,6)
    assert.equal(document.querySelector<HTMLInputElement>('label input')!.value,'Эклер EOS')
    assert(button('Сохранить').disabled)
    // Submit event reaches the form independently of browser validity checks; backend validates reason.
    fail=true
    await act(async()=>document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})))
    assert.match(document.querySelector('[role="alert"]')!.textContent!,/Данные изменились/)
    assert.equal(commands.at(-1)!.body.expected_version,3)
    assert.equal(commands.at(-1)!.body.composition,'Мука')
    assert.equal(commands.at(-1)!.body.name,'Эклер EOS')
    await render(React.createElement(ProductEditor,{product:{...product,allowed_actions:['RESTORE']},categories:[],onSaved:()=>saved++}))
    assert.equal(document.querySelectorAll('button').length,1)
    await act(async()=>button('Восстановление').click())
    fail=false;release=()=>{}
    await act(async()=>{document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}))})
    assert.equal(commands.filter(c=>c.path.endsWith('/restore')).length,1)
    assert(document.querySelector('fieldset')!.disabled)
    await act(async()=>release!());release=undefined;assert.equal(saved,1)
    await render(React.createElement(ManualProductAdd,{onSaved:()=>saved++}))
    await act(async()=>document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})))
    assert.match(document.body.textContent!,new RegExp(candidate.iiko_product_id))
    await act(async()=>document.querySelector<HTMLInputElement>('input[type="radio"]')!.click())
    assert.match(document.querySelector('legend')!.textContent!,/Подтверждение/)
    await act(async()=>document.querySelectorAll('form')[1].dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})))
    assert.equal(commands.at(-1)!.body.iiko_product_id,candidate.iiko_product_id)
    assert.equal(commands.at(-1)!.body.confirmation_hash,candidate.confirmation_hash)
    assert.equal(commands.at(-1)!.body.sale_status,'OFF_SALE')
  } finally {
    if(root)await act(async()=>root!.unmount());globalThis.fetch=originalFetch
    Object.keys(values).forEach((name,i)=>{const d=previous[i];if(d)Object.defineProperty(globalThis,name,d);else Reflect.deleteProperty(globalThis,name)})
    dom.window.close();await server.close()
  }
})
