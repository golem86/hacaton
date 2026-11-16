import type {
  AnonymousSubmission,
  Questionnaire,
  SubmissionResponse,
} from '../types/questionnaireApi'

export interface Assessment {
  id: number
  name: string
  start_date: string
  status: 'open' | 'closed'
  min_group_size: number
}

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isAssessment(value: unknown): value is Assessment {
  return isRecord(value)
    && Number.isInteger(value.id)
    && typeof value.name === 'string'
    && typeof value.start_date === 'string'
    && (value.status === 'open' || value.status === 'closed')
    && Number.isInteger(value.min_group_size)
}

function isAssessmentList(value: unknown): value is Assessment[] {
  return Array.isArray(value) && value.every(isAssessment)
}

function isQuestionnaire(value: unknown): value is Questionnaire {
  return Array.isArray(value) && value.every(component =>
    isRecord(component)
    && typeof component.code === 'string'
    && typeof component.name === 'string'
    && typeof component.weight === 'number'
    && Number.isFinite(component.weight)
    && Array.isArray(component.questions)
    && component.questions.every((question: unknown) =>
      isRecord(question)
      && Number.isInteger(question.id)
      && typeof question.text === 'string'
      && Array.isArray(question.scale)
      && question.scale.length === 2
      && question.scale.every((bound: unknown) => Number.isInteger(bound))
    )
  )
}

function isUnitList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(unit => typeof unit === 'string')
}

async function getJson<T>(
  path: string,
  validate: (value: unknown) => value is T,
  signal?: AbortSignal,
  role = 'manager',
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { 'X-Role': role },
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('Не вдалося з’єднатися з API. Перевірте запуск backend.')
  }

  if (!response.ok) {
    throw new Error(`Помилка API (${response.status}). Спробуйте ще раз.`)
  }

  let result: unknown
  try {
    result = await response.json()
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('API повернув некоректну відповідь. Спробуйте пізніше.')
  }
  if (!validate(result)) {
    throw new Error('API повернув некоректну відповідь. Спробуйте пізніше.')
  }
  return result
}

export function getAssessments(signal?: AbortSignal): Promise<Assessment[]> {
  return getJson('/api/assessments', isAssessmentList, signal)
}

export function getAssessment(id: number, signal?: AbortSignal): Promise<Assessment> {
  return getJson(`/api/assessments/${id}`, isAssessment, signal)
}

export function getQuestionnaire(id: number, signal?: AbortSignal): Promise<Questionnaire> {
  return getJson(`/api/assessments/${id}/questionnaires`, isQuestionnaire, signal, 'respondent')
}

export function getUnits(signal?: AbortSignal): Promise<string[]> {
  return getJson('/api/units', isUnitList, signal, 'respondent')
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
      return new Error('API не прийняв роль респондента. Зверніться до відповідального за систему.')
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
    response = await fetch(`${apiBaseUrl}/api/assessments/${id}/submissions`, {
      method: 'POST',
      headers: {
        'X-Role': 'respondent',
        'Content-Type': 'application/json',
      },
      body: requestBody,
      signal,
    })
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
