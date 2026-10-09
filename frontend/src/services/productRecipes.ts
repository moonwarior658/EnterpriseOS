import { getStoredToken } from './auth'

export type RecipeRow = { product_id: string | null; name: string; unit: string | null; gross: string | null; net: string | null; output: string | null; writeoff: string | null; scope_note: string | null }
export type RecipeChart = { version_id: string; chart_id: string; product_id: string; kind: 'SOURCE' | 'PREPARED'; roles: string[]; name: string; unit: string | null; valid_from: string | null; valid_to: string | null; valid_to_known: boolean; base_amount: string | null; technology: string | null; writeoff_strategy: string; size_strategy: string; store_note: string; items: RecipeRow[] }
export type RecipeApproval = { author: string | null; employee_id: string; confirmed_at: string; evidence: string; version_ids: string[] }
export type RecipeProgress = { state: string; label: string; active: boolean; requested_at: string; finished_at: string | null }
export type RecipeObservation = { id: string; manifest_hash: string; root_product_id: string; effective_on: string; observed_at: string; status: 'UNCONFIRMED' | 'INCOMPLETE' | 'CONFLICT'; status_label: string; is_current: boolean; ready_for_production: false; issues: string[]; charts: RecipeChart[]; confirmation: RecipeApproval | null }
export type RecipePortal = { contexts: { key: string; label: string; warehouse_label: string; size_label: string }[]; context_key: string | null; observation: RecipeObservation | null; last_updated_at: string | null; history: { id: string; observed_at: string; effective_on: string; status: string; status_label: string; is_current: boolean; confirmation: RecipeApproval | null; version_ids: string[] }[]; total: number; offset: number; limit: number; allowed_actions: string[]; refresh: RecipeProgress | null }
export class RecipeApiError extends Error {
  status: number
  constructor(status: number) {
    super(status === 403 ? 'Нет доступа к технологическим картам' : status === 404 ? 'Рецептура или выбранное наблюдение недоступны' : status === 409 ? 'Данные или состояние обновления изменились. Обновите раздел и проверьте версию' : status === 422 ? 'Проверьте дату и описание сверки с iikoOffice' : 'Не удалось получить результат. Повторите запрос; ранее сохранённая история остаётся доступна')
    this.name = 'RecipeApiError'
    this.status = status
  }
}
async function request<T>(id: string, suffix: string, signal?: AbortSignal, body?: object): Promise<T> {
  const response = await fetch(`/api/products/${encodeURIComponent(id)}/recipes${suffix}`, {
    method: body ? 'POST' : 'GET', signal,
    headers: { Authorization: `Bearer ${getStoredToken()}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (!response.ok) throw new RecipeApiError(response.status)
  return response.json() as Promise<T>
}
export const getRecipePortal = (id: string, params: URLSearchParams, signal: AbortSignal) => request<RecipePortal>(id, `?${params}`, signal)
export const confirmRecipe = (id: string, body: { observation_id: string; manifest_hash: string; office_evidence: string }) => request<RecipePortal>(id, '/confirm', undefined, body)
export const refreshRecipe = (id: string, body: { context_key: string; effective_on: string; request_id: string }) => request<{ refresh: RecipeProgress }>(id, '/refresh', undefined, body)
// Norms deliberately remain exact decimal strings, including zero and precision.
export const recipeNorm = (value: string | null) => value === null ? 'Нет данных' : value.replace('.', ',')
export const recipeError = (error: unknown) => error instanceof RecipeApiError ? error.message : 'Не удалось получить результат. Повторите запрос; ранее сохранённая история остаётся доступна'
