import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { EosPagination, EosSearchField, EosSelect } from '../components/EosFormControls'
import { materialRequest, materialPhoto, MaterialApiError, type Material, type MaterialCatalog, type MaterialHistory, type Knowledge, type Specification, type MaterialSupplier } from '../services/rawMaterials'
import { UsagePanel, UsageValue } from '../components/MaterialUsage'
import { PurchasePanel, PurchaseValue } from '../components/MaterialPurchase'
import './ProductKnowledgePage.css'
import './RawMaterialsPage.css'

const PAGE_SIZE = 25
const dateLabel = (value: string) => new Date(value).toLocaleString('ru-RU',{timeZone:'Asia/Yekaterinburg'})
const errorLabel = (error: unknown) => error instanceof MaterialApiError ? error.message : 'Не удалось выполнить действие. Повторите позже'
const supplierLabel = (supplier: MaterialSupplier | null) => supplier ? `${supplier.name}${supplier.available ? '' : ' · недоступен'}` : 'Нет данных'
const labels = {purpose:'Назначение',composition:'Состав',allergens:'Аллергены',characteristics:'Характеристики',receiving_requirements:'Требования к приёмке',storage:'Условия хранения',shelf_life:'Срок годности',manufacturer:'Производитель основного товара',weight_evidence:'Основание веса условной единицы'}
const emptyKnowledge: Knowledge = {purpose:'',composition:'',allergens:'',characteristics:'',receiving_requirements:'',storage:'',shelf_life:'',manufacturer:'',unit_weight_kg:null,weight_evidence:''}

export function RawMaterialPhoto({material, large=false}: {material: Material; large?: boolean}) {
  const [image, setImage] = useState<{key:string;url:string}|null>(null)
  const key = `${material.id}:${material.photo_hash}`
  useEffect(() => {
    if (!material.photo_hash) return
    const controller = new AbortController(); let url: string | null = null
    materialPhoto(material.id,material.photo_hash,controller.signal).then(blob => {
      if (controller.signal.aborted) return
      url = URL.createObjectURL(blob);setImage({key,url})
    }).catch(() => {})
    return () => {controller.abort();if(url)URL.revokeObjectURL(url)}
  }, [material.id,material.photo_hash,key])
  return image?.key === key ? <img className={`material-photo ${large ? 'material-photo-large' : ''}`} src={image.url} alt={material.name} /> : <span className={`material-photo material-photo-empty ${large ? 'material-photo-large' : ''}`} aria-label="Фото отсутствует">Нет фото</span>
}

function SpecificationView({value, title}: {value: Specification | null | undefined; title: string}) {
  return <section className="product-knowledge-section"><h2>{title}</h2>{value ? <>
    <p>Версия {value.revision} · {value.status === 'CONFIRMED' ? 'Подтверждена' : 'Черновик'} · {value.author || 'Сотрудник'} · {dateLabel(value.created_at)}</p>
    {value.confirmed_at && <p>Подтвердил: {value.approver || 'Сотрудник'} · {dateLabel(value.confirmed_at)}</p>}
    <dl>{Object.entries(labels).map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{value.knowledge[key as keyof Knowledge] || 'Нет данных'}</dd></div>)}<dt>Вес условной единицы, кг</dt><dd>{value.knowledge.unit_weight_kg || 'Нет данных'}</dd></dl>
  </> : <p>Нет данных</p>}</section>
}

function MaterialEditor({material,onSaved}: {material:Material;onSaved:()=>void}) {
  const [knowledge,setKnowledge] = useState<Knowledge>({...emptyKnowledge,...material.latest?.knowledge})
  const [reason,setReason] = useState(''), [consulted,setConsulted] = useState(false)
  const [file,setFile] = useState<File|null>(null), [busy,setBusy] = useState(false), [error,setError] = useState('')
  const pending = useRef(false)
  const mutate = async (operation:()=>Promise<unknown>) => {
    if (pending.current) return
    pending.current=true;setBusy(true);setError('')
    try {await operation();onSaved()} catch(e) {setError(errorLabel(e))} finally {pending.current=false;setBusy(false)}
  }
  const command = {expected_version:material.version,reason}
  const disabled = busy || reason.trim().length < 3
  const editable = !material.archived && material.supply_active
  const draftChanged = JSON.stringify(knowledge) !== JSON.stringify({...emptyKnowledge,...material.latest?.knowledge})
  const canConfirm = material.latest?.status === 'DRAFT' && material.allowed_actions.includes('CONFIRM') && editable
  if (!material.allowed_actions.includes('EDIT')) return null
  const submit = (event: FormEvent) => {event.preventDefault();void mutate(() => materialRequest(`/${material.id}/knowledge`,{method:'PATCH',body:JSON.stringify({...command,knowledge})}))}
  return <section className="product-knowledge-section material-editor"><h2>Ведение спецификации</h2>
    <label>Причина изменения<input value={reason} maxLength={1000} onChange={e=>setReason(e.target.value)} required /></label>
    {error && <p role="alert">{error}</p>}
    <form onSubmit={submit}><fieldset disabled={busy || !editable}><legend>Новый черновик</legend><div className="product-knowledge-grid">{Object.entries(labels).map(([key,label]) => <label key={key}>{label}<textarea value={knowledge[key as keyof Knowledge] || ''} maxLength={key==='manufacturer'?240:key==='characteristics'||key==='receiving_requirements'?3000:key==='allergens'||key==='shelf_life'||key==='weight_evidence'?1000:2000} onChange={e=>setKnowledge({...knowledge,[key]:e.target.value})} /></label>)}</div>
    <label>Вес условной единицы, кг<input type="number" min="0.000000001" max="100000" step="0.000000001" value={knowledge.unit_weight_kg || ''} onChange={e=>setKnowledge({...knowledge,unit_weight_kg:e.target.value || null})} /></label>
    <p className="muted-text">Вес — подтверждаемая характеристика. Учётная единица iiko не изменяется.</p>
    <button type="submit" disabled={disabled || !editable}>Сохранить черновик</button></fieldset></form>
    {canConfirm && <div>{draftChanged && <p role="status">Сначала сохраните изменения черновика.</p>}<p>Основной утверждённый товар: {material.name}. Версия {material.latest!.revision}.</p><label><input type="checkbox" checked={consulted} disabled={busy} onChange={e=>setConsulted(e.target.checked)} /> Консультации с кондитерами проведены, эта версия проверена</label><button disabled={disabled || !consulted || draftChanged} onClick={()=>void mutate(()=>materialRequest(`/${material.id}/knowledge/confirm`,{method:'POST',body:JSON.stringify({...command,specification_id:material.latest!.id,content_hash:material.latest!.content_hash,primary_product_id:material.id})}))}>Подтвердить версию {material.latest!.revision}</button></div>}
    <form onSubmit={e=>{e.preventDefault();if (!file || file.size>10*1024*1024) {setError('Выберите JPEG, PNG или WebP до 10 МБ');return}const data=new FormData();data.set('file',file);data.set('reason',reason);data.set('expected_version',String(material.version));void mutate(()=>materialRequest(`/${material.id}/photo`,{method:'PUT',body:data}))}}><fieldset disabled={busy || !editable}><legend>Фотография</legend><label>JPEG, PNG или WebP до 10 МБ<input type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>setFile(e.target.files?.[0] || null)} /></label><button disabled={disabled || !file || !editable}>Загрузить фотографию</button>{material.photo_hash && <button type="button" className="secondary-action" disabled={disabled || !editable} onClick={()=>void mutate(()=>materialRequest(`/${material.id}/photo`,{method:'DELETE',body:JSON.stringify(command)}))}>Убрать фотографию</button>}</fieldset></form>
    <button className="secondary-action" disabled={disabled || (!material.archived && !material.supply_active)} onClick={()=>void mutate(()=>materialRequest(`/${material.id}/archive`,{method:'PATCH',body:JSON.stringify({...command,archived:!material.archived})}))}>{material.archived?'Восстановить карточку':'Архивировать карточку'}</button>
  </section>
}

const operations:Record<string,string>={ENROLLED:'Включение в раздел',DRAFT_SAVED:'Сохранение черновика',CONFIRMED:'Подтверждение версии',PHOTO_UPLOADED:'Загрузка фотографии',PHOTO_REMOVED:'Удаление фотографии из карточки',ARCHIVED:'Архивирование',RESTORED:'Восстановление'}
function History({material}: {material:Material}) {
  const [offset,setOffset]=useState(0),[retry,setRetry]=useState(0)
  const key=JSON.stringify([material.id,material.version,offset,retry])
  const [state,setState]=useState<{key:string;data:MaterialHistory|null;error:string}>({key:'',data:null,error:''})
  useEffect(()=>{const controller=new AbortController();materialRequest<MaterialHistory>(`/${material.id}/history?offset=${offset}&limit=10`,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setState({key,data,error:''})}).catch(e=>{if(!controller.signal.aborted)setState({key,data:null,error:errorLabel(e)})});return()=>controller.abort()},[material.id,offset,key])
  return <section className="product-knowledge-section"><h2>История изменений</h2>{state.key!==key?<p role="status">Загружаем историю…</p>:state.error?<p role="alert">{state.error}<button onClick={()=>setRetry(v=>v+1)}>Повторить</button></p>:state.data&&<>
    {state.data.versions.map(v=><SpecificationView key={v.id} title={`Спецификация · версия ${v.revision}`} value={v}/>)}
    <h3>Действия сотрудников</h3>{state.data.events.map(e=><p key={e.id}>{dateLabel(e.occurred_at)} · {operations[e.operation] || 'Изменение карточки'} · {e.author || 'Сотрудник'} · {e.reason}</p>)}
    {!state.data.event_total && <p>История пока пуста</p>}
    <EosPagination offset={offset} total={Math.max(state.data.total,state.data.event_total)} pageSize={10} itemCount={Math.max(state.data.versions.length,state.data.events.length)} onPageChange={setOffset}/>
  </>}</section>
}

function EnrollMaterial({onSaved}:{onSaved:()=>void}) {
  const [open,setOpen]=useState(false),[q,setQ]=useState(''),[selected,setSelected]=useState(''),[kind,setKind]=useState('RAW_MATERIAL'),[reason,setReason]=useState(''),[confirmed,setConfirmed]=useState(false)
  const [items,setItems]=useState<{id:string;name:string}[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[loading,setLoading]=useState(false)
  const pending=useRef(false)
  useEffect(()=>{if(!open)return;const controller=new AbortController();const timer=setTimeout(()=>{setLoading(true);materialRequest<{items:{id:string;name:string}[]}>(`/candidates?q=${encodeURIComponent(q)}`,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted){setItems(data.items);setLoading(false)}}).catch(e=>{if(!controller.signal.aborted){setError(errorLabel(e));setLoading(false)}})},200);return()=>{clearTimeout(timer);controller.abort()}},[open,q])
  return <section className="product-knowledge-section"><button className="secondary-action" onClick={()=>setOpen(!open)}>{open?'Закрыть выбор':'Включить существующий товар Supply'}</button>{open&&<form onSubmit={async e=>{e.preventDefault();if(pending.current)return;pending.current=true;setBusy(true);setError('');try{await materialRequest('',{method:'POST',body:JSON.stringify({product_id:selected,kind,reason})});onSaved()}catch(e){setError(errorLabel(e))}finally{pending.current=false;setBusy(false)}}}>
    <p>Включайте только согласованные владельцем UUID. Предложение пилота само по себе не является согласованием.</p>
    <EosSearchField label="Поиск товара Supply" value={q} onChange={e=>{setQ(e.target.value);setSelected('')}}/>
    {loading?<p role="status">Ищем товары…</p>:<label>Существующий товар<EosSelect value={selected} onChange={e=>setSelected(e.target.value)} required><option value="">Выберите товар</option>{items.map(p=><option value={p.id} key={p.id}>{p.name} · {p.id}</option>)}</EosSelect></label>}
    <label>Вид<EosSelect value={kind} onChange={e=>setKind(e.target.value)}><option value="RAW_MATERIAL">Сырьё</option><option value="PACKAGING">Упаковка</option></EosSelect></label>
    <label>Основание включения<input required minLength={3} maxLength={1000} value={reason} onChange={e=>setReason(e.target.value)}/></label>
    <label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/> Состав согласован владельцем</label>
    {error&&<p role="alert">{error}</p>}<button disabled={busy||loading||!selected||reason.trim().length<3||!confirmed}>Включить в раздел</button>
  </form>}</section>
}

export default function RawMaterialsPage() {
  const {productId}=useParams(),[params,setParams]=useSearchParams(),[retry,setRetry]=useState(0)
  const rawPage=Number(params.get('page')||1), page=Number.isSafeInteger(rawPage)&&rawPage>0&&rawPage<1000000?rawPage:1,offset=(page-1)*PAGE_SIZE
  const key=JSON.stringify([productId,params.toString(),retry])
  const [state,setState]=useState<{key:string;catalog:MaterialCatalog|null;material:Material|null;error:string}>({key:'',catalog:null,material:null,error:''})
  const query=params.toString()
  useEffect(()=>{const controller=new AbortController();const request=new URLSearchParams(query);request.delete('page');request.set('offset',String(offset));request.set('limit',String(PAGE_SIZE));const timer=setTimeout(()=>{
    (productId?materialRequest<Material>(`/${productId}`,{signal:controller.signal}).then(material=>({material,catalog:null})):materialRequest<MaterialCatalog>(`?${request}`,{signal:controller.signal}).then(catalog=>({catalog,material:null}))).then(data=>{if(!controller.signal.aborted)setState({key,...data,error:''})}).catch(e=>{if(!controller.signal.aborted)setState({key,catalog:null,material:null,error:errorLabel(e)})})
  },200);return()=>{clearTimeout(timer);controller.abort()}},[productId,query,offset,key])
  const update=(name:string,value:string)=>{const next=new URLSearchParams(params);if(value)next.set(name,value);else next.delete(name);if(name!=='page')next.delete('page');setParams(next,{replace:true})}
  const loading=key!==state.key,material=state.material,catalog=state.catalog,qs=query?`?${query}`:'',reload=()=>setRetry(v=>v+1)
  return <div className="page-shell"><section className="page-panel product-page material-page"><div className="page-title-row"><div><p className="eyebrow">БАЗА ЗНАНИЙ</p><h1>{productId&&!loading?material?.name||'Карточка сырья':'Сырьё'}</h1><p className="muted-text">Технологические сведения, спецификации и поставщики</p></div></div>
    {productId&&<Link className="product-back" to={`/raw-materials${qs}`}>← К списку сырья</Link>}
    {!productId&&<div className="product-filters"><EosSearchField label="Поиск" placeholder="Название, алиас или UUID" value={params.get('q')||''} onChange={e=>update('q',e.target.value)}/><label>Вид<EosSelect value={params.get('kind')||''} onChange={e=>update('kind',e.target.value)}><option value="">Все виды</option><option value="RAW_MATERIAL">Сырьё</option><option value="PACKAGING">Упаковка</option></EosSelect></label><label>Категория<EosSelect value={params.get('category_id')||''} onChange={e=>update('category_id',e.target.value)}><option value="">Все категории</option>{catalog?.categories.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</EosSelect></label><label>Спецификация<EosSelect value={params.get('state')||''} onChange={e=>update('state',e.target.value)}><option value="">Все состояния</option><option value="CONFIRMED">Есть подтверждённая версия</option><option value="UNCONFIRMED">Нет подтверждённой версии</option></EosSelect></label><label>Поставщик<EosSelect value={params.get('supplier_id')||''} onChange={e=>update('supplier_id',e.target.value)}><option value="">Все поставщики</option>{catalog?.suppliers.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</EosSelect></label><label><input type="checkbox" checked={params.get('without_supplier')==='true'} onChange={e=>update('without_supplier',e.target.checked?'true':'')}/> Без поставщика</label><label><input type="checkbox" checked={params.get('archived')==='true'} onChange={e=>update('archived',e.target.checked?'true':'')}/> Архив карточек</label><button className="secondary-action" onClick={()=>setParams({})}>Сбросить фильтры</button></div>}
    {loading?<p className="product-state" role="status">Загружаем сырьё…</p>:state.error?<div role="alert"><p>{state.error}</p><button onClick={reload}>Повторить</button></div>:material?<>
      <div className="product-card-overview"><RawMaterialPhoto material={material} large/><div><p>{material.kind==='PACKAGING'?'Упаковка':'Сырьё'} · {material.archived?'В архиве':'Активная карточка'}</p><p>Учётная единица iiko: {material.unit||'Не подтверждена'}</p><p>Вес условной единицы: {material.unit_weight_kg?`${material.unit_weight_kg} кг`:'Нет данных'}</p><small>SupplyProduct: {material.id}</small>{!material.supply_active&&<p role="status">Товар Supply архивирован</p>}</div></div>
      <div className="product-knowledge-grid"><section className="product-knowledge-section"><h2>Закупочные показатели</h2>{material.purchase_access?<><PurchasePanel material={material} onUpdated={reload}/><small>Цены с НДС · документные факты iiko</small></>:<p>Нет доступа к закупочным ценам</p>}<p>Расход за прошлый месяц: <UsageValue metric={material.monthly_consumption}/></p><UsagePanel key={`${material.id}:${retry}`} id={material.id}/></section><section className="product-knowledge-section"><h2>Товары и поставщики</h2><p>Основной утверждённый товар: {material.current?material.name:'Ещё не утверждён'}</p><p>Резервные товары: Ещё не утверждены</p><p>Основной поставщик: {supplierLabel(material.primary_supplier)}</p><p>Резервный поставщик: {material.backup_ambiguous?'Несколько кандидатов':supplierLabel(material.backup_supplier)}</p>{material.suppliers.filter(s=>s.role==='BACKUP').map(s=><p key={s.id}>Резерв: {supplierLabel(s)}</p>)}<small>Назначения поставщиков из Supply. Товарный резерв утверждается отдельно.</small></section></div>
      <SpecificationView value={material.current} title="Подтверждённая спецификация"/>
      {material.latest?.status==='DRAFT'&&<SpecificationView value={material.latest} title="Неподтверждённый черновик"/>}
      <MaterialEditor key={`${material.id}:${material.version}`} material={material} onSaved={reload}/><History material={material}/>
    </>:catalog?<>
      {catalog.can_enroll&&<EnrollMaterial key={retry} onSaved={reload}/>}
      <p className="product-scroll-hint">Прокрутите таблицу вправо, чтобы увидеть все колонки.</p>
      <div className="product-table-wrap" role="region" aria-label="Реестр сырья" tabIndex={0}><table className="product-table"><caption className="product-sr-only">Сырьё и упаковка</caption><thead><tr>{['Фото','Название','Вес условной единицы','Основной поставщик','Резервный поставщик','Последняя цена прихода','Средневзвешенная цена за 6 месяцев','Расход за прошлый месяц'].map(c=><th scope="col" key={c}>{c}</th>)}</tr></thead><tbody>{catalog.items.map(p=><tr key={p.id}><td><Link to={`/raw-materials/${p.id}${qs}`} aria-label={`Карточка ${p.name}`}><RawMaterialPhoto material={p}/></Link></td><td><Link to={`/raw-materials/${p.id}${qs}`}>{p.name}</Link><small>{p.unit||'Единица не подтверждена'} · {p.kind==='PACKAGING'?'Упаковка':'Сырьё'}{!p.supply_active?' · Товар Supply архивирован':''}</small></td><td>{p.unit_weight_kg?`${p.unit_weight_kg} кг`:'Нет данных'}</td><td>{supplierLabel(p.primary_supplier)}</td><td>{p.backup_ambiguous?'Несколько кандидатов':supplierLabel(p.backup_supplier)}</td><td>{catalog.purchase_access?<PurchaseValue metric={p.last_purchase_price}/>: 'Нет доступа'}</td><td>{catalog.purchase_access?<PurchaseValue metric={p.six_month_average}/>:'Нет доступа'}</td><td><UsageValue metric={p.monthly_consumption}/></td></tr>)}</tbody></table></div>
      {!catalog.items.length&&<div className="product-state" role="status"><h2>Ничего не найдено</h2><p>Измените фильтры. Новые карточки включаются явно после согласования состава.</p></div>}
      <EosPagination offset={offset} total={catalog.total} pageSize={PAGE_SIZE} itemCount={catalog.items.length} onPageChange={next=>update('page',String(next/PAGE_SIZE+1))}/>
    </>:null}
  </section></div>
}
