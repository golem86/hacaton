import { ApiError, getJson } from './client'

/**
 * Клієнт GET /api/assessments/{id}/maturity («Зрілість за Додатком В»).
 * Контракт: annex-v-maturity-0.1, рівні a=1…e=5 (варіант f не має рівня), синтетичні дані.
 * Відповідь перевіряється під час виконання: некоректна структура не потрапляє в UI.
 */
export const MATURITY_METHODOLOGY = 'annex-v-maturity-0.1'

export type SourceStatus = 'ok' | 'suppressed' | 'missing'
export type GapSource = 'expert' | 'checklist'

export interface SelfSource {
  /** Середній рівень 1–5 з точністю до 0,1; null, якщо приховано або відсутнє. */
  level: number | null
  responses: number | null
  status: SourceStatus
}

export interface CategoryLevel {
  category: string
  level: number | null
  /** Категорія прихована правилом k-анонімності (первинне або вторинне приховування). */
  hidden: boolean
}

export interface ExpertSource {
  level: number | null
  experts: number
  status: SourceStatus
}

export interface ChecklistSource {
  level: number | null
  items_total: number
  items_confirmed: number
  status: SourceStatus
}

export interface ObjectiveValue {
  name: string
  value: number | null
  target: number | null
  confirmed: boolean
}

export interface MaturityGap {
  rule_id: string
  left: 'self'
  right: GapSource
  /** self − right; null, якщо одне з джерел недоступне. */
  diff: number | null
  flag: boolean
}

export interface MaturityCriterion {
  key: string
  name_uk: string
  component_code: string | null
  self: SelfSource
  self_by_category: CategoryLevel[]
  expert: ExpertSource
  checklist: ChecklistSource
  objective: ObjectiveValue[]
  gaps: MaturityGap[]
}

export interface MaturityRecommendation {
  id: string
  rule_id: string
  criterion: string
  basis: Record<string, unknown>
  text: string
  requires_human_decision: boolean
}

export interface MaturityIndices {
  self: number | null
  expert: number | null
  checklist: number | null
}

export interface MaturityReport {
  assessment: { id: number; name: string; status: string }
  methodology_version: string
  level_rule: string
  min_group_size: number
  criteria: MaturityCriterion[]
  overall_self_declared: { level: number | null; status: SourceStatus }
  indices: MaturityIndices
  recommendations: MaturityRecommendation[]
}

export const MATURITY_MESSAGES: Readonly<Record<number, string>> = {
  401: 'Сесію завершено або вхід не підтверджено. Увійдіть знову.',
  403: 'Для вашої ролі аналітика зрілості за Додатком В недоступна.',
  404: 'Цикл оцінювання не знайдено.',
  409: 'Цикл ще відкритий. Зрілість за Додатком В розраховується лише після закриття циклу.',
  503: 'Демонстраційна аналітика зрілості вимкнена в поточній конфігурації сервера (INTEGRITY_ANALYTICS_DEMO). Результат не сформовано.',
}

export const INVALID_MATURITY_MESSAGE = 'API повернув некоректну відповідь аналітики зрілості.'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
const isString = (value: unknown): value is string => typeof value === 'string'
const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const isCount = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0
const isNullable = (check: (value: unknown) => boolean) => (value: unknown) => value === null || check(value)
const isStatus = (value: unknown) => value === 'ok' || value === 'suppressed' || value === 'missing'
const isArrayOf = (value: unknown, check: (item: unknown) => boolean) => Array.isArray(value) && value.every(check)
/** Рівень 1–5; значення поза шкалою відхиляються, а не обрізаються. */
const isLevel = (value: unknown) => isFiniteNumber(value) && value >= 1 && value <= 5
const isNullableLevel = isNullable(isLevel)
const isIndex = isNullable(value => isFiniteNumber(value) && value >= 0 && value <= 100)

/** Приховане чи відсутнє джерело не може мати рівня: значення під приховуванням не потрапляє в UI. */
function levelMatchesStatus(source: Record<string, unknown>): boolean {
  return source.status === 'ok' ? isNullableLevel(source.level) : source.level === null
}

function isCriterion(item: unknown): boolean {
  if (!isRecord(item)) return false
  const { self, expert, checklist } = item
  return isString(item.key) && item.key.length > 0 && isString(item.name_uk)
    && isNullable(isString)(item.component_code)
    && isRecord(self) && isStatus(self.status) && levelMatchesStatus(self) && isNullable(isCount)(self.responses)
    && isArrayOf(item.self_by_category, category => isRecord(category) && isString(category.category)
      && typeof category.hidden === 'boolean' && isNullableLevel(category.level)
      && (!category.hidden || category.level === null))
    && isRecord(expert) && isStatus(expert.status) && levelMatchesStatus(expert) && isCount(expert.experts)
    && isRecord(checklist) && isStatus(checklist.status) && levelMatchesStatus(checklist)
    && isCount(checklist.items_total) && isCount(checklist.items_confirmed)
    && (checklist.items_confirmed as number) <= (checklist.items_total as number)
    && isArrayOf(item.objective, objective => isRecord(objective) && isString(objective.name)
      && isNullable(isFiniteNumber)(objective.value) && isNullable(isFiniteNumber)(objective.target)
      && typeof objective.confirmed === 'boolean')
    && isArrayOf(item.gaps, gap => isRecord(gap) && isString(gap.rule_id) && gap.left === 'self'
      && (gap.right === 'expert' || gap.right === 'checklist')
      && isNullable(isFiniteNumber)(gap.diff) && typeof gap.flag === 'boolean')
}

function isRecommendation(item: unknown): boolean {
  return isRecord(item) && isString(item.id) && isString(item.rule_id) && isString(item.criterion)
    && isRecord(item.basis) && isString(item.text) && item.requires_human_decision === true
}

/** Runtime validator for the endpoint-5 payload; exported for tests and reuse. */
export function isMaturityReport(value: unknown, id?: number): value is MaturityReport {
  if (!isRecord(value)) return false
  const { assessment, overall_self_declared: overall, indices } = value
  return isRecord(assessment) && Number.isSafeInteger(assessment.id) && (id === undefined || assessment.id === id)
    && isString(assessment.name) && isString(assessment.status)
    && value.methodology_version === MATURITY_METHODOLOGY && isString(value.level_rule)
    && Number.isSafeInteger(value.min_group_size) && (value.min_group_size as number) >= 1
    && isArrayOf(value.criteria, isCriterion)
    && isRecord(overall) && isStatus(overall.status) && levelMatchesStatus(overall)
    && isRecord(indices) && isIndex(indices.self) && isIndex(indices.expert) && isIndex(indices.checklist)
    && isArrayOf(value.recommendations, isRecommendation)
}

export async function getMaturity(id: number, signal?: AbortSignal): Promise<MaturityReport> {
  const value = await getJson<unknown>(`/api/assessments/${id}/maturity`, signal, MATURITY_MESSAGES)
  if (!isMaturityReport(value, id)) throw new ApiError(200, INVALID_MATURITY_MESSAGE)
  return value
}
