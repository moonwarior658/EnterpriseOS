import {
  getStoredToken,
  type CurrentUser,
} from './auth.ts'

export type UserRecord = CurrentUser

export type CreateUserInput = {
  username: string
  display_name: string
  password?: string
  is_admin: boolean
  can_view_requests: boolean
  account_type?: 'HUMAN' | 'SERVICE'
  employee_id?: string
}

export type GeneratedCredentials = {
  username: string
  temporary_password: string
}

export type CreatedUserRecord = UserRecord & {
  temporary_password: string | null
}

export type UpdateUserInput = {
  username?: string
  display_name?: string
  password?: string
  is_active?: boolean
  is_admin?: boolean
  can_view_requests?: boolean
  reason?: string
}

async function authorizedRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getStoredToken()

  if (!token) {
    throw new Error('Сессия не найдена')
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    const detail = typeof errorBody?.detail === 'string' ? errorBody.detail : ''
    if (response.status === 403 && detail === 'Текущий пароль указан неверно') throw new Error(detail)
    if (response.status === 403) throw new Error('Недостаточно прав для этого действия')
    if (response.status === 422) throw new Error('Проверьте поля и укажите причину изменения, если она требуется')
    if (response.status === 409 && detail === 'Login already exists') throw new Error('Этот логин уже занят')
    if (response.status === 409) throw new Error('Изменение конфликтует с текущим состоянием учётной записи')
    if (response.status === 404) throw new Error('Учётная запись не найдена')
    throw new Error('Не удалось выполнить запрос')
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function changeOwnPassword(newPassword: string): Promise<void> {
  return authorizedRequest<void>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  })
}

export function getUsers(): Promise<UserRecord[]> {
  return authorizedRequest<UserRecord[]>('/users')
}

export function createUser(
  input: CreateUserInput,
): Promise<CreatedUserRecord> {
  return authorizedRequest<CreatedUserRecord>('/users', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function resetEmployeePassword(
  employeeId: string,
  reason?: string,
): Promise<GeneratedCredentials> {
  const trimmedReason = reason?.trim()
  return authorizedRequest<GeneratedCredentials>(`/employees/${employeeId}/password-reset`, {
    method: 'POST',
    body: JSON.stringify(trimmedReason ? { reason: trimmedReason } : {}),
  })
}

export function updateUser(
  userId: number,
  input: UpdateUserInput,
): Promise<UserRecord> {
  return authorizedRequest<UserRecord>(`/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}
