import { ProductRecipes } from './productKnowledge/ProductRecipes'
import { ProductPhoto, ProductPhotoEditor } from './productKnowledge/ProductPhoto'
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { EosDateField, EosPagination, EosSearchField, EosSelect } from '../components/EosFormControls'
import { getProduct, getProductCatalog, priceLabel, saleModeLabel, saleStatusLabel, weightLabel, type Catalog, type Product, type ProductPrice, type PriceHealth } from '../services/productKnowledge'
import './ProductKnowledgePage.css'
import { ManualProductAdd, ProductEditor, ProductHistoryPanel } from './productKnowledge/ProductManagement'

const PAGE_SIZE = 25
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Yekaterinburg', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const checkedAt = (value: string) => new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Yekaterinburg' })
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
export default function ProductKnowledgePage() {
  const { productId } = useParams()
  const [params, setParams] = useSearchParams()
  const [retry, setRetry] = useState(0)
  const [state, setState] = useState<{ key: string; catalog: Catalog | null; product: Product | null; error: string | null }>({key: '', catalog: null, product: null, error: null})
  const point = params.get('point') || '', date = params.get('date') || today()
  const query = params.get('q') || '', status = params.get('status') || '', mode = params.get('mode') || '', category = params.get('category') || ''
  const deleted = params.get('deleted') === 'true', unverified = params.get('unverified') === 'true'
  const rawPage = Number(params.get('page') || '1'), page = Number.isSafeInteger(rawPage) && rawPage > 0 && rawPage < 1000000 ? rawPage : 1
  const offset = (page - 1) * PAGE_SIZE
  const key = JSON.stringify([productId, point, date, query, status, mode, category, deleted, unverified, offset, retry])
  useEffect(() => {
    const controller = new AbortController()
    const request = new URLSearchParams({ price_at: date, offset: String(productId ? 0 : offset), limit: String(productId ? 1 : PAGE_SIZE) })
    if (point) request.set('department_id', point)
    if (!productId) { if (deleted) request.set('deleted', 'true'); if (unverified) request.set('unverified', 'true'); if (query) request.set('q', query); if (status) request.set('status', status); if (mode) request.set('mode', mode); if (category) request.set('category_id', category) }
    const selected = new URLSearchParams({price_at: date}); if (point) selected.set('department_id', point)
    const timer = setTimeout(() => {
      Promise.all([getProductCatalog(request, controller.signal), productId ? getProduct(productId, selected, controller.signal) : Promise.resolve(null)])
        .then(([catalog, product]) => { if (!controller.signal.aborted) setState({key, catalog, product, error: null}) })
        .catch((error: unknown) => { if (!controller.signal.aborted) setState({key, catalog: null, product: null, error: error instanceof Error && error.name === 'ProductApiError' ? error.message : 'Не удалось загрузить продукцию. Повторите позже'}) })
    }, 200)
    return () => { clearTimeout(timer); controller.abort() }
  }, [key, productId, point, date, query, status, mode, category, deleted, unverified, offset])
  const loading = state.key !== key, catalog = state.catalog, product = state.product
  const update = (name: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(name, value); else next.delete(name)
    if (name !== 'page') next.delete('page')
    setParams(next, { replace: true })
  }
  const queryString = params.size ? `?${params.toString()}` : ''
  const controls = <div className="product-price-controls"><label>Точка цены<EosSelect aria-label="Точка цены" value={point} onChange={e => update('point', e.target.value)}><option value="">Выберите точку</option>{catalog?.points.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</EosSelect></label><EosDateField label="Дата цены" value={date} onChange={e => update('date', e.target.value)} /></div>
  return <div className="page-shell"><section className="page-panel product-page">
    <div className="page-title-row"><div><p className="eyebrow">БАЗА ЗНАНИЙ</p><h1>{productId && !loading ? product?.name || 'Карточка продукции' : 'Продукция'}</h1><p className="muted-text">Изделия, характеристики и материалы для работы</p></div></div>
    {productId && <Link className="product-back" to={`/products${queryString}`}>← К списку продукции</Link>}
    {!productId && <>
      <div className="product-filters"><EosSearchField label="Поиск" placeholder="Название или артикул" value={query} onChange={e => update('q', e.target.value)} /><label>Статус<EosSelect value={status} onChange={e => update('status', e.target.value)}><option value="">Все статусы</option><option value="ON_SALE">В продаже</option><option value="OFF_SALE">Выведено из продажи</option></EosSelect></label><label>Категория EOS<EosSelect value={category} onChange={e => update('category', e.target.value)}><option value="">Все категории</option>{catalog?.categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</EosSelect></label><label>Тип продажи<EosSelect value={mode} onChange={e => update('mode', e.target.value)}><option value="">Все типы</option><option value="PORTION">Порционный</option><option value="WEIGHT">Весовой</option><option value="UNKNOWN">Нет данных</option></EosSelect></label></div>
      <div className="product-filter-footer"><label><input type="checkbox" checked={unverified} onChange={e => update('unverified', e.target.checked ? 'true' : '')} /> Только непроверенные</label><label><input type="checkbox" checked={deleted} onChange={e => update('deleted', e.target.checked ? 'true' : '')} /> Удалённые из EOS</label>{controls}<button className="secondary-action" onClick={() => { const next = new URLSearchParams(params); ['q','status','mode','category','page','deleted','unverified'].forEach(k => next.delete(k)); setParams(next, {replace:true}) }}>Сбросить фильтры</button></div>
    </>}
    {loading ? <div className="product-state" role="status">Загружаем продукцию…</div> : state.error ? <div className="product-state" role="alert"><p>{state.error}</p><button className="secondary-action" onClick={() => setRetry(x => x + 1)}>Повторить</button></div> : productId && product ? <>
      <div className="product-card-overview"><ProductPhoto product={product} large /><div><p className="muted-text">{product.sku || 'Артикул отсутствует'} · {product.category_name || 'Категория не подтверждена'}</p><span className={`product-status ${product.sale_status === 'OFF_SALE' ? 'product-status-off' : ''}`}>{saleStatusLabel(product.sale_status)}</span><dl><dt>Единица</dt><dd>{product.unit_name}</dd><dt>Вес основной единицы</dt><dd>{weightLabel(product)}</dd><dt>Тип продажи</dt><dd>{saleModeLabel(product.sale_mode)}</dd><dt>Цена</dt><dd>{priceLabel(product.price, point, product.price_conflict_points)}<PriceContext price={product.price} /><PriceHealthNotice health={product.price_health?.find(h => h.department_id === point)} /></dd></dl><small>Источник: iiko · данные получены {checkedAt(product.observed_at)}</small></div></div>
      {controls}
      {product.deleted_at && <p className="product-notice">Удалено из справочника EOS {checkedAt(product.deleted_at)}</p>}
      <p>{product.verified_at ? `Проверено: ${product.verified_by_name || 'Сотрудник'} · ${checkedAt(product.verified_at)}` : 'Сведения EOS не проверены'}</p>
      <ProductPhotoEditor key={`photo:${product.id}:${product.version}`} product={product} onSaved={() => setRetry(x => x + 1)} />
      <ProductEditor key={`${product.id}:${product.version}`} product={product} categories={catalog?.categories || []} onSaved={() => setRetry(x => x + 1)} />
      {product.source_deleted && <p className="product-notice" role="status">Запись удалена в источнике iiko. Статус ассортимента EOS требует отдельной проверки.</p>}
      <div className="product-knowledge-grid"><MissingSection title="Описание" source={product.description_source} text={product.description} /><MissingSection title="Характеристики" text={product.characteristics} /><MissingSection title="Состав и ингредиенты" text={product.composition} /><MissingSection title="Аллергены" text={product.allergens} /><MissingSection title="Сроки и условия хранения" text={product.storage} /><MissingSection title="Обучение продавцов" text={product.training} /><section className="product-knowledge-section"><h2>Цены по точкам</h2>{catalog?.points.map(p => { const price = product.prices.find(price => price.department_id === p.id) || null; return <p key={p.id}>{p.name}: <strong>{priceLabel(price, p.id, product.price_conflict_points)}</strong><PriceContext price={price} /><PriceHealthNotice health={product.price_health?.find(h => h.department_id === p.id)} /></p> })}<small>Подтверждённые цены на {date}</small></section></div>
      {product.recipe_access && <ProductRecipes key={product.id} productId={product.id} />}
      <ProductHistoryPanel key={product.id} product={product} />
    </> : catalog ? <>
      {catalog.allowed_actions?.includes('ADD') && <ManualProductAdd onSaved={() => setRetry(x => x + 1)} />}
      <p className="muted-text">Актуализация: проверено {catalog.verified_count || 0} из {catalog.active_count || 0} изделий рабочего каталога.</p>
      {catalog.observed_at && <p className="muted-text">Данные источника получены {checkedAt(catalog.observed_at)}. Автоматическое расширение ассортимента отключено.</p>}
      <div className="product-mobile-catalog">{catalog.items.map(p => <article key={p.id}><ProductPhoto product={p} /><div><Link to={`/products/${p.id}${queryString}`}>{p.name}</Link><p>{p.unit_name} · {weightLabel(p)} · {saleModeLabel(p.sale_mode)}</p><p>{priceLabel(p.price, point, p.price_conflict_points)}</p><PriceHealthNotice health={p.price_health?.find(h => h.department_id === point)} /><small>{p.deleted_at ? 'Удалено из EOS' : saleStatusLabel(p.sale_status)} · {p.verified_at ? 'Проверено' : 'Не проверено'}</small></div></article>)}</div>
      <p className="product-scroll-hint">Прокрутите таблицу вправо, чтобы увидеть все колонки.</p>
      <div className="product-table-wrap" role="region" aria-label="Таблица продукции с горизонтальной прокруткой" tabIndex={0}><table className="product-table"><caption className="product-sr-only">Каталог продукции</caption><thead><tr>{['Фото','Название','Вес','Порционный / весовой товар','Цена','Статус'].map(c => <th scope="col" key={c}>{c}</th>)}</tr></thead><tbody>{catalog.items.map(p => <tr key={p.id}><td><ProductPhoto product={p} /></td><td><Link to={`/products/${p.id}${queryString}`}>{p.name}</Link><small>{p.sku || 'Артикул отсутствует'} · {p.category_name || 'Категория не подтверждена'} · {p.unit_name}</small></td><td>{weightLabel(p)}</td><td>{saleModeLabel(p.sale_mode)}</td><td>{priceLabel(p.price, point, p.price_conflict_points)}<PriceHealthNotice health={p.price_health?.find(h => h.department_id === point)} /></td><td>{p.deleted_at ? 'Удалено из EOS' : saleStatusLabel(p.sale_status)}<small>{p.verified_at ? `Проверено: ${p.verified_by_name || 'Сотрудник'}` : 'Не проверено'}</small></td></tr>)}</tbody></table></div>
      {catalog.items.length === 0 && <div className="product-state" role="status"><h2>{catalog.total === 0 && !query && !status && !mode && !category ? 'Каталог пока пуст' : 'Ничего не найдено'}</h2><p>Измените фильтры или дождитесь подтверждённого наполнения базы.</p></div>}
      <EosPagination offset={offset} total={catalog.total} pageSize={PAGE_SIZE} itemCount={catalog.items.length} onPageChange={next => update('page', String(next / PAGE_SIZE + 1))} />
    </> : null}
  </section></div>
}
