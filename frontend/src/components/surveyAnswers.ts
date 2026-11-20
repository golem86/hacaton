import type { AnonymousSubmission, Questionnaire, QuestionnaireQuestion, RespondentCategory, SubmissionAnswer } from '../types/questionnaireApi'

export function isValidAnswer(question: QuestionnaireQuestion, value: unknown): value is number {
  return Number.isInteger(value)
    && Number.isInteger(question.scale[0])
    && Number.isInteger(question.scale[1])
    && question.scale[0] <= question.scale[1]
    && (value as number) >= question.scale[0]
    && (value as number) <= question.scale[1]
}

export function collectAnswers(
  questionnaire: Questionnaire,
  selected: Readonly<Record<number, number>>,
): SubmissionAnswer[] | null {
  const questions = questionnaire.flatMap(component => component.questions)
  if (questions.length === 0) return null
  const seen = new Set<number>()
  const answers: SubmissionAnswer[] = []
  for (const question of questions) {
    if (!Number.isInteger(question.id) || seen.has(question.id)) return null
    seen.add(question.id)
    const value = selected[question.id]
    if (!isValidAnswer(question, value)) return null
    answers.push({ question_id: question.id, value })
  }
  return answers
}

export function prepareSubmission(
  questionnaire: Questionnaire,
  selected: Readonly<Record<number, number>>,
  category: RespondentCategory | '',
  unit: string,
  token: string,
  units: readonly string[],
): AnonymousSubmission | null {
  if (!category || !units.includes(unit) || !token.trim()) return null
  const answers = collectAnswers(questionnaire, selected)
  if (!answers) return null
  return { token, respondent_category: category, unit, answers }
}
