import { ApiError, request } from './client'
import type { Assessment } from './assessments'

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
export const issueAccessTokens = (assessmentId: number, count: number, category?: string) => json<{ tokens: string[] }>(`/api/assessments/${assessmentId}/tokens?count=${count}${category ? `&category=${encodeURIComponent(category)}` : ''}`, { method: 'POST' })
export const createCycle = (body: object) => json<Assessment>('/api/assessments', { method: 'POST', body: JSON.stringify(body) })
export const activateCycle = (id: number) => json<Assessment>(`/api/assessments/${id}/activate`, { method: 'POST' })
export const closeCycle = (id: number) => json<Assessment>(`/api/assessments/${id}/close`, { method: 'POST' })
export interface Participation { status: string; tokens_issued: number; tokens_unused: number | null; responses_total: number | null; participation_percent: number | null }
export const getParticipation = (id: number) => json<Participation>(`/api/assessments/${id}/participation`)
