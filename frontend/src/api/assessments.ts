import type {
  AnonymousSubmission,
  Questionnaire,
  SubmissionResponse,
} from '../types/questionnaireApi'
import { ApiError, getJson, getPublicJson, request } from './client'

export interface Assessment {
  id: number
  name: string
  start_date: string
  status: 'draft' | 'open' | 'closed'
  min_group_size: number
  description?: string
  scope?: string
  end_date?: string | null
  categories?: Array<'mgmt' | 'npp' | 'cadets' | 'staff'>
  questionnaire_version?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isCalendarDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^(?!0000)\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(value)
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value
}

function isAssessment(value: unknown): value is Assessment {
  return isRecord(value)
    && Number.isSafeInteger(value.id) && (value.id as number) > 0
    && typeof value.name === 'string'
    && isCalendarDate(value.start_date)
    && (value.status === 'draft' || value.status === 'open' || value.status === 'closed')
    && Number.isSafeInteger(value.min_group_size) && (value.min_group_size as number) > 0
}

function isAssessmentList(value: unknown): value is Assessment[] {
  return Array.isArray(value) && value.every(isAssessment)
}

function isQuestionnaire(value: unknown): value is Questionnaire {
  if (!Array.isArray(value)) return false
  const questionIds = new Set<number>()
  return value.every(component => {
    if (!isRecord(component)
      || typeof component.code !== 'string'
      || typeof component.name !== 'string'
      || typeof component.weight !== 'number'
      || !Number.isFinite(component.weight)
      || !Array.isArray(component.questions)) return false

    return component.questions.every((question: unknown) => {
      if (!isRecord(question)
        || !Number.isInteger(question.id)
        || typeof question.text !== 'string'
        || !Array.isArray(question.scale)
        || question.scale.length !== 2) return false

      const [min, max] = question.scale
      if (!Number.isSafeInteger(min) || !Number.isSafeInteger(max) || min > max
        || BigInt(max) - BigInt(min) >= 10n) return false

      const id = question.id as number
      if (questionIds.has(id)) return false
      questionIds.add(id)
      return true
    })
  })
}

function isUnitList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(unit => typeof unit === 'string')
}

async function getValidatedJson<T>(
  path: string,
  validate: (value: unknown) => value is T,
  signal?: AbortSignal,
  publicRequest = false,
): Promise<T> {
  const result = publicRequest ? await getPublicJson<unknown>(path, signal) : await getJson<unknown>(path, signal)
  if (!validate(result)) {
    throw new ApiError(200, 'API повернув некоректну відповідь. Спробуйте пізніше.')
  }
  return result
}
export function getAssessments(signal?: AbortSignal): Promise<Assessment[]> {
  return getValidatedJson('/api/assessments', isAssessmentList, signal, true)
}

export function getAssessment(id: number, signal?: AbortSignal): Promise<Assessment> {
  return getValidatedJson(`/api/assessments/${id}`, isAssessment, signal, true)
}

export function getQuestionnaire(id: number, signal?: AbortSignal): Promise<Questionnaire> {
  return getValidatedJson(`/api/assessments/${id}/questionnaires`, isQuestionnaire, signal, true)
}

export function getUnits(signal?: AbortSignal): Promise<string[]> {
  return getValidatedJson('/api/units', isUnitList, signal, true)
}

export class SubmissionOutcomeUnknownError extends Error {
  readonly kind = 'submission-outcome-unknown'

  constructor() {
    super('Не вдалося підтвердити результат надсилання. Анкету могли прийняти. Не надсилайте її повторно без перевірки через погоджений із командою канал')
    this.name = 'SubmissionOutcomeUnknownError'
  }
}

// FastAPI returns detail as a string or an array of validation objects.
// Never display it verbatim: it may contain submitted input, including a code.
async function readErrorDetail(response: Response): Promise<unknown> {
  try {
    const body: unknown = await response.json()
    if (isRecord(body) && 'detail' in body) return body.detail
  } catch {
    // A non-JSON or empty refusal still gets a safe status-based message.
  }
  return undefined
}

function validationField(detail: unknown, field: string): boolean {
  return Array.isArray(detail) && detail.some(item => {
    if (!isRecord(item)) return false
    return Array.isArray(item.loc) && item.loc.includes(field)
  })
}

function submissionError(status: number, detail: unknown): Error {
  switch (status) {
    case 400:
      return new Error('Некоректний запит. Перевірте дані анкети та спробуйте ще раз.')
    case 401:
      return new Error('Сесію не підтверджено. Перевірте код доступу або зверніться до відповідального.')
    case 403:
      return new Error(detail === 'Недійсний або вже використаний код доступу'
        ? 'Код доступу недійсний або вже використаний.'
        : 'Немає доступу до надсилання анкети.')
    case 409:
      return new Error('Цикл оцінювання закрито. Анкету не надіслано.')
    case 422:
      if (validationField(detail, 'unit') || (typeof detail === 'string' && detail.startsWith('Підрозділ не з довідника'))) {
        return new Error('Оберіть підрозділ зі списку та повторіть спробу.')
      }
      if (validationField(detail, 'respondent_category')) {
        return new Error('Оберіть дійсну категорію респондента.')
      }
      if (validationField(detail, 'token')) {
        return new Error('Введіть код доступу та повторіть спробу.')
      }
      return new Error('Перевірте, чи є рівно одна допустима відповідь на кожне питання анкети.')
    default:
      return new Error(`Помилка API (${status}). Анкету не надіслано.`)
  }
}

export async function submitQuestionnaire(
  id: number,
  body: AnonymousSubmission,
  signal?: AbortSignal,
): Promise<SubmissionResponse> {
  let requestBody: string
  try {
    requestBody = JSON.stringify(body)
  } catch {
    throw new Error('Не вдалося підготувати анкету до надсилання.')
  }

  let response: Response
  try {
    response = await request(`/api/assessments/${id}/submissions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: requestBody,
      signal,
    }, 'omit')
  } catch {
    throw new SubmissionOutcomeUnknownError()
  }

  if ([400, 401, 403, 409, 422].includes(response.status)) {
    throw submissionError(response.status, await readErrorDetail(response))
  }
  if (response.status !== 201) throw new SubmissionOutcomeUnknownError()

  try {
    const result: unknown = await response.json()
    if (isRecord(result) && result.status === 'accepted') {
      return { status: 'accepted' }
    }
  } catch {
    // HTTP 201 may follow a committed submission even if its body cannot be read.
  }
  throw new SubmissionOutcomeUnknownError()
}
