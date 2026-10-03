export function formatDateOnly(value: string | null | undefined, empty = '—'): string {
  if (!value) return empty
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value)
  if (!match) return empty
  return `${match[3]}-${match[2]}-${match[1]}`
}
