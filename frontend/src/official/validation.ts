import type { OfficialTemplate } from './catalog'

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
