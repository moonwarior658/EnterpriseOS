const quantity = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 6 })
const money = new Intl.NumberFormat('ru-RU', {
  style: 'currency', currency: 'RUB', minimumFractionDigits: 2, maximumFractionDigits: 2,
})

export function formatQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? quantity.format(number) : String(value)
}

export function formatMoney(value: string | number | null | undefined): string {
  const number = Number(value ?? 0)
  return money.format(Number.isFinite(number) ? number : 0)
}
