import { useState } from 'react'
import { metricNumber as fmt } from './salesAnalyticsLogic'
import { previousDayDelta, trendGeometry, type TrendRow } from './salesTrendLogic'

const dateLabel = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', weekday: 'short' })
export default function SalesTrendChart({ rows: input, title = 'Динамика выручки', money = false }: { rows: TrendRow[]; title?: string; money?: boolean }) {
  const model = trendGeometry(input)
  const [hovered, setHovered] = useState<string | null>(null)
  const index = model.rows.findIndex((r) => r.date === hovered)
  const active = model.rows[index]
  const delta = index < 0 ? null : previousDayDelta(model.rows, index)
  const deltaLabel = (value: number | null) => value === null ? 'Нет данных за предыдущий день' : `${value > 0 ? '+' : ''}${fmt(value, money)}`
  return <section className="page-panel statistics-panel"><h2>{title}</h2>{model.rows.some((r) => r.value !== null) ? <>
    <div className="statistics-chart-scroll"><div className="statistics-chart-frame" onPointerLeave={() => setHovered(null)}>
      <svg className="statistics-chart" viewBox="0 0 760 275" role="group" aria-label={`${title}. Даты по горизонтали, значения по вертикали. Выберите точку для подробностей.`}>
        {model.ticks.map((value) => <g key={value}><line className="statistics-chart-grid" x1="85" x2="735" y1={model.y(value)} y2={model.y(value)} /><text x="75" y={model.y(value) + 4} textAnchor="end">{fmt(value)}</text></g>)}
        {model.dates.map((date) => <g key={date}><line className="statistics-chart-grid" x1={model.x(date)} x2={model.x(date)} y1="30" y2="225" /><text x={model.x(date)} y="247" textAnchor={model.x(date) > 700 ? 'end' : 'middle'}>{dateLabel(date)}</text></g>)}
        <line className="statistics-chart-axis" x1="85" x2="735" y1="225" y2="225" /><line className="statistics-chart-axis" x1="85" x2="85" y1="30" y2="225" />
        <text x="85" y="17">{money ? 'Сумма, ₽' : 'Значение'}</text><text x="735" y="269" textAnchor="end">Дата</text>
        {model.segments.map((segment) => <polyline key={segment[0].date} points={segment.map((r) => `${model.x(r.date)},${model.y(r.value!)}`).join(' ')} />)}
        {model.rows.map((row, i) => row.value === null ? null : <circle key={row.date} cx={model.x(row.date)} cy={model.y(row.value)} r={row.date === hovered ? 6 : 4} tabIndex={0} role="img"
          aria-label={`${dateLabel(row.date)}: ${fmt(row.value, money)}. Изменение: ${deltaLabel(previousDayDelta(model.rows, i))}`}
          onPointerEnter={() => setHovered(row.date)} onFocus={() => setHovered(row.date)} onBlur={() => setHovered(null)}>
          <title>{dateLabel(row.date)} · {fmt(row.value, money)} · {deltaLabel(previousDayDelta(model.rows, i))}</title>
        </circle>)}
      </svg>
      {active && <div className="statistics-chart-tooltip" role="status"><strong>{dateLabel(active.date)}</strong><span>{fmt(active.value, money)}</span><span>К предыдущему дню: {deltaLabel(delta)}</span></div>}
    </div></div>
    <p className="statistics-muted">Наведите на точку или выберите её клавишей Tab. Разрывы означают отсутствие данных.</p>
    <details><summary>Значения и изменения по дням</summary><div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Дата</th><th>Значение</th><th>К предыдущему дню</th></tr></thead><tbody>{model.rows.map((row, i) => <tr key={row.date}><td>{dateLabel(row.date)}</td><td>{fmt(row.value, money)}</td><td>{deltaLabel(previousDayDelta(model.rows, i))}</td></tr>)}</tbody></table></div></details>
  </> : <p className="statistics-muted">За выбранный период нет загруженных данных</p>}</section>
}
