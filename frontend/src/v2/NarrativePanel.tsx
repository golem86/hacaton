import { useEffect, useRef, useState } from 'react'
import type { Assessment } from '../api/assessments'
import {
  pollNarrativeJob, startCompareNarrative, startCycleNarrative,
  type LmStatus, type NarrativeJob, type NarrativeKind,
} from '../api/narrative'
import './narrative.css'

export const DRAFT_NOTICE = 'Чернетка, згенерована локальною ШІ. Перевірте перед використанням.'
export type LmState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: LmStatus }

const KIND_TITLES: Record<NarrativeKind, string> = {
  summary: 'Резюме циклу',
  recommendations: 'Чернетки рекомендацій',
  compare: 'Порівняння циклів',
}

/** null — генерацію можна запускати; інакше — пояснення, чому кнопки неактивні. */
export function lmBlockReason(lm: LmState): string | null {
  if (lm.status === 'loading') return 'Перевіряємо доступність локальної ШІ…'
  if (lm.status === 'error') return `Не вдалося перевірити локальну ШІ: ${lm.message}`
  if (!lm.data.enabled) return 'Локальна ШІ не налаштована на сервері, тому чернетки ШІ недоступні.'
  if (!lm.data.reachable) return 'Локальна ШІ зараз недоступна (модель завантажується або службу зупинено). Спробуйте пізніше.'
  return null
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Не вдалося запустити генерацію.'
}

type DraftState = { status: 'idle' } | { status: 'starting'; kind: NarrativeKind } | { status: 'error'; message: string }
  | { status: 'job'; job: NarrativeJob }

/** Запуск завдання й опитування кожні 4 с; при розмонтуванні опитування зупиняється. */
function useNarrativeJob() {
  const [state, setState] = useState<DraftState>({ status: 'idle' })
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])

  async function run(kind: NarrativeKind, start: (signal: AbortSignal) => Promise<string>) {
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setState({ status: 'starting', kind })
    try {
      const jobId = await start(current.signal)
      await pollNarrativeJob(jobId, {
        signal: current.signal,
        onUpdate: job => { if (!current.signal.aborted) setState({ status: 'job', job }) },
      })
    } catch (error) {
      if (!current.signal.aborted) setState({ status: 'error', message: errorMessage(error) })
    }
  }
  const busy = state.status === 'starting' || (state.status === 'job' && (state.job.status === 'queued' || state.job.status === 'running'))
  return { state, run, busy }
}

export function NarrativeDraft({ state }: { state: DraftState }) {
  if (state.status === 'idle') return null
  if (state.status === 'starting') return <p className="narrative__progress" role="status">Ставимо завдання в чергу…</p>
  if (state.status === 'error') return <p className="v2-auth-error narrative__error" role="alert">{state.message}</p>
  return <NarrativeResult job={state.job} />
}

/** Відображення завдання: прогрес, помилка або простий текст з позначкою чернетки. */
export function NarrativeResult({ job }: { job: NarrativeJob }) {
  if (job.status === 'queued') {
    return <p className="narrative__progress" role="status">{KIND_TITLES[job.kind]}: у черзі. Генерація на сервері може тривати 1–2 хв.</p>
  }
  if (job.status === 'running') {
    return <p className="narrative__progress" role="status">{KIND_TITLES[job.kind]}: генеруємо текст… Це може тривати 1–2 хв.</p>
  }
  if (job.status === 'failed') {
    return <p className="v2-auth-error narrative__error" role="alert">{job.error ?? 'Не вдалося згенерувати текст.'}</p>
  }
  const unverified = job.unverified_numbers ?? []
  return (
    <article className="narrative__result" aria-label={KIND_TITLES[job.kind]}>
      <p className="narrative__notice"><strong>{DRAFT_NOTICE}</strong></p>
      {job.verified === false && (
        <div className="narrative__warning" role="alert">
          <p>Деяких чисел немає в даних звіту — перевірте їх вручну або видаліть:</p>
          <ul>{unverified.map(number => <li key={number}>{number}</li>)}</ul>
        </div>
      )}
      <div className="narrative__text">{job.text}</div>
      <CopyButton text={job.text ?? ''} />
    </article>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState<'idle' | 'ok' | 'error'>('idle')
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied('ok')
    } catch {
      setCopied('error')
    }
  }
  return (
    <div className="narrative__copy">
      <button type="button" className="v2-button" onClick={() => void copy()}>Копіювати</button>
      {copied === 'ok' && <span role="status">Скопійовано.</span>}
      {copied === 'error' && <span role="alert">Не вдалося скопіювати. Виділіть текст вручну.</span>}
    </div>
  )
}

export function LmNote({ lm }: { lm: LmState }) {
  const reason = lmBlockReason(lm)
  return reason ? <p className="v2-muted narrative__note">{reason}</p> : null
}

/** Кнопки «Резюме (ШІ)» і «Чернетки рекомендацій (ШІ)» для одного закритого циклу. */
export function CycleNarrative({ id, lm }: { id: number; lm: LmState }) {
  const { state, run, busy } = useNarrativeJob()
  const blocked = lmBlockReason(lm) !== null
  return (
    <section className="narrative" aria-labelledby={`narrative-${id}`}>
      <h3 id={`narrative-${id}`}>Текст звіту (ШІ)</h3>
      <LmNote lm={lm} />
      <div className="v2-report__downloads">
        <button type="button" className="v2-button" disabled={blocked || busy}
                onClick={() => void run('summary', signal => startCycleNarrative(id, 'summary', signal))}>
          Резюме (ШІ)
        </button>
        <button type="button" className="v2-button" disabled={blocked || busy}
                onClick={() => void run('recommendations', signal => startCycleNarrative(id, 'recommendations', signal))}>
          Чернетки рекомендацій (ШІ)
        </button>
      </div>
      <p className="v2-muted narrative__hint">Чернетки рекомендацій не зберігаються в трекер: рішення ухвалює посадова особа.</p>
      <NarrativeDraft state={state} />
    </section>
  )
}

/** Порівняння двох закритих циклів: base (попередній) → target (поточний). */
export function CompareNarrative({ cycles, lm }: { cycles: Assessment[]; lm: LmState }) {
  const [baseId, setBaseId] = useState<number | null>(cycles[1]?.id ?? null)
  const [targetId, setTargetId] = useState<number | null>(cycles[0]?.id ?? null)
  const { state, run, busy } = useNarrativeJob()
  if (cycles.length < 2) return null
  const blocked = lmBlockReason(lm) !== null
  const same = baseId === targetId
  return (
    <section className="narrative" aria-labelledby="narrative-compare">
      <h3 id="narrative-compare">Порівняння циклів (ШІ)</h3>
      <LmNote lm={lm} />
      <div className="narrative__pair">
        <label className="cycle-select">Попередній цикл
          <select value={baseId ?? ''} onChange={event => setBaseId(Number(event.target.value))}>
            {cycles.map(cycle => <option key={cycle.id} value={cycle.id}>{cycle.name}</option>)}
          </select>
        </label>
        <label className="cycle-select">Поточний цикл
          <select value={targetId ?? ''} onChange={event => setTargetId(Number(event.target.value))}>
            {cycles.map(cycle => <option key={cycle.id} value={cycle.id}>{cycle.name}</option>)}
          </select>
        </label>
      </div>
      {same && <p className="v2-muted">Оберіть два різні цикли.</p>}
      <div className="v2-report__downloads">
        <button type="button" className="v2-button" disabled={blocked || busy || same || baseId === null || targetId === null}
                onClick={() => {
                  if (baseId !== null && targetId !== null) void run('compare', signal => startCompareNarrative(baseId, targetId, signal))
                }}>
          Порівняння циклів (ШІ)
        </button>
      </div>
      <NarrativeDraft state={state} />
    </section>
  )
}
