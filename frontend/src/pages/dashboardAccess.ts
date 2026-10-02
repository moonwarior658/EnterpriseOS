import type { EmployeeRole } from '../services/actionContext'

export type DashboardLink = { to: string; label: string }

export function dashboardAccess(roles: readonly EmployeeRole[]) {
  const has = (...allowed: EmployeeRole[]) => roles.some((role) => allowed.includes(role))
  const readRepairs = has('ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'ACCOUNTANT',
    'SUPPLY_MANAGER', 'HANDYMAN', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION',
    'CHEF_CONFECTIONER', 'SELLER', 'DRIVER', 'CONFECTIONER', 'BAKER')
  const readSupplySummary = has('ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR',
    'SUPPLY_MANAGER', 'ACCOUNTANT')
  const readOperationalSupply = has('ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER')
  const readSupplyRequests = has('ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR',
    'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER',
    'SELLER', 'SUPPLY_MANAGER', 'ACCOUNTANT')
  const readFinance = has('ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'SUPPLY_MANAGER', 'ACCOUNTANT')
  const minimalOnly = roles.length > 0 && roles.every((role) => role === 'CONFECTIONER' || role === 'BAKER')
  const financeOnly = roles.length > 0 && roles.every((role) => role === 'ACCOUNTANT')
  const links: DashboardLink[] = []
  if (readRepairs && !minimalOnly && !financeOnly) links.push({ to: '/requests/repair', label: 'Ремонты' })
  if (readSupplyRequests) links.push({ to: '/supply/requests', label: 'Заявки снабжения' })
  if (has('HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER')) links.push({ to: '/supply/production-procurement', label: 'Закупки производства' })
  if (readFinance) links.push({ to: '/supply/debts', label: 'Долги' })
  if (readFinance) links.push({ to: '/supply/supplier-payments', label: 'Оплаты поставщикам' })
  return {
    readRepairs: readRepairs && !minimalOnly && !financeOnly,
    readSupplySummary,
    readOperationalSupply,
    readFinance,
    links,
  }
}
