import {
  SupplyApiError,
  type SupplySupplier,
  type SupplySupplierInput,
} from '../services/supplyAdmin.ts'

export type SupplySupplierFormValues = {
  displayName: string
  legalName: string
  inn: string
  kpp: string
  ogrn: string
  legalAddress: string
  actualAddress: string
  bankName: string
  bik: string
  correspondentAccount: string
  settlementAccount: string
  orderEmail: string
  phone: string
  comment: string
}

export type SupplySupplierFormErrors = {
  displayName?: string
}

export const EMPTY_SUPPLIER_FORM: SupplySupplierFormValues = {
  displayName: '',
  legalName: '',
  inn: '',
  kpp: '',
  ogrn: '',
  legalAddress: '',
  actualAddress: '',
  bankName: '',
  bik: '',
  correspondentAccount: '',
  settlementAccount: '',
  orderEmail: '',
  phone: '',
  comment: '',
}

function optionalValue(value: string): string | null {
  return value.trim() || null
}

export function supplierToFormValues(
  supplier: SupplySupplier,
): SupplySupplierFormValues {
  return {
    displayName: supplier.display_name,
    legalName: supplier.legal_name ?? '',
    inn: supplier.inn ?? '',
    kpp: supplier.kpp ?? '',
    ogrn: supplier.ogrn ?? '',
    legalAddress: supplier.legal_address ?? '',
    actualAddress: supplier.actual_address ?? '',
    bankName: supplier.bank_name ?? '',
    bik: supplier.bik ?? '',
    correspondentAccount: supplier.correspondent_account ?? '',
    settlementAccount: supplier.settlement_account ?? '',
    orderEmail: supplier.order_email ?? '',
    phone: supplier.phone ?? '',
    comment: supplier.comment ?? '',
  }
}

export function buildSupplierPayload(
  values: SupplySupplierFormValues,
):
  | { status: 'success'; payload: SupplySupplierInput }
  | { status: 'validation'; errors: SupplySupplierFormErrors } {
  const displayName = values.displayName.trim()
  if (!displayName) {
    return {
      status: 'validation',
      errors: { displayName: 'Укажите отображаемое название' },
    }
  }
  if (displayName.length > 240) {
    return {
      status: 'validation',
      errors: {
        displayName: 'Название должно быть не длиннее 240 символов',
      },
    }
  }

  return {
    status: 'success',
    payload: {
      display_name: displayName,
      legal_name: optionalValue(values.legalName),
      inn: optionalValue(values.inn),
      kpp: optionalValue(values.kpp),
      ogrn: optionalValue(values.ogrn),
      legal_address: optionalValue(values.legalAddress),
      actual_address: optionalValue(values.actualAddress),
      bank_name: optionalValue(values.bankName),
      bik: optionalValue(values.bik),
      correspondent_account: optionalValue(values.correspondentAccount),
      settlement_account: optionalValue(values.settlementAccount),
      order_email: optionalValue(values.orderEmail),
      phone: optionalValue(values.phone),
      comment: optionalValue(values.comment),
    },
  }
}

export function supplierErrorMessage(
  error: unknown,
  fallback: string,
): string {
  if (!(error instanceof SupplyApiError)) {
    return fallback
  }
  if (error.status === 409) {
    return 'Активный поставщик с таким ИНН уже существует'
  }
  if (error.status === 404) {
    return 'Поставщик не найден. Обновите список.'
  }
  if (error.status === 403) {
    return 'Недостаточно прав для работы со справочником поставщиков'
  }
  if (error.status === 422) {
    return 'Проверьте заполнение полей поставщика'
  }
  return fallback
}
