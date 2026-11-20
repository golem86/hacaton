import { createElement, type CSSProperties } from 'react'

/**
 * Демонстраційне правило команди: зони сильних і слабких місць та рівні зрілості 1–5.
 *
 * Це НЕ офіційна шкала. Методика індексу team-results-demo-0.1 має статус «запропонована»,
 * а погодженого відображення балів на рівні зрілості з Додатків Б/В немає.
 * Правило детерміноване (без AI), застосовується однаково до Integrity Index, балів
 * компонентів і балів категорій, а його пороги показано в UI (легенда, розгорнутий опис).
 * Обґрунтування порогів: docs/maturity-levels.md.
 *
 * Межі: нижня межа включна, верхня — ні (29,9 → критична; 30 → проблемна).
 * null, нечислові значення та значення поза шкалою 0–100 — «немає даних», ніколи не 0.
 */
export const MATURITY_RULE_ID = 'TEAM_ZONES_LEVELS_DEMO_V1'

export type ScoreZone = 'critical' | 'problem' | 'stable' | 'strength'
export type ZoneOrNone = ScoreZone | 'none'

/** Problem zone ends at 50, the same threshold as the backend rule LOW_SCORE_LT_50_V1. */
export const ZONE_THRESHOLDS = { critical: 30, problem: 50, strength: 75 } as const

export interface ZoneMeta {
  label: string
  short: string
  range: string
  /** Fill for bars, chart points and swatches; at least 3:1 against white. */
  color: string
  /** Light background for badges and table cells. */
  soft: string
  /** Text colour on `soft`; at least 4.5:1. */
  ink: string
}

export const ZONE_META: Record<ZoneOrNone, ZoneMeta> = {
  critical: { label: 'Критична зона', short: 'Критична', range: '< 30', color: '#a3261f', soft: '#fbe9e7', ink: '#7f1d17' },
  problem: { label: 'Проблемна зона', short: 'Проблемна', range: '30 – <50', color: '#c06a00', soft: '#fdf0dc', ink: '#7a4300' },
  stable: { label: 'Стабільна зона', short: 'Стабільна', range: '50 – <75', color: '#4b7f8c', soft: '#e8f1f3', ink: '#2c5560' },
  strength: { label: 'Сильна сторона', short: 'Сильна', range: '≥ 75', color: '#2f7a4d', soft: '#e3f2e8', ink: '#1d5434' },
  none: { label: 'Немає даних', short: 'Немає даних', range: 'приховано або відсутнє', color: '#8a9a96', soft: '#f1f4f3', ink: '#4f625e' },
}

/** Order used by legends: from the weakest zone to the strongest. */
export const ZONE_ORDER: ScoreZone[] = ['critical', 'problem', 'stable', 'strength']

export interface MaturityLevel {
  level: 1 | 2 | 3 | 4 | 5
  label: string
  min: number
  /** Exclusive, except level 5, which includes 100. */
  max: number
  range: string
}

export const MATURITY_LEVELS: readonly MaturityLevel[] = [
  { level: 1, label: 'Початковий', min: 0, max: 20, range: '0 – <20' },
  { level: 2, label: 'Базовий', min: 20, max: 40, range: '20 – <40' },
  { level: 3, label: 'Середній', min: 40, max: 60, range: '40 – <60' },
  { level: 4, label: 'Розвинений', min: 60, max: 80, range: '60 – <80' },
  { level: 5, label: 'Зразковий', min: 80, max: 100, range: '80 – 100' },
]

/** A usable score is a finite number on the 0–100 scale. Anything else is "no data". */
export function isScore(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100
}

export function scoreZone(score: number | null | undefined): ZoneOrNone {
  if (!isScore(score)) return 'none'
  if (score < ZONE_THRESHOLDS.critical) return 'critical'
  if (score < ZONE_THRESHOLDS.problem) return 'problem'
  if (score >= ZONE_THRESHOLDS.strength) return 'strength'
  return 'stable'
}

export function maturityLevel(score: number | null | undefined): MaturityLevel | null {
  if (!isScore(score)) return null
  const value = score
  return MATURITY_LEVELS.find(item => value < item.max) ?? MATURITY_LEVELS[MATURITY_LEVELS.length - 1]
}

export function zoneColor(score: number | null | undefined): string {
  return ZONE_META[scoreZone(score)].color
}

/** "Рівень 3 · Середній" or "Немає даних". */
export function levelText(score: number | null | undefined): string {
  const level = maturityLevel(score)
  return level ? `Рівень ${level.level} · ${level.label}` : 'Немає даних'
}

/** One sentence for screen readers and tooltips: zone and level together. */
export function describeScore(score: number | null | undefined): string {
  const level = maturityLevel(score)
  if (!level) return 'Немає даних'
  return `${ZONE_META[scoreZone(score)].label}, рівень зрілості ${level.level} з 5 «${level.label}»`
}

/** CSS custom properties consumed by .zone-badge, .zone-swatch and coloured fills. */
export function zoneStyle(zone: ZoneOrNone): CSSProperties {
  const meta = ZONE_META[zone]
  return { '--zone': meta.color, '--zone-soft': meta.soft, '--zone-ink': meta.ink } as CSSProperties
}

/** Text label next to the colour, so the zone never depends on colour alone. */
export function ZoneBadge({ zone, short = false }: { zone: ZoneOrNone; short?: boolean }) {
  const meta = ZONE_META[zone]
  return createElement('span', { className: `zone-badge zone-badge-${zone}`, style: zoneStyle(zone) }, short ? meta.short : meta.label)
}

/** The visible rule: legend text is generated from the same thresholds that colour the data. */
export function ZoneLegend({ note }: { note?: string }) {
  return createElement('div', { className: 'zone-legend', role: 'note', 'aria-label': 'Легенда кольорів зон' },
    createElement('span', { className: 'zone-legend-title' }, 'Зони (демонстраційне правило команди, не офіційна шкала):'),
    ...ZONE_ORDER.map(zone => createElement('span', { key: zone, className: 'zone-legend-item', style: zoneStyle(zone) },
      createElement('span', { className: 'zone-swatch', 'aria-hidden': true }),
      `${ZONE_META[zone].short} ${ZONE_META[zone].range}`)),
    createElement('span', { className: 'zone-legend-item', style: zoneStyle('none') },
      createElement('span', { className: 'zone-swatch zone-swatch-empty', 'aria-hidden': true }), 'Немає даних: приховано або відсутнє'),
    note ? createElement('span', { className: 'zone-legend-note' }, note) : null,
  )
}

/** Signed difference in percentage points, rounded to 0.01: "+3,25 п.п.", "−1,2 п.п.", "0 п.п.". */
export function formatDeltaPoints(delta: number): string {
  const rounded = Math.round(delta * 100) / 100
  if (rounded === 0) return '0 п.п.'
  const text = Math.abs(rounded).toLocaleString('uk-UA', { maximumFractionDigits: 2 })
  return `${rounded > 0 ? '+' : '−'}${text} п.п.`
}
