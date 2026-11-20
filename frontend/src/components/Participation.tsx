import { useEffect, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import type { Assessment } from '../api/assessments'
import { getParticipation, type Participation, type ParticipationGroup } from '../api/admin'
import { SuppressionNote } from '../dashboard/suppression'
import { categoryLabel } from './categories'
import './AssessmentManager.css'
import './participation.css'

const usedColor = '#276456'
const unusedColor = '#b7cec4'
export const formatCount = (value: number) => value.toLocaleString('uk-UA')
export const formatPercent = (value: number) => `${value.toLocaleString('uk-UA', { maximumFractionDigits: 1 })}%`

/** Старий backend не надсилав `counts_exact`, і його значення були точними. */
export function isExact(participation: Pick<Participation, 'counts_exact'> | { counts_exact?: boolean }) {
  return participation.counts_exact !== false
}

/**
 * Кількість участі для показу. null — «приховано» (менше k), ніколи не 0.
 * Неточне значення відкритого циклу округлено сервером вниз до кратного 5, тому показується як «≥ N».
 */
export function formatParticipationCount(value: number | null | undefined, exact: boolean): string {
  if (value === null || value === undefined) return 'приховано'
  return exact ? formatCount(value) : `≥ ${formatCount(value)}`
}

export function formatParticipationPercent(value: number | null | undefined, exact: boolean): string {
  if (value === null || value === undefined) return 'приховано'
  return exact ? formatPercent(value) : `≈ ${formatPercent(value)}`
}

/** Пояснення до неточних значень відкритого циклу. */
export function approximateCountsNote(k: number) {
  return `Цикл відкритий: кількість анкет і невикористаних кодів округлено вниз до кратного 5 і показано лише від порогу групи (${k}). «≥ N» означає «щонайменше N». Точні значення з’являться після закриття циклу.`
}

/**
 * Кругова діаграма використаних і невикористаних кодів.
 * null від API означає «приховано через мінімальний розмір групи» — його не перетворюємо на 0.
 * Неточні (округлені) значення відкритого циклу діаграмою не показуються.
 */
export function ParticipationChart({ participation }: { participation: (Omit<Participation, 'counts_exact' | 'groups' | 'suppressed'> & { counts_exact?: boolean }) | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const exact = participation ? isExact(participation) : true
  const issued = participation?.tokens_issued ?? null
  const unused = participation?.tokens_unused ?? null
  const used = issued !== null && unused !== null ? Math.max(issued - unused, 0) : null
  const visible = exact && issued !== null && issued > 0 && unused !== null && used !== null

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !visible || !issued || used === null || unused === null) return
    const chart = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: ['Використані коди', 'Невикористані коди'],
        datasets: [{ data: [used, unused], backgroundColor: [usedColor, unusedColor], borderColor: '#ffffff', borderWidth: 2, hoverOffset: 4 }],
      },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: context => ` ${context.label}: ${formatCount(Number(context.raw))}` } },
        },
      },
    })
    return () => chart.destroy()
  }, [visible, issued, used, unused])

  if (!participation) return <p className="cycle-manager__chart-state" role="status">Завантажуємо дані участі…</p>
  if (participation.tokens_issued === 0) {
    return <div className="cycle-manager__chart-state"><strong>Коди ще не видано</strong><span>Діаграма з’явиться після видачі перших кодів доступу.</span></div>
  }
  if (!exact && unused !== null) {
    return <div className="cycle-manager__chart-state cycle-manager__chart-state--hidden"><strong>Приблизні дані відкритого циклу</strong><span>Точний розподіл кодів з’явиться на діаграмі після закриття циклу.</span></div>
  }
  if (!visible) {
    return <div className="cycle-manager__chart-state cycle-manager__chart-state--hidden"><strong>Розподіл кодів приховано</strong><span>Діаграма з’явиться, коли кількість анкет досягне порогу групи.</span></div>
  }
  return (
    <figure className="cycle-manager__chart">
      <div className="cycle-manager__chart-canvas">
        <canvas ref={canvasRef} role="img" aria-label={`Кругова діаграма участі: використано ${formatCount(used)} з ${formatCount(issued)} кодів, невикористаних ${formatCount(unused)}`} />
        {participation.participation_percent !== null && (
          <div className="cycle-manager__chart-center" aria-hidden="true"><strong>{formatPercent(participation.participation_percent)}</strong><span>участь</span></div>
        )}
      </div>
      <figcaption>
        <ul className="cycle-manager__legend">
          <li><i className="cycle-manager__swatch cycle-manager__swatch--used" aria-hidden="true" /><span>Використані коди</span><strong>{formatCount(used)}</strong></li>
          <li><i className="cycle-manager__swatch cycle-manager__swatch--unused" aria-hidden="true" /><span>Невикористані коди</span><strong>{formatCount(unused)}</strong></li>
        </ul>
      </figcaption>
    </figure>
  )
}

function groupLabel(group: ParticipationGroup) {
  return group.unit ? `${categoryLabel(group.category)} · ${group.unit}` : categoryLabel(group.category)
}

/** Розбивка анкет закритого циклу. Сервер не перелічує прихованих груп; лишається прапорець suppressed. */
export function ParticipationGroups({ participation, minGroupSize, byUnit, onByUnitChange }: {
  participation: Participation
  minGroupSize: number
  byUnit: boolean
  onByUnitChange?: (value: boolean) => void
}) {
  if (participation.status !== 'closed') {
    return <p className="participation__groups-note">Розбивка за категоріями й підрозділами з’явиться після закриття циклу.</p>
  }
  const groups = participation.groups
  return (
    <div className="participation__groups">
      <div className="participation__groups-head">
        <h5>{byUnit ? 'Анкети за категоріями й підрозділами' : 'Анкети за категоріями'}</h5>
        {onByUnitChange && (
          <label className="participation__toggle">
            <input type="checkbox" checked={byUnit} onChange={event => onByUnitChange(event.target.checked)} />
            <span>За підрозділами</span>
          </label>
        )}
      </div>
      {groups === null ? (
        <p className="participation__groups-note">Розбивки немає: анкет менше за поріг групи ({minGroupSize}).</p>
      ) : groups.length === 0 ? (
        <p className="participation__groups-note">Жодна група не досягла порогу ({minGroupSize}).</p>
      ) : (
        <table className="participation__table">
          <caption className="participation__sr-only">Кількість анкет у групах, що досягли порогу</caption>
          <thead><tr><th scope="col">{byUnit ? 'Категорія · підрозділ' : 'Категорія'}</th><th scope="col">Анкет</th></tr></thead>
          <tbody>
            {groups.map(group => (
              <tr key={`${group.category}|${group.unit ?? ''}`}>
                <th scope="row">{groupLabel(group)}</th>
                <td>{formatParticipationCount(group.responses, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {participation.suppressed && <SuppressionNote k={minGroupSize} className="cycle-manager__privacy-note" />}
    </div>
  )
}

/** Показ участі без завантаження (для admin і data_officer). */
export function ParticipationView({ participation, cycle, byUnit = false, onByUnitChange, headingId = 'cycle-participation-title' }: {
  participation: Participation | null
  cycle: Pick<Assessment, 'min_group_size' | 'status'>
  byUnit?: boolean
  onByUnitChange?: (value: boolean) => void
  headingId?: string
}) {
  const exact = participation ? isExact(participation) : true
  return (
    <section className="cycle-manager__participation" aria-labelledby={headingId}>
      <h4 id={headingId}>Участь</h4>
      {participation && !exact && (
        <p className="participation__approx" role="note"><strong>Приблизні значення.</strong> {approximateCountsNote(cycle.min_group_size)}</p>
      )}
      <ParticipationChart participation={participation} />
      <dl className="cycle-manager__metrics">
        <div><dt>Видано кодів:</dt>{' '}<dd>{participation ? formatCount(participation.tokens_issued) : '—'}</dd></div>
        <div><dt>Невикористаних:</dt>{' '}<dd>{participation ? formatParticipationCount(participation.tokens_unused, exact) : '—'}</dd></div>
        <div><dt>Анкет:</dt>{' '}<dd>{participation ? formatParticipationCount(participation.responses_total, exact) : '—'}</dd></div>
        <div className="cycle-manager__metric-accent"><dt>Рівень участі:</dt>{' '}<dd>{participation ? formatParticipationPercent(participation.participation_percent, exact) : '—'}</dd></div>
      </dl>
      <p className="cycle-manager__privacy-note">Участь малих груп приховано: доки анкет менше за поріг групи ({cycle.min_group_size}), кількість анкет, невикористаних кодів і рівень участі не показуються, щоб захистити анонімність.</p>
      {participation && exact && participation.status === 'closed' && <p className="participation__exact">Цикл закрито: показано точні значення.</p>}
      {participation && <ParticipationGroups participation={participation} minGroupSize={cycle.min_group_size} byUnit={byUnit} onByUnitChange={onByUnitChange} />}
    </section>
  )
}

/** Завантажує участь вибраного циклу; `refreshKey` перезавантажує дані після дій із циклом. */
export function ParticipationPanel({ cycle, refreshKey, headingId }: {
  cycle: Pick<Assessment, 'id' | 'min_group_size' | 'status'>
  refreshKey?: unknown
  headingId?: string
}) {
  const [participation, setParticipation] = useState<Participation | null>(null)
  const [byUnit, setByUnit] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setParticipation(null)
    setError('')
    getParticipation(cycle.id, { byUnit: byUnit && cycle.status === 'closed', signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setParticipation(value) })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Не вдалося завантажити участь') })
    return () => controller.abort()
  }, [cycle.id, cycle.status, byUnit, refreshKey])

  return (
    <>
      {error && <p className="cycle-manager__error" role="alert">{error}</p>}
      <ParticipationView participation={participation} cycle={cycle} byUnit={byUnit} onByUnitChange={setByUnit} headingId={headingId} />
    </>
  )
}
