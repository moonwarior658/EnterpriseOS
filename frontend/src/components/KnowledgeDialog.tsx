import { useEffect, useRef, useState, type ReactNode } from 'react'
import { EosDialog } from './EosDialog'

/** Knowledge actions reuse the EOS dialog, including its shared scroll lock. */
export function KnowledgeDialog({title,children,onClose,dirty=false,busy=false,cancelLabel}:{title:string;children:ReactNode;onClose:()=>void;dirty?:boolean;busy?:boolean;cancelLabel?:string}) {
  const [discard,setDiscard]=useState(false)
  const body=useRef<HTMLDivElement>(null)
  const close=()=>{if(busy)return;if(discard){setDiscard(false);return}if(dirty)setDiscard(true);else onClose()}
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null
    const dialog=body.current?.closest<HTMLElement>('[role="dialog"]')
    const focusable=()=>Array.from((dialog?.querySelector('[role="alertdialog"]')||dialog)?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex="0"]')||[]).filter(el=>!el.closest('fieldset:disabled,[hidden],[inert]')&&!el.hidden&&(!el.closest('details:not([open])')||el.tagName==='SUMMARY'))
    focusable()[0]?.focus()
    const trap=(e:KeyboardEvent)=>{
      if(e.key!=='Tab')return
      const items=focusable(),first=items[0],last=items.at(-1)
      if(e.shiftKey&&(document.activeElement===first||!dialog?.contains(document.activeElement))){e.preventDefault();last?.focus()}
      else if(!e.shiftKey&&(document.activeElement===last||!dialog?.contains(document.activeElement))){e.preventDefault();first?.focus()}
    }
    document.addEventListener('keydown',trap)
    return()=>{document.removeEventListener('keydown',trap);previous?.focus()}
  },[])
  useEffect(()=>{
    if(!dirty)return
    const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''}
    window.addEventListener('beforeunload',warn)
    return()=>window.removeEventListener('beforeunload',warn)
  },[dirty])
  useEffect(()=>{
    if(discard)body.current?.parentElement?.querySelector<HTMLButtonElement>('[role="alertdialog"] button')?.focus()
  },[discard])
  return <EosDialog title={title} onClose={close} className="material-dialog product-page">
    <button type="button" className="secondary-action material-dialog-close" aria-label="Закрыть окно" disabled={busy} onClick={close}>×</button>
    <div ref={body} className="material-dialog-body" inert={discard}>{children}</div>
    {cancelLabel&&<button className="secondary-action" disabled={busy} onClick={close}>{cancelLabel}</button>}
    {busy&&<p role="status">Сохраняем изменения. Дождитесь завершения.</p>}
    {discard&&<div role="alertdialog" aria-label="Несохранённые изменения" className="material-discard"><p>Есть несохранённые изменения. Закрыть окно без сохранения?</p><button className="secondary-action" onClick={()=>setDiscard(false)}>Продолжить редактирование</button><button className="danger-action" onClick={onClose}>Закрыть без сохранения</button></div>}
  </EosDialog>
}
