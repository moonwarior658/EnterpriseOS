import { getStoredToken } from './auth'
import type { EmployeeRole } from './employees'
export const RAW_MATERIAL_ROLES: EmployeeRole[] = ['ADMIN','SUPPLY_MANAGER','DIRECTOR','DEPUTY_DIRECTOR','ACCOUNTANT','HEAD_OF_PRODUCTION','CHEF_CONFECTIONER','CONFECTIONER','BAKER']
export type ApprovedProduct = {product_id:string;role:'PRIMARY'|'RESERVE';manufacturer:string;restrictions:string;evidence:string;name?:string}
export type UnitConversion = {from_unit_id:string;to_unit_id:string;supplier_iiko_id:string;container_id:string|null;factor:string;valid_from:string;valid_to:string;evidence:string;packaging:string}
export type Knowledge = { approved_products?:ApprovedProduct[]; conversions?:UnitConversion[]; allowed_manufacturers?:string[]; application_limits?:string; package_net_quantity?:string|null; package_unit_id?:string|null;package_evidence?:string; purpose: string; composition: string; allergens: string; characteristics: string; receiving_requirements: string; storage: string; shelf_life: string; manufacturer: string; unit_weight_kg: string | null; weight_evidence: string }
export type Specification = { id: string; revision: number; content_hash: string; status: 'DRAFT' | 'CONFIRMED'; knowledge: Knowledge; author: string | null; approver: string | null; created_at: string; confirmed_at: string | null; primary_product_id: string | null }
export type MaterialSupplier = { id: string; name: string; role: string; priority: number; available: boolean }
export type UsageMetric = {id?:string;status:'READY'|'BLOCKED'|'NO_DATA';quantity:string|null;unit?:string;date_from?:string;date_to?:string;reasons?:string[];categories?:Record<string,string>;balance?:Record<string,string|null>;documents?:{category:string;quantity:string;date:string;document_id:string;number:string}[]}
export type PurchaseMetric = { six_month_average?: PurchaseMetric; id?: string; status: 'READY' | 'BLOCKED' | 'NO_DATA'; amount: string | null; currency?: string; unit?: string; receipt_at?: string | null; observed_at?: string; reasons?: string[]; stale?: boolean; date_from?: string; date_to?: string }
export type PurchaseProgress = { status: string; label: string; active: boolean; requested_at: string; finished_at: string | null }
export type PurchaseHistory = { current?: PurchaseMetric; items: PurchaseMetric[]; refresh: PurchaseProgress | null }
export type PurchaseLine = {num:string;amountUnit:string;amount?:string;actualAmount:string;containerId?:string;unit_name?:string|null;sum:string;vatSum:string;original_line?:PurchaseLine}
export type PurchaseDocument = {document_id:string;source_hash:string;number:string;receipt_at:string|null;supplier_name:string|null;supplier_flags?:{is_employee:boolean};numerator:string;denominator:string;lines:PurchaseLine[]}
export type DocumentAdmission = {id:string;snapshot_id:string;kind:'EMPLOYEE_PURCHASE'|'BASE_UNIT_CONTAINER';action:'GRANT'|'REVOKE';revision:number;document_id:string;document_hash:string;line_num:string;evidence:string;comment:string;author:string;created_at:string;current?:boolean}
export type AdmissionHistory = {items:DocumentAdmission[];current_items:DocumentAdmission[];version:number}
export type PurchaseSources = { documents?:PurchaseDocument[];admission_validity?:{latest:boolean;average:boolean}; analytics?:{average?:PurchaseMetric & {numerator:string;denominator:string;documents:{document_id:string;number:string;numerator:string;denominator:string}[]}}; metric: PurchaseMetric; warehouse: string; hash: string; candidates: {document_id:string;number:string;receipt_at:string|null;supplier_name:string|null; numerator:string;denominator:string;lines:{num:string;amountUnit:string;actualAmount:string;unit_name?:string|null;sum:string;vatSum:string}[]}[]; unit_conflicts?: {document_id:string;number:string;receipt_at:string|null}[]; exclusions: {document_id:string;reason:string}[] }
export type Material = { id: string; name: string; kind: 'RAW_MATERIAL' | 'PACKAGING'; archived: boolean; supply_active: boolean; version: number; unit: string | null; unit_id: string | null; unit_weight_kg: string | null; photo_hash: string | null; primary_supplier: MaterialSupplier | null; backup_supplier: MaterialSupplier | null; backup_ambiguous: boolean; suppliers: MaterialSupplier[]; purchase_access: boolean; approved_products?:ApprovedProduct[]; selected_reserve_product_id?:string|null; reserves?:ApprovedProduct[]; last_purchase_price?: PurchaseMetric; six_month_average?:PurchaseMetric; monthly_consumption?:UsageMetric; allowed_actions: string[]; current?: Specification | null; latest?: Specification | null }
export type MaterialCatalog = { items: Material[]; total: number; offset: number; limit: number; can_enroll: boolean; purchase_access: boolean; categories: {id:string;name:string}[]; suppliers: {id:string;name:string}[] }
export type MaterialHistory = { versions: Specification[]; total: number; events: {id:string; operation:string; occurred_at:string; author:string|null; reason:string; before:Record<string,unknown>; after:Record<string,unknown>}[]; event_total: number }
export class MaterialApiError extends Error {
  constructor(status: number) {
    super(status === 403 ? 'Недостаточно прав для работы с сырьём' : status === 404 ? 'Карточка или фотография не найдена' : status === 409 ? 'Карточка изменилась или действие недоступно. Обновите данные' : status === 413 ? 'Размер фотографии не должен превышать 10 МБ' : status === 415 ? 'Фотография должна быть JPEG, PNG или WebP' : status === 422 ? 'Проверьте обязательные поля, формат значений и документальные основания' : 'Не удалось выполнить действие. Повторите позже')
    this.name = 'MaterialApiError'
  }
}
export async function materialRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers); headers.set('Authorization', `Bearer ${getStoredToken()}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type','application/json')
  const response = await fetch(`/api/raw-materials${path}`, {...init,headers,cache:'no-store'})
  if (!response.ok) throw new MaterialApiError(response.status)
  return response.json() as Promise<T>
}
export async function materialPhoto(id: string, hash: string, signal: AbortSignal): Promise<Blob> {
  const response = await fetch(`/api/raw-materials/${id}/photo?photo_hash=${hash}`,{headers:{Authorization:`Bearer ${getStoredToken()}`},signal,cache:'no-store'})
  if (!response.ok) throw new MaterialApiError(response.status)
  return response.blob()
}
