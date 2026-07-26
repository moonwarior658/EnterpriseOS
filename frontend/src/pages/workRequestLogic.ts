import type {
  CreateWorkRequestInput,
  RepairPriority,
  WarehouseCategory,
  WorkRequest,
  WorkRequestStatus,
  WorkRequestType,
} from '../services/requests.ts'

export const DEPARTMENTS = [
  'Производство',
  'Кондитерский цех',
  'Кафе',
  'М15',
  'М6а',
  'М35',
  'Снабжение',
  'Администрация',
  'Другое',
] as const

export const WAREHOUSE_CATEGORIES: Array<{
  value: WarehouseCategory
  label: string
}> = [
  { value: 'products', label: 'Продукты' },
  { value: 'household', label: 'Хозяйственные товары' },
  { value: 'packaging', label: 'Упаковка' },
]

export const REPAIR_CATEGORIES = [
  'Сантехника',
  'Электрика',
  'Кассовое оборудование',
  'Компьютерное оборудование',
  'Холодильное оборудование',
  'Тепловое оборудование',
  'Кофемашина',
  'Интернет',
  'Другое',
] as const

export const PRIORITIES: Array<{
  value: RepairPriority
  label: string
}> = [
  { value: 'routine', label: 'Рутина' },
  { value: 'important', label: 'Важно' },
  { value: 'urgent', label: 'Срочно' },
]

export const REQUEST_STATUSES: Array<{
  value: WorkRequestStatus
  label: string
}> = [
  { value: 'new', label: 'Новая' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'completed', label: 'Выполнена' },
  { value: 'cancelled', label: 'Отменена' },
]

export type WorkRequestFormValues = {
  department: string
  category: string
  priority: string
  description: string
}

export type WorkRequestFormErrors = Partial<
  Record<keyof WorkRequestFormValues, string>
>

export const EMPTY_WORK_REQUEST_FORM: WorkRequestFormValues = {
  department: '',
  category: '',
  priority: '',
  description: '',
}

export type SubmissionGuard = { active: boolean }

export function createSubmissionGuard(): SubmissionGuard {
  return { active: false }
}

export async function submitWorkRequest(
  requestType: WorkRequestType,
  values: WorkRequestFormValues,
  create: (input: CreateWorkRequestInput) => Promise<WorkRequest>,
  guard: SubmissionGuard,
): Promise<
  | { status: 'success'; request: WorkRequest }
  | { status: 'validation'; errors: WorkRequestFormErrors }
  | { status: 'error'; message: string }
  | { status: 'busy' }
> {
  if (guard.active) {
    return { status: 'busy' }
  }

  const errors: WorkRequestFormErrors = {}
  const description = values.description.trim()

  if (!values.department) {
    errors.department = 'Выберите подразделение'
  }
  if (!values.category) {
    errors.category =
      requestType === 'warehouse'
        ? 'Выберите категорию склада'
        : 'Выберите категорию ремонта'
  }
  if (requestType === 'repair' && !values.priority) {
    errors.priority = 'Выберите приоритет'
  }
  if (!description) {
    errors.description =
      requestType === 'warehouse'
        ? 'Укажите содержание заявки'
        : 'Опишите проблему'
  }

  if (Object.keys(errors).length > 0) {
    return { status: 'validation', errors }
  }

  const input: CreateWorkRequestInput = {
    request_type: requestType,
    department: values.department,
    description,
  }

  if (requestType === 'warehouse') {
    input.warehouse_category = values.category as WarehouseCategory
  } else {
    input.repair_category = values.category
    input.priority = values.priority as RepairPriority
  }

  guard.active = true
  try {
    return { status: 'success', request: await create(input) }
  } catch {
    return {
      status: 'error',
      message: 'Не удалось отправить заявку. Проверьте данные и попробуйте ещё раз',
    }
  } finally {
    guard.active = false
  }
}

export function statusLabel(status: WorkRequestStatus): string {
  return (
    REQUEST_STATUSES.find((option) => option.value === status)?.label ??
    'Неизвестно'
  )
}

export function warehouseCategoryLabel(
  category: WarehouseCategory | null,
): string {
  return (
    WAREHOUSE_CATEGORIES.find((option) => option.value === category)?.label ??
    'Не указана'
  )
}

export function priorityLabel(priority: RepairPriority | null): string {
  return (
    PRIORITIES.find((option) => option.value === priority)?.label ??
    'Не указан'
  )
}

export function activeRequestsByType(requests: WorkRequest[]): {
  warehouse: WorkRequest[]
  repair: WorkRequest[]
} {
  const active = requests.filter(
    (request) =>
      request.status === 'new' || request.status === 'in_progress',
  )

  return {
    warehouse: active.filter(
      (request) => request.request_type === 'warehouse',
    ),
    repair: active.filter((request) => request.request_type === 'repair'),
  }
}
