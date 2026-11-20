import type { CSSProperties, ReactNode, SVGProps } from 'react'
import type { AdminSection, OfficerSection, UserSection } from './navigation'

/**
 * Власні вбудовані SVG-іконки оболонки V2 (без npm-залежностей).
 * Єдиний стиль: viewBox 24×24, лише контур `currentColor`, товщина 1,85 px, заокруглені кінці.
 * Іконки декоративні (aria-hidden): доступну назву дає кнопка (aria-label і title).
 */
export type IconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & { size?: number | string }
export type IconComponent = (props: IconProps) => ReactNode

function icon(paths: ReactNode): IconComponent {
  return function Icon({ size = 20, ...rest }: IconProps) {
    return (
      <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.85}
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
        {paths}
      </svg>
    )
  }
}

const CLIPBOARD = <>
  <rect x="8" y="2.5" width="8" height="4" rx="1" />
  <path d="M16 4.5h1.5a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2H8" />
</>

/** Огляд: плитки панелі. */
export const DashboardIcon = icon(<>
  <rect x="3.5" y="3.5" width="7" height="9" rx="1.5" />
  <rect x="13.5" y="3.5" width="7" height="5" rx="1.5" />
  <rect x="13.5" y="11.5" width="7" height="9" rx="1.5" />
  <rect x="3.5" y="15.5" width="7" height="5" rx="1.5" />
</>)

/** Аналітика: стовпчикова діаграма. */
export const BarChartIcon = icon(<>
  <path d="M3.5 20.5h17" />
  <rect x="5" y="12" width="3.5" height="5.5" rx="1" />
  <rect x="10.25" y="5" width="3.5" height="12.5" rx="1" />
  <rect x="15.5" y="9" width="3.5" height="8.5" rx="1" />
</>)

/** Трекер рекомендацій: список із позначками. */
export const ListCheckIcon = icon(<>
  <path d="m3.5 6.5 1.75 1.75L8.75 4.75" />
  <path d="m3.5 12.5 1.75 1.75 3.5-3.5" />
  <path d="M4 18.5h4" />
  <path d="M12.5 6.5h8M12.5 12.5h8M12.5 18.5h8" />
</>)

/** Цикли оцінювання: календар із круговою стрілкою. */
export const CalendarCycleIcon = icon(<>
  <rect x="3.5" y="5" width="17" height="15.5" rx="2" />
  <path d="M8 3v4M16 3v4M3.5 9.5h17" />
  <path d="M15.2 15a3.2 3.2 0 1 1-.94-2.26" />
  <path d="M14.6 11.6v1.6H13" />
</>)

/** Користувачі й ролі. */
export const UsersIcon = icon(<>
  <circle cx="9" cy="8" r="3.5" />
  <path d="M2.5 20v-.5a5 5 0 0 1 5-5h3a5 5 0 0 1 5 5v.5" />
  <path d="M16 4.6a3.5 3.5 0 0 1 0 6.8" />
  <path d="M18.5 14.6a5 5 0 0 1 3 4.6v.8" />
</>)

/** Експертне оцінювання: анкета з позначкою. */
export const ClipboardCheckIcon = icon(<>
  {CLIPBOARD}
  <path d="m9 14 2 2 4-4" />
</>)

/** Офіційна анкета: аркуш анкети з пунктами. */
export const ClipboardListIcon = icon(<>
  {CLIPBOARD}
  <path d="M12 11h4M12 16h4M8.5 11h.01M8.5 16h.01" />
</>)

/** Журнал дій: історія (годинник із зворотною стрілкою). */
export const HistoryIcon = icon(<>
  <path d="M3.5 12a8.5 8.5 0 1 0 2.5-6L3.5 8.5" />
  <path d="M3.5 4v4.5H8" />
  <path d="M12 7.5V12l3 2" />
</>)

/** Звіти: завантаження файлу. */
export const FileDownloadIcon = icon(<>
  <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
  <path d="M14 3v5h5" />
  <path d="M12 11.5v6M9.5 15l2.5 2.5 2.5-2.5" />
</>)

/** Відкриті цикли й коди: ключ доступу. */
export const KeyIcon = icon(<>
  <circle cx="8" cy="15.5" r="4.5" />
  <path d="m11.2 12.3 8.8-8.8" />
  <path d="m17.2 6.3 2.5 2.5M14.6 8.9l2 2" />
</>)

/** Участь: кругова діаграма. */
export const PieChartIcon = icon(<>
  <path d="M11.5 4.5a8 8 0 1 0 8 8h-8z" />
  <path d="M14 2.5a7.5 7.5 0 0 1 7.5 7.5H14z" />
</>)

/** Мій кабінет: користувач. */
export const UserIcon = icon(<>
  <circle cx="12" cy="8" r="4" />
  <path d="M4.5 20.5v-.5a6 6 0 0 1 6-6h3a6 6 0 0 1 6 6v.5" />
</>)

/** Мої тестування: список із кнопкою запуску. */
export const ListPlayIcon = icon(<>
  <path d="M3.5 6h12M3.5 12h12M3.5 18h7" />
  <path d="m15 14.5 5.5 3.5-5.5 3.5z" />
</>)

/** Поточне тестування: годинник. */
export const ClockIcon = icon(<>
  <circle cx="12" cy="12" r="8.5" />
  <path d="M12 7.5V12l3 2" />
</>)

/** Мої результати: нагорода. */
export const AwardIcon = icon(<>
  <circle cx="12" cy="9" r="5.5" />
  <path d="M8.6 13.4 7.5 21l4.5-2.5 4.5 2.5-1.1-7.6" />
</>)

/** Персональна статистика: зростання. */
export const TrendingUpIcon = icon(<>
  <path d="m3 17 6-6 4 4 8-8" />
  <path d="M15 7h6v6" />
</>)

/** Результати підрозділу: будівля. */
export const BuildingIcon = icon(<>
  <rect x="5" y="3" width="14" height="18" rx="1.5" />
  <path d="M9 7h.01M12 7h.01M15 7h.01M9 11h.01M12 11h.01M15 11h.01M9 15h.01M15 15h.01" />
  <path d="M10.5 21v-3.5h3V21" />
</>)

/** Анонімне опитування: відкриття окремої сторінки. */
export const ExternalLinkIcon = icon(<>
  <path d="M14 4h6v6" />
  <path d="M20 4 11 13" />
  <path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />
</>)

/** Вийти: двері зі стрілкою. */
export const LogOutIcon = icon(<>
  <path d="M9.5 20.5H6a2 2 0 0 1-2-2v-13a2 2 0 0 1 2-2h3.5" />
  <path d="m15.5 16.5 4.5-4.5-4.5-4.5" />
  <path d="M20 12H9.5" />
</>)

/** Вийти на всіх пристроях: ноутбук і телефон. */
export const DevicesIcon = icon(<>
  <rect x="2.5" y="5" width="11" height="8.5" rx="1.5" />
  <path d="M1.5 16.5h13" />
  <rect x="16.5" y="8" width="5.5" height="12.5" rx="1.2" />
  <path d="M19.25 17.5h.01" />
</>)

/** Ключ пункту меню посилання на анонімне опитування (admin і data_officer). */
export const SURVEY_NAV_KEY = 'survey'
export type NavIconKey = AdminSection | OfficerSection | UserSection | typeof SURVEY_NAV_KEY

/** Іконка для кожного ключа навігації всіх ролей (admin, data_officer, user) і посилання на опитування. */
export const NAV_ICONS = {
  overview: DashboardIcon,
  analytics: BarChartIcon,
  tracker: ListCheckIcon,
  testing: CalendarCycleIcon,
  users: UsersIcon,
  expert: ClipboardCheckIcon,
  audit: HistoryIcon,
  reports: FileDownloadIcon,
  codes: KeyIcon,
  participation: PieChartIcon,
  profile: UserIcon,
  available: ListPlayIcon,
  official: ClipboardListIcon,
  attempt: ClockIcon,
  history: AwardIcon,
  stats: TrendingUpIcon,
  'unit-results': BuildingIcon,
  survey: ExternalLinkIcon,
} satisfies Partial<Record<NavIconKey, IconComponent>>

export function hasNavIcon(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(NAV_ICONS, key)
}

/** Іконка пункту навігації; для невідомого ключа — нейтральна плитка, щоб кнопка не лишилась порожньою. */
export function NavIcon({ name, ...rest }: IconProps & { name: string }) {
  const Icon: IconComponent = hasNavIcon(name) ? NAV_ICONS[name as keyof typeof NAV_ICONS] : DashboardIcon
  return <Icon className="v2-nav-icon" data-icon={name} {...rest} />
}

/**
 * Кнопка бічного меню: іконка й підпис (desktop) або лише іконка (≤ 900 px, підпис приховує CSS).
 * Доступна назва й підказка — завжди український заголовок розділу (aria-label і title).
 */
export function NavButton({ navKey, title, active = false, onClick }: { navKey: string; title: string; active?: boolean; onClick: () => void }) {
  return (
    <button type="button" className={active ? 'is-active' : undefined} aria-current={active ? 'page' : undefined}
      aria-label={title} title={title} onClick={onClick}>
      <NavIcon name={navKey} /><span className="v2-nav-text">{title}</span>
    </button>
  )
}

const TAP = 44 // мінімальна ціль дотику, px
const GAP = 4 // проміжок між кнопками (.25rem), px
const GUTTER = 24 // внутрішні відступи бічної панелі (2 × .75rem), px

/** Колонок мобільного меню: один ряд, якщо кнопки ≥ 44 px вміщаються в ширину, інакше два рівні ряди. */
export function navGridColumns(count: number, viewport: number): number {
  const items = Math.max(1, count)
  return items * TAP + (items - 1) * GAP + GUTTER <= viewport ? items : Math.ceil(items / 2)
}

/** CSS-змінні сітки мобільної навігації: планшет (≤ 900 px), телефон (≥ 360 px) і вузький телефон (320 px). */
export function navGridStyle(count: number): CSSProperties {
  return {
    '--v2-nav-count': Math.max(1, count),
    '--v2-nav-cols-sm': navGridColumns(count, 360),
    '--v2-nav-cols-xs': navGridColumns(count, 320),
  } as CSSProperties
}
