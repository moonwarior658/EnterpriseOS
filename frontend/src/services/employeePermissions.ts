import type { EmployeeRole } from './actionContext.ts'

const EMPLOYEE_READ = new Set<EmployeeRole>([
  'ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER',
  'HEAD_OF_PRODUCTION', 'SUPPLY_MANAGER',
])
const USER_READ = new Set<EmployeeRole>([
  'ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER',
])
const DEPUTY_ASSIGNABLE = new Set<EmployeeRole>([
  'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'SUPPLY_MANAGER', 'ACCOUNTANT',
  'CHEF_CONFECTIONER', 'HANDYMAN', 'DRIVER', 'SELLER', 'CONFECTIONER', 'BAKER',
])
const NETWORK_ASSIGNABLE = new Set<EmployeeRole>(['SELLER', 'DRIVER', 'HANDYMAN'])

export const canReadEmployees = (roles: EmployeeRole[]) => roles.some((role) => EMPLOYEE_READ.has(role))
export const canReadUsers = (roles: EmployeeRole[]) => roles.some((role) => USER_READ.has(role))
export const canCreateEmployee = (roles: EmployeeRole[]) =>
  roles.some((role) => ['ADMIN', 'DEPUTY_DIRECTOR', 'NETWORK_MANAGER'].includes(role))
export const canDismissEmployee = (roles: EmployeeRole[]) =>
  roles.some((role) => ['ADMIN', 'DEPUTY_DIRECTOR'].includes(role))
export const canCreateHumanUser = (roles: EmployeeRole[]) =>
  roles.some((role) => ['ADMIN', 'NETWORK_MANAGER'].includes(role))
export const canBlockHumanUser = (roles: EmployeeRole[]) =>
  roles.some((role) => ['ADMIN', 'DEPUTY_DIRECTOR'].includes(role))
export const canReadServiceUsers = (roles: EmployeeRole[]) => roles.includes('ADMIN')
export const canReadAudit = (roles: EmployeeRole[]) => roles.includes('ADMIN')

export function assignableRoles(roles: EmployeeRole[]): EmployeeRole[] {
  if (roles.includes('ADMIN')) return [
    'ADMIN', 'DIRECTOR', 'DEPUTY_DIRECTOR', 'ACCOUNTANT', 'SUPPLY_MANAGER',
    'DRIVER', 'HANDYMAN', 'NETWORK_MANAGER', 'CHEF_CONFECTIONER',
    'CONFECTIONER', 'BAKER', 'HEAD_OF_PRODUCTION', 'SELLER',
  ]
  if (roles.includes('DEPUTY_DIRECTOR')) return [...DEPUTY_ASSIGNABLE]
  if (roles.includes('NETWORK_MANAGER')) return [...NETWORK_ASSIGNABLE]
  return []
}
