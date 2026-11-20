import { getV2AdminJson, mutateV2Json } from './auth'
import { ApiError, request, statusMessage } from './client'

export interface PersonalQuestion { id: string; component: string; prompt: string; hint: string }
export interface PersonalAssessment { id: string; name: string; duration: string; /** Дата створення в каталозі, ISO 8601 з поясом. */ created_at: string; opens_at: string; closes_at: string; status: 'open' | 'unavailable'; questions: PersonalQuestion[] }
export interface PersonalAttempt { id: string; assessment_id: string; assessment_name: string; status: 'draft' | 'completed'; answers: Record<string, number>; started_at: string; completed_at: string | null; updated_at: string }
export interface PersonalStats { completed_tests: number; responses_total: number; average_response: number | null; official_index: number | null }
export const getPersonalAssessments = (signal?: AbortSignal) => getV2AdminJson<PersonalAssessment[]>('/v2/user/assessments', signal)
export const getPersonalAttempts = (signal?: AbortSignal) => getV2AdminJson<PersonalAttempt[]>('/v2/user/attempts', signal)
export const getPersonalStats = (signal?: AbortSignal) => getV2AdminJson<PersonalStats>('/v2/user/stats', signal)
export const createPersonalAttempt = (input: { assessment_id: string; answers?: Record<string, number> }) => mutateV2Json<PersonalAttempt>('/v2/user/attempts', 'POST', { ...input, status: 'draft' })
export const savePersonalDraft = (attemptId: string, input: { assessment_id: string; answers: Record<string, number> }) => mutateV2Json<PersonalAttempt>(`/v2/user/attempts/${encodeURIComponent(attemptId)}`, 'PATCH', { ...input, status: 'draft' })
export const completePersonalAttempt = (attemptId: string, input: { answers: Record<string, number> }) => mutateV2Json<PersonalAttempt>(`/v2/user/attempts/${encodeURIComponent(attemptId)}/complete`, 'POST', input)

/* ---------- Результати підрозділу: GET /v2/user/unit-results ---------- */

export type UnitPrivacyStatus = 'available' | 'suppressed' | 'no_unit'
export type UnitComponentStatus = 'available' | 'suppressed' | 'insufficient_data'
export interface UnitComponentResult { code: string; name: string; score: number | null; status: UnitComponentStatus }
export interface UnitResults {
  assessment: { id: number; name: string; status: 'closed' }
  /** Підрозділ, призначений власником сервера; null — не призначено. */
  unit: string | null
  methodology_version: string
  /** Мінімальний розмір групи k. */
  min_group_size: number
  privacy_status: UnitPrivacyStatus
  /** Кількість відповідей; лише коли privacy_status === 'available'. */
  responses: number | null
  components: UnitComponentResult[]
}

export const UNIT_RESULTS_NOT_CLOSED_MESSAGE = 'Результати з’являться після закриття циклу.'
export const UNIT_RESULTS_INVALID_MESSAGE = 'API повернув некоректну відповідь. Спробуйте пізніше.'
const UNIT_RESULTS_MESSAGES: Partial<Record<number, string>> = {
  403: 'Перегляд результатів підрозділу доступний лише користувачам.',
  404: 'Цикл не знайдено.',
  409: UNIT_RESULTS_NOT_CLOSED_MESSAGE,
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
const isPositiveId = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0

function parseUnitComponent(value: unknown, groupAvailable: boolean): UnitComponentResult | null {
  if (!isPlainRecord(value) || typeof value.code !== 'string' || !value.code || typeof value.name !== 'string') return null
  const { status, score } = value
  if (status === 'available') {
    // Бал компонента дозволений лише для доступної групи й лише на шкалі 0–100.
    if (!groupAvailable || typeof score !== 'number' || !Number.isFinite(score) || score < 0 || score > 100) return null
    return { code: value.code, name: value.name, score, status }
  }
  if (status !== 'suppressed' && status !== 'insufficient_data') return null
  // Приховане значення не може надходити разом з балом.
  if (score !== null) return null
  return { code: value.code, name: value.name, score: null, status }
}

/** Перевіряє форму відповіді; некоректна або суперечлива відповідь повертає null. */
export function parseUnitResults(value: unknown, assessmentId?: number): UnitResults | null {
  if (!isPlainRecord(value) || !isPlainRecord(value.assessment)) return null
  const { assessment } = value
  if (!isPositiveId(assessment.id) || typeof assessment.name !== 'string' || assessment.status !== 'closed') return null
  if (assessmentId !== undefined && assessment.id !== assessmentId) return null
  if (typeof value.methodology_version !== 'string' || !isPositiveId(value.min_group_size)) return null
  const privacy = value.privacy_status
  if (privacy !== 'available' && privacy !== 'suppressed' && privacy !== 'no_unit') return null
  if (privacy === 'no_unit' ? value.unit !== null : typeof value.unit !== 'string' || !value.unit) return null
  let responses: number | null = null
  if (privacy === 'available') {
    if (!Number.isSafeInteger(value.responses) || (value.responses as number) < 0) return null
    responses = value.responses as number
  } else if (value.responses !== null && value.responses !== undefined) {
    // Кількість для прихованої групи не показується за жодних умов.
    return null
  }
  if (!Array.isArray(value.components)) return null
  const codes = new Set<string>()
  const components: UnitComponentResult[] = []
  for (const item of value.components) {
    const component = parseUnitComponent(item, privacy === 'available')
    if (!component || codes.has(component.code)) return null
    codes.add(component.code)
    components.push(component)
  }
  return {
    assessment: { id: assessment.id, name: assessment.name, status: 'closed' },
    unit: privacy === 'no_unit' ? null : value.unit as string,
    methodology_version: value.methodology_version,
    min_group_size: value.min_group_size,
    privacy_status: privacy,
    responses,
    components,
  }
}

/**
 * Агреговані результати підрозділу користувача за закритий цикл.
 * Підрозділ визначає сервер; клієнт передає лише assessment_id. Текст `detail` сервера не показується.
 */
export async function getUnitResults(assessmentId: number, signal?: AbortSignal): Promise<UnitResults> {
  if (!isPositiveId(assessmentId)) throw new ApiError(400, 'Оберіть цикл оцінювання.')
  const response = await request(`/v2/user/unit-results?assessment_id=${encodeURIComponent(String(assessmentId))}`, { signal })
  if (!response.ok) throw new ApiError(response.status, statusMessage(response.status, UNIT_RESULTS_MESSAGES))
  let body: unknown
  try { body = await response.json() } catch { throw new ApiError(response.status, UNIT_RESULTS_INVALID_MESSAGE) }
  const result = parseUnitResults(body, assessmentId)
  if (!result) throw new ApiError(response.status, UNIT_RESULTS_INVALID_MESSAGE)
  return result
}
