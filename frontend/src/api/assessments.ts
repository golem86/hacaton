import { getJson } from './client'

export interface Assessment {
  id: number
  name: string
  start_date: string
  status: 'open' | 'closed'
  min_group_size: number
}

export function getAssessments(signal?: AbortSignal): Promise<Assessment[]> {
  return getJson<Assessment[]>('/api/assessments', signal)
}

export function getAssessment(id: number, signal?: AbortSignal): Promise<Assessment> {
  return getJson<Assessment>(`/api/assessments/${id}`, signal)
}
