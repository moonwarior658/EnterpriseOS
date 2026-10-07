export type TrendRow = { date: string; value: number | null }
export const dayTime = (date: string) => Date.parse(`${date}T00:00:00Z`)
export function previousDayDelta(rows: TrendRow[], index: number) {
  const current = rows[index], previous = rows[index - 1]
  if (!previous || current.value === null || previous.value === null || dayTime(current.date) - dayTime(previous.date) !== 86_400_000) return null
  return current.value - previous.value
}
export function visibleTrendRows(input: TrendRow[], through?: string) {
  return through ? input.filter(row => row.date <= through) : input
}
export function trendGeometry(input: TrendRow[], width = 760, height = 275) {
  const rows = [...input].sort((a, b) => a.date.localeCompare(b.date))
  const numbers = rows.flatMap((r) => r.value === null || !Number.isFinite(r.value) ? [] : [r.value])
  const minimum = Math.min(0, ...numbers), maximum = Math.max(1, ...numbers)
  const rough = (maximum - minimum) / 4
  const power = 10 ** Math.floor(Math.log10(rough))
  const step = ([1, 2, 2.5, 5, 10].find((n) => n * power >= rough) || 10) * power
  const low = Math.floor(minimum / step) * step, high = Math.ceil(maximum / step) * step
  const first = rows.length ? dayTime(rows[0].date) : 0
  const last = rows.length ? dayTime(rows[rows.length - 1].date) : first
  const x = (date: string) => last === first ? (85 + width - 25) / 2 : 85 + (dayTime(date) - first) / (last - first) * (width - 110)
  const y = (value: number) => height - 50 - (value - low) / (high - low) * (height - 80)
  const ticks = Array.from({ length: Math.round((high - low) / step) + 1 }, (_, i) => low + step * i)
  const tickCount = Math.min(Math.max(2, Math.floor((width - 110) / 115)), rows.length)
  const dates = [...new Set(Array.from({ length: tickCount }, (_, i) => rows[Math.round(i * (rows.length - 1) / Math.max(1, tickCount - 1))].date))]
  const segments: TrendRow[][] = []; let active: TrendRow[] = []
  for (const row of rows) {
    if (row.value === null || !Number.isFinite(row.value)) { if (active.length) segments.push(active); active = []; continue }
    if (active.length && dayTime(row.date) - dayTime(active[active.length - 1].date) !== 86_400_000) { segments.push(active); active = [] }
    active.push(row)
  }
  if (active.length) segments.push(active)
  return { rows, x, y, ticks, dates, segments }
}
