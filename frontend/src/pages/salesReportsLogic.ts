import { SALES_FULL_ROLES, analyticsQuery } from './salesAnalyticsLogic.ts'
export function salesReportScope(roles: readonly string[]): 'full' | 'products' | null {
  if (roles.some(r => SALES_FULL_ROLES.includes(r))) return 'full'
  return roles.some(r => ['CHEF_CONFECTIONER', 'HEAD_OF_PRODUCTION'].includes(r)) ? 'products' : null
}
export function salesExportAllowed(roles: readonly string[], view: string) {
  const scope = salesReportScope(roles)
  return ['overview', 'points', 'sellers', 'products'].includes(view) && (scope === 'full' || (scope === 'products' && view === 'products'))
}
export function salesExportQuery(params: URLSearchParams, view: string, format: 'xlsx' | 'pdf') {
  const endpoint = view === 'products' ? 'products' : view === 'sellers' ? 'sellers' : 'overview'
  const result = new URLSearchParams(analyticsQuery(params, endpoint))
  if (view !== 'products') {
    for (const name of ['staff', 'iiko_product_id', 'category']) if (params.get(name)) result.set(name, params.get(name)!)
  }
  result.set('view', view); result.set('format', format)
  return result.toString()
}
