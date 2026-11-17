import { getV2AdminJson } from './auth'
import type { Assessment } from './assessments'
import type { AssessmentResults } from '../dashboard/types'

export function getV2AdminAssessments(signal?: AbortSignal) {
  return getV2AdminJson<Assessment[]>('/v2/admin/assessments', signal)
}

export function getV2AdminAssessment(id: number, signal?: AbortSignal) {
  return getV2AdminJson<Assessment>(`/v2/admin/assessments/${id}`, signal)
}

export function getV2AdminResults(id: number, signal?: AbortSignal) {
  return getV2AdminJson<AssessmentResults>(`/v2/admin/assessments/${id}/results`, signal)
}
