import test from 'node:test'
import assert from 'node:assert/strict'
import React,{act} from 'react'
import {JSDOM} from 'jsdom'
import {createServer} from 'vite'

test('explicit document proof, safe retry key, withdrawal history and read-only role',async()=>{
 const server=await createServer({server:{middlewareMode:true,ws:false},appType:'custom'})
 const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost',pretendToBeVisual:true})
 const values={window:dom.window,document:dom.window.document,sessionStorage:dom.window.sessionStorage,IS_REACT_ACT_ENVIRONMENT:true}
 const previous=Object.keys(values).map(k=>Object.getOwnPropertyDescriptor(globalThis,k)),oldFetch=globalThis.fetch
 let root:ReturnType<typeof import('react-dom/client').createRoot>|undefined
 const doc={document_id:'invoice',source_hash:'a'.repeat(64),number:'2929',receipt_at:'2026-06-08',supplier_flags:{is_employee:true},lines:[{num:'1',amountUnit:'kg',amount:'5.32',actualAmount:'5.32',containerId:'package',sum:'2939.86',unit_name:'кг'}]}
 const decision={id:'decision',snapshot_id:'snapshot',kind:'EMPLOYEE_PURCHASE',action:'GRANT',revision:1,document_id:'invoice',document_hash:doc.source_hash,line_num:'',evidence:'Чек №42',comment:'Проверка первички',author:'Снабжение',created_at:'2026-10-20T09:00:00Z',current:true}
 let granted=false,fail=true,version=1,saved=0
 const commands:Record<string,unknown>[]=[]
 try{
  Object.entries(values).forEach(([k,v])=>Object.defineProperty(globalThis,k,{value:v,configurable:true}))
  globalThis.fetch=async(url,init)=>{
   if(init?.method==='POST'){
    assert.match(String(url),/\/metrics\/snapshot\/admissions$/)
    const body=JSON.parse(String(init.body));commands.push(body)
    if(fail)return new Response('{"detail":"private trace"}',{status:503})
    granted=body.action==='GRANT';version++;return Response.json(decision)
   }
   assert.match(String(url),/\/document-admissions\?offset=/)
   return Response.json({version,items:version>1?[{...decision,action:granted?'GRANT':'REVOKE'}]:[],current_items:version>1?[{...decision,action:granted?'GRANT':'REVOKE',revision:version-1}]:[]})
  }
  const {createRoot}=await import('react-dom/client'),{MaterialDocumentAdmissions}=await server.ssrLoadModule('/src/components/MaterialDocumentAdmissions.tsx')
  root=createRoot(document.getElementById('root')!)
  const props={material:{id:'product',unit:'кг',unit_id:'kg',allowed_actions:['DOCUMENT_ADMIT']},sources:{metric:{id:'snapshot'},documents:[doc]},onUpdated:()=>saved++}
  await act(async()=>{root!.render(React.createElement(MaterialDocumentAdmissions,props))})
  assert.match(document.body.textContent!,/Контрагент отмечен в iiko как сотрудник/)
  assert.equal([...document.querySelectorAll('button')].filter(b=>b.textContent?.includes('Верифицировать')).length,1)
  const choose=()=>[...document.querySelectorAll('button')].find(b=>b.textContent?.includes('строки этого сырья в документе'))!
  await act(async()=>choose().click())
  assert.equal((document.querySelector('input[type="checkbox"]') as HTMLInputElement).checked,false)
  assert.equal((document.querySelector('input') as HTMLInputElement).value,'')
  async function fill(){
   await act(async()=>{
    const input=document.querySelector('input')!,area=document.querySelector('textarea')!
    Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value')!.set!.call(input,'Чек №42');input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));input.dispatchEvent(new dom.window.Event('change',{bubbles:true}))
    Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype,'value')!.set!.call(area,'Проверка первички');area.dispatchEvent(new dom.window.Event('input',{bubbles:true}));area.dispatchEvent(new dom.window.Event('change',{bubbles:true}))
    ;(document.querySelector('input[type="checkbox"]') as HTMLInputElement|null)?.click()
   })
  }
  await fill()
  const submit=async()=>act(async()=>{document.querySelector('form')!.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}))})
  await submit();assert.match(document.body.textContent!,/повторный запрос безопасен/);assert.doesNotMatch(document.body.textContent!,/private trace/)
  fail=false;await submit();assert.equal(commands[0].request_id,commands[1].request_id);assert.equal(commands[1].line_num,'');assert.equal(commands[1].primary_checked,true);assert.equal(saved,1)
  assert.match(document.body.textContent!,/Чек №42/);assert.match(document.body.textContent!,/Снабжение/)
  await act(async()=>choose().click());await fill();await submit()
  assert.equal(commands[2].action,'REVOKE');assert.equal(commands[2].expected_revision,1);assert.notEqual(commands[2].request_id,commands[1].request_id)
  await act(async()=>{root!.render(React.createElement(MaterialDocumentAdmissions,{...props,material:{...props.material,allowed_actions:[]}}))})
  assert.equal(document.querySelectorAll('form').length,0);assert.equal([...document.querySelectorAll('button')].filter(b=>b.textContent?.includes('Проверить')||b.textContent?.includes('Отозвать')||b.textContent?.includes('Верифицировать')).length,0)
 }finally{
  if(root)await act(async()=>root!.unmount());globalThis.fetch=oldFetch
  Object.keys(values).forEach((k,i)=>{if(previous[i])Object.defineProperty(globalThis,k,previous[i]!);else Reflect.deleteProperty(globalThis,k)})
  dom.window.close();await server.close()
 }
})
