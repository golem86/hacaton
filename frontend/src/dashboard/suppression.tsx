import type { AssessmentResults, CategoryScore, ResultCategory, ResultComponent } from './types'

/**
 * Захист малих груп у UI (V2 hardening contract, розділ 3 «Поведінка даних»).
 *
 * Сервер більше не перелічує прихованих клітинок: немає ні назви категорії чи підрозділу, ні чисел.
 * Натомість кожен розріз має булеве `suppressed`. UI показує лише те, що прийшло, і примітку,
 * якщо частину груп приховано. Елементи старого формату з `hidden: true` відкидаються повністю
 * (не показуються навіть назви), щоб випадкова відповідь старого backend нічого не розкрила.
 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** Елемент старого формату, який сервер позначив прихованим. */
export function isHiddenEntry(value: unknown): boolean {
  return isRecord(value) && value.hidden === true
}

/** Прапорець розрізу. Підтримує `suppressed` і довші назви, які може обрати backend для окремого розрізу. */
export function sliceFlag(value: unknown, ...keys: string[]): boolean {
  if (!isRecord(value)) return false
  return ['suppressed', ...keys].some(key => value[key] === true)
}

export function visibleCategories(categories: readonly ResultCategory[] | null | undefined): ResultCategory[] {
  return Array.isArray(categories) ? categories.filter(item => isRecord(item) && !isHiddenEntry(item)) : []
}

/**
 * Видимі клітинки компонента. Якщо передано перелік категорій, клітинка має належати видимій категорії:
 * прихована категорія приховує всі свої клітинки, навіть якщо бал помилково надіслано.
 */
export function visibleCells(component: Pick<ResultComponent, 'by_category'>, categories?: readonly ResultCategory[] | null): CategoryScore[] {
  const cells = Array.isArray(component.by_category) ? component.by_category : []
  const allowed = categories ? new Set(visibleCategories(categories).map(item => item.category)) : null
  return cells.filter(cell => isRecord(cell) && !isHiddenEntry(cell) && (allowed === null || allowed.has(cell.category)))
}

export function componentSuppressed(component: ResultComponent, categories?: readonly ResultCategory[] | null): boolean {
  const cells = Array.isArray(component.by_category) ? component.by_category : []
  return sliceFlag(component, 'by_category_suppressed') || visibleCells(component, categories).length < cells.length
}

/** Чи приховано частину груп у результатах (будь-який розріз). */
export function resultsSuppressed(results: Pick<AssessmentResults, 'categories' | 'components'> & { suppressed?: boolean }): boolean {
  const categories = Array.isArray(results.categories) ? results.categories : []
  return sliceFlag(results, 'categories_suppressed')
    || visibleCategories(categories).length < categories.length
    || (Array.isArray(results.components) ? results.components : []).some(component => componentSuppressed(component, categories))
}

/** Приводить відповідь /results (новий або старий формат) до нового: лише видимі групи + `suppressed`. */
export function normalizeResults(raw: AssessmentResults): AssessmentResults {
  const rawCategories = Array.isArray(raw.categories) ? raw.categories : []
  const categories = visibleCategories(rawCategories).map(item => ({ category: item.category, responses: item.responses ?? null }))
  const components = (Array.isArray(raw.components) ? raw.components : []).map(component => ({
    ...component,
    by_category: visibleCells(component, rawCategories).map(cell => ({ category: cell.category, score: cell.score ?? null })),
    objective_indicators: Array.isArray(component.objective_indicators) ? component.objective_indicators : [],
    suppressed: componentSuppressed(component, rawCategories),
  }))
  return { ...raw, categories, components, suppressed: resultsSuppressed(raw) }
}

/** Текст примітки; k — мінімальний розмір групи циклу, якщо відомий. */
export function suppressionNoteText(k?: number | null): string {
  const threshold = typeof k === 'number' && Number.isSafeInteger(k) && k > 0 ? String(k) : 'k'
  return `Частину груп приховано для захисту анонімності (менше ${threshold} відповідей).`
}

export function SuppressionNote({ k, className = 'dashboard-privacy-note' }: { k?: number | null; className?: string }) {
  return <p className={className} data-suppressed="true">{suppressionNoteText(k)}</p>
}
