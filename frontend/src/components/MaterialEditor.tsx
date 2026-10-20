import { useRef, useState, type FormEvent } from 'react'
import { KnowledgePhotoPicker } from './KnowledgeUI'
import { MaterialDialog } from './MaterialDialog'
import { EosCheckbox } from './EosFormControls'
import { knowledgeLabels } from './materialPresentation'
import { StandardsEditor } from './MaterialStandards'
import { materialRequest, MaterialApiError, type Material, type Knowledge } from '../services/rawMaterials'


const emptyKnowledge:Knowledge={purpose:'',composition:'',allergens:'',characteristics:'',receiving_requirements:'',storage:'',shelf_life:'',manufacturer:'',unit_weight_kg:null,weight_evidence:''}
const errorLabel=(e:unknown)=>e instanceof MaterialApiError?e.message:'Не удалось сохранить изменения. Повторите позже'

type Props={material:Material;onSaved:(reason?:string)=>void;onClose:()=>void;initialReason?:string}
export function MaterialEditor({material,onSaved,onClose,initialReason=''}:Props) {
  const initial={...emptyKnowledge,...material.latest?.knowledge}
  const [knowledge,setKnowledge]=useState<Knowledge>(initial)
  const [reason,setReason]=useState(initialReason),[consulted,setConsulted]=useState(false),[override,setOverride]=useState(false)
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  const pending=useRef(false)
  const draftChanged=JSON.stringify(knowledge)!==JSON.stringify(initial)
  const editable=!material.archived&&material.supply_active
  const hasDraft=material.latest?.status==='DRAFT'
  const canConfirm=hasDraft&&material.allowed_actions.includes('CONFIRM')&&editable
  const validReason=reason.trim().length>=3
  const disabledWhy=!editable?'Сначала восстановите карточку и товар Supply.':!validReason?'Укажите причину изменения: не менее 3 символов.':''
  const confirmWhy=disabledWhy||(!hasDraft?'Сначала сохраните черновик.':!material.allowed_actions.includes('CONFIRM')?'Нет права подтверждать спецификации.':draftChanged?'Сначала сохраните изменения черновика.':knowledge.approved_products?.length&&!knowledge.approved_products.some(p=>p.role==='PRIMARY')?'Выберите основной товар и сохраните черновик.':!consulted?'Подтвердите проверку версии и консультации с кондитерами.':'')
  async function mutate(operation:()=>Promise<unknown>) {
    if(pending.current)return
    pending.current=true;setBusy(true);setError('')
    try{await operation();onSaved(reason)}catch(e){setError(errorLabel(e))}finally{pending.current=false;setBusy(false)}
  }
  const command={expected_version:material.version,reason}
  function submit(e:FormEvent){e.preventDefault();if(disabledWhy)return;void mutate(()=>materialRequest(`/${material.id}/knowledge`,{method:'PATCH',body:JSON.stringify({...command,knowledge})}))}
  return <MaterialDialog title="Изменить спецификацию" dirty={draftChanged||reason!==initialReason||consulted||override} busy={busy} onClose={onClose}>
    <p>{material.current?`Действующая подтверждённая версия: ${material.current.revision}.`:'Подтверждённой спецификации пока нет.'} {hasDraft?`Сохранённый черновик: версия ${material.latest!.revision}.`:`Сохранение создаст новый черновик версии ${(material.latest?.revision||0)+1}.`}</p>
    <p>При сохранении создаётся новая черновая версия {(material.latest?.revision||0)+1}.</p><p>1. Заполните сведения → 2. Сохраните черновик → 3. Проверьте сохранённую версию и подтвердите. История предыдущих версий сохраняется.</p>
    <form onSubmit={submit} className="material-editor"><fieldset disabled={busy||!editable}>
      <legend>1. Технологические сведения</legend><p className="muted-text">* — обязательные поля. Неизвестные характеристики можно оставить пустыми. Если указан вес, требуется документальное основание.</p>
      <label>Причина изменения *<input required minLength={3} maxLength={1000} placeholder="Например: уточнены условия хранения по этикетке" value={reason} onChange={e=>setReason(e.target.value)}/></label>
      <div className="product-knowledge-grid">{Object.entries(knowledgeLabels).map(([key,label])=><label key={key}>{label}{key==='weight_evidence'&&knowledge.unit_weight_kg?' *':''}<textarea required={key==='weight_evidence'&&Boolean(knowledge.unit_weight_kg)} minLength={key==='weight_evidence'&&knowledge.unit_weight_kg?3:undefined} value={knowledge[key as keyof typeof knowledgeLabels]||''} maxLength={key==='manufacturer'?240:key==='characteristics'||key==='receiving_requirements'?3000:key==='allergens'||key==='shelf_life'||key==='weight_evidence'?1000:2000} onChange={e=>setKnowledge({...knowledge,[key]:e.target.value})}/></label>)}</div>
      <label>Вес условной единицы, кг<input type="number" min="0.000000001" max="100000" step="0.000000001" value={knowledge.unit_weight_kg||''} onChange={e=>setKnowledge({...knowledge,unit_weight_kg:e.target.value||null})}/></label>
      <p>Вес — подтверждаемая характеристика. Учётная единица iiko не изменяется. Этот вес не заменяет подтверждённый коэффициент пересчёта.</p>
      <StandardsEditor material={material} knowledge={knowledge} onChange={setKnowledge}/>
      {disabledWhy&&<p id="material-save-hint" role="status">{disabledWhy}</p>}
      <div className="product-actions"><button className="primary-action" disabled={busy||Boolean(disabledWhy)} aria-describedby="material-save-hint">{busy?'Сохраняем…':'Сохранить черновик'}</button></div>
    </fieldset></form>
    <section className="material-confirm"><h3>5. Подтверждение сохранённой версии</h3>
      {hasDraft&&<p>Подтверждается сохранённая версия {material.latest!.revision}. Несохранённые изменения подтвердить нельзя.</p>}
      <EosCheckbox label="Консультации с кондитерами проведены, эта версия проверена" checked={consulted} disabled={busy||!canConfirm} onChange={e=>setConsulted(e.target.checked)}/>
      <EosCheckbox label="Владелец отдельно изменил стандарт производителя (подтверждает администратор)" checked={override} disabled={busy||!canConfirm} onChange={e=>setOverride(e.target.checked)}/>
      <p>Действующий стандарт: сливки — БМК, мука — Ларица. Изменение этого стандарта требует решения владельца и подтверждения администратором.</p>
      {confirmWhy&&<p id="material-confirm-hint" role="status">{confirmWhy}</p>}
      <button className="primary-action" disabled={busy||Boolean(confirmWhy)} aria-describedby="material-confirm-hint" onClick={()=>void mutate(()=>materialRequest(`/${material.id}/knowledge/confirm`,{method:'POST',body:JSON.stringify({...command,specification_id:material.latest!.id,content_hash:material.latest!.content_hash,primary_product_id:material.latest!.knowledge.approved_products?.find(p=>p.role==='PRIMARY')?.product_id||material.id,owner_standard_override:override})}))}>{hasDraft?`Подтвердить версию ${material.latest!.revision}`:'Подтвердить версию'}</button>
    </section>
    {error&&<p role="alert">{error}</p>}
  </MaterialDialog>
}

export function MaterialPhotoEditor({material,onSaved,onClose}:Props) {
  const [file,setFile]=useState<File|null>(null),[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const pending=useRef(false)
  async function mutate(remove=false){
    if(pending.current||reason.trim().length<3)return
    if(!remove&&(!file||file.size>10*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type))){setError('Выберите JPEG, PNG или WebP до 10 МБ');return}
    pending.current=true;setBusy(true);setError('')
    try{
      if(remove)await materialRequest(`/${material.id}/photo`,{method:'DELETE',body:JSON.stringify({expected_version:material.version,reason})})
      else {const data=new FormData();data.set('file',file!);data.set('reason',reason);data.set('expected_version',String(material.version));await materialRequest(`/${material.id}/photo`,{method:'PUT',body:data})}
      onSaved();onClose()
    }catch(e){setError(errorLabel(e))}finally{pending.current=false;setBusy(false)}
  }
  return <MaterialDialog title="Фотография сырья" dirty={Boolean(file||reason)} busy={busy} onClose={onClose}><form className="material-editor" onSubmit={e=>{e.preventDefault();void mutate()}}><fieldset disabled={busy}>
    <legend>JPEG, PNG или WebP до 10 МБ</legend><KnowledgePhotoPicker file={file} disabled={busy} onChange={setFile}/>
    <label>Причина изменения *<input required minLength={3} maxLength={1000} value={reason} onChange={e=>setReason(e.target.value)} placeholder="Например: фото упаковки с актуальной маркировкой"/></label>
    {reason.trim().length<3&&<p role="status">Укажите причину изменения: не менее 3 символов.</p>}{!file&&<p>Выберите файл для загрузки.</p>}
    {error&&<p role="alert">{error}</p>}<div className="product-actions"><button className="primary-action" disabled={busy||!file||reason.trim().length<3}>{busy?'Загружаем…':'Загрузить фотографию'}</button>{material.photo_hash&&<button className="danger-action" type="button" disabled={busy||reason.trim().length<3} onClick={()=>void mutate(true)}>Убрать фотографию</button>}</div>
  </fieldset></form></MaterialDialog>
}

export function MaterialArchiveEditor({material,onSaved,onClose}:Props) {
  const [reason,setReason]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const pending=useRef(false)
  return <MaterialDialog title={material.archived?'Восстановить карточку':'Архивировать карточку'} dirty={Boolean(reason)} busy={busy} onClose={onClose}><form className="material-editor" onSubmit={async e=>{e.preventDefault();if(pending.current)return;pending.current=true;setBusy(true);try{await materialRequest(`/${material.id}/archive`,{method:'PATCH',body:JSON.stringify({expected_version:material.version,reason,archived:!material.archived})});onSaved();onClose()}catch(e){setError(errorLabel(e))}finally{pending.current=false;setBusy(false)}}}>
    <label>Причина *<input disabled={busy} required minLength={3} maxLength={1000} value={reason} onChange={e=>setReason(e.target.value)}/></label>{error&&<p role="alert">{error}</p>}<button className="primary-action" disabled={busy||reason.trim().length<3}>{busy?'Сохраняем…':'Сохранить'}</button>
  </form></MaterialDialog>
}
