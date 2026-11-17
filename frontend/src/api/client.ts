const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

let csrfToken = ''
export function setCsrfToken(token: string) { csrfToken = token }
export function getCsrfToken() { return csrfToken }

export async function request(
  path: string,
  options: RequestInit = {},
  credentials: RequestCredentials = 'include',
): Promise<Response> {
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  if (options.body !== undefined && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (credentials === 'include' && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    if (!csrfToken) throw new ApiError(403, 'CSRF-токен відсутній. Оновіть сторінку й повторіть дію.')
    headers.set('X-CSRF-Token', csrfToken)
  }
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, { ...options, credentials, headers })
    if (response.status === 401 && credentials === 'include' && !path.startsWith('/v2/auth/') && typeof window !== 'undefined') {
      window.dispatchEvent(new Event('v2-session-expired'))
    }
    return response
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError(0, 'Не вдалося з’єднатися з API. Перевірте backend та мережу.')
  }
}

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
  messages: Partial<Record<number, string>> = {},
): Promise<T> {
  const response = await request(path, { signal })
  if (!response.ok) throw new ApiError(response.status, messages[response.status] ?? `Помилка API (${response.status}).`)
  try { return await response.json() as T } catch {
    throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.')
  }
}

export async function getPublicJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal }, 'omit')
  if (!response.ok) throw new ApiError(response.status, `Помилка API (${response.status}).`)
  try { return await response.json() as T } catch {
    throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.')
  }
}
