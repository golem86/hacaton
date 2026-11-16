import type { AssessmentResults } from './types'

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export class ResultsError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ResultsError'
  }
}

export async function getAssessmentResults(id: number, signal?: AbortSignal): Promise<AssessmentResults> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}/api/assessments/${id}/results`, {
      headers: { 'X-Role': 'manager' },
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ResultsError(0, 'Не вдалося з’єднатися з API. Перевірте запуск backend та мережу.')
  }

  if (!response.ok) {
    const messages: Record<number, string> = {
      401: 'Демо-роль не розпізнано. Перевірте налаштування доступу до API.',
      403: 'Для цієї демо-ролі перегляд результатів заборонено.',
      404: 'Результати для вибраного циклу не знайдено. Оновіть список циклів.',
      409: 'Результати доступні після закриття циклу оцінювання.',
    }
    throw new ResultsError(response.status, messages[response.status] ?? `Помилка API (${response.status}). Спробуйте ще раз.`)
  }

  return response.json() as Promise<AssessmentResults>
}
