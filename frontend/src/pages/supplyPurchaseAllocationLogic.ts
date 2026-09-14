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
