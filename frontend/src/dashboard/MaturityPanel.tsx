import { Fragment, useEffect, useId, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import { ApiError } from '../api/client'
import type { Assessment } from '../api/assessments'
import {
  MATURITY_MESSAGES, getMaturity,
  type GapSource, type MaturityCriterion, type MaturityGap, type MaturityRecommendation, type MaturityReport, type SourceStatus,
} from '../api/maturity'
import { categoryLabel } from '../components/categories'
import { MaturityReportButtons } from './MaturityReportButtons'
import './dashboard.css'
import './maturity-panel.css'

/**
 * Панель «Зрілість за Додатком В».
 *
 * API для підключення: `<MaturityPanel assessments={…} selectedId={…} />`.
 * - `assessments` — цикли, які вже завантажив батьківський розділ (GET /api/assessments);
 * - `selectedId` — початково вибраний цикл (або null).
 * Панель має власний вибір циклу серед переданих `assessments` і сама завантажує
 * GET /api/assessments/{id}/maturity лише для закритого циклу.
 */
export interface MaturityPanelProps {
  assessments: Assessment[]
  selectedId: number | null
  /** Показати кнопки звіту зрілості PDF/XLSX (лише розділ адміністратора; сервер усе одно перевіряє роль). */
  exportable?: boolean
}

/** Обидва правила розбіжностей контракту мають поріг 1,0 рівня. */
export const GAP_THRESHOLD = 1

export const SOURCE_LABELS: Record<'self' | GapSource, string> = {
  self: 'Самооцінювання',
  expert: 'Експерт',
  checklist: 'Чеклист Додатка Б',
}
const SOURCE_IN_SENTENCE: Record<GapSource, string> = { expert: 'експерт', checklist: 'чеклист' }
const SOURCE_COLORS: Record<'self' | GapSource, string> = { self: '#28777a', expert: '#6b4a9b', checklist: '#b35c00' }

export type LevelBand = 'low' | 'medium' | 'high' | 'none'

/**
 * Колір рівня: 1–2 низький, 3 середній, 4–5 високий. Дробові середні округлюються
 * до найближчого цілого рівня: < 2,5 низький, 2,5 – < 3,5 середній, ≥ 3,5 високий.
 */
export function levelBand(level: number | null | undefined): LevelBand {
  if (typeof level !== 'number' || !Number.isFinite(level)) return 'none'
  if (level < 2.5) return 'low'
  if (level < 3.5) return 'medium'
  return 'high'
}

export const BAND_META: Record<LevelBand, { label: string; range: string }> = {
  low: { label: 'Низький', range: '1–2 (до 2,4)' },
  medium: { label: 'Середній', range: '3 (2,5–3,4)' },
  high: { label: 'Високий', range: '4–5 (від 3,5)' },
  none: { label: 'Немає рівня', range: 'приховано або відсутнє' },
}

const decimal = (value: number, digits = 1) =>
  value.toLocaleString('uk-UA', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export function formatLevel(level: number | null): string {
  return level === null ? '—' : decimal(level)
}

export function formatIndex(value: number | null): string {
  return value === null ? 'Немає даних' : decimal(value)
}

function plainNumber(value: number): string {
  return value.toLocaleString('uk-UA', { maximumFractionDigits: 2 })
}

export function statusText(status: SourceStatus): string {
  if (status === 'suppressed') return 'Приховано'
  return 'Немає даних'
}

function LevelValue({ level, status, detail }: { level: number | null; status: SourceStatus; detail?: string }) {
  if (level === null) {
    const hint = status === 'suppressed' ? 'Приховано правилом мінімального розміру групи' : 'Немає даних від цього джерела'
    return <span className={`mp-level mp-level-none${status === 'suppressed' ? ' mp-level-hidden' : ''}`} title={hint}>{statusText(status)}</span>
  }
  const band = levelBand(level)
  return (
    <span className="mp-level-wrap">
      <span className={`mp-level mp-level-${band}`}>
        <strong>{formatLevel(level)}</strong> <span className="mp-level-band">{BAND_META[band].label}</span>
      </span>
      {detail && <small className="mp-cell-detail">{detail}</small>}
    </span>
  )
}

function rightLevel(criterion: MaturityCriterion, right: GapSource): number | null {
  return right === 'expert' ? criterion.expert.level : criterion.checklist.level
}

/** «Самооцінка 4,2 vs експерт 2,8: розрив 1,4 ≥ 1,0, правило MAT_SELF_EXPERT_GAP_GE_1». */
export function gapSentence(criterion: MaturityCriterion, gap: MaturityGap): string {
  const diff = gap.diff === null ? '—' : decimal(gap.diff)
  const relation = gap.diff !== null && gap.diff >= GAP_THRESHOLD ? '≥' : '<'
  return `Самооцінка ${formatLevel(criterion.self.level)} vs ${SOURCE_IN_SENTENCE[gap.right]} ${formatLevel(rightLevel(criterion, gap.right))}: `
    + `розрив ${diff} ${relation} ${decimal(GAP_THRESHOLD)}, правило ${gap.rule_id}`
}

const BASIS_LABELS: Record<string, string> = {
  self: 'самооцінка', expert: 'експерт', checklist: 'чеклист', diff: 'розрив', threshold: 'поріг',
  level: 'рівень', source: 'джерело', value: 'значення', target: 'цільове значення', name: 'показник',
  confirmed: 'підтверджено', criterion: 'критерій', status: 'статус',
  self_min: 'поріг самооцінки', indicators_total: 'показників усього', indicators_confirmed: 'підтверджених показників',
  indicators: 'показники', expert_level: 'рівень експерта',
}

function basisValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return plainNumber(value)
  if (typeof value === 'boolean') return value ? 'так' : 'ні'
  if (typeof value === 'string') return value in SOURCE_LABELS ? SOURCE_LABELS[value as keyof typeof SOURCE_LABELS] : value
  if (Array.isArray(value)) return value.map(item => item && typeof item === 'object' && 'name' in item
    ? `${String((item as { name: unknown }).name)}: ${basisValue((item as { value?: unknown }).value)} (ціль ${basisValue((item as { target?: unknown }).target)})`
    : basisValue(item)).join('; ') || '—'
  return JSON.stringify(value)
}

/** Ділить критерії: 10 критеріїв індексу та окремий «загальний рівень зрілості». */
function indexCriteria(report: MaturityReport): MaturityCriterion[] {
  return report.criteria.filter(criterion => criterion.key !== 'maturity')
}

function MaturityChart({ criteria }: { criteria: MaturityCriterion[] }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || criteria.length === 0) return
    const sources = [
      { key: 'self' as const, data: criteria.map(item => item.self.level) },
      { key: 'expert' as const, data: criteria.map(item => item.expert.level) },
      { key: 'checklist' as const, data: criteria.map(item => item.checklist.level) },
    ]
    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: criteria.map(item => item.name_uk),
        datasets: sources.map(source => ({
          label: SOURCE_LABELS[source.key],
          // null лишається null: Chart.js не малює стовпця, тобто прогалина, а не 0.
          data: source.data,
          backgroundColor: SOURCE_COLORS[source.key],
          borderRadius: 3,
          maxBarThickness: 14,
          categoryPercentage: .78,
          barPercentage: .92,
        })),
      },
      options: {
        animation: false,
        indexAxis: 'y',
        maintainAspectRatio: false,
        responsive: true,
        scales: {
          x: { min: 0, max: 5, ticks: { stepSize: 1, color: '#526762' }, grid: { color: '#e4ece8' }, title: { display: true, text: 'Рівень 1–5', color: '#526762' } },
          y: {
            grid: { display: false },
            ticks: {
              color: '#17302f',
              font: { size: 12, weight: 600 },
              callback(value) {
                const label = this.getLabelForValue(Number(value))
                const limit = this.chart.width < 360 ? 13 : this.chart.width < 480 ? 16 : 40
                return label.length > limit ? `${label.slice(0, limit - 1)}…` : label
              },
            },
          },
        },
        plugins: {
          legend: { position: 'top', labels: { color: '#17302f', boxWidth: 14 } },
          tooltip: {
            callbacks: {
              label: context => context.raw === null
                ? ` ${context.dataset.label}: немає рівня`
                : ` ${context.dataset.label}: ${formatLevel(Number(context.raw))}`,
            },
          },
        },
      },
    })
    return () => chart.destroy()
  }, [criteria])

  const description = criteria.map(item =>
    `${item.name_uk}: самооцінювання ${item.self.level === null ? statusText(item.self.status) : formatLevel(item.self.level)}, `
    + `експерт ${item.expert.level === null ? statusText(item.expert.status) : formatLevel(item.expert.level)}, `
    + `чеклист ${item.checklist.level === null ? statusText(item.checklist.status) : formatLevel(item.checklist.level)}`)

  return (
    <div className="mp-chart" style={{ height: `${Math.max(320, criteria.length * 54 + 90)}px` }}>
      <canvas ref={canvasRef} role="img"
        aria-label="Згрупована діаграма рівнів 1–5 за критеріями Додатка В у трьох джерелах: самооцінювання, експерт, чеклист Додатка Б. Відсутній стовпець означає приховане або відсутнє значення, а не нуль. Повний текстовий опис наведено нижче й у таблиці.">
        {description.join('; ')}
      </canvas>
      <ul className="sr-only">{description.map(text => <li key={text}>{text}</li>)}</ul>
    </div>
  )
}

function LevelLegend() {
  return (
    <div className="mp-legend" role="note" aria-label="Легенда кольорів рівнів">
      <span className="mp-legend-title">Кольори рівнів:</span>
      {(['low', 'medium', 'high', 'none'] as const).map(band => (
        <span key={band} className="mp-legend-item">
          <span className={`mp-swatch mp-level-${band}`} aria-hidden="true" />
          {BAND_META[band].label} {BAND_META[band].range}
        </span>
      ))}
    </div>
  )
}

function ObjectiveCell({ criterion }: { criterion: MaturityCriterion }) {
  if (criterion.objective.length === 0) return <span className="mp-muted">Немає показників</span>
  return (
    <ul className="mp-objective">
      {criterion.objective.map(item => (
        <li key={item.name}>
          <span>{item.name}</span>{' '}
          <span className="mp-nowrap">
            {item.value === null ? '—' : plainNumber(item.value)} / ціль {item.target === null ? '—' : plainNumber(item.target)}
          </span>{' '}
          <span className={`mp-badge ${item.confirmed ? 'mp-badge-ok' : 'mp-badge-warn'}`}>{item.confirmed ? 'Підтверджено' : 'Не підтверджено'}</span>
        </li>
      ))}
    </ul>
  )
}

function GapCell({ criterion }: { criterion: MaturityCriterion }) {
  if (criterion.gaps.length === 0) return <span className="mp-muted">Немає порівняння</span>
  return (
    <ul className="mp-gaps-cell">
      {criterion.gaps.map(gap => (
        <li key={`${gap.rule_id}:${gap.right}`} className={gap.flag ? 'mp-gap-flag' : undefined}>
          <span className={`mp-badge ${gap.flag ? 'mp-badge-alert' : 'mp-badge-neutral'}`}>{gap.flag ? 'Розбіжність' : 'У межах'}</span>{' '}
          vs {SOURCE_IN_SENTENCE[gap.right]}: {gap.diff === null ? '—' : decimal(gap.diff)}
          <small className="mp-rule">{gap.rule_id}</small>
        </li>
      ))}
    </ul>
  )
}

function CriteriaTable({ criteria, minGroupSize }: { criteria: MaturityCriterion[]; minGroupSize: number }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const baseId = useId()
  return (
    <div className="mp-table-scroll" role="region" aria-label="Таблиця критеріїв Додатка В, прокручується горизонтально" tabIndex={0}>
      <table className="mp-table">
        <caption>Рівні критеріїв Додатка В за джерелами, об’єктивні показники та позначки розбіжностей</caption>
        <thead>
          <tr>
            <th scope="col">Критерій</th>
            <th scope="col">Компонент</th>
            <th scope="col">Самооцінювання<small>рівень (відповіді)</small></th>
            <th scope="col">Експерт<small>рівень (експертів)</small></th>
            <th scope="col">Чеклист Додатка Б<small>рівень (підтв./усього)</small></th>
            <th scope="col">Об’єктивні показники<small>значення / ціль</small></th>
            <th scope="col">Розбіжності<small>правило, різниця</small></th>
          </tr>
        </thead>
        <tbody>
          {criteria.map(criterion => {
            const open = expanded === criterion.key
            const detailId = `${baseId}-${criterion.key}`
            return (
              <Fragment key={criterion.key}>
                <tr className={criterion.gaps.some(gap => gap.flag) ? 'mp-row-flagged' : undefined}>
                  <th scope="row">
                    <button type="button" className="mp-expand" aria-expanded={open} aria-controls={detailId}
                      onClick={() => setExpanded(open ? null : criterion.key)}>
                      <span aria-hidden="true" className="mp-chevron">{open ? '▾' : '▸'}</span>
                      <span>{criterion.name_uk}</span>
                    </button>
                    {criterion.key === 'maturity' && <small className="mp-cell-detail">Загальний рівень; не входить до індексів</small>}
                  </th>
                  <td>{criterion.component_code ?? <span className="mp-muted" title="Для цього критерію немає відповідного компонента">—</span>}</td>
                  <td><LevelValue level={criterion.self.level} status={criterion.self.status}
                    detail={criterion.self.responses === null ? undefined : `${criterion.self.responses} відп.`} /></td>
                  <td><LevelValue level={criterion.expert.level} status={criterion.expert.status} detail={`${criterion.expert.experts} експ.`} /></td>
                  <td><LevelValue level={criterion.checklist.level} status={criterion.checklist.status}
                    detail={`${criterion.checklist.items_confirmed}/${criterion.checklist.items_total} підтв.`} /></td>
                  <td><ObjectiveCell criterion={criterion} /></td>
                  <td><GapCell criterion={criterion} /></td>
                </tr>
                <tr id={detailId} className="mp-detail-row" hidden={!open}>
                  <td colSpan={7}>
                    <p className="mp-detail-title">Самооцінювання за категоріями: {criterion.name_uk}</p>
                    {criterion.self_by_category.length === 0 ? <p className="mp-muted">Немає даних за категоріями.</p> : (
                      <ul className="mp-categories">
                        {criterion.self_by_category.map(item => (
                          <li key={item.category}>
                            <span>{categoryLabel(item.category)}</span>
                            {item.hidden
                              ? <span className="mp-level mp-level-none mp-level-hidden" title={`Менше ${minGroupSize} відповідей або вторинне приховування`}>Приховано</span>
                              : <LevelValue level={item.level} status={item.level === null ? 'missing' : 'ok'} />}
                          </li>
                        ))}
                      </ul>
                    )}
                    <p className="mp-muted mp-small">Категорії з менш ніж {minGroupSize} відповідями приховано; додатково може застосовуватися вторинне приховування.</p>
                  </td>
                </tr>
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Discrepancies({ criteria }: { criteria: MaturityCriterion[] }) {
  const flagged = criteria.flatMap(criterion => criterion.gaps.filter(gap => gap.flag).map(gap => ({ criterion, gap })))
  return (
    <section className="mp-block" aria-labelledby="mp-gaps-heading">
      <h3 id="mp-gaps-heading">Розбіжності джерел</h3>
      <p className="mp-muted">Розбіжність — це сигнал для перевірки, а не доказ проблеми чи порушення. Поріг: різниця самооцінки та іншого джерела ≥ {decimal(GAP_THRESHOLD)} рівня.</p>
      {flagged.length === 0 ? <p className="mp-empty">Розбіжностей, що перевищують поріг, не виявлено.</p> : (
        <ul className="mp-list">
          {flagged.map(({ criterion, gap }) => (
            <li key={`${criterion.key}:${gap.rule_id}:${gap.right}`}>
              <strong>{criterion.name_uk}.</strong> {gapSentence(criterion, gap)}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function Recommendations({ items, criteria }: { items: MaturityRecommendation[]; criteria: MaturityCriterion[] }) {
  const names = new Map(criteria.map(criterion => [criterion.key, criterion.name_uk]))
  return (
    <section className="mp-block" aria-labelledby="mp-recs-heading">
      <h3 id="mp-recs-heading">Рекомендації за Додатком В</h3>
      <p className="mp-muted">Пропозиції сформовано детермінованими правилами без AI. Рішення про дії ухвалює посадова особа.</p>
      {items.length === 0 ? <p className="mp-empty">Правила не сформували рекомендацій для цього циклу.</p> : (
        <ul className="mp-list mp-recs">
          {items.map(item => (
            <li key={item.id}>
              <p className="mp-rec-head">
                <span className="mp-badge mp-badge-decision">Потребує рішення посадової особи</span>
                <span className="mp-rule">{item.rule_id}</span>
              </p>
              <p><strong>{names.get(item.criterion) ?? item.criterion}:</strong> {item.text}</p>
              {Object.keys(item.basis).length > 0 && (
                <dl className="mp-basis" aria-label="Підстава рекомендації">
                  {Object.entries(item.basis).map(([key, value]) => (
                    <div key={key}><dt>{BASIS_LABELS[key] ?? key}</dt><dd>{basisValue(value)}</dd></div>
                  ))}
                </dl>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function MaturityContent({ report }: { report: MaturityReport }) {
  const criteria = report.criteria
  const indexed = indexCriteria(report)
  const overall = report.overall_self_declared
  const indexCards = [
    { key: 'self' as const, label: 'Індекс самооцінювання', value: report.indices.self },
    { key: 'expert' as const, label: 'Експертний індекс', value: report.indices.expert },
    { key: 'checklist' as const, label: 'Індекс чеклиста Додатка Б', value: report.indices.checklist },
  ]
  return (
    <div className="mp-content">
      <p className="mp-notice" role="note">
        Демонстрація на синтетичних даних. Методика {report.methodology_version} — пропозиція команди, не затверджена;
        результати не є офіційним оцінюванням.
      </p>
      <div className="mp-indices" role="group" aria-label="Індекси зрілості за трьома джерелами, шкала 0–100">
        {indexCards.map(card => (
          <div key={card.key} className="mp-index" data-source={card.key}>
            <span>{card.label}</span>
            <strong>{formatIndex(card.value)}{card.value !== null && <small> / 100</small>}</strong>
            {card.value === null && <small>Не обчислено: хоча б один критерій прихований або без даних.</small>}
          </div>
        ))}
        <div className="mp-index mp-index-overall">
          <span>Загальний рівень (самооцінка)</span>
          <strong>{overall.level === null ? statusText(overall.status) : <>{formatLevel(overall.level)}<small> / 5</small></>}</strong>
          <small>Окреме питання анкети; не входить до індексів.</small>
        </div>
      </div>
      <details className="mp-method" open>
        <summary>Методика: {report.methodology_version}</summary>
        <dl>
          <div><dt>Правило рівнів</dt><dd>варіант a = рівень 1, b = 2, c = 3, d = 4, e = рівень 5; у питанні про викривачів (6 варіантів) — a = 1, b = 2, c = 3, d = 4, e = 4, f = 5 (Додаток Г, с. 73). <span className="mp-muted">(сервер: {report.level_rule})</span></dd></div>
          <div><dt>Формула індексу</dt><dd>(середній рівень критеріїв − 1) / 4 × 100; рівні ваги (1/10) для 10 критеріїв без загального рівня зрілості. Якщо хоча б один критерій джерела прихований або відсутній, індекс джерела не обчислюється.</dd></div>
          <div><dt>Рівень чеклиста</dt><dd>1 + 4 × (так + 0,5 × частково) / підтверджені пункти; враховуються лише підтверджені пункти.</dd></div>
          <div><dt>Анонімність</dt><dd>Мінімальний розмір групи k = {report.min_group_size}.</dd></div>
        </dl>
      </details>
      {criteria.length === 0 ? <p className="mp-empty">Для цього циклу ще немає даних за Додатком В.</p> : (
        <>
          <section className="mp-block" aria-labelledby="mp-chart-heading">
            <h3 id="mp-chart-heading">Рівні критеріїв за джерелами</h3>
            {indexed.length > 0 && <MaturityChart criteria={indexed} />}
            <LevelLegend />
          </section>
          <section className="mp-block" aria-labelledby="mp-table-heading">
            <h3 id="mp-table-heading">Критерії Додатка В</h3>
            <p className="mp-muted mp-small">Розгорніть рядок, щоб побачити самооцінювання за категоріями.</p>
            <CriteriaTable criteria={criteria} minGroupSize={report.min_group_size} />
          </section>
          <Discrepancies criteria={criteria} />
          <Recommendations items={report.recommendations} criteria={criteria} />
        </>
      )}
    </div>
  )
}

export type MaturityState =
  | { status: 'loading' }
  | { status: 'blocked'; message: string }
  | { status: 'error'; code: number; message: string }
  | { status: 'success'; data: MaturityReport }

export function MaturityStatus({ state, retry }: { state: MaturityState; retry: () => void }) {
  if (state.status === 'loading') return <p role="status" className="mp-state">Завантажуємо аналітику зрілості…</p>
  if (state.status === 'blocked') return <p role="status" className="mp-state mp-state-info">{state.message}</p>
  if (state.status === 'error') {
    const retryable = ![403, 404, 409, 503].includes(state.code)
    return (
      <div role="alert" className={`mp-state ${state.code === 409 || state.code === 503 ? 'mp-state-info' : 'mp-state-error'}`}>
        <p>{state.message}</p>
        {retryable && <button type="button" className="mp-button" onClick={retry}>Спробувати ще раз</button>}
      </div>
    )
  }
  return <MaturityContent report={state.data} />
}

/** Стан для циклу, який ще не можна аналізувати, визначається без запиту. */
export function localBlock(assessment: Assessment | undefined): string | null {
  if (!assessment) return 'Оберіть цикл оцінювання.'
  if (assessment.status === 'closed') return null
  if (assessment.status === 'draft') return 'Цикл ще не розпочато. Зрілість за Додатком В розраховується лише після закриття циклу.'
  return MATURITY_MESSAGES[409]
}

export default function MaturityPanel({ assessments, selectedId, exportable = false }: MaturityPanelProps) {
  const [chosen, setChosen] = useState<number | null>(selectedId)
  const [retry, setRetry] = useState(0)
  const [stored, setStored] = useState<{ key: string; state: MaturityState }>({ key: '', state: { status: 'loading' } })
  const selectId = useId()

  useEffect(() => { setChosen(selectedId) }, [selectedId])

  const assessment = assessments.find(item => item.id === chosen)
  const block = localBlock(assessment)
  const key = `${chosen}:${retry}`

  useEffect(() => {
    if (block !== null || chosen === null) return
    const controller = new AbortController()
    setStored({ key, state: { status: 'loading' } })
    getMaturity(chosen, controller.signal)
      .then(data => { if (!controller.signal.aborted) setStored({ key, state: { status: 'success', data } }) })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setStored({ key, state: {
          status: 'error',
          code: error instanceof ApiError ? error.status : 0,
          message: error instanceof Error ? error.message : 'Не вдалося завантажити аналітику зрілості.',
        } })
      })
    return () => controller.abort()
  }, [key, block, chosen])

  const state: MaturityState = block !== null ? { status: 'blocked', message: block }
    : stored.key === key ? stored.state : { status: 'loading' }

  return (
    <section className="dashboard-panel mp-panel" aria-labelledby="mp-heading">
      <div className="mp-heading">
        <p className="dashboard-kicker">Аналітика · Додаток В</p>
        <h2 id="mp-heading">Зрілість за Додатком В</h2>
        <p className="mp-muted">Наскільки зріла система доброчесності за трьома джерелами — самооцінюванням, експертом і чеклистом Додатка Б — і де вони розходяться.</p>
      </div>
      {assessments.length === 0 ? <p className="mp-empty">Немає циклів оцінювання.</p> : (
        <>
          <label className="mp-select" htmlFor={selectId}>Цикл оцінювання</label>
          <select id={selectId} className="mp-select-input" value={chosen ?? ''}
            onChange={event => setChosen(event.target.value === '' ? null : Number(event.target.value))}>
            <option value="">Оберіть цикл</option>
            {assessments.map(item => (
              <option key={item.id} value={item.id}>{item.name}{item.status === 'closed' ? '' : ' (не закрито)'}</option>
            ))}
          </select>
          {exportable && state.status === 'success' && <MaturityReportButtons key={state.data.assessment.id} id={state.data.assessment.id} />}
          <MaturityStatus state={state} retry={() => setRetry(value => value + 1)} />
        </>
      )}
    </section>
  )
}
