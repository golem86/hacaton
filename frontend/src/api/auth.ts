const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export interface AuthUser {
  id: number
  name: string
  email: string
  role: 'user' | 'admin'
}

export interface AuthSession {
  requires_2fa: boolean
  user: AuthUser
}

function normalizeSession(payload: AuthSession | AuthUser): AuthSession {
  if ('requires_2fa' in payload && payload.user) return payload
    throw new AuthApiError(426, 'Сервіс автентифікації потребує оновлення. Спробуйте ще раз або зверніться до адміністратора.')
}

export class AuthApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'AuthApiError'
  }
}

let csrfToken = ''

async function readError(response: Response) {
  try {
    const payload = await response.json() as { detail?: string }
    return payload.detail ?? `Помилка API (${response.status}).`
  } catch {
    return `Помилка API (${response.status}).`
  }
}

async function request<T>(path: string, options: RequestInit = {}, credentials: RequestCredentials = 'include'): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, { ...options, credentials, headers: { 'Content-Type': 'application/json', ...(options.headers ?? {}) } })
  } catch {
    throw new AuthApiError(0, 'Не вдалося підключитися до сервісу автентифікації. Перевірте з’єднання та спробуйте ще раз.')
  }
  if (!response.ok) throw new AuthApiError(response.status, await readError(response))
  return await response.json() as T
}

export async function ensureCsrf() {
  const response = await request<{ csrf_token: string }>('/v2/auth/csrf')
  csrfToken = response.csrf_token
}

async function mutate<T>(path: string, body?: unknown): Promise<T> {
  if (!csrfToken) await ensureCsrf()
  return request<T>(path, { method: 'POST', headers: { 'X-CSRF-Token': csrfToken }, body: body === undefined ? undefined : JSON.stringify(body) })
}

export function getCurrentUser(): Promise<AuthSession> {
  return request<AuthSession | AuthUser>('/v2/auth/me').then(normalizeSession)
}

export function registerUser(input: { name: string; email: string; password: string; password_confirmation: string }): Promise<AuthUser> {
  return mutate<AuthUser>('/v2/auth/register', input)
}

export function loginUser(input: { email: string; password: string }): Promise<AuthSession> {
  return mutate<AuthSession | AuthUser>('/v2/auth/login', input).then(normalizeSession)
}

export function verifyTwoFactor(code: string): Promise<AuthUser> {
  return mutate<AuthUser>('/v2/auth/2fa/verify', { code })
}

export function resendTwoFactor(): Promise<{ status: string }> {
  return mutate<{ status: string }>('/v2/auth/2fa/resend')
}

export function requestPasswordReset(email: string): Promise<{ status: string }> {
  return mutate<{ status: string }>('/v2/auth/password-reset/request', { email })
}

export function confirmPasswordReset(input: { email: string; code: string; password: string; password_confirmation: string }): Promise<{ status: string }> {
  return mutate<{ status: string }>('/v2/auth/password-reset/confirm', input)
}

export function logoutUser(): Promise<{ status: string }> {
  return mutate<{ status: string }>('/v2/auth/logout')
}

export async function getV2AdminJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { signal })
}

export async function getV2Json<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { signal })
}

export async function mutateV2Json<T>(path: string, method: 'POST' | 'PATCH', body?: unknown): Promise<T> {
  if (!csrfToken) await ensureCsrf()
  return request<T>(path, {
    method,
    headers: { 'X-CSRF-Token': csrfToken },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function getPublicV2Json<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { signal }, 'omit')
}

export function postPublicV2Json<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: 'POST', signal, body: JSON.stringify(body) }, 'omit')
}
