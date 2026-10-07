export const SALES_FULL_ROLES = ['ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER']
export const SALES_ROLES = [...SALES_FULL_ROLES, 'CHEF_CONFECTIONER', 'HEAD_OF_PRODUCTION', 'SELLER']
export function statisticsViews(roles: readonly string[]) {
  const full = roles.some((role) => SALES_FULL_ROLES.includes(role))
  return [...(full ? ['overview', 'points', 'sellers', 'products'] : roles.some((r) => ['CHEF_CONFECTIONER', 'HEAD_OF_PRODUCTION'].includes(r)) ? ['products'] : []), ...(roles.includes('SELLER') ? ['me'] : [])]
}
export function analyticsQuery(params: URLSearchParams, endpoint: string) {
  const query = new URLSearchParams({ period: params.get('period') || 'month' })
  const dates = query.get('period') === 'custom' ? ['start', 'end'] : ['anchor']
  const filters = endpoint === 'overview' ? ['department_id', 'employee_id'] : endpoint === 'sellers' ? ['department_id', 'employee_id', 'staff'] : endpoint === 'products' ? ['department_id', 'iiko_product_id', 'category'] : []
  for (const key of [...dates, ...filters]) if (params.get(key)) query.set(key, params.get(key)!)
  return query.toString()
}
export function metricNumber(value: string | number | null | undefined, money = false) {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2, ...(money ? { style: 'currency', currency: 'RUB' } : {}) }).format(Number(value))
}

export function workspaceQuery(params: URLSearchParams, view: string) {
  if (['seller-products', 'me-products'].includes(view)) {
    const query = new URLSearchParams(analyticsQuery(params, 'me'))
    query.set('view', view)
    for (const name of [...(view === 'seller-products' ? ['employee_id', 'department_id', 'staff'] : []), 'category', 'iiko_product_id']) if (params.get(name)) query.set(name, params.get(name)!)
    return query.toString()
  }
  const endpoint = view === 'me' ? 'me' : view === 'products' ? 'products' : 'overview'
  const query = new URLSearchParams(analyticsQuery(params, endpoint))
  query.set('view', view)
  if (['overview', 'points', 'sellers'].includes(view) && params.get('staff')) query.set('staff', params.get('staff')!)
  if (['overview', 'points'].includes(view)) for (const name of ['iiko_product_id', 'category']) if (params.get(name)) query.set(name, params.get(name)!)
  return query.toString()
}

export type ProductSortKey = 'product_name' | 'department_name' | 'category' | 'quantity' | 'revenue' | 'previous_quantity' | 'previous_revenue'
export function sortSalesProducts<K extends string, T extends Record<K, string | null>>(rows: readonly T[], key: K, direction: 'asc' | 'desc') {
  const text = ['product_name', 'department_name', 'category'].includes(key)
  const label = (row: T) => row[key] || (key === 'category' ? 'Без категории' : 'Без названия')
  return [...rows].sort((a, b) => (text ? label(a).localeCompare(label(b), 'ru') : Number(a[key]) - Number(b[key])) * (direction === 'asc' ? 1 : -1))
}

// Picker values remain ordinary API anchors; the source timezone supplies today.
export function salesPeriodOptions(kind: 'month' | 'week', historyFrom: string, today: string) {
  if (!historyFrom || !today) return []
  const day = new Date(`${today}T12:00:00Z`)
  if (kind === 'month') day.setUTCDate(1)
  else day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7)
  const options: { value: string; label: string }[] = []
  while (day.toISOString().slice(0, 10) >= historyFrom) {
    const value = day.toISOString().slice(0, 10)
    const end = new Date(day)
    end.setUTCDate(end.getUTCDate() + 6)
    const label = kind === 'month'
      ? day.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric', timeZone: 'UTC' }).replace(/ г\.$/, '')
      : `${day.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', timeZone: 'UTC' })} — ${end.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' })}`
    options.push({ value, label: label[0].toUpperCase() + label.slice(1) })
    if (kind === 'month') day.setUTCMonth(day.getUTCMonth() - 1)
    else day.setUTCDate(day.getUTCDate() - 7)
  }
  return options
}
export function salesPeriodAnchor(kind: 'month' | 'week', anchor: string) {
  if (!anchor) return ''
  const day = new Date(`${anchor}T12:00:00Z`)
  if (Number.isNaN(day.getTime())) return ''
  if (kind === 'month') day.setUTCDate(1)
  else day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7)
  return day.toISOString().slice(0, 10)
}
