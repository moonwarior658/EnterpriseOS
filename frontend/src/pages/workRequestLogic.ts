import type {
  PublicRepairRequestInput,
  RepairPriority,
  WorkRequest,
  WorkRequestStatus,
} from '../services/requests.ts'

export const DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS = 10_000

export const DEPARTMENTS = [
  'М15',
  'М35',
  'М6А',
  'Цех ГХ',
  'Бар ГХ',
  'Кухня',
  'Авто',
] as const

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
  Record<keyof WorkRequestFormValues | 'photos', string>
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

function photoIdentity(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}:${file.type}`
}

export function addRepairPhotos(
  current: File[],
  incoming: File[],
): { files: File[]; error: string | null } {
  const files = [...current]
  const identities = new Set(current.map(photoIdentity))
  let error: string | null = null

  for (const file of incoming) {
    if (identities.has(photoIdentity(file))) {
      error ??= `Файл «${file.name}» уже добавлен`
      continue
    }
    if (!ALLOWED_PHOTO_TYPES.includes(
      file.type as (typeof ALLOWED_PHOTO_TYPES)[number],
    )) {
      error ??= `Файл «${file.name}» имеет неподдерживаемый формат`
      continue
    }
    if (file.size > MAX_PHOTO_SIZE) {
      error ??= `Файл «${file.name}» больше 8 МБ`
      continue
    }
    if (files.length >= MAX_PHOTO_COUNT) {
      error ??= 'Можно прикрепить не более 5 фотографий'
      continue
    }
    identities.add(photoIdentity(file))
    files.push(file)
  }
  return { files, error }
}

export function formatFileSize(size: number): string {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} КБ`
  return `${(size / (1024 * 1024)).toFixed(1)} МБ`
}

export async function submitPublicRepairRequest(
  values: WorkRequestFormValues,
  photos: File[],
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

  if (!values.department) errors.department = 'Выберите подразделение'
  if (!values.category) errors.category = 'Выберите категорию ремонта'
  if (!values.priority) {
    errors.priority = 'Выберите приоритет'
  }
  if (!description) errors.description = 'Опишите проблему'
  const photoError = validateRepairPhotos(photos)
  if (photoError) errors.photos = photoError

  if (Object.keys(errors).length > 0) {
    return { status: 'validation', errors }
  }

  guard.active = true
  try {
    const request = await createRepair(
      {
        request_type: 'repair',
        department: values.department,
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
