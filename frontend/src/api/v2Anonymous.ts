import { getPublicV2Json, postPublicV2Json } from './auth'

export interface AnonymousQuestion {
  id: string
  prompt: string
}

export interface AnonymousSurvey {
  id: string
  name: string
  status: 'open'
  questions: AnonymousQuestion[]
}

export function getAnonymousSurveys(signal?: AbortSignal) {
  return getPublicV2Json<AnonymousSurvey[]>('/v2/anonymous/assessments', signal)
}

export function submitAnonymousAnswers(surveyId: string, submissionId: string, answers: Record<string, number>, signal?: AbortSignal) {
  return postPublicV2Json<{ status: string; submission_id: string }>(`/v2/anonymous/assessments/${encodeURIComponent(surveyId)}/responses`, { submission_id: submissionId, answers }, signal)
}
