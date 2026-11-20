import { useEffect, useState } from 'react'
import { criterionLabel, getExpertAssessments, type ExpertAssessmentList as ExpertList, type ExpertRecord } from '../api/annexV'
import { roleLabel } from '../api/auth'
import { formatAuditDate } from './AuditTrail'
import { ListPagination, usePagination } from './ListPagination'
import './annex-v.css'

type Load<T> = { status: 'idle' } | { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }
export type ExpertListState = Load<ExpertList>

/** Рівень у форматі uk-UA: до двох знаків після коми (3,5; 2,25), відсутній — «—». */
export function formatExpertLevel(level: number | null | undefined): string {
  return level === null || level === undefined ? '—' : level.toLocaleString('uk-UA', { maximumFractionDigits: 2 })
}

/** Хто вніс: роль і id облікового запису (демо-режим без сесії не має id). */
export function enteredByLabel(record: Pick<ExpertRecord, 'entered_role' | 'entered_by_user_id'>): string {
  const role = record.entered_role ? roleLabel(record.entered_role) : 'Невідомо'
  return record.entered_by_user_id === null ? role : `${role} · id ${record.entered_by_user_id}`
}

/**
 * Рівні критеріїв одного запису в порядку питань: середнє рівнів відповідей критерію
 * (у формі 1 openness має два питання — як у розрахунку сервера).
 */
export function recordLevels(record: ExpertRecord): { criterion: string; level: number | null }[] {
  const groups = new Map<string, number[]>()
  for (const answer of record.answers) {
    if (!answer.criterion) continue
    const list = groups.get(answer.criterion) ?? []
    if (answer.level !== null) list.push(answer.level)
    groups.set(answer.criterion, list)
  }
  return [...groups].map(([criterion, levels]) => ({
    criterion, level: levels.length ? levels.reduce((sum, value) => sum + value, 0) / levels.length : null,
  }))
}

function RecordAnswers({ record }: { record: ExpertRecord }) {
  return <details className="annex-details expert-answers">
    <summary>Відповіді ({record.answers.length})</summary>
    <ol className="expert-answer-list">
      {record.answers.map(answer => <li key={answer.question_id}>
        <strong>{answer.question ?? answer.question_id}</strong>
        <span>{answer.option ?? answer.option_id ?? '—'}</span>
        <small>Рівень: {formatExpertLevel(answer.level)}{answer.criterion ? ` · ${criterionLabel(answer.criterion)}` : ''}</small>
      </li>)}
    </ol>
  </details>
}

/** Таблиця записів із пагінацією; кожен запис розгортається до відповідей (питання → варіант → рівень). */
export function ExpertRecordsTable({ items, resetKey = '' }: { items: ExpertRecord[]; resetKey?: string }) {
  const { current, setPage, setPageSize } = usePagination(items, { resetKey })
  return <ListPagination current={current} onPageChange={setPage} onPageSizeChange={setPageSize} name="експертних оцінок">
    <table className="annex-table expert-records">
      <caption className="annex-sr-only">Внесені експертні оцінки циклу</caption>
      <thead><tr><th scope="col">Посада експерта</th><th scope="col">Дата внесення</th><th scope="col">Хто вніс</th><th scope="col">Рівні за критеріями</th><th scope="col">Відповіді</th></tr></thead>
      <tbody>{current.items.map(record => <tr key={record.id}>
        <th scope="row" data-label="Посада експерта">{record.expert_label}<small className="v2-form-hint">Запис № {record.id}</small></th>
        <td data-label="Дата внесення">{record.created_at ? formatAuditDate(record.created_at) : '—'}</td>
        <td data-label="Хто вніс">{enteredByLabel(record)}</td>
        <td data-label="Рівні за критеріями">
          <dl className="expert-levels">{recordLevels(record).map(item => <div key={item.criterion}>
            <dt>{criterionLabel(item.criterion)}</dt><dd>{formatExpertLevel(item.level)}</dd>
          </div>)}</dl>
        </td>
        <td data-label="Відповіді"><RecordAnswers record={record} /></td>
      </tr>)}</tbody>
    </table>
  </ListPagination>
}

/** Підсумок за критеріями: середній рівень і кількість експертів. */
export function ExpertSummaryTable({ data }: { data: ExpertList }) {
  return <table className="annex-table expert-summary">
    <caption className="annex-sr-only">Підсумок експертних оцінок за критеріями</caption>
    <thead><tr><th scope="col">Критерій</th><th scope="col">Середній рівень</th><th scope="col">Експертів</th><th scope="col">Рівні експертів</th></tr></thead>
    <tbody>{data.by_criterion.map(item => <tr key={item.criterion}>
      <th scope="row" data-label="Критерій">{criterionLabel(item.criterion) === item.criterion ? item.title : criterionLabel(item.criterion)}</th>
      <td data-label="Середній рівень"><strong>{formatExpertLevel(item.mean)}</strong></td>
      <td data-label="Експертів">{item.levels.length}</td>
      <td data-label="Рівні експертів">{item.levels.length ? item.levels.map(formatExpertLevel).join('; ') : '—'}</td>
    </tr>)}</tbody>
  </table>
}

/** Представлення без завантаження (для тестів і повторного використання). */
export function ExpertListView({ state, onRetry, resetKey = '' }: { state: ExpertListState; onRetry?: () => void; resetKey?: string }) {
  return <section className="expert-list" aria-labelledby="expert-list-title">
    <h3 id="expert-list-title">Внесені експертні оцінки циклу</h3>
    {state.status === 'idle' && <p className="v2-empty" role="status">Оберіть цикл, щоб переглянути внесені експертні оцінки.</p>}
    {state.status === 'loading' && <p role="status">Завантажуємо експертні оцінки…</p>}
    {state.status === 'error' && <div className="v2-inline-error" role="alert"><p>{state.message}</p>
      {onRetry && <button type="button" className="v2-button" onClick={onRetry}>Спробувати ще раз</button>}</div>}
    {state.status === 'ready' && (state.data.items.length === 0
      ? <p className="v2-empty" role="status">Для цього циклу експертних оцінок ще не внесено.</p>
      : <>
        <p>Записів: {state.data.items.length}. Експерт позначений посадою; тексти відповідей і рівні — з каталогу Додатка В (редакція {state.data.version}).</p>
        <ExpertRecordsTable items={state.data.items} resetKey={resetKey} />
        <h4>Підсумок за критеріями</h4>
        <ExpertSummaryTable data={state.data} />
      </>)}
  </section>
}

/** Завантажує внесені оцінки обраного циклу; зміна `refreshKey` (успішне внесення) оновлює список. */
export default function ExpertAssessmentList({ assessmentId, refreshKey = 0 }: { assessmentId: number | null; refreshKey?: number }) {
  const [state, setState] = useState<ExpertListState>(() => assessmentId === null ? { status: 'idle' } : { status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (assessmentId === null) { setState({ status: 'idle' }); return }
    const controller = new AbortController()
    setState({ status: 'loading' })
    getExpertAssessments(assessmentId, controller.signal)
      .then(data => { if (!controller.signal.aborted) setState({ status: 'ready', data }) })
      .catch(error => { if (!controller.signal.aborted) setState({ status: 'error', message: error instanceof Error ? error.message : 'Не вдалося завантажити експертні оцінки.' }) })
    return () => controller.abort()
  }, [assessmentId, refreshKey, attempt])
  return <ExpertListView state={state} onRetry={() => setAttempt(value => value + 1)} resetKey={String(assessmentId ?? '')} />
}
