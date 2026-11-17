const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export type ApiRole = 'manager' | 'respondent'

interface ApiRequestOptions {
  method?: 'GET' | 'POST'
  headers?: Record<string, string>
  body?: string
  signal?: AbortSignal
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function request(path: string, options: ApiRequestOptions = {}, role: ApiRole = 'manager'): Promise<Response> {
  const { headers, ...init } = options
  try {
    return await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      headers: { ...headers, 'X-Role': role },
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError(0, 'Не вдалося з’єднатися з API. Перевірте запуск backend та мережу.')
  }
}

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
  messages: Partial<Record<number, string>> = {},
  role: ApiRole = 'manager',
): Promise<T> {
  const response = await request(path, { signal }, role)

  if (!response.ok) {
    throw new ApiError(response.status, messages[response.status] ?? `Помилка API (${response.status}). Спробуйте ще раз.`)
  }

  try {
    return await response.json() as T
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.')
  }
}
