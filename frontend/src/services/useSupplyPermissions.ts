import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { getActionContext, type ActionContext } from './actionContext'

export function useSupplyPermissions() {
  const { user } = useAuth()
  const [access, setAccess] = useState<ActionContext | null>(null)
  useEffect(() => {
    if (!user) return
    let active = true
    getActionContext().then((context) => {
      if (active) setAccess(context)
    }).catch(() => {
      if (active) setAccess(null)
    })
    return () => { active = false }
  }, [user])
  const context = access?.user_id === user?.id ? access : null
  const roles = context?.roles ?? []
  return {
    context,
    canCreateRequest: roles.some((role) => ['ADMIN', 'SUPPLY_MANAGER', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER'].includes(role))
      || (roles.includes('SELLER') && Boolean(context?.shift_id)),
    isAdmin: roles.includes('ADMIN'),
    canOperate: roles.some((role) => role === 'ADMIN' || role === 'SUPPLY_MANAGER'),
    canEditSupplier: roles.some((role) => ['ADMIN', 'SUPPLY_MANAGER', 'ACCOUNTANT'].includes(role)),
    canWritePayment: roles.some((role) => ['ADMIN', 'SUPPLY_MANAGER', 'ACCOUNTANT'].includes(role)),
  }
}
