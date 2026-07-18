export type ApiHealth = {
  status: string
  service: string
  version: string
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: {
      Accept: 'application/json',
    },
  })

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export function getApiHealth(): Promise<ApiHealth> {
  return request<ApiHealth>('/health')
}
