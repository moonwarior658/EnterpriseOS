import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { getActionContext } from '../services/actionContext'
import { EosDateField, EosSelect } from '../components/EosFormControls'
import SalesTrendChart from './SalesTrendChart'
import SalesReportsPage from './SalesReportsPage'
import SalesControlMenu from '../components/SalesControlMenu'
import SalesExportButtons from '../components/SalesExportButtons'
import { salesReportScope, salesExportAllowed, salesExportQuery } from './salesReportsLogic'
import { salesRequest, type Completeness, type Analytics, type Freshness, type Metric, type MetricName, type Metrics, type Point, type Products, type Seller, type Target } from '../services/salesAnalytics'
import { workspaceQuery, metricNumber as fmt, statisticsViews, SALES_FULL_ROLES, sortSalesProducts, salesPeriodOptions, salesPeriodAnchor, type ProductSortKey } from './salesAnalyticsLogic'
import './StatisticsPage.css'

const labels: Record<string, string> = { overview: 'Обзор', points: 'Точки', sellers: 'Продавцы', 'seller-products': 'Продавец → Продукция', 'me-products': 'Моя продукция', products: 'Продукция', me: 'Мои показатели' }
const metricLabels: Record<MetricName, string> = { revenue: 'Выручка', check_count: 'Количество чеков', average_check: 'Средний чек', fullness: 'Наполняемость' }
const statusLabels = { green: 'Цель выполнена', warning: 'Небольшое отставание', red: 'Ниже 85% цели', no_target: 'Цель не задана', no_data: 'Нет чеков', mixed_targets: 'Разные цели по месяцам' }
const names: MetricName[] = ['revenue', 'check_count', 'average_check', 'fullness']
const isMoney = (name: MetricName) => name === 'revenue' || name === 'average_check'
const dateLabel = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString('ru-RU')
function Status({ metric }: { metric: Metric }) {
  return <span className={`statistics-status ${metric.status}`}>{statusLabels[metric.status]}{metric.completion_percent !== null ? ` · ${fmt(metric.completion_percent)}%` : ''}</span>
}
function MetricCards({ metrics, personal = false }: { metrics: Metrics; personal?: boolean }) {
  return <div className="statistics-cards">{(personal ? ['average_check', 'fullness', 'revenue', 'check_count'] as MetricName[] : names).map((name) => {
    const metric = metrics[name]
    return <section className="statistics-card" key={name}>
      <span className="statistics-muted">{personal && name === 'revenue' ? 'Лично продано' : metricLabels[name]}</span>
      <strong>{fmt(metric.fact, isMoney(name))}</strong>
      {(name === 'average_check' || name === 'fullness' || metric.target !== null) && <><span>Цель: {fmt(metric.target, isMoney(name))}</span><Status metric={metric} /></>}
      <p className="statistics-muted">Предыдущий период: {fmt(metric.previous, isMoney(name))}</p>
      <p className="statistics-muted">Изменение: {metric.change !== null && Number(metric.change) > 0 ? '+' : ''}{fmt(metric.change, isMoney(name))} · {fmt(metric.change_percent)}%</p>
    </section>
  })}</div>
}
function TargetEditor({ onSaved, canEdit }: { onSaved: () => void; canEdit: boolean }) {
  const [targets, setTargets] = useState<Target[]>([])
  const [open, setOpen] = useState(false)
  const [metric, setMetric] = useState<MetricName>('average_check')
  const [month, setMonth] = useState('')
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      salesRequest<Target[]>('targets', '', controller.signal).then((rows) => {
        if (!controller.signal.aborted) setTargets(rows)
      }).catch((e: Error) => { if (!controller.signal.aborted) setMessage(e.message) })
    }, 150)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [open])
  async function save(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setMessage('')
    try {
      const revisions = targets.filter((t) => t.month === `${month}-01` && t.metric === metric)
      await salesRequest<Target>('targets', '', undefined, { metric, month: `${month}-01`, value, expected_revision: Math.max(0, ...revisions.map((t) => t.revision)) })
      setTargets(await salesRequest<Target[]>('targets')); setMessage('Цель сохранена'); onSaved()
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Не удалось сохранить цель'); salesRequest<Target[]>('targets').then(setTargets).catch(() => {}) }
    finally { setBusy(false) }
  }
  return <details className="page-panel statistics-panel statistics-targets" onToggle={event => setOpen(event.currentTarget.open)}><summary>Цели и план сети <span className="statistics-muted">Средний чек · наполняемость · месячная выручка</span></summary><p className="statistics-muted">Изменять цели может только заместитель директора. Новая редакция сохраняется в истории.</p>{canEdit && <form className="statistics-target-form" onSubmit={save}>
    <label>Показатель<EosSelect value={metric} onChange={(e) => setMetric(e.target.value as MetricName)} disabled={busy}>{['average_check', 'fullness', 'revenue'].map((n) => <option key={n} value={n}>{n === 'revenue' ? 'Месячный план выручки' : metricLabels[n as MetricName]}</option>)}</EosSelect></label>
    <label className="eos-field">Месяц<input type="month" required value={month} onChange={(e) => setMonth(e.target.value)} disabled={busy} /></label>
    <label className="eos-field">Цель<input type="number" min="0.000001" step="0.000001" required value={value} onChange={(e) => setValue(e.target.value)} disabled={busy} /></label>
    <button className="primary-action" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить новую редакцию'}</button>
  </form>}{message && <p role="status">{message}</p>}<div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Показатель</th><th>Месяц</th><th>Цель</th><th>Редакция</th><th>Изменено</th></tr></thead><tbody>{[...targets].reverse().map((t) => <tr key={`${t.metric}-${t.month}-${t.revision}`}><td>{metricLabels[t.metric]}</td><td>{t.month.slice(0, 7)}</td><td>{fmt(t.value, isMoney(t.metric))}</td><td>{t.revision}</td><td>{new Date(t.created_at).toLocaleString('ru-RU')}</td></tr>)}</tbody></table></div></details>
}

type Data = { seller_mix?: import('../services/salesAnalytics').SellerMix | null; key: string; completeness: Completeness; status: Freshness; analytics?: Analytics; points: Point[]; sellers: Seller[]; products?: Products }
function StatisticsContent({ roles, userId }: { roles: string[]; userId: number }) {
  const { view = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const views = statisticsViews(roles)
  const viewAllowed = views.includes(view) || (view === 'seller-products' && roles.some(r => SALES_FULL_ROLES.includes(r))) || (view === 'me-products' && roles.includes('SELLER'))
  const full = roles.some((r) => SALES_FULL_ROLES.includes(r))
  const [busyKey, setBusyKey] = useState('')
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [sort, setSort] = useState('revenue')
  const [productSort, setProductSort] = useState<{ key: ProductSortKey; direction: 'asc' | 'desc' } | null>(null)
  const [trendMetric, setTrendMetric] = useState<MetricName>('revenue')
  const queryKey = params.toString()
  const key = `${userId}:${roles.join(',')}:${view}:${queryKey}`
  useEffect(() => {
    if (!viewAllowed) return
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running || document.hidden) return
      running = true
      setBusyKey(key)
      try {
        const result = await salesRequest<Omit<Data, 'key'>>('workspace', workspaceQuery(new URLSearchParams(queryKey), view), controller.signal)
        if (!controller.signal.aborted) { setData({ ...result, key }); setError(null) }
      } catch (e) { if (!controller.signal.aborted) setError({ key, message: e instanceof Error ? e.message : 'Не удалось загрузить статистику' }) }
      finally { running = false; if (!controller.signal.aborted) setBusyKey('') }
    }
    const initial = window.setTimeout(() => { void load() }, 150)
    const timer = window.setInterval(() => { void load() }, 60_000)
    const visible = () => { if (!document.hidden) void load() }
    document.addEventListener('visibilitychange', visible)
    return () => { controller.abort(); window.clearTimeout(initial); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [key, queryKey, full, view, viewAllowed, refresh]) // role and user identity are part of key
  if (!viewAllowed) return views.length ? <Navigate to={`/statistics/${views[0]}?${params}`} replace /> : <p>Нет доступа к статистике</p>
  const current = data?.key === key ? data : null
  function change(changes: Record<string, string>) {
    const next = new URLSearchParams(params)
    for (const [name, value] of Object.entries(changes)) { if (value) next.set(name, value); else next.delete(name) }
    setParams(next)
  }
  function link(nextView: string, changes: Record<string, string> = {}) {
    const next = new URLSearchParams(params)
    for (const [name, value] of Object.entries(changes)) { if (value) next.set(name, value); else next.delete(name) }
    return `/statistics/${nextView}?${next}`
  }
  const period = current?.analytics?.period || current?.products?.period || current?.seller_mix?.period
  const department = params.get('department_id') || '', employee = params.get('employee_id') || ''
  const productRows = current?.products?.products || []
  const pointOptions = current?.points.length ? current.points.map((p) => ({ id: p.department_id, name: p.department_name })) : [...new Map(productRows.map((p) => [p.department_id, { id: p.department_id, name: p.department_name || 'Без названия' }])).values()]
  const sellerRows = [...(current?.sellers || [])].filter((s) => !employee || s.employee_id === employee).sort((a, b) => {
    const name = sort.replace('_completion', '') as MetricName
    const value = (s: Seller) => sort.endsWith('_completion') ? s.metrics[name].completion_percent : s.metrics[name].fact
    return (value(b) === null ? -Infinity : Number(value(b))) - (value(a) === null ? -Infinity : Number(value(a))) || a.employee_name.localeCompare(b.employee_name)
  })
  const categories = current?.products?.categories || []
  const category = params.get('category') || ''
  const selectedProduct = params.get('iiko_product_id') || ''
  const filteredProducts = productRows.filter((p) => !category || (p.category || 'Без категории') === category)
  const groupedProducts = current?.products?.summaries || []
  const periodKind = params.get('period') || 'month'
  const pickerKind = periodKind === 'week' ? 'week' : 'month'
  const pickerOptions = salesPeriodOptions(pickerKind, data?.status.history_from || '', data?.status.today || '')
  const pickerValue = salesPeriodAnchor(pickerKind, params.get('anchor') || data?.status.today || '')
  const sortableRows = selectedProduct ? filteredProducts : groupedProducts
  const sortedProducts = productSort ? sortSalesProducts(sortableRows, productSort.key, productSort.direction) : sortableRows
  const productColumns: { key: ProductSortKey; label: string }[] = [
    { key: selectedProduct ? 'department_name' : 'product_name', label: selectedProduct ? 'Точка' : 'Позиция' },
    { key: 'category', label: 'Категория' }, { key: 'quantity', label: 'Количество' },
    { key: 'revenue', label: 'Выручка' }, { key: 'previous_quantity', label: 'Пред. количество' },
    { key: 'previous_revenue', label: 'Пред. выручка' },
  ]
  const sellerSortOptions = [...names.map(n => ({ value: n, label: metricLabels[n] })),
    { value: 'average_check_completion', label: 'Выполнение среднего чека' }, { value: 'fullness_completion', label: 'Выполнение наполняемости' }]

  return <div className="page-shell statistics-page">
    <header className="statistics-header"><div><p className="eyebrow">ПРОДАЖИ</p><h1>Статистика</h1></div><div className="statistics-muted" role="status">{current ? `Обновлено: ${current.status.last_success_at ? new Date(current.status.last_success_at).toLocaleString('ru-RU', { timeZone: current.status.source_timezone }) : 'ещё не обновлялось'}` : error?.key === key ? 'Статистика недоступна' : 'Загружаем статистику…'}</div></header>
    <nav className="statistics-tabs" aria-label="Разделы статистики">{views.map((v) => <Link key={v} to={link(v)} aria-current={view === v ? 'page' : undefined}>{labels[v]}</Link>)}{salesReportScope(roles) && <Link to="/statistics/reports">Отчёты</Link>}</nav>
    <section className="page-panel statistics-panel statistics-filters" aria-label="Фильтры статистики">
      <label>Период<EosSelect value={params.get('period') || 'month'} onChange={(e) => change({ period: e.target.value, anchor: '', start: e.target.value === 'custom' ? current?.status.today || '' : '', end: e.target.value === 'custom' ? current?.status.today || '' : '' })}><option value="week">Неделя</option><option value="month">Месяц</option><option value="custom">Произвольный</option></EosSelect></label>
      {periodKind === 'custom' ? ['start', 'end'].map(name => <EosDateField key={name} label={name === 'start' ? 'С' : 'По'} value={params.get(name) || ''} min={current?.status.history_from} max={current?.status.today} onChange={e => change({ [name]: e.target.value })} />)
        : <label>{pickerKind === 'month' ? 'Месяц' : 'Неделя'}<EosSelect value={pickerValue} disabled={!data} onChange={e => change({ anchor: e.target.value })}>
          {!pickerOptions.some(option => option.value === pickerValue) && <option value={pickerValue}>{period ? `${dateLabel(period.start)} — ${dateLabel(period.end)}` : 'Загружаем периоды…'}</option>}
          {pickerOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </EosSelect></label>}
      {!['me', 'me-products'].includes(view) && <label>Точка<EosSelect value={department} onChange={(e) => change({ department_id: e.target.value, ...(view === 'seller-products' ? {} : { employee_id: '' }) })}><option value="">Все точки</option>{pointOptions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</EosSelect></label>}
      {full && ['overview', 'points', 'sellers'].includes(view) && <><label>Статус продавцов<EosSelect value={params.get('staff') || 'active'} onChange={(e) => change({ staff: e.target.value, employee_id: '' })}><option value="active">Активные</option><option value="dismissed">Уволенные</option><option value="all">Все</option></EosSelect></label><label>Продавец<EosSelect value={employee} onChange={(e) => change({ employee_id: e.target.value })}><option value="">Все продавцы</option>{current?.sellers.map((s) => <option key={s.employee_id} value={s.employee_id}>{s.employee_name}</option>)}</EosSelect></label></>}
      {view === 'products' && <label>Категория<EosSelect value={category} onChange={(e) => change({ category: e.target.value, iiko_product_id: '' })}><option value="">Все категории</option>{categories.map((c) => <option key={c}>{c}</option>)}</EosSelect></label>}
      <button className="secondary-action" type="button" disabled={busyKey === key} onClick={() => setRefresh((n) => n + 1)}>Обновить</button>
      <button className="secondary-action" type="button" onClick={() => setParams({ ...(view === 'seller-products' ? { employee_id: employee, ...(params.get('staff') ? { staff: params.get('staff')! } : {}) } : {}), period: params.get('period') || 'month', ...(params.get('anchor') ? { anchor: params.get('anchor')! } : {}), ...(params.get('period') === 'custom' ? { start: params.get('start') || '', end: params.get('end') || '' } : {}) })}>Сбросить фильтры</button>
      {salesExportAllowed(roles, view) && <SalesExportButtons key={key} endpoint="export" query={format => salesExportQuery(params, view, format)} />}
    </section>
    {error?.key === key && <p className="statistics-warning" role="alert">{error.message}{current ? '. Показаны последние загруженные данные' : ''}</p>}
    {current?.completeness.warning && <div className="statistics-warning" role="status">
      {!current.completeness.current.complete && <p>Данные выбранного периода неполные: загружено {current.completeness.current.loaded_days} из {current.completeness.current.expected_days} дней. История догружается в фоне.</p>}
      {!current.completeness.previous.complete && <p>Предыдущий период неполный: загружено {current.completeness.previous.loaded_days} из {current.completeness.previous.expected_days} дней. Сравнение предварительное.</p>}
    </div>}
    {current?.status.update_failed && <p className="statistics-warning" role="status">Последнее обновление продаж не выполнено. Показаны данные последней успешной синхронизации.</p>}
    {current?.status.stale && <p className="statistics-warning" role="status">Данные устарели: успешного обновления не было более 30 минут или синхронизация ещё не выполнялась.</p>}
    {period && <p className="statistics-muted">{dateLabel(period.start)} — {dateLabel(period.end)} · Сравнение: {dateLabel(period.previous_start)} — {dateLabel(period.previous_end)}</p>}
    {full && <TargetEditor canEdit={roles.includes('DEPUTY_DIRECTOR')} onSaved={() => setRefresh((n) => n + 1)} />}
    {current?.analytics && <><MetricCards metrics={current.analytics.metrics} personal={view === 'me'} />
      {current.analytics.target_segments.length > 1 && <details className="page-panel statistics-panel"><summary>Цели и фактические показатели по месяцам</summary>{current.analytics.target_segments.map((s) => <div key={s.start}><p>{dateLabel(s.start)} — {dateLabel(s.end)}</p><MetricCards metrics={s.metrics} personal={view === 'me'} /></div>)}</details>}
      <label className="statistics-title-row">Динамика показателя<EosSelect value={trendMetric} onChange={(e) => setTrendMetric(e.target.value as MetricName)}>{names.map((n) => <option key={n} value={n}>{metricLabels[n]}</option>)}</EosSelect></label>
      <SalesTrendChart through={current.status.today} money={isMoney(trendMetric)} title={`Динамика: ${metricLabels[trendMetric]}`} rows={current.analytics.dynamics.map((r) => ({ date: r.date, value: r.metrics[trendMetric].fact === null ? null : Number(r.metrics[trendMetric].fact) }))} />
    </>}
    {current && full && ['overview', 'points'].includes(view) && !employee && <section className="page-panel statistics-panel"><h2>Точки</h2><div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Точка</th>{names.map((n) => <th key={n}>{metricLabels[n]}</th>)}</tr></thead><tbody>{current.points.filter((p) => !department || p.department_id === department).map((p) => <tr key={p.department_id}><td><Link to={link('points', { department_id: p.department_id, employee_id: '' })}>{p.department_name}</Link></td>{names.map((n) => <td key={n}>{fmt(p.metrics[n].fact, isMoney(n))}</td>)}</tr>)}</tbody></table></div>{!current.points.length && <p>Нет продаж по точкам за выбранный период</p>}</section>}
    {current && full && ['overview', 'points', 'sellers'].includes(view) && <section className="page-panel statistics-panel"><div className="statistics-title-row"><h2>Продавцы</h2><SalesControlMenu label={`Сортировка: ${sellerSortOptions.find(option => option.value === sort)?.label}`} items={sellerSortOptions.map(option => ({ label: option.label, selected: sort === option.value, onSelect: () => setSort(option.value) }))} /></div><div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Продавец</th>{names.map((n) => <th key={n}>{metricLabels[n]}</th>)}<th>Цель среднего чека</th><th>Цель наполняемости</th></tr></thead><tbody>{sellerRows.map((s) => <tr key={s.employee_id}><td><Link to={link('sellers', { employee_id: s.employee_id })}>{s.employee_name}</Link> · <Link to={link('seller-products', { employee_id: s.employee_id })}>Продукция</Link>{s.employee_status === 'DISMISSED' && <span className="statistics-muted"> · Уволен</span>}</td>{names.map((n) => <td key={n}>{fmt(s.metrics[n].fact, isMoney(n))}</td>)}<td><Status metric={s.metrics.average_check} /></td><td><Status metric={s.metrics.fullness} /></td></tr>)}</tbody></table></div>{!sellerRows.length && <p>Нет продаж сотрудников по выбранным фильтрам</p>}</section>}
    {view === 'me' && <Link to={link('me-products')}>Моя продукция →</Link>}
    {current?.seller_mix && <section className="page-panel statistics-panel"><h2>{current.seller_mix.employee_name || 'Продавец'} → Продукция</h2>
      <Link to={link(view === 'me-products' ? 'me' : 'sellers', { iiko_product_id: '', category: '' })}>← К показателям продавца</Link>
      <label className="eos-field">Категория<EosSelect value={category} onChange={e => change({ category: e.target.value, iiko_product_id: '' })}><option value="">Все категории</option>{current.seller_mix.categories.map(c => <option key={c}>{c}</option>)}</EosSelect></label>
      {params.get('iiko_product_id') && <Link to={link(view, { iiko_product_id: '' })}>← Все позиции</Link>}
      <div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Позиция</th><th>Категория</th><th>Количество</th><th>Выручка</th><th>Доля, %</th><th>Предыдущее количество</th><th>Предыдущая выручка</th><th>Изменение количества</th><th>Изменение выручки</th></tr></thead><tbody>{current.seller_mix.products.map(p => <tr key={p.iiko_product_id}><td><Link to={link(view, { iiko_product_id: p.iiko_product_id })}>{p.product_name || 'Без названия'}</Link></td><td>{p.category || 'Без категории'}</td><td>{fmt(p.quantity)}</td><td>{fmt(p.revenue, true)}</td><td>{fmt(p.share_percent)}</td><td>{fmt(p.previous_quantity)}</td><td>{fmt(p.previous_revenue, true)}</td><td>{fmt(p.quantity_change)}</td><td>{fmt(p.revenue_change, true)}</td></tr>)}</tbody></table></div>
      {!current.seller_mix.products.length && <p>Нет атрибутированных продаж продукции за выбранный период</p>}
      <SalesTrendChart through={current.status.today} money rows={current.seller_mix.dynamics.map(r => ({ date: r.date, value: r.revenue === null ? null : Number(r.revenue) }))} />
    </section>}
    {current?.products && <section className="page-panel statistics-panel"><h2>Продукция{selectedProduct ? ` · ${filteredProducts[0]?.product_name || 'Без названия'}` : ''}</h2>
      {selectedProduct && <Link to={link('products', { iiko_product_id: '' })}>← Все позиции</Link>}
      <div className="statistics-table-wrap"><table className="statistics-table"><thead><tr>{productColumns.map(column => <th key={column.key} aria-sort={productSort?.key === column.key ? productSort.direction === 'asc' ? 'ascending' : 'descending' : 'none'}><button type="button" className="statistics-sort-heading" onClick={() => setProductSort(previous => ({ key: column.key, direction: previous?.key === column.key && previous.direction === 'asc' ? 'desc' : 'asc' }))}>{column.label} <span aria-hidden="true">{productSort?.key === column.key ? productSort.direction === 'asc' ? '↑' : '↓' : '↕'}</span></button></th>)}{selectedProduct && <th>Чеки с позицией</th>}</tr></thead><tbody>{sortedProducts.map((p) => {
        return <tr key={`${p.iiko_product_id}-${selectedProduct ? p.department_id : ''}`}><td>{selectedProduct ? full ? <Link to={link('points', { department_id: p.department_id, employee_id: '', iiko_product_id: '', category: '' })}>{p.department_name || 'Без названия'}</Link> : <button type="button" className="statistics-link" onClick={() => change({ department_id: p.department_id })}>{p.department_name || 'Без названия'}</button> : <Link to={link('products', { iiko_product_id: p.iiko_product_id, employee_id: '' })}>{p.product_name || 'Без названия'}</Link>}</td><td>{p.category || 'Без категории'}</td><td>{fmt(p.quantity)}</td><td>{fmt(p.revenue, true)}</td><td>{fmt(p.previous_quantity)}</td><td>{fmt(p.previous_revenue, true)}</td>{selectedProduct && <td>{p.check_count}</td>}</tr>
      })}</tbody></table></div>{!filteredProducts.length && <p>Нет продаж продукции по выбранным фильтрам</p>}
    </section>}
    {view === 'products' && current?.products && <SalesTrendChart through={current.status.today} money rows={current.products.dynamics.map((r) => ({ date: r.date, value: r.revenue === null ? null : Number(r.revenue) }))} title="Динамика продаж продукции · выручка" />}
  </div>
}
export default function StatisticsPage() {
  const { user } = useAuth()
  const { view } = useParams()
  const [access, setAccess] = useState<{ userId: number; roles: string[] } | null>(null)
  useEffect(() => { let active = true; if (user) getActionContext().then((c) => { if (active) setAccess({ userId: user.id, roles: c.roles }) }).catch(() => { if (active) setAccess({ userId: user.id, roles: [] }) }); return () => { active = false } }, [user])
  if (!user || access?.userId !== user.id) return <p role="status">Проверяем доступ к статистике…</p>
  if (view === 'reports') return <SalesReportsPage key={user.id} roles={access.roles} />
  return <StatisticsContent key={user.id} userId={user.id} roles={access.roles} />
}
