import { getStoredToken } from './auth'
import type { EmployeeRole } from './actionContext'
export const PRODUCT_KNOWLEDGE_ROLES: EmployeeRole[] = ['ADMIN','DIRECTOR','DEPUTY_DIRECTOR','NETWORK_MANAGER','SUPPLY_MANAGER','ACCOUNTANT','HEAD_OF_PRODUCTION','CHEF_CONFECTIONER','CONFECTIONER','BAKER','SELLER']
export type ProductPrice = { department_id: string; department_name: string; amount: string; currency: string; price_unit: string; valid_from: string; valid_to: string; observed_at: string }
export type Product = {
  id: string; name: string; sku: string | null; unit_name: string; unit_weight_kg: string | null
  sale_mode: string; sale_status: string; category_id: string | null; category_name: string | null
  description: string | null; observed_at: string; source_deleted: boolean
  price: ProductPrice | null; prices: ProductPrice[]; allowed_actions: string[]
}
export type Catalog = { items: Product[]; total: number; offset: number; limit: number; points: {id: string; name: string}[]; categories: {id: string; name: string}[]; observed_at: string | null }
export class ProductApiError extends Error { status: number; constructor(status: number) { super(status === 403 ? 'Нет доступа к продукции' : status === 404 ? 'Изделие или точка недоступны' : 'Не удалось загрузить продукцию. Повторите позже'); this.name = 'ProductApiError'; this.status = status } }
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
export function priceLabel(price: ProductPrice | null, point: string) {
  if (!point) return 'Выберите точку'
  if (!price) return 'Нет подтверждённой цены'
  return `${Number(price.amount).toLocaleString('ru-RU', { maximumFractionDigits: 6 })} ${price.currency} / ${price.price_unit}`
}
export function weightLabel(product: Product) {
  return product.unit_weight_kg ? `${Number(product.unit_weight_kg).toLocaleString('ru-RU', { maximumFractionDigits: 6 })} кг / ${product.unit_name}` : 'Нет данных'
}
