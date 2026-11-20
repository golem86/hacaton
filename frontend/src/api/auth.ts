import { ApiError, getCsrfToken, readErrorBody, request, setCsrfToken, statusMessage } from './client'

/** Серверні ролі V2 (docs/V2_HARDENING_CONTRACT.md, розділ 1). Один акаунт має одну роль. */
export type UserRole = 'user' | 'admin' | 'data_officer'
export const USER_ROLES: readonly UserRole[] = ['user', 'admin', 'data_officer']

export const ROLE_LABELS: Readonly<Record<UserRole, string>> = {
  user: 'Користувач',
  admin: 'Адміністратор',
  data_officer: 'Відповідальний за коди доступу',
}

export function isUserRole(value: unknown): value is UserRole {
  return typeof value === 'string' && (USER_ROLES as readonly string[]).includes(value)
}

/** Підпис ролі; невідоме значення показується як є. */
export function roleLabel(role: string) {
  return isUserRole(role) ? ROLE_LABELS[role] : role
}

export interface AuthUser {
  id: number
  name: string
  email: string
  role: UserRole
  two_factor_verified?: boolean
}

export interface AuthState { requires_2fa: boolean; user: AuthUser }

/** 429 на verify/resend: акаунт тимчасово заблоковано після невдалих кодів (auth.2fa_lockout). */
export const TWO_FACTOR_LOCKOUT_MESSAGE = 'Забагато невдалих спроб коду. Спробуйте пізніше або зверніться до адміністратора.'

async function json<T>(
  path: string,
  init: RequestInit = {},
  credentials: RequestCredentials = 'include',
  overrides: Partial<Record<number, string>> = {},
): Promise<T> {
  const response = await request(path, init, credentials)
  if (!response.ok) {
    const override = overrides[response.status]
    if (override) throw new ApiError(response.status, override)
    const body = await readErrorBody(response)
    // Рядок detail від auth-маршрутів — безпечний для показу; масиви валідації 422 не показуємо.
    const message = typeof body.detail === 'string' && response.status !== 413
      ? body.detail
      : statusMessage(response.status, { 401: 'Потрібен вхід до системи.' })
    throw new ApiError(response.status, message)
  }
  try { return await response.json() as T } catch { throw new ApiError(response.status, 'API повернув некоректну відповідь.') }
}

export async function ensureCsrf(): Promise<string> {
  const result = await json<{ csrf_token: string }>('/v2/auth/csrf')
  setCsrfToken(result.csrf_token)
  return result.csrf_token
}

export async function getCurrentUser(): Promise<AuthState> {
  const result = await json<AuthState>('/v2/auth/me')
  if (result.requires_2fa) return result
  return { requires_2fa: false, user: result.user }
}

export async function loginUser(input: { email: string; password: string }): Promise<AuthState> {
  if (!getCsrfToken()) await ensureCsrf()
  const result = await json<AuthState & { csrf_token?: string }>('/v2/auth/login', { method: 'POST', body: JSON.stringify(input) })
  if (result.csrf_token) setCsrfToken(result.csrf_token)
  return result
}

export async function registerUser(input: { name: string; email: string; password: string; password_confirmation: string }): Promise<void> {
  if (!getCsrfToken()) await ensureCsrf()
  await json('/v2/auth/register', { method: 'POST', body: JSON.stringify(input) })
}

export async function verifyTwoFactor(code: string): Promise<AuthUser> {
  const result = await json<AuthUser & { csrf_token: string }>('/v2/auth/2fa/verify', { method: 'POST', body: JSON.stringify({ code }) }, 'include', { 429: TWO_FACTOR_LOCKOUT_MESSAGE })
  setCsrfToken(result.csrf_token)
  return result
}

export function resendTwoFactor() { return json<{ status: string }>('/v2/auth/2fa/resend', { method: 'POST' }, 'include', { 429: TWO_FACTOR_LOCKOUT_MESSAGE }) }
export function requestPasswordReset(email: string) { return ensureCsrf().then(() => json<{ status: string }>('/v2/auth/password-reset/request', { method: 'POST', body: JSON.stringify({ email }) })) }
export function confirmPasswordReset(input: { email: string; code: string; password: string; password_confirmation: string }) { return ensureCsrf().then(() => json<{ status: string }>('/v2/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify(input) })) }
export function logoutUser() { return json<{ status: string }>('/v2/auth/logout', { method: 'POST' }) }

/**
 * Вихід на всіх пристроях: сервер видаляє всі сесії поточного користувача (сесія + CSRF).
 * 401 означає, що сесію вже завершено, — для UI це той самий успішний вихід.
 */
export async function logoutAllSessions(): Promise<{ status: string }> {
  try {
    return await json<{ status: string }>('/v2/auth/logout-all', { method: 'POST' })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return { status: 'logged_out_all' }
    throw error
  }
}

export async function getV2AdminJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal })
  if (!response.ok) throw new ApiError(response.status, statusMessage(response.status))
  return response.json() as Promise<T>
}
export const getV2Json = getV2AdminJson
export async function mutateV2Json<T>(path: string, method: 'POST' | 'PATCH', body?: unknown): Promise<T> {
  const response = await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!response.ok) throw new ApiError(response.status, statusMessage(response.status))
  return response.json() as Promise<T>
}
export async function getPublicV2Json<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal }, 'omit')
  if (!response.ok) throw new ApiError(response.status, `Помилка API (${response.status}).`)
  return response.json() as Promise<T>
}
export async function postPublicV2Json<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { method: 'POST', signal, body: JSON.stringify(body) }, 'omit')
  if (!response.ok) throw new ApiError(response.status, statusMessage(response.status))
  return response.json() as Promise<T>
}
