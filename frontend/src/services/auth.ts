export type AuthToken = {
  access_token: string
  token_type: string
}

export type CurrentUser = {
  id: number
  username: string
  display_name: string
  avatar_url: string | null
  is_active: boolean
  is_admin: boolean
  created_at: string
}

const TOKEN_KEY = 'eos_access_token'

export async function loginRequest(
  username: string,
  password: string,
): Promise<AuthToken> {
  const body = new URLSearchParams({
    username,
    password,
  })

  const response = await fetch('/api/auth/token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Accept: 'application/json',
    },
    body,
  })

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Неверный логин или пароль')
    }

    throw new Error('Не удалось подключиться к системе')
  }

  return response.json() as Promise<AuthToken>
}

export async function getCurrentUser(
  token: string,
): Promise<CurrentUser> {
  const response = await fetch('/api/auth/me', {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error('Session is invalid')
  }

  return response.json() as Promise<CurrentUser>
}

export function getStoredToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function storeToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token)
}

export function removeStoredToken(): void {
  sessionStorage.removeItem(TOKEN_KEY)
}
