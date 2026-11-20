import type { OfficialTemplate } from './catalog'
import { ANNEX_V_CRITERIA } from './catalog-v2'

export type OfficialAnswers = Record<string, string>

export function validateOfficialAnswers(template: OfficialTemplate, answers: OfficialAnswers): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const question of template.questions) {
    const selected = answers[question.id]
    if (!selected) errors[question.id] = 'Оберіть один варіант відповіді.'
    else if (!question.options.some(option => option.id === selected)) errors[question.id] = 'Обраний варіант не належить до цього питання.'
  }
  return errors
}

/** Лише відповіді на питання шаблону (без сторонніх ключів) — саме вони потрапляють у тіло запиту. */
export function answersForTemplate(template: OfficialTemplate, answers: OfficialAnswers): OfficialAnswers {
  return Object.fromEntries(template.questions.filter(question => answers[question.id]).map(question => [question.id, answers[question.id]]))
}

export const ACCESS_CODE_MAX = 128
export const EXPERT_LABEL_MIN = 3
export const EXPERT_LABEL_MAX = 120

/** Одноразовий код: обов’язковий, без пробілів по краях, не довший за 128 символів (як у backend). */
export function validateAccessCode(code: string): string | null {
  const value = code.trim()
  if (!value) return 'Введіть одноразовий код доступу.'
  if (value.length > ACCESS_CODE_MAX) return `Код доступу не може бути довшим за ${ACCESS_CODE_MAX} символів.`
  if (/\s/.test(value)) return 'Код доступу не містить пробілів. Перевірте введення.'
  return null
}

// Два-три слова з великої літери (Прізвище Ім’я По батькові) або прізвище з ініціалами — схоже на ПІБ.
const NAME_WORD = "[A-ZА-ЯІЇЄҐ][a-zа-яіїєґ'’ʼ-]+"
const FULL_NAME = new RegExp(`^${NAME_WORD}(\\s+${NAME_WORD}){1,2}$`, 'u')
const INITIALS = /^[A-ZА-ЯІЇЄҐ][a-zа-яіїєґ'’ʼ-]+\s+[A-ZА-ЯІЇЄҐ]\.\s?([A-ZА-ЯІЇЄҐ]\.)?$|^[A-ZА-ЯІЇЄҐ]\.\s?([A-ZА-ЯІЇЄҐ]\.\s?)?[A-ZА-ЯІЇЄҐ][a-zа-яіїєґ'’ʼ-]+$/u

/** Позначка експерта — посада або роль, не ПІБ і не контакти (3–120 символів). */
export function validateExpertLabel(label: string): string | null {
  const value = label.trim()
  if (value.length < EXPERT_LABEL_MIN) return `Вкажіть посаду або роль експерта: щонайменше ${EXPERT_LABEL_MIN} символи.`
  if (value.length > EXPERT_LABEL_MAX) return `Позначка експерта не може бути довшою за ${EXPERT_LABEL_MAX} символів.`
  if (/@|\+?\d[\d\s()-]{6,}/.test(value)) return 'Не вказуйте email чи телефон — лише посаду або роль.'
  if (FULL_NAME.test(value) || INITIALS.test(value)) return 'Схоже на прізвище та ім’я. Вкажіть посаду або роль (наприклад, «Начальник кафедри»), а не ПІБ.'
  return null
}

export const EVIDENCE_MAX = 500
export const INDICATOR_NAME_MIN = 3
export const INDICATOR_NAME_MAX = 200
export const PERIOD_MAX = 40

/** Внесення пункту чеклиста: статус обов’язковий, доказ — необов’язковий короткий опис або посилання. */
export function validateChecklistEntry(entry: { status: string; evidence: string }): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!['yes', 'partial', 'no'].includes(entry.status)) errors.status = 'Оберіть статус: Так, Частково або Ні.'
  if (entry.evidence.trim().length > EVIDENCE_MAX) errors.evidence = `Доказ не може бути довшим за ${EVIDENCE_MAX} символів.`
  return errors
}

export interface IndicatorDraft { criterion: string; name: string; value: string; target: string; period: string }

function percent(raw: string): number | null {
  const value = Number(raw.trim().replace(',', '.'))
  return raw.trim() !== '' && Number.isFinite(value) ? value : null
}

/** Об’єктивний показник: критерій Додатка В (без `maturity`), назва, значення й ціль у відсотках 0–100, період. */
export function validateIndicatorDraft(draft: IndicatorDraft): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!ANNEX_V_CRITERIA.includes(draft.criterion as never) || draft.criterion === 'maturity') errors.criterion = 'Оберіть критерій зі списку.'
  const name = draft.name.trim()
  if (name.length < INDICATOR_NAME_MIN || name.length > INDICATOR_NAME_MAX) errors.name = `Назва показника — від ${INDICATOR_NAME_MIN} до ${INDICATOR_NAME_MAX} символів.`
  for (const field of ['value', 'target'] as const) {
    const value = percent(draft[field])
    if (value === null || value < 0 || value > 100) errors[field] = 'Введіть число від 0 до 100.'
  }
  const period = draft.period.trim()
  if (!period || period.length > PERIOD_MAX) errors.period = `Вкажіть період (до ${PERIOD_MAX} символів), наприклад «2026, I півріччя».`
  return errors
}

export function indicatorPayload(draft: IndicatorDraft) {
  return { criterion: draft.criterion, name: draft.name.trim(), value: percent(draft.value) ?? 0, target: percent(draft.target) ?? 0, period: draft.period.trim() }
}
