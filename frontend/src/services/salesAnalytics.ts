import { getStoredToken } from './auth'

export type Metric = {
  fact: string | null; target: string | null; completion_percent: string | null
  previous: string | null; change: string | null; change_percent: string | null
  status: 'green' | 'warning' | 'red' | 'no_target' | 'no_data' | 'mixed_targets'
}
export type MetricName = 'revenue' | 'check_count' | 'average_check' | 'fullness'
export type Metrics = Record<MetricName, Metric>
export type Period = { kind: string; start: string; end: string; previous_start: string; previous_end: string }
export type Completeness = {
  current: { complete: boolean; loaded_days: number; expected_days: number; missing_dates: string[] }
  previous: { complete: boolean; loaded_days: number; expected_days: number; missing_dates: string[] }
  as_of: string; warning: boolean
}
export type Analytics = {
  period: Period; metrics: Metrics; completeness?: Completeness | null
  target_segments: { start: string; end: string; metrics: Metrics }[]
  dynamics: { date: string; metrics: Metrics }[]
}
export type Point = Analytics & { department_id: string; department_name: string }
export type Seller = Analytics & { employee_id: string; employee_name: string; employee_status: string }
export type Product = {
  iiko_product_id: string; department_id: string; product_name: string | null
  department_name: string | null; category: string | null; quantity: string; revenue: string
  previous_quantity: string; previous_revenue: string; check_count: number
  dynamics: { date: string; quantity: string | null; revenue: string | null }[]
}
export type Products = { period: Period; products: Product[]; summaries: Product[]; categories: string[]; dynamics: Product['dynamics'] }
export type Freshness = {
  last_success_at: string | null; stale: boolean; update_failed: boolean
  today: string; history_from: string; source_timezone: string
}
export type Target = { metric: MetricName; month: string; value: string; revision: number; created_at: string }

export async function salesRequest<T>(endpoint: string, query = '', signal?: AbortSignal, body?: object): Promise<T> {
  const token = getStoredToken()
  if (!token) throw new Error('Сессия завершена. Войдите снова')
  const response = await fetch(`/api/sales/analytics/${endpoint}${query ? `?${query}` : ''}`, {
    signal, cache: 'no-store', method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) {
    // Never display provider errors, payloads or validation internals.
    const messages: Record<number, string> = {
      401: 'Сессия завершена. Войдите снова', 403: 'Нет доступа к выбранной статистике',
      409: body ? 'Цель уже изменена. Обновите страницу и повторите' : 'Источник статистики ещё не готов',
      422: 'Проверьте период: доступны последние шесть месяцев. Цель должна быть положительным числом',
    }
    throw new Error(messages[response.status] || 'Не удалось загрузить статистику. Повторите позже')
  }
  return response.json() as Promise<T>
}
