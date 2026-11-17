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

export interface Recommendation {
  id: string
  rule_id: string
  component_code: string
  text: string
  status: 'proposed'
  requires_human_decision: boolean
}

export interface Recommendations {
  assessment: { id: number; name: string; status: 'closed' }
  methodology_version: string
  approval_status: string
  proposals: Recommendation[]
  persistence: string
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
  401: 'Демо-роль не розпізнано.',
  403: 'Для цієї ролі аналітика недоступна.',
  404: 'Цикл або версію методики не знайдено.',
  409: 'Аналітика доступна лише для закритого циклу з відповідними компонентами й вагами.',
  422: 'Параметри аналітики не відповідають контракту API.',
  503: 'Демоаналітика вимкнена на backend. Для синтетичної бази потрібне окреме ввімкнення.',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isClosedAssessment(value: unknown, id?: number): boolean {
  return isRecord(value) && value.status === 'closed' && Number.isSafeInteger(value.id)
    && (id === undefined || value.id === id) && typeof value.name === 'string'
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
    && value.proposals.every((item: unknown) => isRecord(item)
      && typeof item.id === 'string' && typeof item.rule_id === 'string'
      && typeof item.component_code === 'string' && typeof item.text === 'string'
      && item.status === 'proposed' && typeof item.requires_human_decision === 'boolean'), signal)
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
      && Array.isArray(value.period_comparison.warnings)
      && value.period_comparison.warnings.every((item: unknown) => typeof item === 'string'))
    && (comparisonId === undefined ? value.period_comparison === null : value.period_comparison !== null), signal)
}
