import { ApiError, readErrorBody, request, statusMessage } from './client'
import { isUserRole, type UserRole } from './auth'

/**
 * Керування користувачами й ролями (лише admin; docs/V2_HARDENING_CONTRACT.md, розділ 3 «auth»).
 * Перелік містить лише замаскований email; повний email повертає тільки пошук за точною адресою.
 */
export interface AdminUser {
  id: number
  name: string
  role: UserRole | string
  email_masked: string
  created_at: string
}

/** Результат пошуку за точним email: той самий запис, але з повною адресою. */
export interface AdminUserMatch {
  id: number
  name: string
  role: UserRole | string
  email: string
  created_at: string
  email_masked?: string
}

export interface RoleChange {
  id: number
  actor_user_id: number | null
  target_user_id: number
  old_role: string
  new_role: string
  changed_at: string
}

export const SELF_ROLE_CHANGE_MESSAGE = 'Не можна змінити власну роль.'
export const ROLE_CONFLICT_MESSAGE = 'Роль уже змінена іншим адміністратором, оновіть список.'
export const USER_NOT_FOUND_MESSAGE = 'Користувача не знайдено. Оновіть список.'
/** 403 `admin_role_server_only`: роль admin у вебі не призначає й не знімає ніхто — лише власник сервера командою. */
export const ADMIN_ROLE_SERVER_ONLY_MESSAGE = 'Роль адміністратора призначає й знімає лише власник сервера.'
/** Ролі, які адміністратор може призначити у вебі (без «Адміністратор»). */
export const WEB_ASSIGNABLE_ROLES: readonly UserRole[] = ['user', 'data_officer']
/** `actor_user_id` серверної команди (python -m app.v2_role_cli) в історії змін ролей. */
export const SERVER_ACTOR_ID = 0

const READ_MESSAGES: Partial<Record<number, string>> = {
  403: 'Керування користувачами доступне лише адміністратору.',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function errorCodes(body: { detail?: unknown; code?: unknown }): string[] {
  const values = [body.code, body.detail, isRecord(body.detail) ? body.detail.code : undefined,
    isRecord(body.detail) ? body.detail.error : undefined, isRecord(body.detail) ? body.detail.reason : undefined]
  return values.filter((value): value is string => typeof value === 'string')
}

/** 403 `self_change`: backend може передати код у `detail` (рядок або об’єкт) чи в полі `code`. */
export function isSelfChangeError(body: { detail?: unknown; code?: unknown }): boolean {
  return errorCodes(body).some(value => /self_change/.test(value))
}

/** 403 `admin_role_server_only` — у тих самих місцях, що й `self_change`. */
export function isAdminRoleServerOnlyError(body: { detail?: unknown; code?: unknown }): boolean {
  return errorCodes(body).some(value => /admin_role_server_only/.test(value))
}

/** Роль admin (призначення чи зняття) вебом не змінюється: такий запит навіть не надсилається. */
export function touchesAdminRole(expectedRole: string, newRole: string): boolean {
  return expectedRole === 'admin' || newRole === 'admin'
}

async function fail(response: Response, messages: Partial<Record<number, string>>): Promise<never> {
  const body = await readErrorBody(response)
  if (response.status === 403 && isSelfChangeError(body)) throw new ApiError(403, SELF_ROLE_CHANGE_MESSAGE)
  if (response.status === 403 && isAdminRoleServerOnlyError(body)) throw new ApiError(403, ADMIN_ROLE_SERVER_ONLY_MESSAGE)
  throw new ApiError(response.status, statusMessage(response.status, messages))
}

/** Контракт: масив. Обгортку {users|changes|items: [...]} теж приймаємо, щоб не зламатися на дрібній розбіжності. */
function extractList(body: unknown, key: string): unknown[] | null {
  if (Array.isArray(body)) return body
  if (isRecord(body) && Array.isArray(body[key])) return body[key] as unknown[]
  if (isRecord(body) && Array.isArray(body.items)) return body.items as unknown[]
  return null
}

async function readJson<T>(response: Response): Promise<T> {
  try { return await response.json() as T } catch { throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.') }
}

function isAdminUser(value: unknown): value is AdminUser {
  return isRecord(value) && Number.isSafeInteger(value.id) && typeof value.name === 'string'
    && typeof value.role === 'string' && typeof value.email_masked === 'string' && typeof value.created_at === 'string'
}

function isAdminUserMatch(value: unknown): value is AdminUserMatch {
  return isRecord(value) && Number.isSafeInteger(value.id) && typeof value.name === 'string'
    && typeof value.role === 'string' && typeof value.email === 'string' && typeof value.created_at === 'string'
}

function isRoleChange(value: unknown): value is RoleChange {
  return isRecord(value) && Number.isSafeInteger(value.id) && Number.isSafeInteger(value.target_user_id)
    && (value.actor_user_id === null || Number.isSafeInteger(value.actor_user_id))
    && typeof value.old_role === 'string' && typeof value.new_role === 'string' && typeof value.changed_at === 'string'
}

/** GET /v2/admin/users — до 500 записів із замаскованим email. */
export async function listUsers(signal?: AbortSignal): Promise<AdminUser[]> {
  const response = await request('/v2/admin/users', { signal })
  if (!response.ok) return fail(response, READ_MESSAGES)
  const list = extractList(await readJson<unknown>(response), 'users')
  if (list === null || !list.every(isAdminUser)) throw new ApiError(200, 'API повернув некоректний перелік користувачів.')
  return list
}

/**
 * POST /v2/admin/users/lookup з тілом `{"email": "..."}` і CSRF сесії — пошук за точною адресою.
 * Email іде лише в тілі запиту (не в URL, тож не потрапляє в журнали адрес). null — користувача немає (404).
 * У UI адреса не зберігається після нового пошуку.
 */
export async function findUserByEmail(email: string, signal?: AbortSignal): Promise<AdminUserMatch | null> {
  const exact = email.trim()
  if (!exact) throw new ApiError(422, 'Введіть email повністю.')
  const response = await request('/v2/admin/users/lookup', { method: 'POST', body: JSON.stringify({ email: exact }), signal })
  if (response.status === 404) return null
  if (!response.ok) return fail(response, { ...READ_MESSAGES, 422: 'Введіть коректний email повністю.' })
  const body = await readJson<unknown>(response)
  const record = Array.isArray(body) ? body[0] : body
  if (!isAdminUserMatch(record)) throw new ApiError(200, 'API повернув некоректний запис користувача.')
  return record
}

/**
 * POST /v2/admin/users/{id}/role — зміна ролі з перевіркою конкурентних змін (`expected_role`).
 * Backend в одній транзакції змінює роль і завершує всі сесії цього користувача.
 * Лише «Користувач» ↔ «Відповідальний за коди доступу»: роль admin призначає й знімає власник сервера
 * (403 `admin_role_server_only`), тож такий запит не надсилається.
 */
export async function changeUserRole(userId: number, expectedRole: string, newRole: UserRole): Promise<unknown> {
  if (!isUserRole(newRole)) throw new ApiError(422, 'Невідома роль.')
  if (touchesAdminRole(expectedRole, newRole)) throw new ApiError(403, ADMIN_ROLE_SERVER_ONLY_MESSAGE)
  const response = await request(`/v2/admin/users/${userId}/role`, {
    method: 'POST',
    body: JSON.stringify({ expected_role: expectedRole, new_role: newRole }),
  })
  if (!response.ok) {
    return fail(response, {
      403: 'Недостатньо прав для зміни ролей.',
      404: USER_NOT_FOUND_MESSAGE,
      409: ROLE_CONFLICT_MESSAGE,
      422: 'Сервер відхилив запит на зміну ролі. Оновіть список і повторіть спробу.',
    })
  }
  return response.json().catch(() => null)
}

/** POST /v2/admin/users/{id}/revoke-sessions → кількість завершених сесій. Для іншого admin — 403 `admin_role_server_only`. */
export async function revokeUserSessions(userId: number): Promise<number> {
  const response = await request(`/v2/admin/users/${userId}/revoke-sessions`, { method: 'POST' })
  if (!response.ok) return fail(response, { 403: 'Недостатньо прав для завершення сесій.', 404: USER_NOT_FOUND_MESSAGE })
  const body = await readJson<unknown>(response)
  if (!isRecord(body) || !Number.isSafeInteger(body.revoked)) throw new ApiError(200, 'API повернув некоректну відповідь.')
  return body.revoked as number
}

/** GET /v2/admin/role-changes — до 500 останніх змін ролей (append-only). */
export async function getRoleChanges(signal?: AbortSignal): Promise<RoleChange[]> {
  const response = await request('/v2/admin/role-changes', { signal })
  if (!response.ok) return fail(response, READ_MESSAGES)
  const list = extractList(await readJson<unknown>(response), 'changes')
  if (list === null || !list.every(isRoleChange)) throw new ApiError(200, 'API повернув некоректну історію змін ролей.')
  return list
}
