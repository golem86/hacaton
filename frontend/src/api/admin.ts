import { ApiError, readErrorBody, request, statusMessage } from './client'
import type { Assessment } from './assessments'

async function json<T>(path: string, init: RequestInit = {}, signal?: AbortSignal, messages: Partial<Record<number, string>> = {}): Promise<T> {
  const response = await request(path, { ...init, signal })
  if (!response.ok) {
    let message = statusMessage(response.status, messages)
    if (messages[response.status] === undefined) {
      const body = await readErrorBody(response)
      // Рядок detail безпечний для показу; масиви валідації 422 (без input) не показуємо.
      if (typeof body.detail === 'string' && ![401, 413, 429].includes(response.status)) message = body.detail
    }
    if (response.status === 501) message = 'Функція очікує окремого погодженого API.'
    if (response.status === 503) message = 'Сервіс тимчасово недоступний.'
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export interface AuditEvent { id: number; created_at: string; actor_role: string; action: string; assessment_id: number | null; details: Record<string, number> }
export const getAuditEvents = (signal?: AbortSignal) => json<AuditEvent[]>('/api/audit-events?limit=100', {}, signal)

/** Строк дії кодів за замовчуванням у backend (`expires_days`, 1..365). */
export const DEFAULT_CODE_EXPIRY_DAYS = 14
export const MAX_CODES_PER_REQUEST = 500
export const MAX_CODE_EXPIRY_DAYS = 365

/** Повідомлення для видачі кодів (POST …/tokens — ролі admin і data_officer). */
export const TOKEN_ISSUE_MESSAGES: Readonly<Partial<Record<number, string>>> = {
  403: 'Коди доступу видають лише адміністратор і відповідальний за коди доступу (data_officer).',
  404: 'Цикл не знайдено. Оновіть перелік циклів.',
  409: 'Цикл не відкритий — коди не видано.',
}

/**
 * Видає одноразові коди. Відповідь `{"tokens":[…]}` містить відкриті коди лише один раз:
 * сервер зберігає тільки їхній хеш, тож повторно показати ті самі коди неможливо.
 */
export const issueAccessTokens = (assessmentId: number, count: number, category?: string, expiresDays?: number) => {
  const params = new URLSearchParams({ count: String(count) })
  if (category) params.set('category', category)
  if (expiresDays !== undefined) params.set('expires_days', String(expiresDays))
  return json<{ tokens: string[] }>(`/api/assessments/${assessmentId}/tokens?${params.toString()}`, { method: 'POST' }, undefined, TOKEN_ISSUE_MESSAGES)
}
export const createCycle = (body: object) => json<Assessment>('/api/assessments', { method: 'POST', body: JSON.stringify(body) })
export const activateCycle = (id: number) => json<Assessment>(`/api/assessments/${id}/activate`, { method: 'POST' })
export const closeCycle = (id: number) => json<Assessment>(`/api/assessments/${id}/close`, { method: 'POST' })

/** Група розбивки участі (закритий цикл): категорія або категорія × підрозділ. Приховані групи не перелічуються. */
export interface ParticipationGroup { category: string; unit?: string | null; responses: number | null }

export interface Participation {
  status: string
  tokens_issued: number
  tokens_unused: number | null
  responses_total: number | null
  participation_percent: number | null
  /**
   * false у відкритому циклі: `responses_total` і `tokens_unused` округлено вниз до кратного 5
   * і показано лише якщо ≥ k. true у закритому циклі (точні значення).
   */
  counts_exact: boolean
  /** Розбивка (лише закритий цикл); null, якщо розбивки немає. */
  groups: ParticipationGroup[] | null
  /** Частину груп розбивки приховано (менше k анкет). */
  suppressed: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

const nullableCount = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null

/**
 * Приводить відповідь /participation до нового контракту. Відповідь старого backend (без `counts_exact`)
 * вважається точною; групи старого формату з `hidden: true` відкидаються разом із назвами.
 */
export function normalizeParticipation(raw: unknown): Participation {
  if (!isRecord(raw)) throw new ApiError(200, 'API повернув некоректну відповідь участі.')
  const rawGroups = Array.isArray(raw.groups) ? raw.groups : null
  const groups = rawGroups === null ? null : rawGroups
    .filter(item => isRecord(item) && item.hidden !== true && typeof item.category === 'string')
    .map(item => {
      const group = item as Record<string, unknown>
      return { category: group.category as string, ...(typeof group.unit === 'string' ? { unit: group.unit } : {}), responses: nullableCount(group.responses) }
    })
  const suppressed = raw.suppressed === true || raw.groups_suppressed === true
    || (rawGroups !== null && groups !== null && groups.length < rawGroups.length)
  return {
    status: typeof raw.status === 'string' ? raw.status : 'unknown',
    tokens_issued: nullableCount(raw.tokens_issued) ?? 0,
    tokens_unused: nullableCount(raw.tokens_unused),
    responses_total: nullableCount(raw.responses_total),
    participation_percent: nullableCount(raw.participation_percent),
    counts_exact: raw.counts_exact !== false,
    groups,
    suppressed,
  }
}

/** Участь: ролі admin і data_officer. `byUnit` — розбивка категорія × підрозділ (лише закритий цикл). */
export async function getParticipation(id: number, options: { byUnit?: boolean; signal?: AbortSignal } = {}): Promise<Participation> {
  const query = options.byUnit ? '?by_unit=true' : ''
  return normalizeParticipation(await json<unknown>(`/api/assessments/${id}/participation${query}`, {}, options.signal, {
    403: 'Для вашої ролі дані участі недоступні.',
    404: 'Цикл не знайдено. Оновіть перелік циклів.',
  }))
}
