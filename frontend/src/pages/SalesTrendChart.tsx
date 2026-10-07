import { useEffect, useRef, useState } from 'react'
import { metricNumber as fmt } from './salesAnalyticsLogic'
import { previousDayDelta, trendGeometry, visibleTrendRows, type TrendRow } from './salesTrendLogic'

const dateLabel = (date: string) => {
  const d = new Date(`${date}T12:00:00Z`)
  const weekday = d.toLocaleDateString('ru-RU', { weekday: 'short', timeZone: 'UTC' })
  return `${d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', timeZone: 'UTC' })} · ${weekday[0].toUpperCase()}${weekday.slice(1)}`
}
export default function SalesTrendChart({ rows: input, title = 'Динамика выручки', money = false, through }: { rows: TrendRow[]; title?: string; money?: boolean; through?: string }) {
  const frame = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(760)
  const hasData = visibleTrendRows(input, through).some(r => r.value !== null)
  useEffect(() => {
    if (!frame.current) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(560, entry.contentRect.width)))
    observer.observe(frame.current)
    return () => observer.disconnect()
  }, [hasData])
  const height = 240, bottom = height - 50, right = width - 25
  const model = trendGeometry(visibleTrendRows(input, through), width, height)
  const [hovered, setHovered] = useState<string | null>(null)
  const index = model.rows.findIndex((r) => r.date === hovered)
  const active = model.rows[index]
  const delta = index < 0 ? null : previousDayDelta(model.rows, index)
  const deltaLabel = (value: number | null) => value === null ? 'Нет данных за предыдущий день' : `${value > 0 ? '+' : ''}${fmt(value, money)}`
  return <section className="page-panel statistics-panel"><h2>{title}</h2>{hasData ? <>
    <div className="statistics-chart-scroll"><div ref={frame} className="statistics-chart-frame" onPointerLeave={() => setHovered(null)}>
      <svg className="statistics-chart" viewBox={`0 0 ${width} ${height}`} role="group" aria-label={`${title}. Даты по горизонтали, значения по вертикали. Выберите точку для подробностей.`}>
        {model.ticks.map((value) => <g key={value}><line className="statistics-chart-grid" x1="85" x2={right} y1={model.y(value)} y2={model.y(value)} /><text x="75" y={model.y(value) + 4} textAnchor="end">{fmt(value)}</text></g>)}
        {model.dates.map((date) => <g key={date}><line className="statistics-chart-grid" x1={model.x(date)} x2={model.x(date)} y1="30" y2={bottom} /><text x={model.x(date)} y={height - 20} textAnchor={model.x(date) > width - 60 ? 'end' : 'middle'}>{dateLabel(date)}</text></g>)}
        <line className="statistics-chart-axis" x1="85" x2={right} y1={bottom} y2={bottom} /><line className="statistics-chart-axis" x1="85" x2="85" y1="30" y2={bottom} />
        {model.segments.map((segment) => <polyline key={segment[0].date} points={segment.map((r) => `${model.x(r.date)},${model.y(r.value!)}`).join(' ')} />)}
        {model.rows.map((row, i) => row.value === null ? null : <circle key={row.date} cx={model.x(row.date)} cy={model.y(row.value)} r={row.date === hovered ? 6 : 4} tabIndex={0} role="img"
          aria-label={`${dateLabel(row.date)}: ${fmt(row.value, money)}. Изменение: ${deltaLabel(previousDayDelta(model.rows, i))}`}
          onPointerEnter={() => setHovered(row.date)} onFocus={() => setHovered(row.date)} onBlur={() => setHovered(null)}>
          <title>{dateLabel(row.date)} · {fmt(row.value, money)} · {deltaLabel(previousDayDelta(model.rows, i))}</title>
        </circle>)}
      </svg>
      {active && <div className="statistics-chart-tooltip" style={{ left: `${model.x(active.date) / width * 100}%`, top: `${model.y(active.value!) / height * 100}%`, transform: `translate(${model.x(active.date) > width / 2 ? 'calc(-100% - 12px)' : '12px'}, ${model.y(active.value!) < height / 2 ? '8px' : 'calc(-100% - 8px)'})` }} role="status"><strong>{dateLabel(active.date)}</strong><span>{fmt(active.value, money)}</span><span>К предыдущему дню: {deltaLabel(delta)}</span></div>}
    </div></div>
    <p className="statistics-muted">Наведите на точку или выберите её клавишей Tab. Разрывы означают отсутствие данных.</p>
    <details><summary>Значения и изменения по дням</summary><div className="statistics-table-wrap"><table className="statistics-table"><thead><tr><th>Дата</th><th>Значение</th><th>К предыдущему дню</th></tr></thead><tbody>{model.rows.map((row, i) => <tr key={row.date}><td>{dateLabel(row.date)}</td><td>{fmt(row.value, money)}</td><td>{deltaLabel(previousDayDelta(model.rows, i))}</td></tr>)}</tbody></table></div></details>
  </> : <p className="statistics-muted">За выбранный период нет загруженных данных</p>}</section>
}
