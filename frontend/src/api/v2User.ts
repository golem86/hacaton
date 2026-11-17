import { getV2AdminJson, mutateV2Json } from './auth'

export interface PersonalQuestion { id: string; component: string; prompt: string; hint: string }
export interface PersonalAssessment { id: string; name: string; duration: string; opens_at: string; closes_at: string; status: 'open' | 'unavailable'; questions: PersonalQuestion[] }
export interface PersonalAttempt { id: string; assessment_id: string; assessment_name: string; status: 'draft' | 'completed'; answers: Record<string, number>; started_at: string; completed_at: string | null; updated_at: string }
export interface PersonalStats { completed_tests: number; responses_total: number; average_response: number | null; official_index: number | null }
export const getPersonalAssessments = (signal?: AbortSignal) => getV2AdminJson<PersonalAssessment[]>('/v2/user/assessments', signal)
export const getPersonalAttempts = (signal?: AbortSignal) => getV2AdminJson<PersonalAttempt[]>('/v2/user/attempts', signal)
export const getPersonalStats = (signal?: AbortSignal) => getV2AdminJson<PersonalStats>('/v2/user/stats', signal)
export const createPersonalAttempt = (input: { assessment_id: string; answers?: Record<string, number> }) => mutateV2Json<PersonalAttempt>('/v2/user/attempts', 'POST', { ...input, status: 'draft' })
export const savePersonalDraft = (attemptId: string, input: { assessment_id: string; answers: Record<string, number> }) => mutateV2Json<PersonalAttempt>(`/v2/user/attempts/${encodeURIComponent(attemptId)}`, 'PATCH', { ...input, status: 'draft' })
export const completePersonalAttempt = (attemptId: string, input: { answers: Record<string, number> }) => mutateV2Json<PersonalAttempt>(`/v2/user/attempts/${encodeURIComponent(attemptId)}/complete`, 'POST', input)
