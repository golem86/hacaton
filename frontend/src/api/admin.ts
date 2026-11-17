import { ApiError, request } from './client'

async function json<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const response = await request(path, { ...init, signal })
  if (!response.ok) {
    let message = `Помилка API (${response.status}).`
    try { const body = await response.json() as { detail?: unknown }; if (typeof body.detail === 'string') message = body.detail } catch {}
    if (response.status === 501) message = 'Функція очікує окремого погодженого API.'
    if (response.status === 503) message = 'Сервіс тимчасово недоступний.'
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export interface AuditEvent { id: number; created_at: string; actor_role: string; action: string; assessment_id: number | null; details: Record<string, number> }
export const getAuditEvents = (signal?: AbortSignal) => json<AuditEvent[]>('/api/audit-events?limit=100', {}, signal)
export const issueAccessTokens = (assessmentId: number, count: number) => json<{ tokens: string[] }>(`/api/assessments/${assessmentId}/tokens?count=${count}`, { method: 'POST' })
