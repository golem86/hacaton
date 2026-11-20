import { ApiError, getJson } from '../api/client'
import { normalizeResults } from './suppression'
import type { AssessmentResults } from './types'

export async function getAssessmentResults(id: number, signal?: AbortSignal): Promise<AssessmentResults> {
  const raw = await getJson<unknown>(`/api/assessments/${id}/results`, signal, {
    401: 'Сесію завершено, увійдіть знову.',
    403: 'Для вашої ролі перегляд результатів заборонено.',
    404: 'Результати для вибраного циклу не знайдено. Оновіть список циклів.',
    409: 'Результати доступні після закриття циклу оцінювання.',
  })
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw new ApiError(200, 'API повернув некоректну відповідь результатів.')
  // Приховані групи відкидаються тут, щоб жоден компонент їх не отримав.
  return normalizeResults(raw as AssessmentResults)
}
