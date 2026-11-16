const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal, messages: Partial<Record<number, string>> = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { 'X-Role': 'manager' },
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError(0, 'Не вдалося з’єднатися з API. Перевірте запуск backend та мережу.')
  }

  if (!response.ok) {
    throw new ApiError(response.status, messages[response.status] ?? `Помилка API (${response.status}). Спробуйте ще раз.`)
  }

  try {
    return await response.json() as T
  } catch {
    throw new ApiError(response.status, 'API повернув некоректну відповідь JSON.')
  }
}
