import type {
  SupplyPurchaseAllocationSupplierSubtotal,
} from '../services/supplyAdmin.ts'


export function suggestedPackages(remaining: string, packageQuantity: string): number {
  const remainder = Number(remaining)
  const packageSize = Number(packageQuantity)
  if (!Number.isFinite(remainder) || !Number.isFinite(packageSize) || packageSize <= 0) return 1
  return Math.max(1, Math.ceil(remainder / packageSize))
}

export function coverageLabel(remaining: string, overallocated: string): string {
  if (Number(overallocated) > 0) return `Превышение: ${overallocated}`
  if (Number(remaining) > 0) return `Осталось: ${remaining}`
  return 'Потребность покрыта'
}

export function minimumOrderLabel(
  subtotal: SupplyPurchaseAllocationSupplierSubtotal,
  formatMoney: (value: string) => string,
): string {
  if (subtotal.minimum_order_status === 'NOT_CONFIGURED') {
    return 'Минимальная сумма не задана'
  }
  const minimum = formatMoney(subtotal.minimum_order_amount ?? '0')
  if (subtotal.minimum_order_status === 'MET') {
    return `Минимальный заказ: ${minimum} · минимум выполнен`
  }
  return `Минимальный заказ: ${minimum} · не хватает ${formatMoney(subtotal.minimum_order_shortfall)}`
}
