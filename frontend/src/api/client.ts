const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Повідомлення, коли сервер завершив сесію (відкликання сесій, зміна ролі, вихід на всіх пристроях). */
export const SESSION_EXPIRED_MESSAGE = 'Сесію завершено, увійдіть знову.'
/** 413: тіло запиту перевищило ліміт сервера (V2_MAX_BODY_BYTES). */
export const PAYLOAD_TOO_LARGE_MESSAGE = 'Запит завеликий. Скоротіть дані й повторіть спробу.'
/** 429 без уточнення від маршруту. */
export const TOO_MANY_REQUESTS_MESSAGE = 'Забагато запитів. Спробуйте пізніше.'

/**
 * Типові повідомлення для статусів, спільних для всіх маршрутів. Маршрут може задати власні.
 * 422 навмисно не розкриває деталей: сервер більше не повертає `input`, а UI ніколи не показує масив detail.
 */
export const DEFAULT_STATUS_MESSAGES: Readonly<Partial<Record<number, string>>> = {
  401: SESSION_EXPIRED_MESSAGE,
  413: PAYLOAD_TOO_LARGE_MESSAGE,
  422: 'Сервер відхилив дані запиту. Перевірте поля й повторіть спробу.',
  429: TOO_MANY_REQUESTS_MESSAGE,
}

export function statusMessage(status: number, messages: Partial<Record<number, string>> = {}): string {
  return messages[status] ?? DEFAULT_STATUS_MESSAGES[status] ?? `Помилка API (${status}).`
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
    // 401 після відкликання сесії чи зміни ролі: застосунок повертає на сторінку входу.
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
  if (!response.ok) throw new ApiError(response.status, statusMessage(response.status, messages))
  try { return await response.json() as T } catch {
    throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.')
  }
}

export async function getPublicJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal }, 'omit')
  if (!response.ok) throw new ApiError(response.status, statusMessage(response.status, { 401: 'Потрібен вхід до системи.' }))
  try { return await response.json() as T } catch {
    throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.')
  }
}

/** Безпечно читає `detail` з тіла помилки: рядок або об’єкт; масиви валідації не повертаються. */
export async function readErrorBody(response: Response): Promise<{ detail?: unknown; code?: unknown }> {
  try {
    const body: unknown = await response.json()
    if (body !== null && typeof body === 'object' && !Array.isArray(body)) return body as { detail?: unknown; code?: unknown }
  } catch {
    // Порожня або не-JSON відповідь отримує повідомлення за статусом.
  }
  return {}
}
