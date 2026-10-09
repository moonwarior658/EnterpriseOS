import { getStoredToken } from './auth'

export type Cost = { status: string; amount: string | null; note: string; estimated?: boolean | null; currency?: string; unit?: string; method?: string; source?: string; context?: string; warehouse?: string; stock_at?: string; observed_at?: string }
export type CostDetail = Cost & { verification_at?: string; verification_author?: string | null; observation_id: string; content_hash: string; context_key: string; rounding: string; historical: boolean; components: { name: string | null; quantity: string; unit: string | null; unit_cost: string; contribution: string }[] }
export type CostPortal = { can_review?: boolean; review?: CostReview | null; contexts: {key: string; label: string; warehouse: string}[]; selected_context: string | null; current: CostDetail | null; history: CostDetail[]; total: number; offset: number; limit: number; note: string | null }
export class CostApiError extends Error {
  constructor(status: number) { super(status === 403 ? 'Нет доступа к себестоимости' : status === 404 ? 'Расчёт недоступен' : status === 409 ? 'Расчёт изменился или не допускается к подтверждению. Обновите данные и повторите сверку' : status === 422 ? 'Проверьте сумму, оценочность и подтверждение складов' : 'Не удалось загрузить себестоимость. Повторите позже'); this.name = 'CostApiError' }
}
export async function getProductCosts(id: string, context: string, offset: number, signal: AbortSignal, review = false): Promise<CostPortal> {
  const params = new URLSearchParams({ offset: String(offset), limit: '25' }); if (review) params.set('review','true'); if (context) params.set('context_key', context)
  const response = await fetch(`/api/products/${encodeURIComponent(id)}/costs?${params}`, {headers: {Authorization: `Bearer ${getStoredToken()}`, Accept: 'application/json'}, signal})
  if (!response.ok) throw new CostApiError(response.status)
  return response.json() as Promise<CostPortal>
}
export const exactCostNumber = (value: string) => value.replace('.', ',')
export function costLabel(cost: Cost | null | undefined) {
  if (!cost || cost.status !== 'VERIFIED' || cost.amount === null) return cost?.note || 'Нет подтверждённой себестоимости'
  return `${exactCostNumber(cost.amount)} ₽${cost.estimated ? ' *' : ''}`
}

export type CostReview = {candidate_amount: string | null; components: CostDetail['components']; observation_id: string; content_hash: string; quality: string; issues: string[]; can_confirm: boolean; context: string; warehouse: string; method: string}
export type CostConfirmation = {observation_id: string; content_hash: string; office_ssn: string; estimated: boolean; warehouse_confirmed: boolean; context_confirmed: boolean; office_evidence: string; allow_updates: false}
export async function confirmProductCost(id: string, command: CostConfirmation): Promise<void> {
  const response = await fetch(`/api/products/${encodeURIComponent(id)}/costs/confirm`, {method:'POST', headers:{Authorization:`Bearer ${getStoredToken()}`, 'Content-Type':'application/json'},body:JSON.stringify(command)})
  if (!response.ok) throw new CostApiError(response.status)
}
