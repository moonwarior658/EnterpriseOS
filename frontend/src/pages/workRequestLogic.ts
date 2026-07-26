import type {
  PublicRepairRequestInput,
  PublicWarehouseRequestInput,
  RepairPriority,
  WarehouseCategory,
  WorkRequest,
  WorkRequestStatus,
  WorkRequestType,
} from '../services/requests.ts'

export const DEPARTMENTS = [
  'М15',
  'М35',
  'М6А',
  'Цех ГХ',
  'Бар ГХ',
  'Кухня',
  'Авто',
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
  authorName: string
  category: string
  priority: string
  description: string
}

export type WorkRequestFormErrors = Partial<
  Record<keyof WorkRequestFormValues | 'photos', string>
>

export const EMPTY_WORK_REQUEST_FORM: WorkRequestFormValues = {
  department: '',
  authorName: '',
  category: '',
  priority: '',
  description: '',
}

export type SubmissionGuard = { active: boolean }

export function createSubmissionGuard(): SubmissionGuard {
  return { active: false }
}

export const MAX_PHOTO_COUNT = 5
export const MAX_PHOTO_SIZE = 8 * 1024 * 1024
export const ALLOWED_PHOTO_TYPES = [
  'image/jpeg',
  'image/png',
  'image/webp',
] as const

export function validateRepairPhotos(files: File[]): string | null {
  if (files.length > MAX_PHOTO_COUNT) {
    return 'Можно прикрепить не более 5 фотографий'
  }
  if (
    files.some(
      (file) =>
        !ALLOWED_PHOTO_TYPES.includes(
          file.type as (typeof ALLOWED_PHOTO_TYPES)[number],
        ),
    )
  ) {
    return 'Допустимы только фотографии JPEG, PNG или WebP'
  }
  if (files.some((file) => file.size > MAX_PHOTO_SIZE)) {
    return 'Размер одной фотографии не должен превышать 8 МБ'
  }
  return null
}

export async function submitPublicWorkRequest(
  requestType: WorkRequestType,
  values: WorkRequestFormValues,
  photos: File[],
  createWarehouse: (
    input: PublicWarehouseRequestInput,
  ) => Promise<WorkRequest>,
  createRepair: (
    input: PublicRepairRequestInput,
    photos: File[],
  ) => Promise<WorkRequest>,
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
  const authorName = values.authorName.trim()

  if (!values.department) errors.department = 'Выберите подразделение'
  if (!authorName) errors.authorName = 'Укажите ваше имя'
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
  if (requestType === 'repair') {
    const photoError = validateRepairPhotos(photos)
    if (photoError) errors.photos = photoError
  }

  if (Object.keys(errors).length > 0) {
    return { status: 'validation', errors }
  }

  guard.active = true
  try {
    const request =
      requestType === 'warehouse'
        ? await createWarehouse({
            request_type: 'warehouse',
            department: values.department,
            author_name: authorName,
            description,
            warehouse_category: values.category as WarehouseCategory,
          })
        : await createRepair(
            {
              request_type: 'repair',
              department: values.department,
              author_name: authorName,
              description,
              repair_category: values.category,
              priority: values.priority as RepairPriority,
            },
            photos,
          )
    return { status: 'success', request }
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

export function requestTypeLabel(type: WorkRequestType): string {
  return type === 'warehouse' ? 'Заявка на склад' : 'Заявка на ремонт'
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

export function activeRequestCountLabel(count: number): string {
  if (count === 0) return 'Нет активных заявок'
  const mod100 = count % 100
  const mod10 = count % 10
  if (mod100 >= 11 && mod100 <= 14) {
    return `${count} активных заявок`
  }
  if (mod10 === 1) return `${count} активная заявка`
  if (mod10 >= 2 && mod10 <= 4) return `${count} активные заявки`
  return `${count} активных заявок`
}

export function isActiveRequest(request: WorkRequest): boolean {
  return request.status === 'new' || request.status === 'in_progress'
}

export function sortWorkRequests(requests: WorkRequest[]): WorkRequest[] {
  return [...requests].sort((left, right) => {
    const activityDifference =
      Number(isActiveRequest(right)) - Number(isActiveRequest(left))
    if (activityDifference !== 0) return activityDifference
    return (
      new Date(right.created_at).getTime() -
      new Date(left.created_at).getTime()
    )
  })
}

export function activeRequestsByType(requests: WorkRequest[]): {
  warehouse: WorkRequest[]
  repair: WorkRequest[]
} {
  const active = requests.filter(isActiveRequest)
  return {
    warehouse: active.filter(
      (request) => request.request_type === 'warehouse',
    ),
    repair: active.filter((request) => request.request_type === 'repair'),
  }
}
