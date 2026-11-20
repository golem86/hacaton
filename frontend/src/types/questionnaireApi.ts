export type RespondentCategory = 'mgmt' | 'npp' | 'cadets' | 'staff'

export interface QuestionnaireQuestion {
  id: number
  text: string
  scale: [number, number]
}

export interface QuestionnaireComponent {
  code: string
  name: string
  weight: number
  questions: QuestionnaireQuestion[]
}

export type Questionnaire = QuestionnaireComponent[]

export interface SubmissionAnswer {
  question_id: number
  value: number
}

export interface AnonymousSubmission {
  token: string
  questionnaire_version?: string
  respondent_category: RespondentCategory
  unit: string
  answers: SubmissionAnswer[]
}

export interface SubmissionResponse {
  status: 'accepted'
}
