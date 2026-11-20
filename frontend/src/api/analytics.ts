import { ApiError, getJson } from './client'

export const DEMO_METHODOLOGY = 'team-results-demo-0.1'

export interface Methodology {
  version: string
  approval_status: string
  synthetic_only: boolean
  official: boolean
  formula: string
  weights: Record<string, string>
  limitations: string[]
  /** Optional, not validated: e.g. 'no_index_no_reweighting'. */
  missing?: string
  /** Optional, not validated: SHA-256 of the rule configuration. */
  config_sha256?: string
}

export interface IndexComponent {
  code: string
  name: string
  score: number | null
  weight: number
  contribution: number | null
  status: 'ok' | 'missing' | 'suppressed'
}

export interface IntegrityIndex {
  assessment: { id: number; name: string; status: 'closed' }
  methodology_version: string
  approval_status: string
  synthetic_only: boolean
  official: boolean
  status: 'ok' | 'insufficient_data' | 'suppressed'
  index: number | null
  components: IndexComponent[]
  warnings: string[]
}

/**
 * Inputs of the rule that produced a proposal. The shape depends on `rule_id`;
 * unknown extra fields are allowed and kept.
 * - DATA_QUALITY_V1: `{ status }` ('missing' | 'suppressed')
 * - LOW_SCORE_LT_50_V1: `{ score, threshold }`
 * - CATEGORY_GAP_GE_25_V1: the category comparison object
 *   (`gap_points` = left_category score − right_category score)
 */
export interface RecommendationBasis {
  [key: string]: unknown
  status?: string
  score?: number
  threshold?: number
  component_code?: string
  left_category?: string
  right_category?: string
  gap_points?: number | null
  gap_exact?: string | null
  flag?: boolean | null
  threshold_points?: number
  interpretation?: string
}

/** Hashes of the rule configuration and input data; not validated. */
export interface AnalyticsAudit {
  [key: string]: unknown
  config_sha256?: string
  input_sha256?: string
}

export interface Recommendation {
  id: string
  rule_id: string
  component_code: string
  text: string
  status: 'proposed'
  requires_human_decision: boolean
  /** Optional additions (backend sends them; older payloads may not). */
  assessment_id?: number
  basis?: RecommendationBasis
  audit?: AnalyticsAudit
  owner_role?: string | null
  due_date?: string | null
}

/**
 * Objective indicator shown next to the self-assessment score. Context only:
 * units differ, so the backend never computes a numeric gap (`gap_points` is null).
 */
export interface ObjectiveContextItem {
  component_code: string
  /** Indicator name, not the component name. */
  name: string
  /** Component self-assessment score 0–100; null when hidden or missing. */
  survey_score: number | null
  /** Only a confirmed value; null when unverified or missing. */
  objective_value: number | null
  status: 'ok' | 'unverified'
  comparison_type?: string
  gap_points?: number | null
  reason?: string
}

export interface Recommendations {
  assessment: { id: number; name: string; status: 'closed' }
  methodology_version: string
  approval_status: string
  proposals: Recommendation[]
  persistence: string
  objective_context?: ObjectiveContextItem[]
  audit?: AnalyticsAudit
}

export interface CategoryComparison {
  component_code: string
  left_category: string
  right_category: string
  status: 'ok' | 'unavailable'
  gap_points: number | null
  flag: boolean | null
  interpretation: string
}

export interface PeriodComparison {
  before_assessment: { id: number; name: string; status: 'closed' }
  after_assessment: { id: number; name: string; status: 'closed' }
  status: 'limited_comparability' | 'unavailable'
  change_points: number | null
  components: { component_code: string; change_points: number | null }[]
  warnings: string[]
}

export interface Comparisons {
  assessment: { id: number; name: string; status: 'closed' }
  methodology_version: string
  category_comparisons: CategoryComparison[]
  period_comparison: PeriodComparison | null
}

const messages = {
  401: 'Сесію завершено або вхід не підтверджено. Увійдіть знову.',
  403: 'Для вашої ролі аналітика недоступна.',
  404: 'Цикл або версію методики не знайдено.',
  409: 'Аналітика доступна лише для закритого циклу з відповідними компонентами й вагами.',
  422: 'Параметри аналітики не відповідають контракту API.',
  503: 'Цей аналітичний модуль не ввімкнений у поточній конфігурації сервера. Результат не сформовано; основні агрегати циклу доступні окремо.',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isClosedAssessment(value: unknown, id?: number): boolean {
  return isRecord(value) && value.status === 'closed' && Number.isSafeInteger(value.id)
    && (id === undefined || value.id === id) && typeof value.name === 'string'
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

const isNullableNumber = (value: unknown) => value === null || isFiniteNumber(value)
const isNullableString = (value: unknown) => value === null || typeof value === 'string'
const isString = (value: unknown) => typeof value === 'string'
/** Older payloads may omit a field; when it is present it must be valid. */
const isOptional = (value: unknown, check: (value: unknown) => boolean) => value === undefined || check(value)

/** Known rules must carry the fields their explanation shows; other rules only need an object. */
function isRecommendationBasis(ruleId: unknown, basis: unknown): boolean {
  if (!isRecord(basis)) return false
  if (ruleId === 'LOW_SCORE_LT_50_V1') return isFiniteNumber(basis.score) && isFiniteNumber(basis.threshold)
  if (ruleId === 'CATEGORY_GAP_GE_25_V1') return isString(basis.left_category) && isString(basis.right_category)
    && isNullableNumber(basis.gap_points) && isOptional(basis.threshold_points, isFiniteNumber)
  if (ruleId === 'DATA_QUALITY_V1') return isString(basis.status)
  return true
}

function isRecommendation(item: unknown, id: number): boolean {
  return isRecord(item)
    && typeof item.id === 'string' && typeof item.rule_id === 'string'
    && typeof item.component_code === 'string' && typeof item.text === 'string'
    && item.status === 'proposed' && typeof item.requires_human_decision === 'boolean'
    && isOptional(item.assessment_id, value => value === id)
    && isOptional(item.basis, basis => isRecommendationBasis(item.rule_id, basis))
    && isOptional(item.owner_role, isNullableString)
    && isOptional(item.due_date, isNullableString)
}

function isObjectiveContextItem(item: unknown): boolean {
  return isRecord(item) && isString(item.component_code) && isString(item.name)
    && isNullableNumber(item.survey_score) && isNullableNumber(item.objective_value)
    && (item.status === 'ok' || item.status === 'unverified')
    && isOptional(item.comparison_type, isString) && isOptional(item.reason, isString)
}

async function validated<T>(path: string, check: (value: unknown) => boolean, signal?: AbortSignal): Promise<T> {
  const value = await getJson<unknown>(path, signal, messages)
  if (!check(value)) throw new ApiError(200, 'API повернув некоректну відповідь аналітики.')
  return value as T
}

const methodParam = `methodology=${encodeURIComponent(DEMO_METHODOLOGY)}`

export function getMethodology(signal?: AbortSignal): Promise<Methodology> {
  return validated<Methodology>(`/api/index-methodologies/${DEMO_METHODOLOGY}`, value =>
    isRecord(value) && value.version === DEMO_METHODOLOGY
    && typeof value.approval_status === 'string' && typeof value.synthetic_only === 'boolean'
    && typeof value.official === 'boolean' && typeof value.formula === 'string'
    && isRecord(value.weights) && Array.isArray(value.limitations)
    && value.limitations.every(item => typeof item === 'string'), signal)
}

export function getIntegrityIndex(id: number, signal?: AbortSignal): Promise<IntegrityIndex> {
  return validated<IntegrityIndex>(`/api/assessments/${id}/index?${methodParam}`, value =>
    isRecord(value) && isClosedAssessment(value.assessment, id)
    && value.methodology_version === DEMO_METHODOLOGY
    && typeof value.approval_status === 'string' && typeof value.synthetic_only === 'boolean'
    && typeof value.official === 'boolean'
    && ['ok', 'insufficient_data', 'suppressed'].includes(String(value.status))
    && (value.index === null || typeof value.index === 'number' && Number.isFinite(value.index))
    && Array.isArray(value.components) && value.components.every((item: unknown) =>
      isRecord(item) && typeof item.code === 'string' && typeof item.name === 'string'
      && (item.score === null || typeof item.score === 'number' && Number.isFinite(item.score))
      && typeof item.weight === 'number' && Number.isFinite(item.weight)
      && (item.contribution === null || typeof item.contribution === 'number' && Number.isFinite(item.contribution))
      && ['ok', 'missing', 'suppressed'].includes(String(item.status)))
    && Array.isArray(value.warnings) && value.warnings.every(item => typeof item === 'string'), signal)
}

export function getRecommendations(id: number, signal?: AbortSignal): Promise<Recommendations> {
  return validated<Recommendations>(`/api/assessments/${id}/recommendations?${methodParam}`, value =>
    isRecord(value) && isClosedAssessment(value.assessment, id)
    && value.methodology_version === DEMO_METHODOLOGY && typeof value.approval_status === 'string'
    && typeof value.persistence === 'string' && Array.isArray(value.proposals)
    && value.proposals.every((item: unknown) => isRecommendation(item, id))
    && isOptional(value.objective_context, context =>
      Array.isArray(context) && context.every(isObjectiveContextItem)), signal)
}

export function getComparisons(id: number, comparisonId?: number, signal?: AbortSignal): Promise<Comparisons> {
  const path = `/api/analytics/comparisons?assessment_id=${id}&${methodParam}`
    + (comparisonId === undefined ? '' : `&comparison_assessment_id=${comparisonId}`)
  return validated<Comparisons>(path, value =>
    isRecord(value) && isClosedAssessment(value.assessment, id)
    && value.methodology_version === DEMO_METHODOLOGY
    && Array.isArray(value.category_comparisons)
    && value.category_comparisons.every((item: unknown) => isRecord(item)
      && typeof item.component_code === 'string' && typeof item.left_category === 'string'
      && typeof item.right_category === 'string' && ['ok', 'unavailable'].includes(String(item.status))
      && (item.gap_points === null || typeof item.gap_points === 'number' && Number.isFinite(item.gap_points))
      && (item.flag === null || typeof item.flag === 'boolean')
      && typeof item.interpretation === 'string')
    && (value.period_comparison === null || isRecord(value.period_comparison)
      && isClosedAssessment(value.period_comparison.before_assessment, id)
      && isClosedAssessment(value.period_comparison.after_assessment, comparisonId)
      && ['limited_comparability', 'unavailable'].includes(String(value.period_comparison.status))
      && (value.period_comparison.change_points === null
        || typeof value.period_comparison.change_points === 'number' && Number.isFinite(value.period_comparison.change_points))
      && Array.isArray(value.period_comparison.components)
      && value.period_comparison.components.every((item: unknown) => isRecord(item)
        && isString(item.component_code) && isNullableNumber(item.change_points))
      && Array.isArray(value.period_comparison.warnings)
      && value.period_comparison.warnings.every((item: unknown) => typeof item === 'string'))
    && (comparisonId === undefined ? value.period_comparison === null : value.period_comparison !== null), signal)
}
