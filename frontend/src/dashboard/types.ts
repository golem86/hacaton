import type { Assessment } from '../api/assessments'

/**
 * Aggregate-only response of GET /api/assessments/{id}/results (V2 hardening contract, розділ 3).
 * Hidden cells are no longer listed at all: neither the category name nor its numbers.
 * Each slice carries a boolean `suppressed` instead. No individual answers belong here.
 */
export interface AssessmentResults {
  assessment: Pick<Assessment, 'id' | 'name'> & { status: 'closed' }
  min_group_size: number
  responses_total: number | null
  categories: ResultCategory[]
  components: ResultComponent[]
  /** True when at least one group of this slice (or of any component) was withheld (fewer than k answers). */
  suppressed?: boolean
}

export interface ResultCategory {
  category: string
  responses: number | null
  /** Legacy (pre-hardening) flag. Entries with `hidden: true` are dropped by normalizeResults(). */
  hidden?: boolean
}

export interface CategoryScore {
  category: string
  score: number | null
  /** Legacy (pre-hardening) flag. Entries with `hidden: true` are dropped by normalizeResults(). */
  hidden?: boolean
}

export interface ObjectiveIndicator {
  name: string
  value: number
  confirmed: boolean
}

export interface ResultComponent {
  code: string
  name: string
  weight: number
  score: number | null
  by_category: CategoryScore[]
  objective_indicators: ObjectiveIndicator[]
  /** True when some categories of this component were withheld by the server. */
  suppressed?: boolean
}
