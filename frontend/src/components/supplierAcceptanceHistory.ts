import { formatQuantity } from '../utils/format.ts'

type QuantityField = 'ordered_quantity' | 'accepted_quantity'
type HistoryLine = {
  unit_name_snapshot: string | null
  ordered_quantity: string | null
  accepted_quantity: string
  rejected_quantity: string
  shortage_quantity: string
  excess_quantity: string
}

const SCALE = 1_000_000n

function decimalMicros(value: string | null): bigint | null {
  if (value === null) return null
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole) * SCALE + BigInt(`${fraction}000000`.slice(0, 6))
}

function microsToDecimal(value: bigint): string {
  const whole = value / SCALE
  const fraction = String(value % SCALE).padStart(6, '0')
  return `${whole}.${fraction}`
}

export function summarizeAcceptanceQuantity(lines: HistoryLine[], field: QuantityField): string {
  const totals = new Map<string, bigint>()
  for (const line of lines) {
    const value = decimalMicros(line[field])
    if (value === null) continue
    const unit = line.unit_name_snapshot?.trim() || ''
    totals.set(unit, (totals.get(unit) ?? 0n) + value)
  }
  if (totals.size === 0) return '—'
  return [...totals.entries()]
    .map(([unit, value]) => `${formatQuantity(microsToDecimal(value))}${unit ? ` ${unit}` : ''}`)
    .join(' · ')
}

export function hasAcceptanceDiscrepancy(lines: HistoryLine[], result: string): boolean {
  if (result !== 'FULLY_ACCEPTED') return true
  return lines.some((line) => (
    decimalMicros(line.ordered_quantity) === null
    || decimalMicros(line.ordered_quantity) !== decimalMicros(line.accepted_quantity)
    || decimalMicros(line.rejected_quantity) !== 0n
    || decimalMicros(line.shortage_quantity) !== 0n
    || decimalMicros(line.excess_quantity) !== 0n
  ))
}
