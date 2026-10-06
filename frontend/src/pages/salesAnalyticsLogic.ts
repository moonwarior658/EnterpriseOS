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
