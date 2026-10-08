import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { EosDateField, EosPagination, EosSearchField, EosSelect } from '../components/EosFormControls'
import { EosDialog } from '../components/EosDialog'
import { demoDate, demoPoints, demoProducts, filterCatalog, modeLabel, resolveDemoPrice, statusLabel, type DemoProduct } from './productKnowledge/demoCatalog'
import './ProductKnowledgePage.css'

type Operation = 'add' | 'edit' | 'photo' | 'status'
const operationTitles = { add: 'Добавление продукции', edit: 'Редактирование карточки', photo: 'Фотографии продукции', status: 'Управление статусом' }
const PAGE_SIZE = 6
function ManagementDialog({ operation, product, onClose }: { operation: Operation; product?: DemoProduct; onClose: () => void }) {
  const formRef = useRef<HTMLFormElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const form = formRef.current!
    const elements = () => Array.from(form.querySelectorAll<HTMLElement>('input:not(:disabled), select:not(:disabled), textarea:not(:disabled), button:not(:disabled)'))
    elements()[0]?.focus()
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const targets = elements(), first = targets[0], last = targets[targets.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    form.addEventListener('keydown', trap)
    return () => { form.removeEventListener('keydown', trap); previous?.focus() }
  }, [])
  return <EosDialog title={operationTitles[operation]} onClose={onClose} className="product-management-dialog">
    <form ref={formRef} onSubmit={event => event.preventDefault()} className="product-management-form">
      <p className="product-notice" role="status">Операция недоступна: сохранение пока не подключено. Введённые данные не сохраняются.</p>
      {(operation === 'add' || operation === 'edit') && <>
        <label>Название<input defaultValue={product?.name ?? ''} placeholder="Название изделия" /></label>
        <label>Артикул<input defaultValue={product?.sku ?? ''} /></label>
        <label>Категория EOS<EosSelect defaultValue={product?.category ?? ''}><option value="">Не выбрана</option>{['Десерты', 'Торты', 'Выпечка'].map(c => <option key={c}>{c}</option>)}</EosSelect></label>
        <label>Тип продажи<EosSelect defaultValue={product?.mode ?? 'UNKNOWN'}><option value="UNKNOWN">Нет данных</option><option value="PORTION">Порционный</option><option value="WEIGHT">Весовой</option></EosSelect></label>
        <label>Вес и единица<input defaultValue={product?.weight ?? ''} placeholder="Требует подтверждения" /></label>
        <label>Описание<textarea defaultValue={product?.description ?? ''} rows={3} /></label>
        <label>Состав<textarea defaultValue={product?.composition ?? ''} rows={2} /></label>
        <label>Аллергены<textarea defaultValue={product?.allergens ?? ''} rows={2} /></label>
        <label>Хранение<textarea defaultValue={product?.storage ?? ''} rows={2} /></label>
        <label>Обучение продавцов<textarea defaultValue={product?.training ?? ''} rows={2} /></label>
      </>}
      {operation === 'status' && <>
        <label>Статус<EosSelect defaultValue={product?.status}><option value="ON_SALE">В продаже</option><option value="OFF_SALE">Выведено из продажи</option></EosSelect></label>
        <label>Причина изменения<textarea rows={3} placeholder="Причина вывода или возврата в продажу" /></label>
        <p className="muted-text">Статус EOS независим от меню iiko. Изменение требует серверного подтверждения и истории.</p>
      </>}
      {operation === 'photo' && <>
        <ProductImage product={product} large />
        <label>Новое фото<input type="file" accept="image/jpeg,image/png" disabled aria-describedby="photo-unavailable" /></label>
        <p id="photo-unavailable" className="muted-text">Загрузка, замена и удаление фото недоступны до подключения защищённого хранения.</p>
        <button type="button" className="secondary-action" disabled>Удалить фото</button>
      </>}
      <div className="product-actions"><button className="primary-action" disabled type="submit">Сохранение недоступно</button><button type="button" className="secondary-action" onClick={onClose}>Закрыть</button></div>
    </form>
  </EosDialog>
}
function ProductImage({ product, large = false }: { product?: DemoProduct; large?: boolean }) {
  return <div className={large ? 'product-image product-image-large' : 'product-image'}>{product?.image ? <img src={product.image} alt={`Демонстрационная иллюстрация: ${product.name}`} /> : <span>Нет фото</span>}</div>
}
function KnowledgeSection({ title, text }: { title: string; text: string | null }) {
  return <section className="product-knowledge-section"><h2>{title}</h2><p>{text ?? 'Нет данных'}</p><small>{text ? 'Источник: демонстрационные данные EOS · не проверено' : 'Источник не подтверждён · дата проверки отсутствует'}</small></section>
}
export default function ProductKnowledgePage({ basePath = '/products' }: { basePath?: string }) {
  const { productId } = useParams()
  const [params, setParams] = useSearchParams()
  const [ready, setReady] = useState(false)
  const [operation, setOperation] = useState<Operation | null>(null)
  useEffect(() => { const timer = setTimeout(() => setReady(true), 250); return () => clearTimeout(timer) }, [])
  const scenario = params.get('scenario') ?? 'normal'
  const point = params.get('point') ?? ''
  const date = params.get('date') ?? demoDate
  const filters = { query: params.get('q') ?? '', status: params.get('status') ?? '', category: params.get('category') ?? '', mode: params.get('mode') ?? '' }
  const filtered = filterCatalog(scenario === 'empty' ? [] : demoProducts, filters)
  const rawPage = Number(params.get('page') ?? 1)
  const page = Number.isInteger(rawPage) && rawPage > 0 ? Math.min(rawPage, Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))) : 1
  const offset = (page - 1) * PAGE_SIZE
  const items = filtered.slice(offset, offset + PAGE_SIZE)
  const product = scenario === 'empty' ? undefined : demoProducts.find(p => p.id === productId)
  const loading = !ready || scenario === 'loading'
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value); else next.delete(key)
    if (key !== 'page') next.delete('page')
    setParams(next, { replace: true })
  }
  const queryString = params.size ? `?${params.toString()}` : ''
  const controls = <div className="product-price-controls">
    <label>Точка цены<EosSelect aria-label="Точка цены" value={point} onChange={e => update('point', e.target.value)}><option value="">Выберите точку</option>{demoPoints.map(p => <option key={p}>{p}</option>)}</EosSelect></label>
    <EosDateField label="Дата цены" value={date} onChange={e => update('date', e.target.value)} />
  </div>
  return <div className="page-shell"><section className="page-panel product-page">
    <div className="page-title-row"><div><p className="eyebrow">БАЗА ЗНАНИЙ</p><h1>{productId ? product?.name ?? 'Карточка продукции' : 'Продукция'}</h1><p className="muted-text">Изделия, характеристики и материалы для работы</p></div>
      {!productId && <button className="primary-action" onClick={() => setOperation('add')}>Добавить изделие</button>}
    </div>
    <p className="product-notice">Демонстрационный портал K0. Данные, цены и иллюстрации вымышлены. Сохранение и интеграции недоступны.</p>
    <details className="product-demo-controls"><summary>Сценарии для review</summary><label>Состояние интерфейса<EosSelect aria-label="Состояние интерфейса" value={scenario} onChange={e => update('scenario', e.target.value)}>{[['normal', 'Демонстрационные данные'], ['empty', 'Пустой каталог'], ['loading', 'Загрузка'], ['error', 'Ошибка'], ['stale', 'Устаревшие данные']].map(([v, label]) => <option key={v} value={v}>{label}</option>)}</EosSelect></label></details>
    {productId && <Link className="product-back" to={`${basePath}${queryString}`}>← К списку продукции</Link>}
    {loading ? <div className="product-state" role="status" aria-live="polite">Загружаем продукцию…</div> : scenario === 'error' ? <div className="product-state" role="alert"><h2>Не удалось загрузить продукцию</h2><p>Попробуйте ещё раз. Это демонстрация ошибки загрузки.</p><button className="secondary-action" onClick={() => update('scenario', 'normal')}>Повторить</button></div> : <>
      {scenario === 'stale' && <p role="status" className="product-notice">Данные устарели. Актуальность и цены требуют повторной проверки.</p>}
      {productId ? product ? <>
        <div className="product-card-overview"><ProductImage product={product} large /><div><p className="muted-text">{product.category} · {product.sku}</p><span className={`product-status ${product.status === 'OFF_SALE' ? 'product-status-off' : ''}`}>{statusLabel(product.status)}</span><dl><dt>Вес</dt><dd>{product.weight ?? 'Нет данных'}</dd><dt>Тип продажи</dt><dd>{modeLabel(product.mode)}</dd><dt>Цена</dt><dd>{resolveDemoPrice(product, point, date)}</dd><dt>Себестоимость</dt><dd>Источник не подтверждён</dd></dl><small>Демонстрационные данные · проверка не проводилась</small><div className="product-actions">{(['edit', 'photo', 'status'] as Operation[]).map(op => <button key={op} className="secondary-action" onClick={() => setOperation(op)}>{op === 'edit' ? 'Редактировать' : op === 'photo' ? 'Фотографии' : 'Изменить статус'}</button>)}</div></div></div>
        {controls}
        <div className="product-knowledge-grid">
          <KnowledgeSection title="Описание и характеристики" text={product.description} />
          <KnowledgeSection title="Состав и ингредиенты" text={product.composition} />
          <KnowledgeSection title="Аллергены" text={product.allergens} />
          <KnowledgeSection title="Сроки и условия хранения" text={product.storage} />
          <KnowledgeSection title="Обучение продавцов" text={product.training} />
          <KnowledgeSection title="Технологическая информация" text={null} />
          <KnowledgeSection title="Себестоимость и метод расчёта" text={null} />
          <section className="product-knowledge-section"><h2>Цены по точкам</h2>{demoPoints.map(p => <p key={p}>{p}: <strong>{resolveDemoPrice(product, p, date)}</strong></p>)}<small>Демонстрационные цены · дата {date || 'не выбрана'} · не проверено</small></section>
          <KnowledgeSection title="История изменений" text={null} />
        </div>
      </> : <div className="product-state"><h2>Изделие не найдено</h2><p>Вернитесь к списку и выберите изделие.</p></div> : <>
        <div className="product-filters">
          <EosSearchField label="Поиск" placeholder="Название или артикул" value={filters.query} onChange={e => update('q', e.target.value)} />
          <label>Статус<EosSelect value={filters.status} onChange={e => update('status', e.target.value)}><option value="">Все статусы</option><option value="ON_SALE">В продаже</option><option value="OFF_SALE">Выведено из продажи</option></EosSelect></label>
          <label>Категория EOS<EosSelect value={filters.category} onChange={e => update('category', e.target.value)}><option value="">Все категории</option>{['Десерты', 'Торты', 'Выпечка'].map(c => <option key={c}>{c}</option>)}</EosSelect></label>
          <label>Тип продажи<EosSelect value={filters.mode} onChange={e => update('mode', e.target.value)}><option value="">Все типы</option><option value="PORTION">Порционный</option><option value="WEIGHT">Весовой</option><option value="UNKNOWN">Нет данных</option></EosSelect></label>
        </div>
        <div className="product-filter-footer">{controls}<button className="secondary-action" onClick={() => { const next = new URLSearchParams(params); ['q', 'status', 'category', 'mode', 'page'].forEach(k => next.delete(k)); setParams(next, { replace: true }) }}>Сбросить фильтры</button></div>
        <p className="product-scroll-hint">Прокрутите таблицу вправо, чтобы увидеть все колонки.</p>
        <div className="product-table-wrap" role="region" aria-label="Таблица продукции с горизонтальной прокруткой" tabIndex={0}><table className="product-table"><caption className="product-sr-only">Демонстрационный каталог продукции</caption><thead><tr>{['Фото', 'Название', 'Вес', 'Порционный / весовой товар', 'Цена', 'Себестоимость', 'Статус'].map(c => <th scope="col" key={c}>{c}</th>)}</tr></thead><tbody>{items.map(p => <tr key={p.id}><td><ProductImage product={p} /></td><td><Link to={`${basePath}/${p.id}${queryString}`}>{p.name}</Link><small>{p.sku} · {p.category}</small></td><td>{p.weight ?? 'Нет данных'}</td><td>{modeLabel(p.mode)}</td><td>{resolveDemoPrice(p, point, date)}</td><td><span className="muted-text">Источник не подтверждён</span></td><td><EosSelect aria-label={`Статус ${p.sku}`} value={p.status} disabled><option value="ON_SALE">В продаже</option><option value="OFF_SALE">Выведено из продажи</option></EosSelect></td></tr>)}</tbody></table></div>
        {items.length === 0 && <div className="product-state" role="status"><h2>{scenario === 'empty' ? 'Каталог пока пуст' : 'Ничего не найдено'}</h2><p>{scenario === 'empty' ? 'Изделия появятся после согласованного наполнения базы.' : 'Измените запрос или сбросьте фильтры.'}</p></div>}
        <EosPagination offset={offset} total={filtered.length} pageSize={PAGE_SIZE} itemCount={items.length} onPageChange={next => update('page', String(next / PAGE_SIZE + 1))} />
        <p className="muted-text product-footnote">Статусы доступны для просмотра. Изменение ассортимента пока не подключено.</p>
      </>}
    </>}
    {operation && <ManagementDialog operation={operation} product={product} onClose={() => setOperation(null)} />}
  </section></div>
}
