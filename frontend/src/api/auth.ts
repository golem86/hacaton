import { ApiError, getCsrfToken, request, setCsrfToken } from './client'

export interface AuthUser {
  id: number
  name: string
  email: string
  role: 'user' | 'admin'
  two_factor_verified?: boolean
}

export interface AuthState { requires_2fa: boolean; user: AuthUser }

async function json<T>(path: string, init: RequestInit = {}, credentials: RequestCredentials = 'include'): Promise<T> {
  let response: Response
  try { response = await request(path, init, credentials) }
  catch (error) { throw error }
  if (!response.ok) {
    let message = `Помилка API (${response.status}).`
    try { const body = await response.json() as { detail?: unknown }; if (typeof body.detail === 'string') message = body.detail } catch {}
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
  const result = await json<AuthUser & { csrf_token: string }>('/v2/auth/2fa/verify', { method: 'POST', body: JSON.stringify({ code }) })
  setCsrfToken(result.csrf_token)
  return result
}

export function resendTwoFactor() { return json<{ status: string }>('/v2/auth/2fa/resend', { method: 'POST' }) }
export function requestPasswordReset(email: string) { return ensureCsrf().then(() => json<{ status: string }>('/v2/auth/password-reset/request', { method: 'POST', body: JSON.stringify({ email }) })) }
export function confirmPasswordReset(input: { email: string; code: string; password: string; password_confirmation: string }) { return ensureCsrf().then(() => json<{ status: string }>('/v2/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify(input) })) }
export function logoutUser() { return json<{ status: string }>('/v2/auth/logout', { method: 'POST' }) }

export async function getV2AdminJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal })
  if (!response.ok) throw new ApiError(response.status, `Помилка API (${response.status}).`)
  return response.json() as Promise<T>
}
export const getV2Json = getV2AdminJson
export async function mutateV2Json<T>(path: string, method: 'POST' | 'PATCH', body?: unknown): Promise<T> {
  const response = await request(path, { method, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!response.ok) throw new ApiError(response.status, `Помилка API (${response.status}).`)
  return response.json() as Promise<T>
}
export async function getPublicV2Json<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { signal }, 'omit')
  if (!response.ok) throw new ApiError(response.status, `Помилка API (${response.status}).`)
  return response.json() as Promise<T>
}
export async function postPublicV2Json<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { method: 'POST', signal, body: JSON.stringify(body) }, 'omit')
  if (!response.ok) throw new ApiError(response.status, `Помилка API (${response.status}).`)
  return response.json() as Promise<T>
}
