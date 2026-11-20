import { ApiError, getJson, request } from './client'
import type { Assessment } from './assessments'

/** Статуси заходу після рішення посадової особи (автомат backend/app/services/tracker.py). */
export type TrackerStatus = 'accepted' | 'rejected' | 'in_progress' | 'completed' | 'verified'
export type TransitionTarget = 'in_progress' | 'completed' | 'verified'

export interface TrackerHistoryEntry {
  from_status: string
  to_status: string
  on_date: string
  at: string
  actor_role: string
  reason: string
  evidence_refs: string[]
  owner?: string | null
  due_date?: string | null
  verified_in_assessment_id?: number
}

export interface TrackerAction {
  id: number
  assessment_id: number
  recommendation_id: string
  rule_id: string
  component_code: string
  text: string
  methodology_version: string
  status: TrackerStatus
  owner: string | null
  due_date: string | null
  decision_reason: string
  evidence_refs: string[]
  verified_in_assessment_id: number | null
  overdue: boolean
  allowed_transitions: TransitionTarget[]
  history: TrackerHistoryEntry[]
  created_at: string
  updated_at: string
}

export interface TrackerSummary {
  accepted_total: number
  accepted: number
  in_progress: number
  completed: number
  verified: number
  rejected: number
  overdue: number
}

export interface Tracker {
  assessment: { id: number; name: string; status: string }
  as_of: string
  actions: TrackerAction[]
  summary: TrackerSummary
}

export type DecisionInput =
  | { recommendation_id: string; decision: 'accepted'; owner: string; due_date: string; reason: string }
  | { recommendation_id: string; decision: 'rejected'; reason: string }

export interface TransitionInput {
  status: TransitionTarget
  reason: string
  evidence_refs?: string[]
  verified_in_assessment_id?: number
}

export const STATUS_LABELS: Record<TrackerStatus, string> = {
  accepted: 'Прийнято',
  rejected: 'Відхилено',
  in_progress: 'В роботі',
  completed: 'Виконано',
  verified: 'Перевірено',
}

export const RULE_LABELS: Record<string, string> = {
  LOW_SCORE_LT_50_V1: 'Бал компонента нижче 50',
  CATEGORY_GAP_GE_25_V1: 'Розрив між категоріями ≥ 25 п.п.',
  DATA_QUALITY_V1: 'Якість агрегованих даних',
}

export const OVERDUE_RULE = 'Прострочено: строк минув, а статус не «Виконано» чи «Перевірено». День строку ще не прострочення.'
export const OWNER_MIN = 3
export const OWNER_MAX = 120
export const REASON_MAX = 1000
export const EVIDENCE_MAX = 200
export const EVIDENCE_MAX_ITEMS = 10

const STATUSES: readonly string[] = ['accepted', 'rejected', 'in_progress', 'completed', 'verified']
const TARGETS: readonly string[] = ['in_progress', 'completed', 'verified']

/** Назва кнопки переходу: повернення з «Виконано» в роботу звучить інакше, ніж початок роботи. */
export function transitionLabel(from: TrackerStatus, to: TransitionTarget): string {
  if (to === 'in_progress') return from === 'completed' ? 'Повернути в роботу' : 'Взяти в роботу'
  return to === 'completed' ? 'Позначити виконаним' : 'Підтвердити перевіркою'
}

/** Локальна календарна дата РРРР-ММ-ДД (не UTC), щоб правило прострочення збігалося з тим, що бачить людина. */
export function localDateIso(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

/** Правило прострочення (таке саме, як на сервері): строк минув, а захід ще не виконано й не перевірено. */
export function isOverdue(action: Pick<TrackerAction, 'status' | 'due_date'>, today: string): boolean {
  return (action.status === 'accepted' || action.status === 'in_progress')
    && action.due_date !== null && action.due_date < today
}

export interface TrackerCounters { accepted: number; inProgress: number; completed: number; verified: number; overdue: number; rejected: number }

/** Лічильники панелі: «прийнято» — усі прийняті рішення, незалежно від подальшого статусу. */
export function countActions(actions: TrackerAction[], today: string): TrackerCounters {
  const count = (status: TrackerStatus) => actions.filter(action => action.status === status).length
  return {
    accepted: actions.filter(action => action.status !== 'rejected').length,
    inProgress: count('in_progress'),
    completed: count('completed'),
    verified: count('verified'),
    overdue: actions.filter(action => isOverdue(action, today)).length,
    rejected: count('rejected'),
  }
}

const UPPER = 'А-ЯІЇЄҐA-Z'
const INITIALS = new RegExp(`[${UPPER}]\\.\\s*[${UPPER}]\\.`, 'u')
const NAME_WITH_PATRONYMIC = new RegExp(`[${UPPER}][а-яіїєґ'’]+\\s+[${UPPER}][а-яіїєґ'’]*(?:ович|евич|євич|івна|ївна|овна)(?![а-яіїєґ])`, 'u')

/** Та сама перевірка, що на сервері: посада або підрозділ, без ПІБ і контактів. Повертає текст проблеми або null. */
export function ownerProblem(value: string): string | null {
  const owner = value.trim().split(/\s+/).filter(Boolean).join(' ')
  if (owner.length < OWNER_MIN || owner.length > OWNER_MAX) return `Вкажіть посаду або підрозділ: від ${OWNER_MIN} до ${OWNER_MAX} символів.`
  if (owner.includes('@') || (owner.match(/\d/g)?.length ?? 0) >= 7 || INITIALS.test(owner) || NAME_WITH_PATRONYMIC.test(owner)) {
    return 'Вкажіть посаду або підрозділ, а не ПІБ чи контактні дані.'
  }
  return null
}

/** Посилання на докази: по одному в рядку, без порожніх і повторів. */
export function parseEvidence(text: string): string[] {
  const refs: string[] = []
  for (const line of text.split(/\r?\n/)) {
    const ref = line.trim().split(/\s+/).filter(Boolean).join(' ')
    if (ref && !refs.includes(ref)) refs.push(ref)
  }
  return refs
}

/** Цикли, якими можна перевірити результат: закриті, пізніші за датою початку, з тією самою версією анкети. */
export function laterClosedAssessments(assessments: Assessment[], current: Assessment): Assessment[] {
  const version = current.questionnaire_version ?? 'demo-v1'
  return assessments.filter(item => item.status === 'closed' && item.id !== current.id
    && item.start_date > current.start_date && (item.questionnaire_version ?? 'demo-v1') === version)
}

const readMessages: Partial<Record<number, string>> = {
  401: 'Сесію завершено або вхід не підтверджено. Увійдіть знову.',
  403: 'Для вашої ролі трекер рекомендацій недоступний.',
  404: 'Цикл оцінювання не знайдено.',
}

const writeMessages: Partial<Record<number, string>> = {
  401: readMessages[401],
  403: 'Дію відхилено: рішення ухвалює лише адміністратор із підтвердженою сесією.',
  404: 'Пропозицію або захід не знайдено. Оновіть дані.',
  409: 'Стан змінився або рішення вже ухвалено. Оновіть дані.',
  422: 'Перевірте поля форми: дані не пройшли перевірку.',
  503: 'Пропозиції недоступні: модуль рекомендацій (синтетична демометодика) не ввімкнений на сервері.',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

const isText = (value: unknown): value is string => typeof value === 'string'
const isTextList = (value: unknown): value is string[] => Array.isArray(value) && value.every(isText)
const isId = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0
const isDate = (value: unknown): value is string => isText(value) && /^\d{4}-\d{2}-\d{2}$/.test(value)

function isHistoryEntry(value: unknown): value is TrackerHistoryEntry {
  return isRecord(value) && isText(value.from_status) && isText(value.to_status) && isText(value.on_date)
    && isText(value.at) && isText(value.actor_role) && isText(value.reason) && isTextList(value.evidence_refs)
}

export function isTrackerAction(value: unknown): value is TrackerAction {
  return isRecord(value) && isId(value.id) && isId(value.assessment_id)
    && isText(value.recommendation_id) && isText(value.rule_id) && isText(value.component_code)
    && isText(value.text) && isText(value.methodology_version) && STATUSES.includes(String(value.status))
    && (value.owner === null || isText(value.owner)) && (value.due_date === null || isDate(value.due_date))
    && isText(value.decision_reason) && isTextList(value.evidence_refs)
    && (value.verified_in_assessment_id === null || isId(value.verified_in_assessment_id))
    && typeof value.overdue === 'boolean'
    && Array.isArray(value.allowed_transitions) && value.allowed_transitions.every(item => TARGETS.includes(String(item)))
    && Array.isArray(value.history) && value.history.every(isHistoryEntry)
    && isText(value.created_at) && isText(value.updated_at)
}

function isTracker(value: unknown, id: number): value is Tracker {
  return isRecord(value) && isRecord(value.assessment) && value.assessment.id === id
    && isText(value.assessment.name) && isText(value.assessment.status) && isDate(value.as_of)
    && Array.isArray(value.actions) && value.actions.every(isTrackerAction)
    && isRecord(value.summary)
}

export async function getTracker(assessmentId: number, signal?: AbortSignal): Promise<Tracker> {
  const value = await getJson<unknown>(`/api/assessments/${assessmentId}/tracker`, signal, readMessages)
  if (!isTracker(value, assessmentId)) throw new ApiError(200, 'API повернув некоректну відповідь трекера.')
  return value
}

async function post(path: string, body: object, signal?: AbortSignal): Promise<TrackerAction> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body), signal })
  if (!response.ok) {
    let detail: string | null = null
    try {
      const data: unknown = await response.json()
      if (isRecord(data) && isText(data.detail)) detail = data.detail
    } catch { /* статусне повідомлення нижче */ }
    const fixed = response.status === 401 || response.status === 503
    throw new ApiError(response.status, (!fixed && detail) || writeMessages[response.status] || `Помилка API (${response.status}).`)
  }
  let value: unknown
  try { value = await response.json() } catch { value = null }
  if (!isTrackerAction(value)) throw new ApiError(response.status, 'API повернув некоректну відповідь трекера.')
  return value
}

/** Рішення посадової особи. Надсилаємо лише ідентифікатор пропозиції — текст бере сервер. */
export function decideRecommendation(assessmentId: number, input: DecisionInput, signal?: AbortSignal): Promise<TrackerAction> {
  const body = input.decision === 'accepted'
    ? { recommendation_id: input.recommendation_id, decision: input.decision, owner: input.owner.trim(),
        due_date: input.due_date, reason: input.reason.trim() }
    : { recommendation_id: input.recommendation_id, decision: input.decision, reason: input.reason.trim() }
  return post(`/api/assessments/${assessmentId}/tracker/decisions`, body, signal)
}

export function transitionAction(actionId: number, input: TransitionInput, signal?: AbortSignal): Promise<TrackerAction> {
  const body: Record<string, unknown> = { status: input.status, reason: input.reason.trim() }
  if (input.evidence_refs && input.evidence_refs.length > 0) body.evidence_refs = input.evidence_refs
  if (input.status === 'verified' && input.verified_in_assessment_id !== undefined) {
    body.verified_in_assessment_id = input.verified_in_assessment_id
  }
  return post(`/api/tracker/${actionId}/transition`, body, signal)
}
