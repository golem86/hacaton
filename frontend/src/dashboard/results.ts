import { getJson } from '../api/client'
import type { AssessmentResults } from './types'

export function getAssessmentResults(id: number, signal?: AbortSignal): Promise<AssessmentResults> {
  return getJson<AssessmentResults>(`/api/assessments/${id}/results`, signal, {
    401: 'Сесію завершено або вхід не підтверджено. Увійдіть знову.',
    403: 'Для вашої ролі перегляд результатів заборонено.',
    404: 'Результати для вибраного циклу не знайдено. Оновіть список циклів.',
    409: 'Результати доступні після закриття циклу оцінювання.',
  })
}
