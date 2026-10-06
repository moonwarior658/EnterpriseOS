import { useEffect, useState, type FormEvent } from 'react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { getActionContext } from '../services/actionContext'
import { EosDateField, EosSelect } from '../components/EosFormControls'
import { salesRequest, type Analytics, type Freshness, type Metric, type MetricName, type Metrics, type Point, type Products, type Seller, type Target } from '../services/salesAnalytics'
import { analyticsQuery, metricNumber as fmt, statisticsViews, SALES_FULL_ROLES } from './salesAnalyticsLogic'
import './StatisticsPage.css'

const labels: Record<string, string> = { overview: 'Обзор', points: 'Точки', sellers: 'Продавцы', products: 'Продукция', me: 'Мои показатели' }
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
function Trend({ rows, title = 'Динамика выручки' }: { rows: { date: string; value: number }[]; title?: string }) {
  const low = Math.min(0, ...rows.map((r) => r.value)), high = Math.max(1, ...rows.map((r) => r.value))
  const points = rows.map((r, i) => `${rows.length === 1 ? 300 : i * 600 / (rows.length - 1)},${155 - (r.value - low) / (high - low) * 140}`).join(' ')
  return <section className="page-panel statistics-panel"><h2>{title}</h2>{rows.length ? <>
    <svg className="statistics-chart" viewBox="-5 0 610 170" role="img" aria-label={`${title}: ${rows.length} дней. Точные значения в таблице ниже`}><line x1="0" x2="600" y1="155" y2="155" stroke="#ded8d1" /><polyline points={points} />{rows.length === 1 && <circle cx="300" cy={155 - (rows[0].value - low) / (high - low) * 140} r="4" fill="currentColor" />}</svg>
    <div className="statistics-title-row statistics-muted"><span>{dateLabel(rows[0].date)}</span><span>Максимум: {fmt(high)}</span><span>{dateLabel(rows[rows.length - 1].date)}</span></div>
    <details><summary>Значения по дням</summary><div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Дата</th><th>Значение</th></tr></thead><tbody>{rows.map((r) => <tr key={r.date}><td>{dateLabel(r.date)}</td><td>{fmt(r.value)}</td></tr>)}</tbody></table></div></details>
  </> : <p className="statistics-muted">За выбранный период нет данных</p>}</section>
}
function TargetEditor({ onSaved }: { onSaved: () => void }) {
  const [targets, setTargets] = useState<Target[]>([])
  const [metric, setMetric] = useState<MetricName>('average_check')
  const [month, setMonth] = useState('')
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => { salesRequest<Target[]>('targets').then(setTargets).catch((e: Error) => setMessage(e.message)) }, [])
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
  return <details className="page-panel statistics-panel"><summary>Цели сети и история изменений</summary><form className="statistics-target-form" onSubmit={save}>
    <label>Показатель<EosSelect value={metric} onChange={(e) => setMetric(e.target.value as MetricName)} disabled={busy}>{['average_check', 'fullness', 'revenue'].map((n) => <option key={n} value={n}>{metricLabels[n as MetricName]}</option>)}</EosSelect></label>
    <label>Месяц<input type="month" required value={month} onChange={(e) => setMonth(e.target.value)} disabled={busy} /></label>
    <label>Цель<input type="number" min="0.000001" step="0.000001" required value={value} onChange={(e) => setValue(e.target.value)} disabled={busy} /></label>
    <button className="primary-action" disabled={busy}>{busy ? 'Сохраняем…' : 'Сохранить новую редакцию'}</button>
  </form>{message && <p role="status">{message}</p>}<div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Показатель</th><th>Месяц</th><th>Цель</th><th>Редакция</th><th>Изменено</th></tr></thead><tbody>{[...targets].reverse().map((t) => <tr key={`${t.metric}-${t.month}-${t.revision}`}><td>{metricLabels[t.metric]}</td><td>{t.month.slice(0, 7)}</td><td>{fmt(t.value, isMoney(t.metric))}</td><td>{t.revision}</td><td>{new Date(t.created_at).toLocaleString('ru-RU')}</td></tr>)}</tbody></table></div></details>
}

type Data = { key: string; status: Freshness; analytics?: Analytics; points: Point[]; sellers: Seller[]; products?: Products }
function StatisticsContent({ roles, userId }: { roles: string[]; userId: number }) {
  const { view = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const views = statisticsViews(roles)
  const viewAllowed = views.includes(view)
  const full = roles.some((r) => SALES_FULL_ROLES.includes(r))
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [sort, setSort] = useState('revenue')
  const [trendMetric, setTrendMetric] = useState<MetricName>('revenue')
  const queryKey = params.toString()
  const key = `${userId}:${roles.join(',')}:${view}:${queryKey}`
  useEffect(() => {
    if (!viewAllowed) return
    const controller = new AbortController()
    const query = (endpoint: string) => {
      const selection = new URLSearchParams(queryKey)
      if (endpoint === 'sellers') selection.delete('employee_id')
      return analyticsQuery(selection, endpoint)
    }
    let running = false
    async function load() {
      if (running) return
      running = true
      try {
        const status = await salesRequest<Freshness>('status', '', controller.signal)
        const [analytics, points, sellers, products] = await Promise.all([
          view === 'me' ? salesRequest<Analytics>('me', query('me'), controller.signal) : full && view !== 'products' ? salesRequest<Analytics>('overview', query('overview'), controller.signal) : Promise.resolve(undefined),
          full && view !== 'me' ? salesRequest<Point[]>('points', query('points'), controller.signal) : Promise.resolve([]),
          full && view !== 'me' && view !== 'products' ? salesRequest<Seller[]>('sellers', query('sellers'), controller.signal) : Promise.resolve([]),
          view !== 'me' && (view === 'products' || (full && !new URLSearchParams(queryKey).get('employee_id'))) ? salesRequest<Products>('products', query('products'), controller.signal) : Promise.resolve(undefined),
        ])
        if (!controller.signal.aborted) { setData({ key, status, analytics, points, sellers, products }); setError(null) }
      } catch (e) { if (!controller.signal.aborted) setError({ key, message: e instanceof Error ? e.message : 'Не удалось загрузить статистику' }) }
      finally { running = false }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 60_000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [key, queryKey, full, view, viewAllowed, refresh]) // role and user identity are part of key
  if (!views.includes(view)) return views.length ? <Navigate to={`/statistics/${views[0]}?${params}`} replace /> : <p>Нет доступа к статистике</p>
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
  const period = current?.analytics?.period || current?.products?.period
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
  return <div className="statistics-page">
    <header className="statistics-header"><div><p className="eyebrow">ПРОДАЖИ</p><h1>Статистика</h1></div><div className="statistics-muted" role="status">{current ? `Обновлено: ${current.status.last_success_at ? new Date(current.status.last_success_at).toLocaleString('ru-RU', { timeZone: current.status.source_timezone }) : 'ещё не обновлялось'}` : error?.key === key ? 'Статистика недоступна' : 'Загружаем статистику…'}</div></header>
    <nav className="statistics-tabs" aria-label="Разделы статистики">{views.map((v) => <Link key={v} to={link(v)} aria-current={view === v ? 'page' : undefined}>{labels[v]}</Link>)}</nav>
    <section className="page-panel statistics-panel statistics-filters" aria-label="Фильтры статистики">
      <label>Период<EosSelect value={params.get('period') || 'month'} onChange={(e) => change({ period: e.target.value, anchor: '', start: e.target.value === 'custom' ? current?.status.today || '' : '', end: e.target.value === 'custom' ? current?.status.today || '' : '' })}><option value="week">Неделя</option><option value="month">Месяц</option><option value="custom">Произвольный</option></EosSelect></label>
      {(params.get('period') === 'custom' ? ['start', 'end'] : ['anchor']).map((name) => <EosDateField key={name} label={name === 'start' ? 'С' : name === 'end' ? 'По' : 'Дата в периоде'} value={params.get(name) || ''} min={current?.status.history_from} max={current?.status.today} onChange={(e) => change({ [name]: e.target.value })} />)}
      {view !== 'me' && <label>Точка<EosSelect value={department} onChange={(e) => change({ department_id: e.target.value, employee_id: '' })}><option value="">Все точки</option>{pointOptions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</EosSelect></label>}
      {full && ['overview', 'points', 'sellers'].includes(view) && <><label>Статус продавцов<EosSelect value={params.get('staff') || 'active'} onChange={(e) => change({ staff: e.target.value, employee_id: '' })}><option value="active">Активные</option><option value="dismissed">Уволенные</option><option value="all">Все</option></EosSelect></label><label>Продавец<EosSelect value={employee} onChange={(e) => change({ employee_id: e.target.value })}><option value="">Все продавцы</option>{current?.sellers.map((s) => <option key={s.employee_id} value={s.employee_id}>{s.employee_name}</option>)}</EosSelect></label></>}
      {view === 'products' && <label>Категория<EosSelect value={category} onChange={(e) => change({ category: e.target.value, iiko_product_id: '' })}><option value="">Все категории</option>{categories.map((c) => <option key={c}>{c}</option>)}</EosSelect></label>}
      <button className="secondary-action" type="button" onClick={() => setRefresh((n) => n + 1)}>Обновить</button>
      <button className="secondary-action" type="button" onClick={() => setParams({ period: params.get('period') || 'month', ...(params.get('anchor') ? { anchor: params.get('anchor')! } : {}), ...(params.get('period') === 'custom' ? { start: params.get('start') || '', end: params.get('end') || '' } : {}) })}>Сбросить фильтры</button>
    </section>
    {error?.key === key && <p className="statistics-warning" role="alert">{error.message}{current ? '. Показаны последние загруженные данные' : ''}</p>}
    {current?.status.update_failed && <p className="statistics-warning" role="status">Последнее обновление продаж не выполнено. Показаны данные последней успешной синхронизации.</p>}
    {current?.status.stale && <p className="statistics-warning" role="status">Данные устарели: успешного обновления не было более 30 минут или синхронизация ещё не выполнялась.</p>}
    {period && <p className="statistics-muted">{dateLabel(period.start)} — {dateLabel(period.end)} · Сравнение: {dateLabel(period.previous_start)} — {dateLabel(period.previous_end)}</p>}
    {current?.analytics && <><MetricCards metrics={current.analytics.metrics} personal={view === 'me'} />
      {current.analytics.target_segments.length > 1 && <details className="page-panel statistics-panel"><summary>Цели и фактические показатели по месяцам</summary>{current.analytics.target_segments.map((s) => <div key={s.start}><p>{dateLabel(s.start)} — {dateLabel(s.end)}</p><MetricCards metrics={s.metrics} personal={view === 'me'} /></div>)}</details>}
      <label className="statistics-title-row">Динамика показателя<EosSelect value={trendMetric} onChange={(e) => setTrendMetric(e.target.value as MetricName)}>{names.map((n) => <option key={n} value={n}>{metricLabels[n]}</option>)}</EosSelect></label>
      <Trend title={`Динамика: ${metricLabels[trendMetric]}`} rows={current.analytics.dynamics.filter((r) => r.metrics[trendMetric].fact !== null).map((r) => ({ date: r.date, value: Number(r.metrics[trendMetric].fact) }))} />
    </>}
    {current && full && ['overview', 'points'].includes(view) && !employee && <section className="page-panel statistics-panel"><h2>Точки</h2><div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Точка</th>{names.map((n) => <th key={n}>{metricLabels[n]}</th>)}</tr></thead><tbody>{current.points.filter((p) => !department || p.department_id === department).map((p) => <tr key={p.department_id}><td><Link to={link('points', { department_id: p.department_id, employee_id: '' })}>{p.department_name}</Link></td>{names.map((n) => <td key={n}>{fmt(p.metrics[n].fact, isMoney(n))}</td>)}</tr>)}</tbody></table></div>{!current.points.length && <p>Нет продаж по точкам за выбранный период</p>}</section>}
    {current && full && ['overview', 'points', 'sellers'].includes(view) && <section className="page-panel statistics-panel"><div className="statistics-title-row"><h2>Продавцы</h2><label>Сортировка<EosSelect value={sort} onChange={(e) => setSort(e.target.value)}>{names.map((n) => <option key={n} value={n}>{metricLabels[n]}</option>)}<option value="average_check_completion">Выполнение среднего чека</option><option value="fullness_completion">Выполнение наполняемости</option></EosSelect></label></div><div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Продавец</th>{names.map((n) => <th key={n}>{metricLabels[n]}</th>)}<th>Цель среднего чека</th><th>Цель наполняемости</th></tr></thead><tbody>{sellerRows.map((s) => <tr key={s.employee_id}><td><Link to={link('sellers', { employee_id: s.employee_id })}>{s.employee_name}</Link>{s.employee_status === 'DISMISSED' && <span className="statistics-muted"> · Уволен</span>}</td>{names.map((n) => <td key={n}>{fmt(s.metrics[n].fact, isMoney(n))}</td>)}<td><Status metric={s.metrics.average_check} /></td><td><Status metric={s.metrics.fullness} /></td></tr>)}</tbody></table></div>{!sellerRows.length && <p>Нет продаж сотрудников по выбранным фильтрам</p>}</section>}
    {current?.products && <section className="page-panel statistics-panel"><h2>Продукция{selectedProduct ? ` · ${filteredProducts[0]?.product_name || 'Без названия'}` : ''}</h2>
      {selectedProduct && <Link to={link('products', { iiko_product_id: '' })}>← Все позиции</Link>}
      {view !== 'products' && <Link to={link('products', { employee_id: '' })}>Открыть продукцию и категории →</Link>}
      {!selectedProduct && <div className="statistics-tabs">{categories.map((c) => <Link key={c} to={link('products', { category: c, iiko_product_id: '', employee_id: '' })}>{c}</Link>)}</div>}
      <div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>{selectedProduct ? 'Точка' : 'Позиция'}</th><th>Категория</th><th>Количество</th><th>Выручка</th><th>Пред. количество</th><th>Пред. выручка</th>{selectedProduct && <th>Чеки с позицией</th>}</tr></thead><tbody>{(selectedProduct ? filteredProducts : groupedProducts).map((p) => {
        return <tr key={`${p.iiko_product_id}-${selectedProduct ? p.department_id : ''}`}><td>{selectedProduct ? full ? <Link to={link('points', { department_id: p.department_id, employee_id: '', iiko_product_id: '', category: '' })}>{p.department_name || 'Без названия'}</Link> : <button type="button" className="statistics-link" onClick={() => change({ department_id: p.department_id })}>{p.department_name || 'Без названия'}</button> : <Link to={link('products', { iiko_product_id: p.iiko_product_id, employee_id: '' })}>{p.product_name || 'Без названия'}</Link>}</td><td>{p.category || 'Без категории'}</td><td>{fmt(p.quantity)}</td><td>{fmt(p.revenue, true)}</td><td>{fmt(p.previous_quantity)}</td><td>{fmt(p.previous_revenue, true)}</td>{selectedProduct && <td>{p.check_count}</td>}</tr>
      })}</tbody></table></div>{!filteredProducts.length && <p>Нет продаж продукции по выбранным фильтрам</p>}
    </section>}
    {view === 'products' && current?.products && <Trend rows={current.products.dynamics.map((r) => ({ date: r.date, value: Number(r.revenue) }))} title="Динамика продаж продукции · выручка" />}
    {view === 'overview' && roles.includes('DEPUTY_DIRECTOR') && <TargetEditor onSaved={() => setRefresh((n) => n + 1)} />}
  </div>
}
export default function StatisticsPage() {
  const { user } = useAuth()
  const [access, setAccess] = useState<{ userId: number; roles: string[] } | null>(null)
  useEffect(() => { let active = true; if (user) getActionContext().then((c) => { if (active) setAccess({ userId: user.id, roles: c.roles }) }).catch(() => { if (active) setAccess({ userId: user.id, roles: [] }) }); return () => { active = false } }, [user])
  if (!user || access?.userId !== user.id) return <p role="status">Проверяем доступ к статистике…</p>
  return <StatisticsContent key={user.id} userId={user.id} roles={access.roles} />
}
