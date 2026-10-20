import assert from 'node:assert/strict'
import test from 'node:test'
import React, {act} from 'react'
import {MemoryRouter, Routes, Route} from 'react-router-dom'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'

test('material API authenticates, carries concurrency version, and hides backend errors',async()=>{
  const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const oldFetch=globalThis.fetch,previous=Object.getOwnPropertyDescriptor(globalThis,'sessionStorage')
  Object.defineProperty(globalThis,'sessionStorage',{configurable:true,value:{getItem:()=> 'fixture'}})
  try {
    const {materialRequest}=await server.ssrLoadModule('/src/services/rawMaterials.ts')
    let path='',command:RequestInit|undefined
    globalThis.fetch=async(url,init)=>{path=String(url);command=init;return Response.json({id:'supply-id'})}
    assert.equal((await materialRequest('/supply-id/knowledge',{method:'PATCH',body:JSON.stringify({expected_version:2,knowledge:{purpose:'Крем'}})})).id,'supply-id')
    assert.equal(path,'/api/raw-materials/supply-id/knowledge');assert.equal(new Headers(command?.headers).get('Authorization'),'Bearer fixture')
    assert.equal(JSON.parse(String(command?.body)).expected_version,2)
    globalThis.fetch=async()=>new Response('{"detail":"private price 98765.43 stack"}',{status:409})
    await assert.rejects(materialRequest('/supply-id'),/Карточка изменилась/)
  }finally{globalThis.fetch=oldFetch;if(previous)Object.defineProperty(globalThis,'sessionStorage',previous);else Reflect.deleteProperty(globalThis,'sessionStorage');await server.close()}
})

test('registry and card show missing metrics, drafts, backend actions and safe failures',async()=>{
  const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
  const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
  const values={window:dom.window,document:dom.window.document,getComputedStyle:dom.window.getComputedStyle,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true}
  const previous=Object.keys(values).map(name=>Object.getOwnPropertyDescriptor(globalThis,name)),oldFetch=globalThis.fetch
  let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
  let monetary=true,allowEdit=true,fail=false
  const specification={id:'spec',revision:1,content_hash:'a'.repeat(64),status:'DRAFT',knowledge:{purpose:'Крем',manufacturer:'БМК'},created_at:'2026-10-20T04:00:00Z',confirmed_at:null,author:'Снабженец',approver:null,primary_product_id:null}
  const product=()=>({id:'supply-id',name:'<script>Сливки</script>',kind:'RAW_MATERIAL',archived:false,supply_active:true,version:2,unit:'кг',unit_weight_kg:null,photo_hash:null,primary_supplier:{id:'supplier',name:'БМК поставка',role:'PRIMARY',priority:0,available:true},backup_supplier:null,backup_ambiguous:false,suppliers:[],purchase_access:monetary,allowed_actions:allowEdit?['EDIT','PHOTO','ARCHIVE','CONFIRM']:[],current:null,latest:specification})
  try{
    Object.entries(values).forEach(([name,value])=>Object.defineProperty(globalThis,name,{configurable:true,value}))
    globalThis.fetch=async(url)=>{
      if(fail)return new Response('{"detail":"private price 98765.43 stack"}',{status:503})
      const path=String(url)
      if(path.includes('/usage'))return Response.json({items:[]})
      if(path.includes('/metrics'))return Response.json({items:[],refresh:null})
      if(path.includes('/history'))return Response.json({versions:[specification],total:1,events:[],event_total:0})
      if(path.includes('/supply-id'))return Response.json(product())
      return Response.json({items:[product()],total:1,offset:0,limit:25,can_enroll:false,purchase_access:monetary,categories:[],suppliers:[]})
    }
    const {createRoot}=await import('react-dom/client'),{default:Page}=await server.ssrLoadModule('/src/pages/RawMaterialsPage.tsx')
    root=createRoot(document.getElementById('root')!)
    const render=async(path:string,key:string)=>{await act(async()=>{root!.render(React.createElement(MemoryRouter,{initialEntries:[path],key},React.createElement(Routes,null,React.createElement(Route,{path:'/raw-materials',element:React.createElement(Page)}),React.createElement(Route,{path:'/raw-materials/:productId',element:React.createElement(Page)}))))});await act(async()=>{await new Promise(r=>setTimeout(r,300))})}
    await render('/raw-materials','list')
    assert.equal(document.querySelectorAll('thead th').length,8);assert.match(document.body.textContent!,/Последняя цена прихода/);assert.match(document.body.textContent!,/Нет данных/);assert.equal(document.querySelector('script'),null)
    await render('/raw-materials/supply-id','card')
    assert.match(document.body.textContent!,/Неподтверждённый черновик/);assert.match(document.body.textContent!,/Резервные товары: Ещё не утверждены/)
    const confirm=[...document.querySelectorAll('button')].find(x=>x.textContent==='Подтвердить версию 1')!;assert.equal(confirm.disabled,true)
    monetary=false;allowEdit=false;await render('/raw-materials/supply-id','restricted')
    assert.match(document.body.textContent!,/Нет доступа к закупочным ценам/);assert.equal(document.querySelector('.material-editor'),null);assert.doesNotMatch(document.body.textContent!,/98765|execution_id|private price/)
    fail=true;await render('/raw-materials','error');assert.match(document.body.textContent!,/Не удалось выполнить/);assert.doesNotMatch(document.body.textContent!,/private price|98765|Сливки/)
  }finally{if(root)await act(async()=>root!.unmount());globalThis.fetch=oldFetch;Object.keys(values).forEach((name,index)=>{if(previous[index])Object.defineProperty(globalThis,name,previous[index]!);else Reflect.deleteProperty(globalThis,name)});dom.window.close();await server.close()}
})
