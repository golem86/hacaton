/**
 * Чисті функції списку «Мої тестування»: пошук, фільтри, сортування й пагінація.
 * Без React і без доступу до сховища, тому їх легко перевіряти в tests/test-list.test.mjs.
 */

export interface TestListItem {
  id: string
  name: string
  status: 'open' | 'unavailable'
  created_at: string
  opens_at: string
  closes_at: string
}

export type StatusFilter = 'all' | 'open' | 'unavailable'
export type SortKey = 'deadline-asc' | 'deadline-desc' | 'created-desc' | 'created-asc' | 'name-asc' | 'name-desc'

export interface TestListFilters {
  query: string
  status: StatusFilter
  /** Межі у форматі YYYY-MM-DD (значення `<input type="date">`), включно; порожній рядок — без межі. */
  createdFrom: string
  createdTo: string
  deadlineFrom: string
  deadlineTo: string
}

export interface FilterOptions {
  /** Часовий пояс для календарних дат; за замовчуванням — пояс браузера (як і дати на картках). */
  timeZone?: string
}

export interface SortOptions {
  /** «Зараз» для поділу недоступних на заплановані й завершені. */
  now?: number
}

export const DEFAULT_FILTERS: Readonly<TestListFilters> = Object.freeze({
  query: '',
  status: 'all',
  createdFrom: '',
  createdTo: '',
  deadlineFrom: '',
  deadlineTo: '',
})

/** За замовчуванням: спершу доступні зараз (найближчий дедлайн першим), далі заплановані, потім завершені. */
export const DEFAULT_SORT: SortKey = 'deadline-asc'
export const PAGE_SIZES = [6, 12, 24] as const
export const DEFAULT_PAGE_SIZE = 6

export const STATUS_OPTIONS: readonly { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'Усі' },
  { value: 'open', label: 'Доступні зараз' },
  { value: 'unavailable', label: 'Недоступні' },
]

export const SORT_OPTIONS: readonly { value: SortKey; label: string }[] = [
  { value: 'deadline-asc', label: 'Дедлайн: найближчий' },
  { value: 'deadline-desc', label: 'Дедлайн: найпізніший' },
  { value: 'created-desc', label: 'Дата створення: новіші' },
  { value: 'created-asc', label: 'Дата створення: старіші' },
  { value: 'name-asc', label: 'Назва: А–Я' },
  { value: 'name-desc', label: 'Назва: Я–А' },
]

const DATE_KEY = /^\d{4}-\d{2}-\d{2}$/

/** Нормалізує текст для пошуку: зайві пробіли, регістр (зокрема Ґ/Є/І/Ї) і різні апострофи. */
export function normalizeSearchText(value: string): string {
  return value
    .normalize('NFC')
    .replace(/[’ʼ`´']/g, '’')
    .replace(/\s+/g, ' ')
    .trim()
    .toLocaleLowerCase('uk-UA')
}

const dateKeyFormatters = new Map<string, Intl.DateTimeFormat>()

/** Календарна дата моменту ISO 8601 у вказаному поясі як YYYY-MM-DD; '' для некоректного значення. */
export function toDateKey(value: string | null | undefined, timeZone?: string): string {
  if (!value) return ''
  const time = Date.parse(value)
  if (Number.isNaN(time)) return ''
  const cacheKey = timeZone ?? ''
  let formatter = dateKeyFormatters.get(cacheKey)
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
    dateKeyFormatters.set(cacheKey, formatter)
  }
  const parts = Object.fromEntries(formatter.formatToParts(time).map((part) => [part.type, part.value]))
  return `${parts.year}-${parts.month}-${parts.day}`
}

function inRange(key: string, from: string, to: string): boolean {
  const hasFrom = DATE_KEY.test(from)
  const hasTo = DATE_KEY.test(to)
  if (!hasFrom && !hasTo) return true
  if (!key) return false
  return (!hasFrom || key >= from) && (!hasTo || key <= to)
}

/** Кількість застосованих фільтрів (для кнопки «Фільтри» і «Скинути фільтри»). */
export function activeFilterCount(filters: TestListFilters): number {
  return [
    normalizeSearchText(filters.query) !== '',
    filters.status !== 'all',
    DATE_KEY.test(filters.createdFrom) || DATE_KEY.test(filters.createdTo),
    DATE_KEY.test(filters.deadlineFrom) || DATE_KEY.test(filters.deadlineTo),
  ].filter(Boolean).length
}

export function filterTests<T extends TestListItem>(items: readonly T[], filters: TestListFilters, options: FilterOptions = {}): T[] {
  const words = normalizeSearchText(filters.query).split(' ').filter(Boolean)
  return items.filter((item) => {
    if (filters.status !== 'all' && item.status !== filters.status) return false
    if (words.length) {
      const name = normalizeSearchText(item.name)
      if (!words.every((word) => name.includes(word))) return false
    }
    if (!inRange(toDateKey(item.created_at, options.timeZone), filters.createdFrom, filters.createdTo)) return false
    return inRange(toDateKey(item.closes_at, options.timeZone), filters.deadlineFrom, filters.deadlineTo)
  })
}

const collator = new Intl.Collator('uk-UA', { sensitivity: 'base', numeric: true })

function time(value: string | null | undefined): number {
  return value ? Date.parse(value) : Number.NaN
}

/** Порівняння дат: некоректні значення завжди в кінці, незалежно від напряму. */
function compareTime(a: number, b: number, direction: 1 | -1): number {
  const aBad = Number.isNaN(a)
  const bBad = Number.isNaN(b)
  if (aBad || bBad) return aBad === bBad ? 0 : aBad ? 1 : -1
  return (a - b) * direction
}

export type Availability = 'open' | 'upcoming' | 'closed'

/** Доступність для підпису на картці: статус із сервера, а недоступні діляться на заплановані й завершені. */
export function availabilityOf(item: Pick<TestListItem, 'status' | 'closes_at'>, now: number = Date.now()): Availability {
  if (item.status === 'open') return 'open'
  const closes = time(item.closes_at)
  return !Number.isNaN(closes) && closes >= now ? 'upcoming' : 'closed'
}

const GROUP_ORDER: Readonly<Record<Availability, number>> = { open: 0, upcoming: 1, closed: 2 }

function deadlineGroup(item: TestListItem, now: number): number {
  return GROUP_ORDER[availabilityOf(item, now)]
}

export function sortTests<T extends TestListItem>(items: readonly T[], sort: SortKey, options: SortOptions = {}): T[] {
  const now = options.now ?? Date.now()
  const byName = (a: T, b: T) => collator.compare(a.name, b.name) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  const compare = (a: T, b: T): number => {
    switch (sort) {
      case 'name-asc': return byName(a, b)
      case 'name-desc': return -byName(a, b)
      case 'created-desc': return compareTime(time(a.created_at), time(b.created_at), -1)
      case 'created-asc': return compareTime(time(a.created_at), time(b.created_at), 1)
      case 'deadline-desc': return compareTime(time(a.closes_at), time(b.closes_at), -1)
      case 'deadline-asc':
      default: {
        const group = deadlineGroup(a, now) - deadlineGroup(b, now)
        if (group) return group
        // Завершені — від найнещодавнішого дедлайну, інші — від найближчого.
        return compareTime(time(a.closes_at), time(b.closes_at), deadlineGroup(a, now) === 2 ? -1 : 1)
      }
    }
  }
  return [...items].sort((a, b) => compare(a, b) || byName(a, b))
}

export interface Page<T> {
  items: T[]
  /** Поточна сторінка після обмеження діапазоном 1…pageCount. */
  page: number
  pageCount: number
  pageSize: number
  total: number
  /** Номер першого показаного запису (з 1); 0, якщо список порожній. */
  start: number
  /** Номер останнього показаного запису; 0, якщо список порожній. */
  end: number
}

export function paginate<T>(items: readonly T[], page: number, pageSize: number): Page<T> {
  const size = Number.isFinite(pageSize) && pageSize >= 1 ? Math.floor(pageSize) : DEFAULT_PAGE_SIZE
  const total = items.length
  const pageCount = Math.max(1, Math.ceil(total / size))
  const requested = Number.isFinite(page) ? Math.floor(page) : 1
  const current = Math.min(Math.max(1, requested), pageCount)
  const offset = (current - 1) * size
  const pageItems = items.slice(offset, offset + size)
  return {
    items: pageItems,
    page: current,
    pageCount,
    pageSize: size,
    total,
    start: total ? offset + 1 : 0,
    end: total ? offset + pageItems.length : 0,
  }
}

export type PageToken = number | 'ellipsis-start' | 'ellipsis-end'

/** Номери сторінок для навігації: перша, остання, поточна ±1, а між ними «…». Не більше 7 позицій. */
export function pageTokens(current: number, pageCount: number): PageToken[] {
  if (pageCount <= 7) return Array.from({ length: Math.max(pageCount, 1) }, (_, index) => index + 1)
  const page = Math.min(Math.max(1, current), pageCount)
  if (page <= 4) return [1, 2, 3, 4, 5, 'ellipsis-end', pageCount]
  if (page >= pageCount - 3) return [1, 'ellipsis-start', pageCount - 4, pageCount - 3, pageCount - 2, pageCount - 1, pageCount]
  return [1, 'ellipsis-start', page - 1, page, page + 1, 'ellipsis-end', pageCount]
}

/** «Показано 1–6 з 17». */
export function shownLabel(page: Pick<Page<unknown>, 'start' | 'end' | 'total'>): string {
  if (!page.total) return 'Показано 0 з 0'
  return `Показано ${page.start}–${page.end} з ${page.total}`
}

export interface StoredListState {
  filters: TestListFilters
  sort: SortKey
  pageSize: number
  page: number
}

const STATUS_VALUES = new Set<string>(STATUS_OPTIONS.map((option) => option.value))
const SORT_VALUES = new Set<string>(SORT_OPTIONS.map((option) => option.value))

/** Перевіряє збережений у sessionStorage стан; невідомі або пошкоджені поля замінюються типовими. */
export function parseStoredState(raw: string | null | undefined): StoredListState | null {
  if (!raw) return null
  let data: unknown
  try { data = JSON.parse(raw) } catch { return null }
  if (!data || typeof data !== 'object') return null
  const source = data as Record<string, unknown>
  const rawFilters = (source.filters && typeof source.filters === 'object' ? source.filters : {}) as Record<string, unknown>
  const text = (value: unknown, max = 200) => (typeof value === 'string' ? value.slice(0, max) : '')
  const date = (value: unknown) => (typeof value === 'string' && DATE_KEY.test(value) ? value : '')
  const status = typeof rawFilters.status === 'string' && STATUS_VALUES.has(rawFilters.status) ? rawFilters.status as StatusFilter : 'all'
  const pageSize = (PAGE_SIZES as readonly number[]).includes(source.pageSize as number) ? source.pageSize as number : DEFAULT_PAGE_SIZE
  const page = typeof source.page === 'number' && Number.isInteger(source.page) && source.page >= 1 ? source.page : 1
  return {
    filters: {
      query: text(rawFilters.query),
      status,
      createdFrom: date(rawFilters.createdFrom),
      createdTo: date(rawFilters.createdTo),
      deadlineFrom: date(rawFilters.deadlineFrom),
      deadlineTo: date(rawFilters.deadlineTo),
    },
    sort: typeof source.sort === 'string' && SORT_VALUES.has(source.sort) ? source.sort as SortKey : DEFAULT_SORT,
    pageSize,
    page,
  }
}
