import { getStoredToken } from './auth'
import type { EmployeeRole } from './actionContext'
export const PRODUCT_KNOWLEDGE_ROLES: EmployeeRole[] = ['ADMIN','DIRECTOR','DEPUTY_DIRECTOR','NETWORK_MANAGER','HEAD_OF_PRODUCTION','CHEF_CONFECTIONER']
export type ProductPrice = { department_id: string; department_name: string; amount: string; currency: string; price_unit: string; valid_from: string; valid_to: string; observed_at: string }
export type PriceHealth = { department_id: string; last_success_at: string | null; stale: boolean; update_failed: boolean }
export type Product = {
  recipe_access?: boolean
  photo?: string | null; id: string; name: string; sku: string | null; unit_name: string; unit_weight_kg: string | null
  sale_mode: string; sale_status: string; category_id: string | null; category_name: string | null
  description_source: 'EOS' | 'iiko'; description: string | null; observed_at: string; source_deleted: boolean
  characteristics: string | null; composition: string | null; allergens: string | null; storage: string | null; training: string | null
  version: number; deleted_at: string | null; verified_at: string | null; verified_by_employee_id: string | null; verified_by_name: string | null
  eligible_for_production: boolean
  price_health?: PriceHealth[]; price: ProductPrice | null; prices: ProductPrice[]; price_conflict_points?: string[]; allowed_actions: string[]
}
export type Catalog = { items: Product[]; total: number; offset: number; limit: number; points: {id: string; name: string}[]; categories: {id: string; name: string}[]; observed_at: string | null; active_count: number; verified_count: number; allowed_actions: string[] }
export class ProductApiError extends Error { status: number; constructor(status: number, photo = false) { super(status === 403 ? 'Нет доступа к продукции' : status === 404 ? 'Изделие или точка недоступны' : status === 409 ? 'Данные изменились. Обновите карточку или выберите изделие заново' : status === 413 ? 'Размер фотографии не должен превышать 10 МБ' : status === 415 ? 'Загрузите JPEG, PNG или WebP' : status === 422 ? photo ? 'Проверьте файл: допустима неподвижная фотография до 16 млн пикселей' : 'Проверьте заполнение полей и категорию' : 'Не удалось загрузить продукцию. Повторите позже'); this.name = 'ProductApiError'; this.status = status } }
async function read<T>(path: string, params: URLSearchParams, signal: AbortSignal): Promise<T> {
  const token = getStoredToken()
  const response = await fetch(`/api/products${path}?${params}`, { headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }, signal })
  if (!response.ok) throw new ProductApiError(response.status)
  return response.json() as Promise<T>
}
export function getProductCatalog(params: URLSearchParams, signal: AbortSignal) { return read<Catalog>('', params, signal) }
export function getProduct(id: string, params: URLSearchParams, signal: AbortSignal) { return read<Product>(`/${encodeURIComponent(id)}`, params, signal) }
export const saleModeLabel = (mode: string) => mode === 'PORTION' ? 'Порционный' : mode === 'WEIGHT' ? 'Весовой' : 'Нет данных'
export const saleStatusLabel = (status: string) => status === 'OFF_SALE' ? 'Выведено из продажи' : 'В продаже'
export function priceLabel(price: ProductPrice | null, point: string, conflicts: string[] = []) {
  if (!point) return 'Выберите точку'
  if (conflicts.includes(point)) return 'Цена требует проверки'
  if (!price) return 'Нет подтверждённой цены'
  return `${Number(price.amount).toLocaleString('ru-RU', { maximumFractionDigits: 6 })} ${price.currency} / ${price.price_unit}`
}
export function weightLabel(product: Product) {
  return product.unit_weight_kg ? `${Number(product.unit_weight_kg).toLocaleString('ru-RU', { maximumFractionDigits: 6 })} кг / ${product.unit_name}` : 'Нет данных'
}

export type IikoCandidate = { source_id: string; iiko_product_id: string; name: string; unit_name: string; source_deleted: boolean; existing_id: string | null; confirmation_hash: string }
export type ProductHistory = { id: string; operation: string; occurred_at: string; actor_name: string | null; reason: string; before: Record<string, unknown>; after: Record<string, unknown> }
export const getIikoCandidates = (q: string, signal: AbortSignal) => read<IikoCandidate[]>('/iiko-candidates', new URLSearchParams({q}), signal)
export const getProductHistory = (id: string, offset: number, signal: AbortSignal) => read<ProductHistory[]>(`/${encodeURIComponent(id)}/history`, new URLSearchParams({offset: String(offset), limit: '25'}), signal)
export async function productCommand(path: string, method: string, body: object): Promise<Product> {
  const response = await fetch(`/api/products${path}`, { method, headers: { Authorization: `Bearer ${getStoredToken()}`, 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok) throw new ProductApiError(response.status)
  return response.json() as Promise<Product>
}
