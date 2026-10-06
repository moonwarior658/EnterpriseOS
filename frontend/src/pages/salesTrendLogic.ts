export type TrendRow = { date: string; value: number | null }
export const dayTime = (date: string) => Date.parse(`${date}T00:00:00Z`)
export function previousDayDelta(rows: TrendRow[], index: number) {
  const current = rows[index], previous = rows[index - 1]
  if (!previous || current.value === null || previous.value === null || dayTime(current.date) - dayTime(previous.date) !== 86_400_000) return null
  return current.value - previous.value
}
export function trendGeometry(input: TrendRow[]) {
  const rows = [...input].sort((a, b) => a.date.localeCompare(b.date))
  const numbers = rows.flatMap((r) => r.value === null || !Number.isFinite(r.value) ? [] : [r.value])
  const minimum = Math.min(0, ...numbers), maximum = Math.max(1, ...numbers)
  const rough = (maximum - minimum) / 4
  const power = 10 ** Math.floor(Math.log10(rough))
  const step = ([1, 2, 2.5, 5, 10].find((n) => n * power >= rough) || 10) * power
  const low = Math.floor(minimum / step) * step, high = Math.ceil(maximum / step) * step
  const first = rows.length ? dayTime(rows[0].date) : 0
  const last = rows.length ? dayTime(rows[rows.length - 1].date) : first
  const x = (date: string) => last === first ? 410 : 85 + (dayTime(date) - first) / (last - first) * 650
  const y = (value: number) => 225 - (value - low) / (high - low) * 195
  const ticks = Array.from({ length: Math.round((high - low) / step) + 1 }, (_, i) => low + step * i)
  const dates = [...new Set(Array.from({ length: Math.min(6, rows.length) }, (_, i) => rows[Math.round(i * (rows.length - 1) / Math.max(1, Math.min(6, rows.length) - 1))].date))]
  const segments: TrendRow[][] = []; let active: TrendRow[] = []
  for (const row of rows) {
    if (row.value === null || !Number.isFinite(row.value)) { if (active.length) segments.push(active); active = []; continue }
    if (active.length && dayTime(row.date) - dayTime(active[active.length - 1].date) !== 86_400_000) { segments.push(active); active = [] }
    active.push(row)
  }
  if (active.length) segments.push(active)
  return { rows, x, y, ticks, dates, segments }
}
