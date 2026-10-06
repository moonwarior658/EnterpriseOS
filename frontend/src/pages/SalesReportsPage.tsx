import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { EosSelect } from '../components/EosFormControls'
import SalesExportButtons from '../components/SalesExportButtons'
import { salesRequest, type SalesReport, type SalesReportSummary, type Analytics, type Seller, type Point, type Products, type MetricName } from '../services/salesAnalytics'
import { statisticsViews, metricNumber as fmt } from './salesAnalyticsLogic'
import { salesReportScope } from './salesReportsLogic'
import './StatisticsPage.css'

const labels: Record<MetricName, string> = { revenue: 'Выручка', check_count: 'Чеки', average_check: 'Средний чек', fullness: 'Наполняемость' }
const metricNames = Object.keys(labels) as MetricName[]
function ReportMetrics({ rows }: { rows: (Analytics & { name: string })[] }) {
  return <div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Объект</th><th>Показатель</th><th>Факт</th><th>Цель</th><th>Выполнение</th><th>Пред. период</th><th>Изменение</th></tr></thead><tbody>{rows.flatMap(row => metricNames.map(n => {
    const m = row.metrics[n], money = n === 'revenue' || n === 'average_check'
    return <tr key={`${row.name}:${n}`}><td>{row.name}</td><td>{labels[n]}</td><td>{fmt(m.fact, money)}</td><td>{fmt(m.target, money)}</td><td>{fmt(m.completion_percent)}%</td><td>{fmt(m.previous, money)}</td><td>{fmt(m.change, money)} · {fmt(m.change_percent)}%</td></tr>
  }))}</tbody></table></div>
}
function ReportProducts({ products }: { products: Products }) {
  return <div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Продукция</th><th>Категория</th><th>Точка</th><th>Количество</th><th>Выручка</th><th>Пред. количество</th><th>Пред. выручка</th><th>Чеки</th></tr></thead><tbody>{products.products.map(p => <tr key={`${p.iiko_product_id}:${p.department_id}`}><td>{p.product_name || 'Без названия'}</td><td>{p.category || 'Без категории'}</td><td>{p.department_name || 'Без названия'}</td><td>{fmt(p.quantity)}</td><td>{fmt(p.revenue, true)}</td><td>{fmt(p.previous_quantity)}</td><td>{fmt(p.previous_revenue, true)}</td><td>{p.check_count}</td></tr>)}</tbody></table></div>
}
export function SalesReportContent({ report }: { report: SalesReport }) {
  const data = report.data
  return <>
    <p>Зафиксирован {new Date(report.created_at).toLocaleString('ru-RU')} · {report.start} — {report.end}. Последующие корректировки продаж не меняют этот отчёт.</p>
    {data.analytics && <section className="page-panel statistics-panel"><h2>Сеть · факт / цель</h2><ReportMetrics rows={[{ ...data.analytics, name: 'Сеть' }]} />
      {data.analytics.target_segments.length > 1 && <details><summary>Цели по месяцам</summary>{data.analytics.target_segments.map(s => <ReportMetrics key={s.start} rows={[{ ...data.analytics!, metrics: s.metrics, name: `${s.start} — ${s.end}` }]} />)}</details>}
    </section>}
    {data.points && <section className="page-panel statistics-panel"><h2>Точки</h2><ReportMetrics rows={data.points.map((p: Point) => ({ ...p, name: p.department_name }))} /></section>}
    {data.sellers && <section className="page-panel statistics-panel"><h2>Продавцы · включая уволенных</h2><ReportMetrics rows={data.sellers.map((s: Seller) => ({ ...s, name: s.employee_name }))} /></section>}
    <section className="page-panel statistics-panel"><h2>Продукция</h2><ReportProducts products={data.products} /></section>
    {(['growth', 'decline'] as const).map(k => <section key={k} className="page-panel statistics-panel"><h2>{k === 'growth' ? 'Основной рост продукции' : 'Основные просадки продукции'} · по выручке</h2>
      {data.product_changes[k].length ? data.product_changes[k].map(p => <p key={p.iiko_product_id}>{p.product_name || 'Без названия'}: {fmt(p.previous_revenue, true)} → {fmt(p.revenue, true)} · {fmt(p.revenue_change, true)}</p>) : <p>Нет изменений</p>}
    </section>)}
  </>
}
function Reports({ scope, roles }: { scope: 'full' | 'products'; roles: string[] }) {
  const [params, setParams] = useSearchParams()
  const kind = params.get('kind') === 'month' ? 'month' : 'week'
  const id = params.get('report') || ''
  const key = `${scope}:${kind}:${id}`
  const [result, setResult] = useState<{ key: string; rows: SalesReportSummary[]; report: SalesReport | null } | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState<{ key: string; text: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void Promise.all([salesRequest<SalesReportSummary[]>('reports', `kind=${kind}&scope=${scope}`, controller.signal),
      id ? salesRequest<SalesReport>(`reports/${encodeURIComponent(id)}`, `scope=${scope}`, controller.signal) : Promise.resolve(null)])
      .then(([rows, report]) => { if (!controller.signal.aborted) { setResult({ key, rows, report }); setError(null) } })
      .catch((e: Error) => { if (!controller.signal.aborted) setError({ key, text: e.message }) })
    return () => { controller.abort() }
  }, [id, kind, scope, key, refresh])
  const current = result?.key === key ? result : null
  return <div className="page-shell statistics-page">
    <header className="statistics-header"><div><p className="eyebrow">СТАТИСТИКА</p><h1>{scope === 'products' ? 'Отчёты продукции' : 'Отчёты продаж'}</h1></div><Link className="secondary-action" to={`/statistics/${scope === 'products' ? 'products' : 'overview'}`}>Актуальная статистика</Link></header>
    <nav className="statistics-tabs" aria-label="Разделы статистики">{statisticsViews(roles).map(view => <Link key={view} to={`/statistics/${view}`}>{{ overview: 'Обзор', points: 'Точки', sellers: 'Продавцы', products: 'Продукция', me: 'Мои показатели' }[view]}</Link>)}<Link to="/statistics/reports" aria-current="page">Отчёты</Link></nav>
    <section className="page-panel statistics-panel statistics-filters" aria-label="Фильтры отчётов">
      <label>Период отчёта<EosSelect value={kind} onChange={e => setParams({ kind: e.target.value })}><option value="week">Закрытая неделя</option><option value="month">Закрытый месяц</option></EosSelect></label>
      <button className="secondary-action" onClick={() => setRefresh(n => n + 1)}>Обновить отчёты</button>
      {current?.report && <SalesExportButtons key={key} endpoint={`reports/${current.report.id}/export`} query={format => `scope=${scope}&format=${format}`} />}
    </section>
    {error?.key === key && <p role="alert">{error.text}</p>}
    {!current && error?.key !== key && <p role="status">Загружаем отчёты…</p>}
    {current && <section className="page-panel statistics-panel"><h2>Сохранённые итоги</h2>{current.rows.length ? current.rows.map(r => <p key={r.start}>
      {r.id ? <Link to={`?kind=${kind}&report=${r.id}`}>{r.start} — {r.end}</Link> : <span>{r.start} — {r.end}: {r.reason}. Загружено {r.completeness.current.loaded_days}/{r.completeness.current.expected_days} дней; сравнение {r.completeness.previous.loaded_days}/{r.completeness.previous.expected_days}.</span>}
    </p>) : <p>Пока нет закрытых периодов в доступной истории.</p>}</section>}
    {current?.report && <SalesReportContent report={current.report} />}
  </div>
}
export default function SalesReportsPage({ roles }: { roles: string[] }) {
  const scope = salesReportScope(roles)
  return scope ? <Reports key={`${scope}:${roles.join(',')}`} scope={scope} roles={roles} /> : <p>Нет доступа к отчётам</p>
}
