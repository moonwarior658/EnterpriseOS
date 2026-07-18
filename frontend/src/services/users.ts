import {
  getStoredToken,
  type CurrentUser,
} from './auth'

export type UserRecord = CurrentUser

export type CreateUserInput = {
  username: string
  display_name: string
  password: string
  is_admin: boolean
}

export type UpdateUserInput = {
  username?: string
  display_name?: string
  password?: string
  is_active?: boolean
  is_admin?: boolean
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

    throw new Error(
      errorBody?.detail ?? 'Не удалось выполнить запрос',
    )
  }

  return response.json() as Promise<T>
}

export function getUsers(): Promise<UserRecord[]> {
  return authorizedRequest<UserRecord[]>('/users')
}

export function createUser(
  input: CreateUserInput,
): Promise<UserRecord> {
  return authorizedRequest<UserRecord>('/users', {
    method: 'POST',
    body: JSON.stringify(input),
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
