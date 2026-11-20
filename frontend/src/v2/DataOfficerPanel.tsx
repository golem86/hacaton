import { useEffect, useMemo, useState } from 'react'
import { getManagedAssessments, type Assessment } from '../api/assessments'
import { AccessCodeIssuer, type IssuedCodes } from '../components/AccessCodeIssuer'
import { cycleStatusLabel } from '../components/AssessmentManager'
import { categoryLabel } from '../components/categories'
import { ParticipationPanel } from '../components/Participation'
import { ListPagination, usePagination } from './ListPagination'
import type { OfficerSection } from './navigation'
import '../components/AssessmentManager.css'
import './officer.css'

type LoadState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }

export const OFFICER_SCOPE_NOTE = 'Ваша роль — видача одноразових кодів доступу й моніторинг участі. Результати, аналітика, журнал дій, звіти й трекер для цієї ролі недоступні: так той, хто видає коди, не бачить відповідей.'

/** Перелік відкритих циклів для видачі кодів. Поки показано видані коди, перемикання заблоковано. */
export function OpenCyclesList({ cycles, selectedId, locked, onSelect }: {
  cycles: Assessment[]
  selectedId: number | null
  locked: boolean
  onSelect: (id: number) => void
}) {
  const open = useMemo(() => cycles.filter(cycle => cycle.status === 'open'), [cycles])
  const { current: page, setPage, setPageSize } = usePagination(open)
  if (open.length === 0) {
    return (
      <div className="v2-empty officer-panel__empty" role="status">
        <strong>Відкритих циклів немає</strong>
        <p>Коди видаються лише для відкритого циклу. Коли адміністратор відкриє цикл, він з’явиться тут.</p>
      </div>
    )
  }
  return (
    <ListPagination current={page} onPageChange={setPage} onPageSizeChange={setPageSize} name="відкритих циклів">
      <ul className="officer-panel__cycles" aria-label="Відкриті цикли оцінювання">
        {page.items.map(cycle => (
          <li key={cycle.id}>
            <button type="button" className={cycle.id === selectedId ? 'officer-panel__cycle is-active' : 'officer-panel__cycle'}
                    aria-pressed={cycle.id === selectedId} disabled={locked && cycle.id !== selectedId} onClick={() => onSelect(cycle.id)}>
              <strong>{cycle.name}</strong>
              <span>{cycle.start_date} — {cycle.end_date ?? 'без кінцевої дати'} · поріг групи {cycle.min_group_size}</span>
              <small>{(cycle.categories ?? []).map(categoryLabel).join(', ') || 'Усі категорії'}</small>
            </button>
          </li>
        ))}
      </ul>
    </ListPagination>
  )
}

/** Кабінет ролі data_officer. */
export default function DataOfficerPanel({ section }: { section: OfficerSection }) {
  const [cycles, setCycles] = useState<LoadState<Assessment[]>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [issued, setIssued] = useState<IssuedCodes | null>(null)
  const [participationKey, setParticipationKey] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setCycles({ status: 'loading' })
    getManagedAssessments(controller.signal)
      .then(list => { if (!controller.signal.aborted) setCycles({ status: 'ready', data: list.filter(cycle => cycle.status !== 'draft') }) })
      .catch(error => { if (!controller.signal.aborted) setCycles({ status: 'error', message: error instanceof Error ? error.message : 'Не вдалося завантажити цикли.' }) })
    return () => controller.abort()
  }, [attempt])

  const list = cycles.status === 'ready' ? cycles.data : []
  const pool = section === 'codes' ? list.filter(cycle => cycle.status === 'open') : list
  const selected = pool.find(cycle => cycle.id === selectedId) ?? pool[0] ?? null

  return (
    <section className="cycle-manager officer-panel" aria-labelledby="officer-panel-title">
      <header className="cycle-manager__masthead">
        <h2 id="officer-panel-title">{section === 'codes' ? 'Відкриті цикли й коди доступу' : 'Участь у циклах'}</h2>
        <p>{OFFICER_SCOPE_NOTE}</p>
      </header>

      {cycles.status === 'loading' && <p role="status">Завантажуємо цикли…</p>}
      {cycles.status === 'error' && (
        <div className="cycle-manager__error" role="alert">
          <p>{cycles.message}</p>
          <button className="v2-button" type="button" onClick={() => setAttempt(value => value + 1)}>Спробувати ще раз</button>
        </div>
      )}

      {cycles.status === 'ready' && section === 'codes' && (
        <div className="officer-panel__layout">
          <div className="v2-card">
            <h3>Відкриті цикли</h3>
            <OpenCyclesList cycles={list} selectedId={selected?.id ?? null} locked={issued !== null} onSelect={setSelectedId} />
            {issued !== null && <p className="officer-panel__hint">Інший цикл можна обрати після того, як ви збережете й сховаєте видані коди.</p>}
          </div>
          <div className="v2-card cycle-manager__overview">
            {selected ? (
              <>
                <h3>{selected.name}</h3>
                <AccessCodeIssuer key={selected.id} cycle={selected} issued={issued}
                  onIssued={codes => { setIssued(codes); setParticipationKey(value => value + 1) }}
                  onDismiss={() => setIssued(null)} />
              </>
            ) : <p className="cycle-manager__empty">Оберіть відкритий цикл, щоб видати коди.</p>}
          </div>
        </div>
      )}

      {cycles.status === 'ready' && section === 'participation' && (
        <div className="v2-card cycle-manager__overview">
          {list.length === 0 ? <p className="cycle-manager__empty">Відкритих або закритих циклів немає.</p> : (
            <>
              <label className="cycle-manager__field">Цикл
                <select value={selected?.id ?? ''} onChange={event => setSelectedId(Number(event.target.value) || null)}>
                  {list.map(cycle => <option key={cycle.id} value={cycle.id}>{cycle.name} · {cycleStatusLabel(cycle.status)}</option>)}
                </select>
              </label>
              {selected && <ParticipationPanel cycle={selected} refreshKey={participationKey} />}
            </>
          )}
        </div>
      )}
    </section>
  )
}
