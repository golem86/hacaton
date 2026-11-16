export interface Assessment {
  id: number
  name: string
  start_date: string
  status: 'open' | 'closed'
  min_group_size: number
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { 'X-Role': 'manager' },
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('Не вдалося з’єднатися з API. Перевірте запуск backend.')
  }

  if (!response.ok) {
    throw new Error(`Помилка API (${response.status}). Спробуйте ще раз.`)
  }

  return response.json() as Promise<T>
}

export function getAssessments(signal?: AbortSignal): Promise<Assessment[]> {
  return getJson<Assessment[]>('/api/assessments', signal)
}

export function getAssessment(id: number, signal?: AbortSignal): Promise<Assessment> {
  return getJson<Assessment>(`/api/assessments/${id}`, signal)
}
