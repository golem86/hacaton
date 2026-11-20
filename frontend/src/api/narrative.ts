import { ApiError, getJson, readErrorBody, request, statusMessage } from './client'

// Чернетки текстів звіту локальною ШІ (backend: /v2/admin/reports/{id}/narrative, /v2/admin/lm/...).
export type NarrativeKind = 'summary' | 'recommendations' | 'compare'
export type NarrativeJobStatus = 'queued' | 'running' | 'done' | 'failed'

export interface LmStatus {
  enabled: boolean
  reachable: boolean
  model: string | null
}

export interface NarrativeJob {
  job_id: string
  status: NarrativeJobStatus
  kind: NarrativeKind
  assessment_ids: number[]
  text?: string
  verified?: boolean
  unverified_numbers?: string[]
  error?: string
  created_at: string
  finished_at?: string
}

export const POLL_INTERVAL_MS = 4000
const JOB_STATUSES: readonly NarrativeJobStatus[] = ['queued', 'running', 'done', 'failed']
const KINDS: readonly NarrativeKind[] = ['summary', 'recommendations', 'compare']

const errors: Partial<Record<number, string>> = {
  403: 'Чернетки ШІ доступні лише адміністратору.',
  404: 'Цикл не знайдено.',
  409: 'Чернетка доступна після закриття циклу.',
  429: 'Черга генерації заповнена. Спробуйте за кілька хвилин.',
  503: 'Локальна ШІ не налаштована на сервері.',
}
const jobErrors: Partial<Record<number, string>> = {
  ...errors,
  404: 'Завдання не знайдено або його строк зберігання минув. Запустіть генерацію ще раз.',
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function invalid(): never {
  throw new ApiError(200, 'API повернув некоректну відповідь локальної ШІ.')
}

export function parseLmStatus(value: unknown): LmStatus {
  if (!isRecord(value) || typeof value.enabled !== 'boolean' || typeof value.reachable !== 'boolean') invalid()
  return {
    enabled: value.enabled,
    reachable: value.enabled && value.reachable,
    model: typeof value.model === 'string' ? value.model : null,
  }
}

/** Перевіряє форму завдання; текст лишається простим рядком (у UI — лише як текст, без HTML). */
export function parseNarrativeJob(value: unknown): NarrativeJob {
  if (!isRecord(value) || typeof value.job_id !== 'string' || !JOB_STATUSES.includes(value.status as NarrativeJobStatus)
      || !KINDS.includes(value.kind as NarrativeKind) || !Array.isArray(value.assessment_ids)
      || !value.assessment_ids.every(id => Number.isSafeInteger(id)) || typeof value.created_at !== 'string') invalid()
  const job: NarrativeJob = {
    job_id: value.job_id, status: value.status as NarrativeJobStatus, kind: value.kind as NarrativeKind,
    assessment_ids: value.assessment_ids as number[], created_at: value.created_at,
  }
  if (typeof value.finished_at === 'string') job.finished_at = value.finished_at
  if (job.status === 'done') {
    if (typeof value.text !== 'string' || typeof value.verified !== 'boolean') invalid()
    job.text = value.text
    job.verified = value.verified
    job.unverified_numbers = Array.isArray(value.unverified_numbers)
      ? value.unverified_numbers.filter((item): item is string => typeof item === 'string')
      : []
  }
  if (job.status === 'failed') job.error = typeof value.error === 'string' && value.error ? value.error : 'Не вдалося згенерувати текст.'
  return job
}

export async function getLmStatus(signal?: AbortSignal): Promise<LmStatus> {
  return parseLmStatus(await getJson<unknown>('/v2/admin/lm/status', signal, errors))
}

async function startJob(path: string, body: unknown, signal?: AbortSignal): Promise<string> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body), signal })
  if (response.status !== 202) {
    const { detail } = await readErrorBody(response)
    // Повідомлення сервера показуємо лише для 422 різних циклів; інші — фіксовані тексти UI
    const message = response.status === 422 && detail === 'Оберіть два різні цикли' ? detail : statusMessage(response.status, errors)
    throw new ApiError(response.status, message)
  }
  let data: unknown
  try { data = await response.json() } catch { invalid() }
  if (!isRecord(data) || typeof data.job_id !== 'string' || !/^[A-Za-z0-9_-]{8,64}$/.test(data.job_id)) invalid()
  return data.job_id
}

export function startCycleNarrative(assessmentId: number, kind: 'summary' | 'recommendations', signal?: AbortSignal) {
  return startJob(`/v2/admin/reports/${assessmentId}/narrative`, { kind }, signal)
}

export function startCompareNarrative(baseAssessmentId: number, targetAssessmentId: number, signal?: AbortSignal) {
  return startJob('/v2/admin/reports/compare/narrative',
                  { base_assessment_id: baseAssessmentId, target_assessment_id: targetAssessmentId }, signal)
}

export async function getNarrativeJob(jobId: string, signal?: AbortSignal): Promise<NarrativeJob> {
  return parseNarrativeJob(await getJson<unknown>(`/v2/admin/lm/jobs/${encodeURIComponent(jobId)}`, signal, jobErrors))
}

function abortableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason ?? new DOMException('Aborted', 'AbortError'))
    const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve() }, ms)
    function onAbort() {
      clearTimeout(timer)
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export interface PollOptions {
  signal?: AbortSignal
  intervalMs?: number
  onUpdate?: (job: NarrativeJob) => void
  sleep?: (ms: number, signal?: AbortSignal) => Promise<void>
}

/** Опитує завдання кожні intervalMs (типово 4 с), доки воно не стане done або failed. */
export async function pollNarrativeJob(jobId: string, options: PollOptions = {}): Promise<NarrativeJob> {
  const { signal, intervalMs = POLL_INTERVAL_MS, onUpdate, sleep = abortableSleep } = options
  for (;;) {
    const job = await getNarrativeJob(jobId, signal)
    onUpdate?.(job)
    if (job.status === 'done' || job.status === 'failed') return job
    await sleep(intervalMs, signal)
  }
}
