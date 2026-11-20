/**
 * Pure, deterministic explanations for analytics results. No network and no AI:
 * every sentence is built from an explicit rule and the data the backend returned.
 * Rules mirror backend/app/services/recommendations.py (team-results-demo-0.1).
 */
import type { ObjectiveContextItem, Recommendation } from '../api/analytics'
import { categoryName } from './format'

export const RULE_LOW_SCORE = 'LOW_SCORE_LT_50_V1'
export const RULE_CATEGORY_GAP = 'CATEGORY_GAP_GE_25_V1'
export const RULE_DATA_QUALITY = 'DATA_QUALITY_V1'
export const LOW_SCORE_THRESHOLD = 50
export const CATEGORY_GAP_THRESHOLD = 25
/** A self-assessment at or above this needs a confirmed objective indicator. */
export const HIGH_SELF_ASSESSMENT = 75

export interface RuleDescription {
  id: string
  title: string
  condition: string
}

/** The rule set shown to the user, listed in priority order. */
export const RULE_SET: readonly RuleDescription[] = [
  { id: RULE_LOW_SCORE, title: 'Низький бал', condition: `бал компонента нижче ${LOW_SCORE_THRESHOLD} зі 100` },
  {
    id: RULE_CATEGORY_GAP,
    title: 'Розрив між категоріями',
    condition: `бали двох видимих категорій різняться на ${CATEGORY_GAP_THRESHOLD} п.п. або більше`,
  },
  { id: RULE_DATA_QUALITY, title: 'Якість даних', condition: 'бал компонента приховано або відсутній' },
]

export const PRIORITY_RULE = 'Порядок: спершу низькі бали (від найнижчого), далі розриви між категоріями '
  + '(від найбільшого), далі якість даних, наприкінці інші правила. Пропозиції згруповано за компонентом; '
  + 'першою йде група з найпріоритетнішою пропозицією.'

export const REVIEW_RULE = 'Позначка «Потребує перевірки» ставиться, якщо об’єктивний показник не підтверджено '
  + `або якщо самооцінка становить ${HIGH_SELF_ASSESSMENT} зі 100 чи більше, а підтвердженого значення показника немає.`

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function formatNumber(value: number): string {
  return value.toLocaleString('uk-UA', { maximumFractionDigits: 2 })
}

/** Signed change, e.g. "+2,5" or "-3"; zero stays "0". */
export function formatChange(value: number): string {
  return value.toLocaleString('uk-UA', { maximumFractionDigits: 2, signDisplay: 'exceptZero' })
}

export function surveyScoreText(score: number | null): string {
  return score === null ? 'Приховано/немає даних' : `${formatNumber(score)} зі 100`
}

export function objectiveValueText(item: Pick<ObjectiveContextItem, 'name' | 'objective_value'>): string {
  if (item.objective_value === null) return 'Немає підтвердженого значення'
  return `${formatNumber(item.objective_value)}${/%\s*$/.test(item.name) ? '%' : ''}`
}

export function ruleTitle(ruleId: string): string {
  return RULE_SET.find(rule => rule.id === ruleId)?.title ?? 'Інше правило'
}

function dataStatusLabel(status: string): string {
  if (status === 'suppressed') return 'приховано для захисту малих груп'
  if (status === 'missing') return 'немає даних для розрахунку'
  return `«${status}»`
}

function factValue(value: unknown): string {
  if (value === null || value === undefined) return 'немає'
  if (typeof value === 'number') return Number.isFinite(value) ? formatNumber(value) : String(value)
  if (typeof value === 'boolean') return value ? 'так' : 'ні'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

/** Raw key/value pairs of a rule basis, used when no rule-specific text applies. */
export function basisFacts(basis: unknown): [string, string][] {
  return isRecord(basis) ? Object.entries(basis).map(([key, value]) => [key, factValue(value)]) : []
}

export interface Explanation {
  /** The «Чому запропоновано» sentence. */
  text: string
  /** False when the rule is unknown or its basis does not fit; the raw facts are shown then. */
  known: boolean
  facts: [string, string][]
}

export function explainRecommendation(item: Recommendation): Explanation {
  const basis = isRecord(item.basis) ? item.basis : undefined
  const facts = basisFacts(basis)
  const rule = `(правило ${item.rule_id})`

  if (basis && item.rule_id === RULE_LOW_SCORE) {
    const { score, threshold } = basis
    if (isFiniteNumber(score) && isFiniteNumber(threshold) && score < threshold) return {
      known: true,
      facts,
      text: `Бал компонента ${item.component_code} — ${formatNumber(score)} зі 100, нижче порогу ${formatNumber(threshold)} ${rule}.`,
    }
  }

  if (basis && item.rule_id === RULE_CATEGORY_GAP) {
    const { left_category: left, right_category: right, gap_points: signedGap } = basis
    const threshold = isFiniteNumber(basis.threshold_points) ? basis.threshold_points : CATEGORY_GAP_THRESHOLD
    if (typeof left === 'string' && typeof right === 'string' && isFiniteNumber(signedGap)
      && Math.abs(signedGap) >= threshold) {
      // gap_points = left score − right score; name the higher-scoring category first.
      const [higher, lower] = signedGap >= 0 ? [left, right] : [right, left]
      const gap = Math.abs(signedGap)
      const direction = gap === 0 ? '' : `; вищий бал у категорії «${categoryName(higher)}»`
      return {
        known: true,
        facts,
        text: `Розрив між категоріями «${categoryName(higher)}» і «${categoryName(lower)}» — ${formatNumber(gap)} п.п., `
          + `поріг сигналу ${formatNumber(threshold)} п.п.${direction} ${rule}. Це сигнал для перегляду, а не доказ порушення.`,
      }
    }
  }

  if (basis && item.rule_id === RULE_DATA_QUALITY && typeof basis.status === 'string') return {
    known: true,
    facts,
    text: `Дані компонента ${item.component_code} приховано або відсутні (стан: ${dataStatusLabel(basis.status)}) `
      + `— перевірте допустимість агрегатів ${rule}.`,
  }

  const described = RULE_SET.some(entry => entry.id === item.rule_id)
  return {
    known: false,
    facts,
    text: !basis
      ? `API не передав обґрунтування для правила ${item.rule_id}.`
      : described
        ? `Обґрунтування не відповідає опису правила ${item.rule_id}; нижче — вихідні значення.`
        : `Правило ${item.rule_id} не має опису в інтерфейсі; нижче — вихідні значення обґрунтування.`,
  }
}

/** 0 = low score, 1 = category gap, 2 = data quality, 3 = any other rule. */
export function rulePriority(ruleId: string): number {
  const index = RULE_SET.findIndex(rule => rule.id === ruleId)
  return index === -1 ? RULE_SET.length : index
}

/** Lower sorts first: low scores ascending, category gaps by absolute size descending. */
function keyWithinRule(item: Recommendation): number {
  if (item.rule_id === RULE_LOW_SCORE) {
    const score = item.basis?.score
    return isFiniteNumber(score) ? score : Infinity
  }
  if (item.rule_id === RULE_CATEGORY_GAP) {
    const gap = item.basis?.gap_points
    return isFiniteNumber(gap) ? -Math.abs(gap) : Infinity
  }
  return 0
}

const collator = new Intl.Collator('en', { numeric: true })
const compareNumbers = (left: number, right: number) => left === right ? 0 : left < right ? -1 : 1

export function compareRecommendations(left: Recommendation, right: Recommendation): number {
  return compareNumbers(rulePriority(left.rule_id), rulePriority(right.rule_id))
    || compareNumbers(keyWithinRule(left), keyWithinRule(right))
    || collator.compare(left.component_code, right.component_code)
    || collator.compare(left.rule_id, right.rule_id)
    || collator.compare(left.id, right.id)
}

export function sortRecommendations(items: readonly Recommendation[]): Recommendation[] {
  return [...items].sort(compareRecommendations)
}

export interface RankedRecommendation {
  item: Recommendation
  /** 1-based position in the overall priority order. */
  rank: number
}

export interface RecommendationGroup {
  componentCode: string
  items: RankedRecommendation[]
}

/** Groups by component; groups follow their highest-priority proposal. */
export function groupRecommendations(items: readonly Recommendation[]): RecommendationGroup[] {
  const groups = new Map<string, RecommendationGroup>()
  sortRecommendations(items).forEach((item, index) => {
    const group = groups.get(item.component_code) ?? { componentCode: item.component_code, items: [] }
    group.items.push({ item, rank: index + 1 })
    groups.set(item.component_code, group)
  })
  return [...groups.values()]
}

export interface ReviewResult {
  needsReview: boolean
  reasons: string[]
}

/** The «Потребує перевірки» rule; see REVIEW_RULE. Never compares numbers across units. */
export function objectiveReview(item: ObjectiveContextItem): ReviewResult {
  const verified = item.status === 'ok' && item.objective_value !== null
  const reasons: string[] = []
  if (item.status !== 'ok') reasons.push('показник не підтверджено')
  if (item.survey_score !== null && item.survey_score >= HIGH_SELF_ASSESSMENT && !verified) {
    reasons.push(`висока самооцінка (≥ ${HIGH_SELF_ASSESSMENT} зі 100) без підтвердженого значення показника`)
  }
  return { needsReview: reasons.length > 0, reasons }
}

/** Ukrainian wording for fixed English strings the backend returns; other text is shown as is. */
const BACKEND_TEXT: Record<string, string> = {
  'Seven synthetic seed components; not the earlier three-component demo-0.2':
    'Сім синтетичних компонентів демонабору; це не попередня трикомпонентна версія demo-0.2.',
  'Input already rounded by /results; no raw-response precision claim':
    'Вхідні бали вже округлені сервісом /results; точність на рівні окремих відповідей не заявляється.',
  'No approved mapping to appendices B/V; no official maturity labels':
    'Немає затвердженої відповідності додаткам Б/В; офіційних рівнів зрілості немає.',
  'No expected cohort size or expert evidence in upstream contract':
    'Вхідні дані не містять очікуваної чисельності груп і експертних доказів.',
  'Database does not yet freeze questionnaire versions per cycle':
    'База даних поки не фіксує версію анкети для кожного циклу.',
  'Caller chooses before/after; chronology is not inferred from IDs':
    'Порядок «до/після» обирає користувач; хронологія не визначається за ідентифікаторами.',
  'Population and historical questionnaire versions are absent from /results':
    'Склад респондентів та історичні версії анкет у /results відсутні.',
  'Numerical change does not establish causal improvement':
    'Числова зміна не доводить причинно-наслідкового покращення.',
  'Metric IDs, units and evidence links are not supplied by /results':
    'Ідентифікатори метрик, одиниці виміру й посилання на докази не передаються з /results.',
}

export function localizeBackendText(text: string): string {
  return BACKEND_TEXT[text] ?? text
}

export function persistenceText(value: string): string {
  return value.startsWith('none')
    ? 'Пропозиції не зберігаються й не призначаються автоматично: прийняття посадовою особою та облік у трекері — окрема дія.'
    : value
}
