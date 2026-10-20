import { useEffect, useState } from 'react'
import { materialRequest, type AdmissionHistory, type DocumentAdmission, type Material, type PurchaseDocument, type PurchaseLine, type PurchaseSources } from '../services/rawMaterials'

type Target = {doc:PurchaseDocument;line?:PurchaseLine;kind:DocumentAdmission['kind'];prior?:DocumentAdmission}
export function MaterialDocumentAdmissions({material,sources,onUpdated}:{material:Material;sources:PurchaseSources;onUpdated:()=>void}) {
  const [history,setHistory]=useState<AdmissionHistory|null>(null),[target,setTarget]=useState<Target|null>(null)
  const [evidence,setEvidence]=useState(''),[comment,setComment]=useState(''),[checked,setChecked]=useState(false),[quantity,setQuantity]=useState('')
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[request,setRequest]=useState<{key:string;id:string}|null>(null),[offset,setOffset]=useState(0),[revision,setRevision]=useState(0)
  const canWrite=material.allowed_actions.includes('DOCUMENT_ADMIT')
  useEffect(()=>{
    const abort=new AbortController()
    materialRequest<AdmissionHistory>(`/${material.id}/document-admissions?offset=${offset}`,{signal:abort.signal}).then(data=>{if(!abort.signal.aborted)setHistory(data)}).catch(()=>{if(!abort.signal.aborted)setError('Не удалось прочитать историю допусков')})
    return()=>abort.abort()
  },[material.id,offset,revision])
  const prior=(doc:PurchaseDocument,kind:DocumentAdmission['kind'],line?:PurchaseLine)=>history?.current_items.find(d=>d.document_id===doc.document_id&&d.document_hash===doc.source_hash&&d.kind===kind&&d.line_num===(line?.num||''))
  function choose(doc:PurchaseDocument,kind:DocumentAdmission['kind'],line?:PurchaseLine) {
    setTarget({doc,kind,line,prior:prior(doc,kind,line)});setEvidence('');setComment('');setQuantity('');setChecked(false);setError('');setRequest(null)
  }
  async function submit(event:React.FormEvent) {
    event.preventDefault();if(!target||!history||busy)return
    const revoke=target.prior?.action==='GRANT'
    const body={expected_version:history.version,expected_revision:target.prior?.revision||0,kind:target.kind,action:revoke?'REVOKE':'GRANT',document_id:target.doc.document_id,document_hash:target.doc.source_hash,line_num:target.line?.num||'',evidence,comment,primary_checked:checked,...(!revoke&&target.kind==='BASE_UNIT_CONTAINER'?{verified_unit_id:material.unit_id,verified_quantity:quantity.replace(',','.')}:{})}
    const key=JSON.stringify(body),id=request?.key===key?request.id:crypto.randomUUID();setRequest({key,id});setBusy(true);setError('')
    try {
      await materialRequest(`/${material.id}/metrics/${sources.metric.id}/admissions`,{method:'POST',body:JSON.stringify({...body,request_id:id})})
      setTarget(null);setRequest(null);setRevision(v=>v+1);onUpdated()
    } catch {setError('Решение не сохранено или ответ не получен. Проверьте основание и версию карточки; повторный запрос безопасен. При конфликте откройте расшифровку заново')}
    finally {setBusy(false)}
  }
  function button(doc:PurchaseDocument,kind:DocumentAdmission['kind'],line?:PurchaseLine) {
    const decision=prior(doc,kind,line)
    return <button type="button" disabled={busy||!history} onClick={()=>choose(doc,kind,line)}>{decision?.action==='GRANT'?'Отозвать допуск':kind==='EMPLOYEE_PURCHASE'?'Проверить внешнюю закупку':'Верифицировать количество в учётной единице'}{line?` · строка ${line.num}`:' · строки этого сырья в документе'}</button>
  }
  return <details><summary>Документные допуски и проверка упаковки</summary>
    <p>Допуск относится только к этому сырью и выбранной версии накладной или строке. Первичные документы iiko и складской учёт не изменяются. После решения запустите новый расчёт показателей.</p>
    {sources.documents?.map(doc=><div key={`${doc.document_id}:${doc.source_hash}`}><h4>Накладная №{doc.number} · {doc.receipt_at?.slice(0,10)||'Дата не подтверждена'}</h4>
      {doc.supplier_flags?.is_employee&&<p>Контрагент отмечен в iiko как сотрудник. Нужна проверка внешней закупки по первичке.</p>}
      {canWrite&&doc.supplier_flags?.is_employee&&button(doc,'EMPLOYEE_PURCHASE')}
      {doc.lines.map(line=>{const raw=line.original_line||line;return <div key={line.num}><p>Строка {line.num}: {raw.actualAmount} {raw.unit_name||(raw.amountUnit===material.unit_id?material.unit:raw.amountUnit)}; сумма с НДС {raw.sum}. {raw.containerId&&`Контейнер: ${raw.containerId}`}</p>
        {canWrite&&doc.supplier_flags?.is_employee&&button(doc,'EMPLOYEE_PURCHASE',line)}
        {canWrite&&raw.containerId&&raw.containerId!=='00000000-0000-0000-0000-000000000000'&&raw.amountUnit===material.unit_id&&button(doc,'BASE_UNIT_CONTAINER',line)}</div>})}
    </div>)}
    {target&&canWrite&&<form onSubmit={event=>void submit(event)} aria-label="Решение по документу"><h4>{target.prior?.action==='GRANT'?'Отзыв допуска':'Подтверждение по первичным документам'} · №{target.doc.number}{target.line?` · строка ${target.line.num}`:' · все строки этого сырья'}</h4>
      <label>Основание (номер или ссылка на первичку)<input required minLength={3} maxLength={2000} value={evidence} disabled={busy} onChange={e=>setEvidence(e.target.value)}/></label>
      <label>Комментарий проверки<textarea required minLength={3} maxLength={2000} value={comment} disabled={busy} onChange={e=>setComment(e.target.value)}/></label>
      {target.prior?.action!=='GRANT'&&<><label><input type="checkbox" required checked={checked} disabled={busy} onChange={e=>setChecked(e.target.checked)}/>Первичка проверена; это внешняя закупка, а указанное количество и единица подтверждены</label>
        {target.kind==='BASE_UNIT_CONTAINER'&&<><p>Подтвердите по первичке, что количество уже выражено в {material.unit}; контейнер описывает упаковку и не требует числового пересчёта. Предполагаемая масса недопустима.</p><label>Проверенное количество в {material.unit}<input required inputMode="decimal" value={quantity} disabled={busy} onChange={e=>setQuantity(e.target.value)}/></label></>}</>}
      <button disabled={busy}>{busy?'Сохраняем…':'Сохранить решение'}</button><button type="button" disabled={busy} onClick={()=>setTarget(null)}>Отмена</button>
    </form>}
    {error&&<p role="alert">{error}</p>}
    <h4>Неизменяемая история решений</h4>{history?.items.map(item=><p key={item.id}>№{sources.documents?.find(d=>d.document_id===item.document_id)?.number||item.document_id}{item.line_num?` · строка ${item.line_num}`:' · строки этого сырья'}: {item.kind==='EMPLOYEE_PURCHASE'?'Внешняя закупка':'Учётная единица и контейнер'} — {item.action==='GRANT'?'подтверждено':'отозвано'} · {item.author} · {new Date(item.created_at).toLocaleString('ru-RU')} · Основание: {item.evidence} · {item.comment}{item.current?' · текущее решение':''}</p>)}
    {!history?.items.length&&<p>Решений пока нет</p>}{offset>0&&<button onClick={()=>setOffset(v=>Math.max(0,v-25))}>Предыдущие решения</button>}{history?.items.length===25&&<button onClick={()=>setOffset(v=>v+25)}>Следующие решения</button>}
  </details>
}
