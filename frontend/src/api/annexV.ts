import { ApiError, readErrorBody, request, statusMessage } from './client'
import { ANNEX_V_CRITERIA, type AnnexVCriterion } from '../official/catalog-v2'

/**
 * Клієнт модуля «Зрілість за Додатком В» (спільний контракт, ендпоїнти 1–4):
 * анонімні відповіді анкет, експертні оцінки, чеклист Додатка Б та об’єктивні показники.
 */

export const ANNEX_V_VERSION = '2.0.0'
export type AnnexVForm = 1 | 2
export type AnnexVAnswers = Record<string, string>

export interface AnnexVResponseBody {
  access_token: string
  category: string
  form: AnnexVForm
  version: typeof ANNEX_V_VERSION
  answers: AnnexVAnswers
}

export interface AnnexVExpertBody {
  expert_label: string
  form: 1
  version: typeof ANNEX_V_VERSION
  answers: AnnexVAnswers
}

export type ChecklistStatus = 'yes' | 'partial' | 'no'
export const CHECKLIST_STATUSES: readonly ChecklistStatus[] = ['yes', 'partial', 'no']
export const CHECKLIST_STATUS_LABELS: Readonly<Record<ChecklistStatus, string>> = { yes: 'Так', partial: 'Частково', no: 'Ні' }

export interface ChecklistItem {
  code: string
  criterion: string
  text: string
  source: string
  status: ChecklistStatus | null
  evidence: string | null
  entered_role: string | null
  entered_at: string | null
  confirmed: boolean
  confirmed_role: string | null
  confirmed_at: string | null
}

export interface ObjectiveIndicator {
  id: number
  criterion: string
  name: string
  unit: string
  value: number
  target: number
  period: string
  entered_role: string | null
  confirmed: boolean
  confirmed_role: string | null
}

export interface ObjectiveIndicatorInput { criterion: string; name: string; value: number; target: number; period: string }

/** Назви критеріїв Додатка В і компонент Integrity Index лише для відображення (C4 не має критерію). */
export const CRITERION_LABELS: Readonly<Record<AnnexVCriterion, string>> = {
  leadership: 'Роль керівника',
  ethics: 'Етика й корпоративна культура',
  education: 'Навчання персоналу',
  openness: 'Відкритість інформації',
  officer: 'Уповноважений з доброчесності',
  strategy: 'Стратегія й політики',
  risks: 'Корупційні ризики',
  checks: 'Перевірка актів, кандидатів і контрагентів',
  whistleblowers: 'Канали повідомлень і захист викривачів',
  audit: 'Аудит системи доброчесності',
  maturity: 'Загальний рівень зрілості (самооцінка)',
}
export const CRITERION_COMPONENTS: Readonly<Partial<Record<AnnexVCriterion, string>>> = {
  leadership: 'C1', ethics: 'C1', strategy: 'C2', officer: 'C2', risks: 'C3', checks: 'C3',
  education: 'C5', whistleblowers: 'C6', openness: 'C7', audit: 'C7',
}
/** Критерії, для яких вносять об’єктивні показники: без `maturity` (самооцінки загального рівня). */
export const INDICATOR_CRITERIA: readonly AnnexVCriterion[] = ANNEX_V_CRITERIA.filter(key => key !== 'maturity')

export function criterionLabel(key: string): string {
  if (!Object.hasOwn(CRITERION_LABELS, key)) return key
  const component = CRITERION_COMPONENTS[key as AnnexVCriterion]
  return component ? `${CRITERION_LABELS[key as AnnexVCriterion]} (${component})` : CRITERION_LABELS[key as AnnexVCriterion]
}

/** Результат надсилання невідомий (мережа, неочікуваний статус): анкету могли прийняти, код міг бути використаний. */
export class AnnexVOutcomeUnknownError extends Error {
  readonly kind = 'annex-v-outcome-unknown'
  constructor() {
    super('Не вдалося підтвердити результат надсилання. Анкету могли прийняти, а код — використати. Не надсилайте повторно без перевірки у координатора.')
    this.name = 'AnnexVOutcomeUnknownError'
  }
}

/** Публічне подання: деталі помилки сервера не показуємо, бо вони можуть містити введений код. */
export const RESPONSE_MESSAGES: Readonly<Partial<Record<number, string>>> = {
  404: 'Цикл оцінювання не знайдено. Оновіть сторінку й оберіть цикл ще раз.',
  409: 'Анкету не прийнято: цикл уже закрито або цей код доступу вже використано.',
  413: 'Запит завеликий. Анкету не надіслано.',
  422: 'Анкету не прийнято: перевірте код доступу (він має відповідати обраній категорії) і відповіді на всі питання.',
  429: 'Забагато спроб надсилання. Анкету не надіслано, спробуйте пізніше.',
}

export const EXPERT_MESSAGES: Readonly<Partial<Record<number, string>>> = {
  403: 'Експертну оцінку вносить лише адміністратор.',
  404: 'Цикл оцінювання не знайдено. Оновіть перелік циклів.',
  409: 'Цей цикл зараз не приймає експертних оцінок.',
  422: 'Сервер відхилив оцінку: перевірте посаду експерта (3–120 символів) і відповіді на всі питання анкети 1.',
}

export const SELF_CONFIRM_MESSAGE = 'Підтвердити запис може лише інший користувач: власне внесення підтверджувати не можна.'

export const CHECKLIST_MESSAGES: Readonly<Partial<Record<number, string>>> = {
  403: 'Для вашої ролі ця дія недоступна.',
  404: 'Цикл або пункт чеклиста не знайдено. Оновіть сторінку.',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
const text = (value: unknown) => typeof value === 'string' ? value : null
const num = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : null

/** Сесійний JSON-запит (CSRF додає `request`). Рядок `detail` показуємо, якщо для статусу немає власного тексту. */
async function json<T>(path: string, init: RequestInit = {}, signal?: AbortSignal, messages: Partial<Record<number, string>> = {}, preferDetail: number[] = []): Promise<T> {
  const response = await request(path, { ...init, signal })
  if (!response.ok) {
    let message = statusMessage(response.status, messages)
    const useDetail = messages[response.status] === undefined || preferDetail.includes(response.status)
    if (useDetail && ![401, 413, 422, 429].includes(response.status)) {
      const body = await readErrorBody(response)
      if (typeof body.detail === 'string' && body.detail.trim()) message = body.detail
    }
    if (response.status === 503) message = 'Сервіс тимчасово недоступний.'
    throw new ApiError(response.status, message)
  }
  try { return await response.json() as T } catch {
    throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.')
  }
}

// ---------------------------------------------------------------- 1. Анонімні відповіді (публічно)

/**
 * Надсилає анкету без cookie сесії (`credentials: 'omit'`): відповідь не пов’язана з обліковим записом.
 * Одноразовий код передається лише в JSON-тілі — не в адресі й не в заголовках.
 */
export async function submitAnnexVResponse(assessmentId: number, body: AnnexVResponseBody, signal?: AbortSignal): Promise<{ status: 'accepted' }> {
  let response: Response
  try {
    response = await request(`/api/assessments/${assessmentId}/annex-v/responses`, { method: 'POST', body: JSON.stringify(body), signal }, 'omit')
  } catch (error) {
    if (signal?.aborted) throw error
    throw new AnnexVOutcomeUnknownError()
  }
  if (response.status === 201) return { status: 'accepted' }
  const message = RESPONSE_MESSAGES[response.status]
  if (message) throw new ApiError(response.status, message)
  if (response.status === 400 || response.status === 403) throw new ApiError(response.status, 'Анкету не прийнято: код доступу недійсний або вже використаний.')
  throw new AnnexVOutcomeUnknownError()
}

// ---------------------------------------------------------------- 2. Експертна оцінка (admin)

export function submitExpertAssessment(assessmentId: number, body: AnnexVExpertBody, signal?: AbortSignal): Promise<{ id: number }> {
  return json<{ id: number }>(`/api/assessments/${assessmentId}/annex-v/expert`, { method: 'POST', body: JSON.stringify(body) }, signal, EXPERT_MESSAGES, [409])
}

/** Відповідь внесеної експертної оцінки: тексти й рівень — із серверного каталогу Додатка В. */
export interface ExpertAnswer {
  question_id: string
  question: string | null
  criterion: string | null
  option_id: string | null
  option: string | null
  level: number | null
}

/** Запис експертної оцінки. Експерт — посада (expert_label), без ПІБ. */
export interface ExpertRecord {
  id: number
  expert_label: string
  form: number
  version: string
  created_at: string | null
  entered_role: string | null
  entered_by_user_id: number | null
  answers: ExpertAnswer[]
}

/** Підсумок критерію: рівні окремих експертів (у порядку записів) і середній рівень. */
export interface ExpertCriterionSummary {
  criterion: string
  title: string
  levels: number[]
  mean: number | null
}

export interface ExpertAssessmentList {
  assessment_id: number
  form: 1
  version: string
  count: number
  items: ExpertRecord[]
  by_criterion: ExpertCriterionSummary[]
}

export const EXPERT_LIST_MESSAGES: Readonly<Partial<Record<number, string>>> = {
  403: 'Внесені експертні оцінки переглядає лише адміністратор.',
  404: 'Цикл оцінювання не знайдено. Оновіть перелік циклів.',
}

const safeId = (value: unknown) => Number.isSafeInteger(value) ? value as number : null

export function normalizeExpertAnswer(raw: unknown): ExpertAnswer | null {
  if (!isRecord(raw) || typeof raw.question_id !== 'string' || !raw.question_id) return null
  return {
    question_id: raw.question_id, question: text(raw.question), criterion: text(raw.criterion),
    option_id: text(raw.option_id), option: text(raw.option), level: num(raw.level),
  }
}

export function normalizeExpertRecord(raw: unknown): ExpertRecord | null {
  if (!isRecord(raw) || safeId(raw.id) === null || typeof raw.expert_label !== 'string') return null
  const answers = Array.isArray(raw.answers) ? raw.answers.map(normalizeExpertAnswer).filter((item): item is ExpertAnswer => item !== null) : []
  return {
    id: raw.id as number, expert_label: raw.expert_label, form: num(raw.form) ?? 1, version: text(raw.version) ?? '',
    created_at: text(raw.created_at), entered_role: text(raw.entered_role), entered_by_user_id: safeId(raw.entered_by_user_id), answers,
  }
}

function normalizeCriterionSummary(raw: unknown): ExpertCriterionSummary | null {
  if (!isRecord(raw) || typeof raw.criterion !== 'string' || !raw.criterion) return null
  const levels = Array.isArray(raw.levels) ? raw.levels.map(num).filter((value): value is number => value !== null) : []
  return { criterion: raw.criterion, title: text(raw.title) ?? raw.criterion, levels, mean: num(raw.mean) }
}

export function normalizeExpertList(raw: unknown, assessmentId: number): ExpertAssessmentList {
  if (!isRecord(raw) || !Array.isArray(raw.items) || !Array.isArray(raw.by_criterion)) throw new ApiError(200, 'API повернув некоректний перелік експертних оцінок.')
  const items = raw.items.map(normalizeExpertRecord).filter((item): item is ExpertRecord => item !== null)
  return {
    assessment_id: safeId(raw.assessment_id) ?? assessmentId, form: 1, version: text(raw.version) ?? ANNEX_V_VERSION, count: items.length, items,
    by_criterion: raw.by_criterion.map(normalizeCriterionSummary).filter((item): item is ExpertCriterionSummary => item !== null),
  }
}

/** Внесені експертні оцінки циклу (лише admin). Читання сервер не журналює. */
export async function getExpertAssessments(assessmentId: number, signal?: AbortSignal): Promise<ExpertAssessmentList> {
  return normalizeExpertList(await json<unknown>(`/api/assessments/${assessmentId}/annex-v/expert`, {}, signal, EXPERT_LIST_MESSAGES), assessmentId)
}

// ---------------------------------------------------------------- 3. Чеклист Додатка Б

export function normalizeChecklistItem(raw: unknown): ChecklistItem | null {
  if (!isRecord(raw) || typeof raw.code !== 'string' || !raw.code) return null
  const status = raw.status === 'yes' || raw.status === 'partial' || raw.status === 'no' ? raw.status : null
  return {
    code: raw.code, criterion: text(raw.criterion) ?? '', text: text(raw.text) ?? '', source: text(raw.source) ?? 'Додаток Б (адаптовано)',
    status, evidence: text(raw.evidence), entered_role: text(raw.entered_role), entered_at: text(raw.entered_at),
    confirmed: raw.confirmed === true, confirmed_role: text(raw.confirmed_role), confirmed_at: text(raw.confirmed_at),
  }
}

function checklistItemOrThrow(raw: unknown): ChecklistItem {
  const item = normalizeChecklistItem(raw)
  if (!item) throw new ApiError(200, 'API повернув некоректний пункт чеклиста.')
  return item
}

export async function getChecklist(assessmentId: number, signal?: AbortSignal): Promise<ChecklistItem[]> {
  const raw = await json<unknown>(`/api/assessments/${assessmentId}/checklist`, {}, signal, CHECKLIST_MESSAGES)
  if (!isRecord(raw) || !Array.isArray(raw.items)) throw new ApiError(200, 'API повернув некоректну відповідь чеклиста.')
  return raw.items.map(normalizeChecklistItem).filter((item): item is ChecklistItem => item !== null)
}

export async function updateChecklistItem(assessmentId: number, code: string, body: { status: ChecklistStatus; evidence?: string }, signal?: AbortSignal): Promise<ChecklistItem> {
  return checklistItemOrThrow(await json<unknown>(`/api/assessments/${assessmentId}/checklist/${encodeURIComponent(code)}`,
    { method: 'PUT', body: JSON.stringify(body) }, signal, { ...CHECKLIST_MESSAGES, 403: 'Вносити пункти чеклиста можуть лише data_officer або адміністратор.' }))
}

export async function confirmChecklistItem(assessmentId: number, code: string, signal?: AbortSignal): Promise<ChecklistItem> {
  return checklistItemOrThrow(await json<unknown>(`/api/assessments/${assessmentId}/checklist/${encodeURIComponent(code)}/confirm`,
    { method: 'POST' }, signal, { ...CHECKLIST_MESSAGES, 403: 'Підтверджує лише адміністратор.', 409: SELF_CONFIRM_MESSAGE }, [409]))
}

// ---------------------------------------------------------------- 4. Об’єктивні показники

export function normalizeIndicator(raw: unknown): ObjectiveIndicator | null {
  if (!isRecord(raw) || !Number.isSafeInteger(raw.id) || typeof raw.name !== 'string') return null
  const value = num(raw.value), target = num(raw.target)
  if (value === null || target === null) return null
  return {
    id: raw.id as number, criterion: text(raw.criterion) ?? '', name: raw.name, unit: text(raw.unit) ?? '%', value, target,
    period: text(raw.period) ?? '', entered_role: text(raw.entered_role), confirmed: raw.confirmed === true, confirmed_role: text(raw.confirmed_role),
  }
}

function indicatorOrThrow(raw: unknown): ObjectiveIndicator {
  const item = normalizeIndicator(raw)
  if (!item) throw new ApiError(200, 'API повернув некоректний показник.')
  return item
}

export async function getObjectiveIndicators(assessmentId: number, signal?: AbortSignal): Promise<ObjectiveIndicator[]> {
  const raw = await json<unknown>(`/api/assessments/${assessmentId}/objective-indicators`, {}, signal, CHECKLIST_MESSAGES)
  if (!isRecord(raw) || !Array.isArray(raw.items)) throw new ApiError(200, 'API повернув некоректну відповідь показників.')
  return raw.items.map(normalizeIndicator).filter((item): item is ObjectiveIndicator => item !== null)
}

export async function createObjectiveIndicator(assessmentId: number, body: ObjectiveIndicatorInput, signal?: AbortSignal): Promise<ObjectiveIndicator> {
  return indicatorOrThrow(await json<unknown>(`/api/assessments/${assessmentId}/objective-indicators`, { method: 'POST', body: JSON.stringify(body) }, signal,
    { ...CHECKLIST_MESSAGES, 403: 'Вносити показники можуть лише data_officer або адміністратор.' }))
}

export async function confirmObjectiveIndicator(indicatorId: number, signal?: AbortSignal): Promise<ObjectiveIndicator> {
  return indicatorOrThrow(await json<unknown>(`/api/objective-indicators/${indicatorId}/confirm`, { method: 'POST' }, signal,
    { 403: 'Підтверджує лише адміністратор.', 404: 'Показник не знайдено. Оновіть сторінку.', 409: SELF_CONFIRM_MESSAGE }, [409]))
}
