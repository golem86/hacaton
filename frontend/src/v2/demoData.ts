export type DemoAnswer = 1 | 2 | 3 | 4 | 5

export interface DemoQuestion {
  id: string
  component: string
  prompt: string
  hint: string
}

export interface DemoAttempt {
  id: string
  assessmentId: string
  assessmentName: string
  startedAt: string
  completedAt?: string
  answers: Record<string, DemoAnswer>
}

export interface DemoStore {
  draft: DemoAttempt | null
  history: DemoAttempt[]
}

export interface DemoAssessment {
  id: string
  name: string
  duration: string
  opensAt: string
  closesAt: string
}

export const demoQuestions: DemoQuestion[] = [
  { id: 'q1', component: 'C1', prompt: 'Я розумію, як у підрозділі приймаються доброчесні рішення.', hint: 'Організаційні орієнтири' },
  { id: 'q2', component: 'C2', prompt: 'Керівники послідовно демонструють нульову толерантність до зловживань.', hint: 'Лідерство та приклад' },
  { id: 'q3', component: 'C3', prompt: 'Я знаю, куди безпечно повідомити про потенційне порушення.', hint: 'Канали повідомлень' },
  { id: 'q4', component: 'C4', prompt: 'Рішення щодо ризиків пояснюються прозоро та своєчасно.', hint: 'Прозорість' },
  { id: 'q5', component: 'C5', prompt: 'Навчання допомагає мені діяти відповідно до політик доброчесності.', hint: 'Компетентності' },
  { id: 'q6', component: 'C6', prompt: 'Контрольні процедури вбудовані у щоденну роботу.', hint: 'Контроль і моніторинг' },
  { id: 'q7', component: 'C7', prompt: 'Після оцінювання команда має зрозумілий план покращень.', hint: 'Покращення' },
]

export const demoAssessments: DemoAssessment[] = [
  { id: 'personal-2026-q4', name: 'Особисте самооцінювання · Q4 2026', duration: '7 питань · близько 5 хв', opensAt: '2026-11-17T00:00:00Z', closesAt: '2026-11-24T23:59:59Z' },
  { id: 'personal-2027-q1', name: 'Особисте самооцінювання · Q1 2027', duration: 'Підготовка · доступне з 2027-01-01', opensAt: '2027-01-01T00:00:00Z', closesAt: '2027-01-08T23:59:59Z' },
]

export const anonymousQuestions = [
  { id: 'a1', prompt: 'Наскільки зрозумілими є правила доброчесності у вашій організації?' },
  { id: 'a2', prompt: 'Наскільки безпечно повідомляти про потенційні порушення?' },
  { id: 'a3', prompt: 'Наскільки послідовно керівництво реагує на ризики?' },
]

export function emptyDemoStore(): DemoStore {
  return { draft: null, history: [] }
}

export function isDemoAssessmentAvailable(assessment: DemoAssessment, now = Date.now()) {
  return now >= Date.parse(assessment.opensAt) && now <= Date.parse(assessment.closesAt)
}

export function formatDeadline(value: string) {
  return new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export function readDemoStore(storageKey = 'integrity-v2-personal-demo'): DemoStore {
  if (typeof window === 'undefined') return emptyDemoStore()
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return emptyDemoStore()
    const parsed = JSON.parse(raw) as Partial<DemoStore>
    return {
      draft: parsed.draft ?? null,
      history: Array.isArray(parsed.history) ? parsed.history : [],
    }
  } catch {
    return emptyDemoStore()
  }
}

export function writeDemoStore(store: DemoStore, storageKey = 'integrity-v2-personal-demo') {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(storageKey, JSON.stringify(store))
}

export function averageAnswer(attempt: DemoAttempt): number | null {
  const values = Object.values(attempt.answers)
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}
