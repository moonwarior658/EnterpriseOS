import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { EosPagination, EosSearchField, EosSelect } from '../components/EosFormControls'
import { materialRequest, materialPhoto, MaterialApiError, type Material, type MaterialCatalog, type MaterialHistory, type Specification, type MaterialSupplier } from '../services/rawMaterials'
import { StandardsView, ReserveSelection } from '../components/MaterialStandards'
import { UsageValue } from '../components/MaterialUsage'
import { PurchasePanel, PurchaseValue } from '../components/MaterialPurchase'
import { MaterialDialog } from '../components/MaterialDialog'
import { MaterialEditor, MaterialPhotoEditor, MaterialArchiveEditor } from '../components/MaterialEditor'
import { EosCheckbox } from '../components/EosFormControls'
import { materialNumber, knowledgeLabels as labels } from '../components/materialPresentation'
import './ProductKnowledgePage.css'
import './RawMaterialsPage.css'

const PAGE_SIZE = 25
const dateLabel = (value: string) => new Date(value).toLocaleString('ru-RU',{timeZone:'Asia/Yekaterinburg'})
const errorLabel = (error: unknown) => error instanceof MaterialApiError ? error.message : 'Не удалось выполнить действие. Повторите позже'
const supplierLabel = (supplier: MaterialSupplier | null) => supplier ? `${supplier.name}${supplier.available ? '' : ' · недоступен'}` : 'Нет данных'
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
    <dl>{Object.entries(labels).map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{value.knowledge[key as keyof typeof labels] || 'Нет данных'}</dd></div>)}<dt>Вес условной единицы, кг</dt><dd>{materialNumber(value.knowledge.unit_weight_kg)}</dd></dl><StandardsView knowledge={value.knowledge}/>
  </> : <p>Нет данных</p>}</section>
}

const operations:Record<string,string>={RESERVE_SELECTED:'Выбор утверждённого резерва',ENROLLED:'Включение в раздел',DRAFT_SAVED:'Сохранение черновика',CONFIRMED:'Подтверждение версии',PHOTO_UPLOADED:'Загрузка фотографии',PHOTO_REMOVED:'Удаление фотографии из карточки',ARCHIVED:'Архивирование',RESTORED:'Восстановление'}
function History({material}: {material:Material}) {
  const [offset,setOffset]=useState(0),[retry,setRetry]=useState(0)
  const key=JSON.stringify([material.id,material.version,offset,retry])
  const [state,setState]=useState<{key:string;data:MaterialHistory|null;error:string}>({key:'',data:null,error:''})
  useEffect(()=>{const controller=new AbortController();materialRequest<MaterialHistory>(`/${material.id}/history?offset=${offset}&limit=10`,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setState({key,data,error:''})}).catch(e=>{if(!controller.signal.aborted)setState({key,data:null,error:errorLabel(e)})});return()=>controller.abort()},[material.id,offset,key])
  return <section className="product-knowledge-section"><h2>История изменений</h2>{state.key!==key?<p role="status">Загружаем историю…</p>:state.error?<p role="alert">{state.error}<button className="secondary-action" onClick={()=>setRetry(v=>v+1)}>Повторить</button></p>:state.data&&<>
    {state.data.versions.map(v=><SpecificationView key={v.id} title={`Спецификация · версия ${v.revision}`} value={v}/>)}
    <h3>Действия сотрудников</h3>{state.data.events.map(e=><p key={e.id}>{dateLabel(e.occurred_at)} · {operations[e.operation] || 'Изменение карточки'} · {e.author || 'Сотрудник'} · {e.reason}{typeof e.after.revision==='number'&&<span> · Версия {e.after.revision}</span>}{typeof e.after.archived==='boolean'&&<span> · {e.after.archived?'Карточка в архиве':'Карточка активна'}</span>}</p>)}
    {!state.data.event_total && <p>История пока пуста</p>}
    <EosPagination offset={offset} total={Math.max(state.data.total,state.data.event_total)} pageSize={10} itemCount={Math.max(state.data.versions.length,state.data.events.length)} onPageChange={setOffset}/>
  </>}</section>
}

function EnrollMaterial({onSaved}:{onSaved:()=>void}) {
  const [open,setOpen]=useState(false),[q,setQ]=useState(''),[selected,setSelected]=useState(''),[kind,setKind]=useState('RAW_MATERIAL'),[reason,setReason]=useState(''),[confirmed,setConfirmed]=useState(false)
  const [items,setItems]=useState<{id:string;name:string}[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[loading,setLoading]=useState(false)
  const pending=useRef(false)
  useEffect(()=>{if(!open)return;const controller=new AbortController();const timer=setTimeout(()=>{setLoading(true);materialRequest<{items:{id:string;name:string}[]}>(`/candidates?q=${encodeURIComponent(q)}`,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted){setItems(data.items);setLoading(false);setError('')}}).catch(e=>{if(!controller.signal.aborted){setError(errorLabel(e));setLoading(false)}})},200);return()=>{clearTimeout(timer);controller.abort()}},[open,q])
  const close=()=>{setOpen(false);setQ('');setSelected('');setKind('RAW_MATERIAL');setReason('');setConfirmed(false);setError('')}
  return <div className="product-actions"><button className="secondary-action" onClick={()=>setOpen(true)}>Включить существующий товар Supply</button>{open&&<MaterialDialog title="Включить товар Supply" onClose={close} dirty={Boolean(selected||reason||confirmed||kind!=='RAW_MATERIAL')} busy={busy}>
    <form className="material-editor" onSubmit={async e=>{e.preventDefault();if(pending.current||!confirmed||!selected||reason.trim().length<3)return;pending.current=true;setBusy(true);setError('');try{await materialRequest('',{method:'POST',body:JSON.stringify({product_id:selected,kind,reason})});close();onSaved()}catch(e){setError(errorLabel(e))}finally{pending.current=false;setBusy(false)}}}><fieldset disabled={busy}>
      <legend>Существующая номенклатура</legend><p>Выберите существующий товар, согласованный владельцем. Новая номенклатура не создаётся.</p>
      <EosSearchField label="Поиск товара Supply" value={q} onChange={e=>{setQ(e.target.value);setSelected('');setLoading(true)}}/>
      {loading&&<p role="status">Ищем товары…</p>}<label>Существующий товар *<EosSelect disabled={loading} value={selected} onChange={e=>setSelected(e.target.value)} required><option value="">Выберите товар</option>{items.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</EosSelect></label>
      {!loading&&!items.length&&<p>Товары не найдены. Измените поиск.</p>}
      <label>Вид<EosSelect value={kind} onChange={e=>setKind(e.target.value)}><option value="RAW_MATERIAL">Сырьё</option><option value="PACKAGING">Упаковка</option></EosSelect></label>
      <label>Основание включения *<input required minLength={3} maxLength={1000} placeholder="Например: согласовано владельцем для реестра сырья" value={reason} onChange={e=>setReason(e.target.value)}/></label>
      <EosCheckbox label="Состав согласован владельцем" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
      {error&&<p role="alert">{error}</p>}<button className="primary-action" disabled={busy||loading||!selected||reason.trim().length<3||!confirmed}>{busy?'Включаем…':'Включить в раздел'}</button>
      {(!selected||reason.trim().length<3||!confirmed)&&<p role="status">Для включения выберите товар, укажите основание и подтвердите согласование владельца.</p>}
    </fieldset></form>
  </MaterialDialog>}</div>
}

function MaterialCard({material,onSaved}:{material:Material;onSaved:()=>void}) {
  const [modal,setModal]=useState<'specification'|'photo'|'history'|'reserve'|'archive'|null>(null),[notice,setNotice]=useState('')
  const [savedReason,setSavedReason]=useState('')
  const [reserveDirty,setReserveDirty]=useState(false),[reserveBusy,setReserveBusy]=useState(false)
  const editable=!material.archived&&material.supply_active
  const close=()=>setModal(null)
  const saved=(reason?:string)=>{if(reason!==undefined)setSavedReason(reason);setNotice('Изменения сохранены. Данные карточки обновлены.');onSaved()}
  const backups=material.suppliers.filter(s=>s.role==='BACKUP')
  return <>
    <div className="material-card-actions product-actions">
      {material.allowed_actions.includes('EDIT')&&<button className="primary-action" disabled={!editable} onClick={()=>{setNotice('');setSavedReason('');setModal('specification')}}>Изменить спецификацию</button>}
      {material.allowed_actions.includes('PHOTO')&&<button className="secondary-action" disabled={!editable} onClick={()=>setModal('photo')}>Изменить фотографию</button>}
      <button className="secondary-action" onClick={()=>setModal('history')}>История изменений</button>
      {material.allowed_actions.includes('ARCHIVE')&&<button className="secondary-action" onClick={()=>setModal('archive')}>{material.archived?'Восстановить карточку':'Архивировать карточку'}</button>}
    </div>
    {notice&&<p role="status" className="material-notice">{notice}</p>}
    {!editable&&<p className="material-notice">{material.archived?'Карточка в архиве. Восстановите её для редактирования.':'Товар Supply архивирован. Сначала восстановите его в Supply.'}</p>}
    <section className="product-card-overview material-overview"><RawMaterialPhoto material={material} large/><div className="product-knowledge-section"><h2>О сырье</h2><dl className="material-info-grid">
      <div><dt>Тип</dt><dd>{material.kind==='PACKAGING'?'Упаковка':'Сырьё'}</dd></div>
      <div><dt>Статус карточки</dt><dd><span className={`material-status ${material.archived?'material-status-empty':'material-status-ready'}`}>{material.archived?'В архиве':'Активна'}</span></dd></div>
      <div><dt>Учётная единица iiko</dt><dd>{material.unit||'Не подтверждена'}</dd></div>
      <div><dt>Вес условной единицы</dt><dd>{material.unit_weight_kg?`${materialNumber(material.unit_weight_kg)} кг`:'Нет данных'}</dd></div>
      <div><dt>Действующий стандарт</dt><dd>{material.current?`Подтверждён · версия ${material.current.revision}`:'Ещё не утверждён'}</dd></div>
      <div><dt>Черновик</dt><dd>{material.latest?.status==='DRAFT'?`Версия ${material.latest.revision} · ожидает подтверждения`:'Нет черновика'}</dd></div>
    </dl></div></section>
    <PurchasePanel material={material} onUpdated={onSaved}/>
    <section className="product-knowledge-section material-suppliers"><h2>Товары и поставщики</h2><div className="product-knowledge-grid">
      <article><h3>Основной утверждённый товар</h3><p>{material.current?(material.approved_products?.find(p=>p.role==='PRIMARY')?.name||material.name):'Ещё не утверждён'}</p><h3>Разрешённые резервные товары</h3>
        {material.reserves?.length?<ul>{material.reserves.map(p=><li key={p.product_id}><strong>{p.name||'Товар недоступен'}</strong><p>Производитель: {p.manufacturer||'Не указан'}</p><p>{p.restrictions||'Без дополнительных ограничений'}{material.selected_reserve_product_id===p.product_id?' · Выбран снабжением':''}</p></li>)}</ul>:<p>Ещё не утверждены</p>}
        {editable&&material.current&&material.allowed_actions.includes('EDIT')&&Boolean(material.reserves?.length)&&<button className="secondary-action" onClick={()=>setModal('reserve')}>Выбрать утверждённый резерв</button>}
      </article><article><h3>Основной поставщик</h3><p>{supplierLabel(material.primary_supplier)}</p><h3>Резервные поставщики</h3>{backups.length?<ul>{backups.map(s=><li key={s.id}>{supplierLabel(s)}</li>)}</ul>:<p>Нет данных</p>}{material.backup_ambiguous&&<p className="material-notice">Несколько поставщиков с одинаковым приоритетом. Основной резерв не определён.</p>}</article>
    </div></section>
    <SpecificationView value={material.current} title="Действующая подтверждённая спецификация"/>
    {material.latest?.status==='DRAFT'&&<div className="material-notice"><strong>Сохранён черновик версии {material.latest.revision}</strong><p>Он пока не является действующим стандартом. Откройте «Изменить спецификацию» для просмотра и подтверждения.</p></div>}
    {modal==='specification'&&<MaterialEditor key={`${material.id}:${material.version}`} material={material} initialReason={savedReason} onSaved={saved} onClose={close}/>}
    {modal==='photo'&&<MaterialPhotoEditor material={material} onSaved={saved} onClose={close}/>}
    {modal==='archive'&&<MaterialArchiveEditor material={material} onSaved={saved} onClose={close}/>}
    {modal==='history'&&<MaterialDialog title="История изменений" onClose={close}><History material={material}/></MaterialDialog>}
    {modal==='reserve'&&<MaterialDialog title="Выбрать утверждённый резерв" dirty={reserveDirty} busy={reserveBusy} onClose={close}><ReserveSelection key={`${material.id}:${material.version}`} material={material} onDirtyChange={setReserveDirty} onBusyChange={setReserveBusy} onSaved={()=>{saved();close()}}/></MaterialDialog>}
  </>
}

const columns=[['','Фото'],['name','Название'],['unit_weight_kg','Вес условной единицы'],['primary_supplier','Основной поставщик'],['backup_supplier','Резервный поставщик'],['last_purchase_price','Последняя цена прихода'],['six_month_average','Средневзвешенная цена за 6 месяцев'],['monthly_consumption','Расход за прошлый месяц']]
export default function RawMaterialsPage() {
  const {productId}=useParams(),[params,setParams]=useSearchParams(),[retry,setRetry]=useState(0)
  const rawPage=Number(params.get('page')||1),page=Number.isSafeInteger(rawPage)&&rawPage>0&&rawPage<1000000?rawPage:1,offset=(page-1)*PAGE_SIZE
  const key=JSON.stringify([productId,params.toString(),retry])
  const [state,setState]=useState<{key:string;catalog:MaterialCatalog|null;material:Material|null;error:string}>({key:'',catalog:null,material:null,error:''})
  const query=params.toString()
  useEffect(()=>{const controller=new AbortController();const request=new URLSearchParams(query);request.delete('page');request.set('offset',String(offset));request.set('limit',String(PAGE_SIZE));const timer=setTimeout(()=>{
    (productId?materialRequest<Material>(`/${productId}`,{signal:controller.signal}).then(material=>({material,catalog:null})):materialRequest<MaterialCatalog>(`?${request}`,{signal:controller.signal}).then(catalog=>({catalog,material:null}))).then(data=>{if(!controller.signal.aborted)setState({key,...data,error:''})}).catch(e=>{if(!controller.signal.aborted)setState({key,catalog:null,material:null,error:errorLabel(e)})})
  },200);return()=>{clearTimeout(timer);controller.abort()}},[productId,query,offset,key])
  const update=(name:string,value:string)=>{const next=new URLSearchParams(params);if(value)next.set(name,value);else next.delete(name);if(name!=='page')next.delete('page');setParams(next,{replace:true})}
  const sort=(field:string)=>{const next=new URLSearchParams(params);next.set('sort',field);next.set('direction',params.get('sort')===field&&params.get('direction')!=='desc'?'desc':'asc');next.delete('page');setParams(next,{replace:true})}
  // Preserve the open action dialog during a successful save/reload of this card.
  const loading=key!==state.key&&(!productId||state.material?.id!==productId),material=state.material,catalog=state.catalog,qs=query?`?${query}`:'',reload=()=>setRetry(v=>v+1)
  return <div className="page-shell"><section className="page-panel product-page material-page"><div className="page-title-row"><div><p className="eyebrow">БАЗА ЗНАНИЙ</p><h1>{productId&&!loading?material?.name||'Карточка сырья':'Сырьё'}</h1><p className="muted-text">Технологические сведения, спецификации и поставщики</p></div></div>
    {productId&&<Link className="product-back" to={`/raw-materials${qs}`}>← К списку сырья</Link>}
    {!productId&&<><div className="product-filters"><EosSearchField label="Поиск" placeholder="Название, алиас или UUID" value={params.get('q')||''} onChange={e=>update('q',e.target.value)}/><label>Вид<EosSelect value={params.get('kind')||''} onChange={e=>update('kind',e.target.value)}><option value="">Все виды</option><option value="RAW_MATERIAL">Сырьё</option><option value="PACKAGING">Упаковка</option></EosSelect></label><label>Категория<EosSelect value={params.get('category_id')||''} onChange={e=>update('category_id',e.target.value)}><option value="">Все категории</option>{catalog?.categories.map(c=><option value={c.id} key={c.id}>{c.name}</option>)}</EosSelect></label><label>Спецификация<EosSelect value={params.get('state')||''} onChange={e=>update('state',e.target.value)}><option value="">Все состояния</option><option value="CONFIRMED">Есть подтверждённая версия</option><option value="UNCONFIRMED">Нет подтверждённой версии</option></EosSelect></label><label>Поставщик<EosSelect value={params.get('supplier_id')||''} onChange={e=>update('supplier_id',e.target.value)}><option value="">Все поставщики</option>{catalog?.suppliers.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</EosSelect></label></div>
      <div className="product-actions material-filter-actions"><button className="secondary-action" aria-pressed={params.get('without_supplier')==='true'} onClick={()=>update('without_supplier',params.get('without_supplier')==='true'?'':'true')}>Без поставщика</button><button className="secondary-action" aria-pressed={params.get('archived')==='true'} onClick={()=>update('archived',params.get('archived')==='true'?'':'true')}>Архив карточек</button><button className="secondary-action" onClick={()=>setParams({})}>Сбросить фильтры</button></div>
    </>}
    {loading?<p className="product-state" role="status">Загружаем сырьё…</p>:state.error?<div role="alert"><p>{state.error}</p><button className="secondary-action" onClick={reload}>Повторить</button></div>:material?<MaterialCard key={material.id} material={material} onSaved={reload}/>:catalog?<>
      {catalog.can_enroll&&<EnrollMaterial onSaved={reload}/>}
      <p className="product-scroll-hint">Прокрутите таблицу вправо, чтобы увидеть все колонки.</p>
      <div className="product-table-wrap" role="region" aria-label="Реестр сырья" tabIndex={0}><table className="product-table"><caption className="product-sr-only">Сырьё и упаковка</caption><thead><tr>{columns.map(([field,label])=>{
        const allowed=field&&!(['last_purchase_price','six_month_average'].includes(field)&&!catalog.purchase_access)
        const selected=(params.get('sort')||'name')===field
        return <th scope="col" key={label} aria-sort={allowed?(selected?(params.get('direction')==='desc'?'descending':'ascending'):'none'):undefined}>{allowed?<button className="material-sort" onClick={()=>sort(field)}>{label}<span aria-hidden="true">{selected?(params.get('direction')==='desc'?' ↓':' ↑'):' ↕'}</span></button>:label}</th>
      })}</tr></thead><tbody>{catalog.items.map(p=><tr key={p.id}><td><Link to={`/raw-materials/${p.id}${qs}`} aria-label={`Карточка ${p.name}`}><RawMaterialPhoto material={p}/></Link></td><td><Link to={`/raw-materials/${p.id}${qs}`}>{p.name}</Link><small>{p.unit||'Единица не подтверждена'} · {p.kind==='PACKAGING'?'Упаковка':'Сырьё'}{!p.supply_active?' · Товар Supply архивирован':''}</small></td><td>{p.unit_weight_kg?`${materialNumber(p.unit_weight_kg)} кг`:'Нет данных'}</td><td>{supplierLabel(p.primary_supplier)}</td><td>{p.backup_ambiguous?'Несколько кандидатов':supplierLabel(p.backup_supplier)}</td><td>{catalog.purchase_access?<PurchaseValue metric={p.last_purchase_price}/>: 'Нет доступа'}</td><td>{catalog.purchase_access?<PurchaseValue metric={p.six_month_average}/>:'Нет доступа'}</td><td><UsageValue metric={p.monthly_consumption}/></td></tr>)}</tbody></table></div>
      {!catalog.items.length&&<div className="product-state" role="status"><h2>Ничего не найдено</h2><p>Измените фильтры. Новые карточки включаются после согласования состава.</p></div>}
      <EosPagination offset={offset} total={catalog.total} pageSize={PAGE_SIZE} itemCount={catalog.items.length} onPageChange={next=>update('page',String(next/PAGE_SIZE+1))}/>
    </>:null}
  </section></div>
}
