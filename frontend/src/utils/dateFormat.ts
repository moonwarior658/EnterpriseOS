export function formatDateOnly(value: string | null | undefined, empty = '—'): string {
  if (!value) return empty
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  if (!match) return empty
  return `${match[3]}-${match[2]}-${match[1]}`
}

export function formatDateTime(value: string | null | undefined, empty = '—'): string {
  if (!value) return empty
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return empty
  const parts = new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(parsed)
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? ''
  return `${part('day')}-${part('month')}-${part('year')} ${part('hour')}:${part('minute')}`
}
