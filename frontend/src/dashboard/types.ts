import type { Assessment } from '../api/assessments'

/** Aggregate-only response proposed by PR #5. No individual answers belong here. */
export interface AssessmentResults {
  assessment: Pick<Assessment, 'id' | 'name'> & { status: 'closed' }
  min_group_size: number
  responses_total: number | null
  categories: ResultCategory[]
  components: ResultComponent[]
}

export interface ResultCategory {
  category: string
  responses: number | null
  hidden: boolean
}

export interface CategoryScore {
  category: string
  score: number | null
  hidden: boolean
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
}
