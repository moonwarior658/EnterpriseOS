import { ProductCosts } from './productKnowledge/ProductCosts'
import { costLabel } from '../services/productCosts'
import { ProductRecipes } from './productKnowledge/ProductRecipes'
import { ProductPhoto, ProductPhotoEditor } from './productKnowledge/ProductPhoto'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { EosDateField, EosPagination, EosSearchField, EosSelect } from '../components/EosFormControls'
import { getProduct, getProductCatalog, priceLabel, saleModeLabel, saleStatusLabel, weightLabel, type Catalog, type Product, type ProductPrice, type PriceHealth } from '../services/productKnowledge'
import { KnowledgeDialog } from '../components/KnowledgeDialog'
import { KnowledgeHeader, KnowledgeInfo, KnowledgeStatus, KnowledgeActions, KnowledgeFilterToggle, KnowledgeSortHeader } from '../components/KnowledgeUI'
import './ProductKnowledgePage.css'
import '../components/KnowledgeUI.css'
import { ManualProductAdd, ProductEditor, ProductHistoryPanel } from './productKnowledge/ProductManagement'

const PAGE_SIZE = 25
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Yekaterinburg', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const checkedAt = (value: string) => new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Yekaterinburg' })
function ProductPriceValue({price,point,conflicts=[]}:{price:ProductPrice|null;point:string;conflicts?:string[]}) {
  const label=priceLabel(price,point,conflicts)
  return !point||conflicts.includes(point)||!price?<KnowledgeStatus tone={point&&conflicts.includes(point)?'blocked':'empty'}>{label}</KnowledgeStatus>:<span className="material-metric-value">{label}</span>
}
function PriceContext({ price }: { price: ProductPrice | null }) {
  if (!price) return null
  return <small>Источник: iiko · период с {price.valid_from} до {price.valid_to} (не включая) · получено {checkedAt(price.observed_at)}</small>
}
function PriceHealthNotice({ health }: { health: PriceHealth | undefined }) {
  if (!health) return null
  return <small role={health.stale || health.update_failed ? 'status' : undefined}>
    {health.update_failed && 'Последнее обновление цен завершилось ошибкой. '}
    {health.stale && (health.last_success_at ? 'Ценовой снимок устарел. ' : 'Ценовой снимок ещё не получен. ')}
    {health.last_success_at && `Последнее успешное получение цен: ${checkedAt(health.last_success_at)}`}
  </small>
}
function MissingSection({ title, text = null, source = 'EOS' }: { title: string; text?: string | null; source?: string }) {
  return <section className="product-knowledge-section"><h2>{title}</h2><p>{text || 'Нет данных'}</p><small>{text ? `Источник: ${source}` : 'Подтверждённые сведения отсутствуют'}</small></section>
}
function ProductCard({product,catalog,point,date,controls,onSaved}:{product:Product;catalog:Catalog|null;point:string;date:string;controls:ReactNode;onSaved:()=>void}) {
  const [modal,setModal]=useState<'history'|'prices'|'costs'|'recipes'|null>(null)
  const [dirty,setDirty]=useState(false),[busy,setBusy]=useState(false)
  const close=()=>{setModal(null);setDirty(false);setBusy(false)}
  return <>
    <KnowledgeActions>
      <ProductEditor key={`edit:${product.id}:${product.version}`} product={product} categories={catalog?.categories||[]} onSaved={onSaved}/>
      <ProductPhotoEditor key={`photo:${product.id}:${product.version}`} product={product} onSaved={onSaved}/>
      <button className="secondary-action" onClick={()=>setModal('history')}>История изменений</button>
      <button className="secondary-action" onClick={onSaved}>Обновить карточку</button>
    </KnowledgeActions>
    <div className="product-card-overview"><ProductPhoto product={product} large/><KnowledgeInfo title="Об изделии" items={[
      {label:'Артикул',value:product.sku||'Артикул отсутствует'},
      {label:'Категория EOS',value:product.category_name||'Категория не подтверждена'},
      {label:'Статус продажи',value:<KnowledgeStatus tone={product.deleted_at||product.sale_status==='OFF_SALE'?'empty':'ready'}>{product.deleted_at?'Удалено из EOS':saleStatusLabel(product.sale_status)}</KnowledgeStatus>},
      {label:'Единица iiko',value:product.unit_name},
      {label:'Вес основной единицы',value:weightLabel(product)},
      {label:'Тип продажи',value:saleModeLabel(product.sale_mode)},
      {label:'Цена по выбранной точке',value:<><ProductPriceValue price={product.price} point={point} conflicts={product.price_conflict_points}/><PriceHealthNotice health={product.price_health?.find(h=>h.department_id===point)}/></>},
      {label:'Проверка сведений',value:product.verified_at?`${product.verified_by_name||'Сотрудник'} · ${checkedAt(product.verified_at)}`:'Сведения EOS не проверены'}
    ]}/></div>
    {controls}
    {product.deleted_at&&<p className="product-notice">Удалено из справочника EOS {checkedAt(product.deleted_at)}. История и связи сохранены.</p>}
    {product.source_deleted&&<p className="product-notice" role="status">Запись удалена в источнике iiko. Статус ассортимента EOS требует отдельной проверки.</p>}
    <div className="product-knowledge-grid"><MissingSection title="Описание" source={product.description_source} text={product.description}/><MissingSection title="Характеристики" text={product.characteristics}/><MissingSection title="Состав и ингредиенты" text={product.composition}/><MissingSection title="Аллергены" text={product.allergens}/><MissingSection title="Сроки и условия хранения" text={product.storage}/><MissingSection title="Обучение продавцов" text={product.training}/></div>
    <section className="product-knowledge-section"><h2>Цены и дополнительные сведения</h2><p>Цена на {date}: <ProductPriceValue price={product.price} point={point} conflicts={product.price_conflict_points}/></p>
      {product.cost_access&&<p>Себестоимость: {costLabel(product.cost)}</p>}
      <div className="product-actions"><button className="secondary-action" onClick={()=>setModal('prices')}>Цены по точкам и источники</button>{product.cost_access&&<button className="secondary-action" onClick={()=>setModal('costs')}>Себестоимость · ССН</button>}{product.recipe_access&&<button className="secondary-action" onClick={()=>setModal('recipes')}>Технологическая карта</button>}</div>
    </section>
    <small>Источник: iiko · данные получены {checkedAt(product.observed_at)}</small>
    {modal&&<KnowledgeDialog title={modal==='history'?'История изменений':modal==='prices'?'Цены по точкам и источники':modal==='costs'?'Себестоимость · ССН':'Технологическая карта'} onClose={close} dirty={dirty} busy={busy}>
      {modal==='history'&&<ProductHistoryPanel product={product}/>}
      {modal==='prices'&&<section><h3>Цены по точкам</h3>{!catalog?.points.length&&<p>Нет доступных точек цены</p>}{catalog?.points.map(p=>{const price=product.prices.find(r=>r.department_id===p.id)||null;return <article className="material-history-item" key={p.id}><p>{p.name}: <strong><ProductPriceValue price={price} point={p.id} conflicts={product.price_conflict_points}/></strong></p><PriceContext price={price}/><PriceHealthNotice health={product.price_health?.find(h=>h.department_id===p.id)}/></article>})}<p>Подтверждённые цены на {date}</p></section>}
      {modal==='costs'&&product.cost_access&&<ProductCosts productId={product.id} onDirtyChange={setDirty} onBusyChange={setBusy}/>}
      {modal==='recipes'&&product.recipe_access&&<ProductRecipes productId={product.id} onDirtyChange={setDirty} onBusyChange={setBusy}/>}
    </KnowledgeDialog>}
  </>
}

export default function ProductKnowledgePage() {
  const { productId } = useParams()
  const [params, setParams] = useSearchParams()
  const [retry, setRetry] = useState(0)
  const [state, setState] = useState<{ key: string; catalog: Catalog | null; product: Product | null; error: string | null }>({key: '', catalog: null, product: null, error: null})
  const point = params.get('point') || '', date = params.get('date') || today()
  const query = params.get('q') || '', status = params.get('status') || '', mode = params.get('mode') || '', category = params.get('category') || ''
  const sort=params.get('sort')||'name',direction=params.get('direction')||'asc'
  const deleted = params.get('deleted') === 'true', unverified = params.get('unverified') === 'true'
  const rawPage = Number(params.get('page') || '1'), page = Number.isSafeInteger(rawPage) && rawPage > 0 && rawPage < 1000000 ? rawPage : 1
  const offset = (page - 1) * PAGE_SIZE
  const key = JSON.stringify([productId, point, date, query, status, mode, category, deleted, unverified, offset, sort, direction, retry])
  useEffect(() => {
    const controller = new AbortController()
    const request = new URLSearchParams({ price_at: date, offset: String(productId ? 0 : offset), limit: String(productId ? 1 : PAGE_SIZE) })
    if (point) request.set('department_id', point)
    if (!productId) { if (deleted) request.set('deleted', 'true'); if (unverified) request.set('unverified', 'true'); if (query) request.set('q', query); if (status) request.set('status', status); if (mode) request.set('mode', mode); if (category) request.set('category_id', category); request.set('sort',sort);request.set('direction',direction) }
    const selected = new URLSearchParams({price_at: date}); if (point) selected.set('department_id', point)
    const timer = setTimeout(() => {
      Promise.all([getProductCatalog(request, controller.signal), productId ? getProduct(productId, selected, controller.signal) : Promise.resolve(null)])
        .then(([catalog, product]) => { if (!controller.signal.aborted) setState({key, catalog, product, error: null}) })
        .catch((error: unknown) => { if (!controller.signal.aborted) setState({key, catalog: null, product: null, error: error instanceof Error && error.name === 'ProductApiError' ? error.message : 'Не удалось загрузить продукцию. Повторите позже'}) })
    }, 200)
    return () => { clearTimeout(timer); controller.abort() }
  }, [key, productId, point, date, query, status, mode, category, deleted, unverified, offset, sort, direction])
  const sameSelection=Boolean(state.key)&&JSON.stringify(JSON.parse(state.key).slice(0,-1))===JSON.stringify(JSON.parse(key).slice(0,-1))
  const loading = state.key !== key&&!(productId&&state.product?.id===productId&&sameSelection), catalog = state.catalog, product = state.product
  const update = (name: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value); else next.delete(name)
    if (name !== 'page') next.delete('page')
    setParams(next, { replace: true })
  }
  const queryString = params.size ? `?${params.toString()}` : ''
  const controls = <div className="product-price-controls"><label>Точка цены<EosSelect aria-label="Точка цены" value={point} onChange={e => update('point', e.target.value)}><option value="">Выберите точку</option>{catalog?.points.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</EosSelect></label><EosDateField label="Дата цены" value={date} onChange={e => update('date', e.target.value)} /></div>
  return <div className="page-shell"><section className="page-panel product-page knowledge-page">
    <KnowledgeHeader title={productId&&!loading?product?.name||'Карточка продукции':'Продукция'} description="Изделия, характеристики и материалы для работы"/>
    {productId && <Link className="product-back" to={`/products${queryString}`}>← К списку продукции</Link>}
    {!productId && <>
      <div className="product-filters"><EosSearchField label="Поиск" placeholder="Название или артикул" value={query} onChange={e => update('q', e.target.value)} /><label>Статус<EosSelect value={status} onChange={e => update('status', e.target.value)}><option value="">Все статусы</option><option value="ON_SALE">В продаже</option><option value="OFF_SALE">Выведено из продажи</option></EosSelect></label><label>Категория EOS<EosSelect value={category} onChange={e => update('category', e.target.value)}><option value="">Все категории</option>{catalog?.categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</EosSelect></label><label>Тип продажи<EosSelect value={mode} onChange={e => update('mode', e.target.value)}><option value="">Все типы</option><option value="PORTION">Порционный</option><option value="WEIGHT">Весовой</option><option value="UNKNOWN">Нет данных</option></EosSelect></label></div>
      <div className="product-filter-footer material-filter-actions"><KnowledgeFilterToggle active={unverified} onClick={()=>update('unverified',unverified?'':'true')}>Только непроверенные</KnowledgeFilterToggle><KnowledgeFilterToggle active={deleted} onClick={()=>update('deleted',deleted?'':'true')}>Удалённые из EOS</KnowledgeFilterToggle>{controls}<button className="secondary-action" onClick={() => { const next = new URLSearchParams(params); ['q','status','mode','category','page','deleted','unverified','sort','direction'].forEach(k => next.delete(k)); setParams(next, {replace:true}) }}>Сбросить фильтры</button></div>
    </>}
    {loading ? <div className="product-state" role="status">Загружаем продукцию…</div> : state.error ? <div className="product-state" role="alert"><p>{state.error}</p><button className="secondary-action" onClick={() => setRetry(x => x + 1)}>Повторить</button></div> : productId && product ? <ProductCard key={product.id} product={product} catalog={catalog} point={point} date={date} controls={controls} onSaved={()=>setRetry(x=>x+1)}/> : catalog ? <>
      {catalog.allowed_actions?.includes('ADD') && <ManualProductAdd onSaved={() => setRetry(x => x + 1)} />}
      <p className="muted-text">Актуализация: проверено {catalog.verified_count || 0} из {catalog.active_count || 0} изделий рабочего каталога.</p>
      {catalog.observed_at && <p className="muted-text">Данные источника получены {checkedAt(catalog.observed_at)}. Автоматическое расширение ассортимента отключено.</p>}
      <p className="product-scroll-hint">Прокрутите таблицу вправо, чтобы увидеть все колонки.</p>
      <div className="product-table-wrap" role="region" aria-label="Таблица продукции с горизонтальной прокруткой" tabIndex={0}><table className="product-table"><caption className="product-sr-only">Каталог продукции</caption><thead><tr>{[['','Фото'],['name','Название'],['unit_weight_kg','Вес'],['sale_mode','Порционный / весовой товар'],['price','Цена'],...(catalog.cost_access?[['cost','Себестоимость']]:[]),['sale_status','Статус']].map(([field,label])=><KnowledgeSortHeader key={label} label={label} field={field} selected={sort} direction={direction} onSort={field=>{const next=new URLSearchParams(params);next.set('sort',field);next.set('direction',sort===field&&params.has('sort')&&direction!=='desc'?'desc':'asc');next.delete('page');setParams(next,{replace:true})}}/>)}</tr></thead><tbody>{catalog.items.map(p => <tr key={p.id}><td><ProductPhoto product={p} /></td><td><Link to={`/products/${p.id}${queryString}`}>{p.name}</Link><small>{p.sku || 'Артикул отсутствует'} · {p.category_name || 'Категория не подтверждена'} · {p.unit_name}</small></td><td>{weightLabel(p)}</td><td>{saleModeLabel(p.sale_mode)}</td><td><ProductPriceValue price={p.price} point={point} conflicts={p.price_conflict_points}/><PriceHealthNotice health={p.price_health?.find(h => h.department_id === point)} /></td>{catalog.cost_access && <td>{costLabel(p.cost)}</td>}<td><KnowledgeStatus tone={p.deleted_at||p.sale_status==='OFF_SALE'?'empty':'ready'}>{p.deleted_at ? 'Удалено из EOS' : saleStatusLabel(p.sale_status)}</KnowledgeStatus><small>{p.verified_at ? `Проверено: ${p.verified_by_name || 'Сотрудник'}` : 'Не проверено'}</small></td></tr>)}</tbody></table></div>
      {catalog.items.length === 0 && <div className="product-state" role="status"><h2>{catalog.total === 0 && !query && !status && !mode && !category ? 'Каталог пока пуст' : 'Ничего не найдено'}</h2><p>Измените фильтры или дождитесь подтверждённого наполнения базы.</p></div>}
      <EosPagination offset={offset} total={catalog.total} pageSize={PAGE_SIZE} itemCount={catalog.items.length} onPageChange={next => update('page', String(next / PAGE_SIZE + 1))} />
    </> : null}
  </section></div>
}
