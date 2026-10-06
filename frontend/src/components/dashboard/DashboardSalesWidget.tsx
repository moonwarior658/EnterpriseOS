import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { salesRequest, type Analytics, type Freshness, type Metric, type Seller } from '../../services/salesAnalytics'
import { metricNumber as fmt } from '../../pages/salesAnalyticsLogic'
import { dashboardSalesDestination, type SalesWidgetKind } from '../../pages/dashboardSalesLogic'
import './DashboardSalesWidget.css'

export type DashboardSalesData = { analytics: Analytics; status: Freshness; attention: Seller[] }
const labels = { green: 'Цель выполнена', warning: 'Небольшое отставание', red: 'Ниже 85% цели', no_target: 'Цель не задана', no_data: 'Нет чеков', mixed_targets: 'Разные цели' }

function Kpi({ label, metric, money = false }: { label: string; metric: Metric; money?: boolean }) {
  return <div className={`dashboard-sales-kpi ${metric.status}`} title={labels[metric.status]}>
    <span>{label}</span><b>{fmt(metric.fact, money)} / {fmt(metric.target, money)}</b>
    <span className="dashboard-sales-assessment">{labels[metric.status]}{metric.completion_percent !== null && ` · ${fmt(metric.completion_percent)}%`}</span>
  </div>
}

export function DashboardSalesContent({ kind, data, error = '' }: { kind: SalesWidgetKind; data: DashboardSalesData | null; error?: string }) {
  const metrics = data?.analytics.metrics
  const incomplete = data?.analytics.completeness?.warning
  const status = data?.status
  return <Link className={`dashboard-sales dashboard-sales-${kind}`} to={dashboardSalesDestination(kind)}>
    <h2>{kind === 'personal' ? 'Мои показатели' : 'Продажи сети'}</h2>
    <span className="dashboard-sales-period">Текущий месяц</span>
    {error && <span role="status" className="dashboard-sales-warning">{error}</span>}
    {!data && !error && <span role="status">Загрузка…</span>}
    {metrics && <>
      {kind !== 'personal' && <div className="dashboard-sales-revenue">
        <span>{kind === 'executive' ? 'Выручка · факт / план' : 'Выручка'}</span>
        <b>{fmt(metrics.revenue.fact, true)}{kind === 'executive' && <> / {fmt(metrics.revenue.target, true)}</>}</b>
        {kind === 'executive' && (metrics.revenue.completion_percent !== null
          ? <progress aria-label="Выполнение плана выручки" max={100} value={Math.max(0, Math.min(100, Number(metrics.revenue.completion_percent)))} />
          : <span>План не задан</span>)}
        <span>Чеки: <b>{fmt(metrics.check_count.fact)}</b></span>
      </div>}
      <Kpi label="Средний чек" metric={metrics.average_check} money />
      <Kpi label="Наполняемость" metric={metrics.fullness} />
      {kind === 'executive' && <div className="dashboard-sales-attention">
        <b>Требуют внимания</b>
        {data.attention.length ? data.attention.slice(0, 2).map((seller) => <div key={seller.employee_id}>
          <span title={seller.employee_name}>{seller.employee_name}</span>
          <small>Чек {fmt(seller.metrics.average_check.completion_percent)}% · нап. {fmt(seller.metrics.fullness.completion_percent)}%</small>
        </div>) : <span>{incomplete ? 'Недостаточно данных для оценки' : 'Нет отклонений ниже 85%'}</span>}
      </div>}
    </>}
    {incomplete && <span className="dashboard-sales-warning" role="status">Неполные данные</span>}
    {status?.update_failed && <span className="dashboard-sales-warning" role="status">Обновление не выполнено</span>}
    {status?.stale && <span className="dashboard-sales-warning" role="status">Данные устарели</span>}
    {status && <time className="dashboard-sales-updated" dateTime={status.last_success_at ?? undefined} title={status.last_success_at ? new Date(status.last_success_at).toLocaleString('ru-RU', { timeZone: status.source_timezone }) : undefined}>
      Обновлено: {status.last_success_at ? new Date(status.last_success_at).toLocaleTimeString('ru-RU', { timeZone: status.source_timezone, hour: '2-digit', minute: '2-digit' }) : 'ещё нет данных'}
    </time>}
    <span className="dashboard-sales-open">Открыть →</span>
  </Link>
}

export default function DashboardSalesWidget({ kind }: { kind: SalesWidgetKind }) {
  const [data, setData] = useState<DashboardSalesData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let running = false
    async function load() {
      if (running || document.hidden) return
      running = true
      try {
        // Wait for every read before releasing the refresh guard, including failures.
        const [analytics, status, attention] = await Promise.allSettled([
          salesRequest<Analytics>(kind === 'personal' ? 'me' : 'overview', 'period=month', controller.signal),
          salesRequest<Freshness>('status', '', controller.signal),
          kind === 'executive' ? salesRequest<Seller[]>('attention', 'period=month', controller.signal) : Promise.resolve([]),
        ])
        if (analytics.status === 'rejected') throw analytics.reason
        if (status.status === 'rejected') throw status.reason
        if (attention.status === 'rejected') throw attention.reason
        if (!controller.signal.aborted) {
          setData({ analytics: analytics.value, status: status.value, attention: attention.value }); setError('')
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          const accessError = e instanceof Error && ['Нет доступа к выбранной статистике', 'Сессия завершена. Войдите снова'].includes(e.message)
          if (accessError) setData(null)
          setError(accessError ? e.message : 'Не удалось обновить статистику')
        }
      } finally { running = false }
    }
    void load()
    const timer = window.setInterval(() => { void load() }, 60_000)
    const visible = () => { if (!document.hidden) void load() }
    document.addEventListener('visibilitychange', visible)
    return () => { controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [kind])
  return <DashboardSalesContent kind={kind} data={data} error={error} />
}
