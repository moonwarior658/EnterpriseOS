export type SalesWidgetKind = 'personal' | 'network' | 'executive'

// One card per person; a network role takes precedence over the seller role.
// ADMIN sees the complete executive sales widget.
export function dashboardSalesKind(roles: readonly string[]): SalesWidgetKind | null {
  if (roles.includes('ADMIN') || roles.includes('DEPUTY_DIRECTOR') || roles.includes('DIRECTOR')) return 'executive'
  if (roles.includes('NETWORK_MANAGER')) return 'network'
  if (roles.includes('SELLER')) return 'personal'
  return null
}

export function dashboardSalesDestination(kind: SalesWidgetKind) {
  return `/statistics/${kind === 'personal' ? 'me' : 'overview'}?period=month`
}
