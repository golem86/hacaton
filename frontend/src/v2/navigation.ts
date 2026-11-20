import type { UserRole } from '../api/auth'
import type { PersonalView } from './PersonalModule'

/**
 * Розмітка кабінетів за серверною роллю (docs/V2_HARDENING_CONTRACT.md, розділ 1).
 * Меню лише допомагає зорієнтуватися: доступ до кожного маршруту перевіряє сервер.
 */
export type AdminSection = 'overview' | 'analytics' | 'maturity' | 'tracker' | 'testing' | 'users' | 'expert' | 'checklist' | 'objective' | 'audit' | 'reports'
export type OfficerSection = 'codes' | 'participation' | 'checklist' | 'objective'
export type UserSection = PersonalView | 'official'

export type AppRoute =
  | { role: 'admin'; section: AdminSection }
  | { role: 'user'; section: UserSection }
  | { role: 'data_officer'; section: OfficerSection }

export interface NavItem<K extends string = string> { key: K; title: string; path: string }

const ROOTS: Readonly<Record<UserRole, string>> = { admin: '/admin', user: '/app', data_officer: '/officer' }

const ADMIN_ITEMS: readonly { key: AdminSection; title: string }[] = [
  { key: 'overview', title: 'Огляд' },
  { key: 'analytics', title: 'Аналітика' },
  { key: 'maturity', title: 'Зрілість (Додаток В)' },
  { key: 'tracker', title: 'Трекер рекомендацій' },
  { key: 'testing', title: 'Цикли оцінювання' },
  { key: 'users', title: 'Користувачі й ролі' },
  { key: 'expert', title: 'Експертне оцінювання' },
  { key: 'checklist', title: 'Чеклист Додатка Б' },
  { key: 'objective', title: 'Об’єктивні показники' },
  { key: 'audit', title: 'Журнал дій' },
  { key: 'reports', title: 'Звіти' },
]

/**
 * Кабінет data_officer: відкриті цикли, видача кодів, участь і внесення даних Додатка В (чеклист, показники).
 * Без результатів, аналітики, журналу, звітів і трекера; внесене підтверджує лише адміністратор.
 */
const OFFICER_ITEMS: readonly { key: OfficerSection; title: string }[] = [
  { key: 'codes', title: 'Відкриті цикли й коди' },
  { key: 'participation', title: 'Участь' },
  { key: 'checklist', title: 'Чеклист Додатка Б' },
  { key: 'objective', title: 'Об’єктивні показники' },
]

const USER_ITEMS: readonly { key: UserSection; title: string }[] = [
  { key: 'profile', title: 'Мій кабінет' },
  { key: 'available', title: 'Мої тестування' },
  { key: 'official', title: 'Офіційна анкета' },
  { key: 'attempt', title: 'Поточне тестування' },
  { key: 'history', title: 'Мої результати' },
  { key: 'stats', title: 'Персональна статистика' },
  { key: 'unit-results', title: 'Результати підрозділу' },
]

const ITEMS = { admin: ADMIN_ITEMS, user: USER_ITEMS, data_officer: OFFICER_ITEMS } as const
const DEFAULT_SECTION = { admin: 'overview', user: 'profile', data_officer: 'codes' } as const

export function navigationFor(role: UserRole): NavItem[] {
  return ITEMS[role].map(item => ({ key: item.key, title: item.title, path: `${ROOTS[role]}/${item.key}` }))
}

export function homePathFor(role: UserRole): string {
  return ROOTS[role]
}

export function sectionTitle(route: AppRoute): string {
  return (ITEMS[route.role] as readonly { key: string; title: string }[]).find(item => item.key === route.section)?.title ?? ''
}

/** Шлях → кабінет і розділ. Невідомий розділ веде на перший розділ кабінету. */
export function routeFromPath(path: string): AppRoute {
  const [root, section] = path.split('/').filter(Boolean)
  const known = (role: UserRole) => (ITEMS[role] as readonly { key: string }[]).some(item => item.key === section)
  if (root === 'app') return { role: 'user', section: known('user') ? section as UserSection : DEFAULT_SECTION.user }
  if (root === 'officer') return { role: 'data_officer', section: known('data_officer') ? section as OfficerSection : DEFAULT_SECTION.data_officer }
  return { role: 'admin', section: known('admin') ? section as AdminSection : DEFAULT_SECTION.admin }
}

export const PANEL_TEXT: Readonly<Record<UserRole, { brand: string; navLabel: string; navAria: string; overline: string; subtitle: string }>> = {
  admin: {
    brand: 'Адміністративна панель', navLabel: 'Адміністрування', navAria: 'Навігація адміністратора', overline: 'АДМІНІСТРАТОР',
    subtitle: 'Організаційні агрегати з Survey API та Analytics.',
  },
  data_officer: {
    brand: 'Коди доступу', navLabel: 'Коди й участь', navAria: 'Навігація відповідального за коди доступу', overline: 'ВІДПОВІДАЛЬНИЙ ЗА КОДИ ДОСТУПУ',
    subtitle: 'Видача одноразових кодів і моніторинг участі. Результати й аналітика для цієї ролі недоступні.',
  },
  user: {
    brand: 'Особистий простір', navLabel: 'Мій простір', navAria: 'Навігація користувача', overline: 'КОРИСТУВАЧ',
    subtitle: 'Ваші особисті тестування й результати.',
  },
}
