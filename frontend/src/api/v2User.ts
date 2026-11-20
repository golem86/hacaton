import { getV2AdminJson, mutateV2Json } from './auth'
import { ApiError, getJson } from './client'

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

/** «Результати підрозділу» (GET /v2/user/unit-results): підрозділ визначає лише сервер, клієнт його не передає. */
export type UnitResultsStatus = 'available' | 'no_unit' | 'no_closed_cycle' | 'insufficient_data'
export type UnitComponentStatus = 'available' | 'suppressed' | 'insufficient_data'
export interface UnitComponentResult { code: string; name: string; score: number | null; status: UnitComponentStatus }
export interface UnitResults {
  status: UnitResultsStatus
  assessment: { id: number; name: string; status: 'closed' } | null
  unit: { id: number; name: string } | null
  min_group_size: number
  /** Лише при status === 'available'; інакше null. */
  respondents: number | null
  /** Порожній, якщо status !== 'available'. */
  components: UnitComponentResult[]
  available_assessments: { id: number; name: string }[]
  methodology_version: string
}

const UNIT_RESULTS_STATUSES: readonly UnitResultsStatus[] = ['available', 'no_unit', 'no_closed_cycle', 'insufficient_data']
const UNIT_COMPONENT_STATUSES: readonly UnitComponentStatus[] = ['available', 'suppressed', 'insufficient_data']

export const UNIT_RESULTS_MESSAGES: Readonly<Partial<Record<number, string>>> = {
  403: 'Немає доступу до результатів підрозділу.',
  404: 'Цикл оцінювання не знайдено.',
  409: 'Результати доступні лише для закритих циклів оцінювання.',
  503: 'Сервіс результатів тимчасово недоступний. Спробуйте пізніше.',
}

const INVALID_UNIT_RESULTS = 'API повернув некоректні результати підрозділу.'
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)
const isId = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value > 0
const isCount = (value: unknown): value is number => typeof value === 'number' && Number.isInteger(value) && value >= 0
const text = (value: unknown) => typeof value === 'string' ? value : ''

function parseNamed(value: unknown): { id: number; name: string } | null {
  return isRecord(value) && isId(value.id) ? { id: value.id, name: text(value.name) || `#${value.id}` } : null
}

function parseComponent(value: unknown): UnitComponentResult | null {
  if (!isRecord(value) || typeof value.code !== 'string' || !value.code) return null
  const status = (UNIT_COMPONENT_STATUSES as readonly unknown[]).includes(value.status) ? value.status as UnitComponentStatus : 'insufficient_data'
  const score = status === 'available' && typeof value.score === 'number' && Number.isFinite(value.score) ? Math.min(100, Math.max(0, value.score)) : null
  // Бал без числа не показуємо як «доступний»: такий компонент вважаємо прихованим.
  return { code: value.code, name: text(value.name), score, status: status === 'available' && score === null ? 'suppressed' : status }
}

/**
 * Нормалізує відповідь сервера. Дані поза статусом «available» (респонденти, компоненти) відкидаються,
 * а прихований компонент ніколи не має балу — навіть якщо сервер помилково його надіслав.
 */
export function parseUnitResults(value: unknown): UnitResults {
  if (!isRecord(value) || !(UNIT_RESULTS_STATUSES as readonly unknown[]).includes(value.status)) throw new ApiError(200, INVALID_UNIT_RESULTS)
  const status = value.status as UnitResultsStatus
  const assessment = parseNamed(value.assessment)
  const unit = status === 'no_unit' ? null : parseNamed(value.unit)
  const available = status === 'available'
  const components = available && Array.isArray(value.components)
    ? value.components.map(parseComponent).filter((item): item is UnitComponentResult => item !== null)
    : []
  return {
    status,
    assessment: assessment ? { ...assessment, status: 'closed' } : null,
    unit,
    min_group_size: isCount(value.min_group_size) ? value.min_group_size : 0,
    respondents: available && isCount(value.respondents) ? value.respondents : null,
    components,
    available_assessments: Array.isArray(value.available_assessments)
      ? value.available_assessments.map(parseNamed).filter((item): item is { id: number; name: string } => item !== null)
      : [],
    methodology_version: text(value.methodology_version),
  }
}

export function unitResultsPath(assessmentId?: number | null) {
  return isId(assessmentId) ? `/v2/user/unit-results?assessment_id=${assessmentId}` : '/v2/user/unit-results'
}

export async function getUnitResults(assessmentId?: number | null, signal?: AbortSignal): Promise<UnitResults> {
  return parseUnitResults(await getJson<unknown>(unitResultsPath(assessmentId), signal, UNIT_RESULTS_MESSAGES))
}
