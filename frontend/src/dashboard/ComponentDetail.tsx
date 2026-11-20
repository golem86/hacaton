import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { IndexComponent, Recommendation } from '../api/analytics'
import type { ResultCategory, ResultComponent } from './types'
import { barWidth, categoryName, scoreText } from './format'
import { formatDeltaPoints, isScore, maturityLevel, scoreZone, ZONE_META, ZoneBadge } from './maturity'
import './dashboard.css'

export interface ComponentDetailProps {
  component: ResultComponent
  /** Category-level suppression flags; a hidden category hides its cells even if a score is sent. */
  categories?: ResultCategory[]
  /** Row of the Integrity Index response. Undefined when the index is not loaded in this view. */
  indexComponent?: IndexComponent
  /** All proposals of the cycle (filtered here by component code); null when unavailable. */
  recommendations?: Recommendation[] | null
  /** Why the index or recommendations are missing (disabled module, loading, error). */
  analyticsNote?: string
  /** Same component in the previous closed cycle, when known. */
  previous?: { name: string; score: number | null } | null
  onClose: () => void
  id?: string
}

function weightText(weight: number): string {
  const percent = Math.round(weight * 1000) / 10
  return `${weight.toLocaleString('uk-UA', { maximumFractionDigits: 3 })} (${percent.toLocaleString('uk-UA')} % індексу)`
}

function contributionText(row: IndexComponent | undefined): string {
  if (!row) return 'Недоступно в цьому поданні'
  if (row.status === 'suppressed') return 'Недоступно: дані приховано для захисту групи'
  if (row.status !== 'ok' || row.contribution === null) return 'Недоступно: немає даних'
  return `${row.contribution.toLocaleString('uk-UA', { maximumFractionDigits: 2 })} бала індексу`
}

export function ComponentDetail({
  component, categories, indexComponent, recommendations, analyticsNote, previous, onClose, id = 'component-detail',
}: ComponentDetailProps) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => { headingRef.current?.focus() }, [component.code])

  const zone = scoreZone(component.score)
  const level = maturityLevel(component.score)
  const hiddenCategories = new Set((categories ?? []).filter(item => item.hidden).map(item => item.category))
  const own = recommendations ? recommendations.filter(item => item.component_code === component.code) : null
  const weight = indexComponent?.weight ?? component.weight
  const delta = previous && isScore(previous.score) && isScore(component.score) ? component.score - previous.score : null

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Escape') return
    event.stopPropagation()
    onClose()
  }

  return (
    <section id={id} className="component-detail" aria-labelledby={`${id}-heading`} onKeyDown={onKeyDown}>
      <div className="component-detail-heading">
        <div>
          <p className="dashboard-kicker">Деталізація компонента</p>
          <h3 id={`${id}-heading`} ref={headingRef} tabIndex={-1}>
            <span className="dashboard-code">{component.code}</span> {component.name}
          </h3>
        </div>
        <button type="button" className="dashboard-action-button" onClick={onClose} aria-label={`Закрити деталізацію ${component.code}`}>Закрити</button>
      </div>

      <dl className="component-detail-facts">
        <div><dt>Бал</dt><dd>{scoreText(component.score)}</dd></div>
        <div><dt>Зона</dt><dd><ZoneBadge zone={zone} /></dd></div>
        <div><dt>Рівень зрілості</dt><dd>{level ? `${level.level} з 5 · ${level.label} (${level.range})` : 'Немає даних'}</dd></div>
        <div><dt>Вага в індексі</dt><dd>{weightText(weight)}</dd></div>
        <div><dt>Внесок в індекс</dt><dd>{contributionText(indexComponent)}</dd></div>
        {previous && <div>
          <dt>Зміна до «{previous.name}»</dt>
          <dd>{delta === null ? 'Немає даних для порівняння' : formatDeltaPoints(delta)}</dd>
        </div>}
      </dl>
      {analyticsNote && <p className="component-detail-note">{analyticsNote}</p>}

      <div className="component-detail-grid">
        <section aria-labelledby={`${id}-categories`}>
          <h4 id={`${id}-categories`}>Бал за категоріями</h4>
          {component.by_category.length === 0 ? <p className="component-detail-empty">Категорій у результатах немає.</p> : (
            <ul className="component-detail-list">
              {component.by_category.map(cell => {
                const hidden = cell.hidden || hiddenCategories.has(cell.category)
                const cellZone = hidden ? 'none' : scoreZone(cell.score)
                return (
                  <li key={cell.category} className={hidden ? 'dashboard-hidden' : undefined}>
                    <span>{categoryName(cell.category)}</span>
                    {hidden ? <span>Приховано</span> : cell.score === null ? <span>Немає даних</span> : (
                      <span className="component-detail-score">
                        <span className="dashboard-mini-track" aria-hidden="true"><span style={{ width: barWidth(cell.score), background: ZONE_META[cellZone].color }} /></span>
                        <span>{scoreText(cell.score)}</span>
                        <ZoneBadge zone={cellZone} short />
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          {component.by_category.some(cell => cell.hidden || hiddenCategories.has(cell.category))
            && <p className="dashboard-privacy-note">Бали малих груп приховано для захисту анонімності.</p>}
        </section>

        <section aria-labelledby={`${id}-indicators`}>
          <h4 id={`${id}-indicators`}>Об’єктивні показники</h4>
          {component.objective_indicators.length === 0 ? <p className="component-detail-empty">Об’єктивних показників для компонента немає.</p> : (
            <ul className="component-detail-list">
              {component.objective_indicators.map((indicator, index) => (
                <li key={`${indicator.name}-${index}`}>
                  <span>{indicator.name}</span>
                  <span className="component-detail-score">
                    <strong>{indicator.value.toLocaleString('uk-UA', { maximumFractionDigits: 1 })}{/%\s*$/.test(indicator.name) ? '%' : ''}</strong>
                    <span className={indicator.confirmed ? 'dashboard-badge dashboard-badge-confirmed' : 'dashboard-badge dashboard-badge-pending'}>
                      {indicator.confirmed ? 'Підтверджено' : 'Не підтверджено'}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section aria-labelledby={`${id}-recommendations`}>
        <h4 id={`${id}-recommendations`}>Рекомендації за правилами</h4>
        {own === null ? <p className="component-detail-empty">Рекомендації недоступні{recommendations === undefined ? ' в цьому поданні' : ''}.</p>
          : own.length === 0 ? <p className="component-detail-empty">За поточними правилами рекомендацій для компонента немає.</p> : (
            <ul className="component-detail-recommendations">
              {own.map(item => (
                <li key={item.id}>
                  <code>{item.rule_id}</code>
                  <span>{item.text}</span>
                  {item.requires_human_decision && <small>Пропозиція; потребує рішення людини.</small>}
                </li>
              ))}
            </ul>
          )}
      </section>

      <p className="component-detail-limit">Деталізація до окремих питань потребує розширення API: зараз API повертає лише агреговані бали компонента, без даних окремих питань.</p>
    </section>
  )
}

/**
 * Open/close state for a drill-down card. Closing with the card's button or Escape returns
 * focus to the control that opened it; opening moves focus to the card heading.
 */
export function useComponentDetail() {
  const [selected, setSelected] = useState<string | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  const restoreFocus = useRef(false)

  useEffect(() => {
    if (selected !== null || !restoreFocus.current) return
    restoreFocus.current = false
    opener.current?.focus()
    opener.current = null
  }, [selected])

  const open = useCallback((code: string, trigger: HTMLElement | null) => {
    opener.current = trigger
    setSelected(current => current === code ? null : code)
  }, [])
  const close = useCallback(() => {
    restoreFocus.current = true
    setSelected(null)
  }, [])

  return { selected, open, close }
}
