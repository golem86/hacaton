import { useEffect, useState, type FormEvent } from 'react'
import { getAssessments, type Assessment } from '../api/assessments'
import { activateCycle, closeCycle, createCycle, getParticipation, issueAccessTokens, type Participation } from '../api/admin'
import './AssessmentManager.css'

const categoryLabels = { mgmt: 'Керівництво', npp: 'Науково-педагогічні працівники', cadets: 'Курсанти', staff: 'Працівники' }
type Category = keyof typeof categoryLabels

export default function AssessmentManager() {
  const [cycles, setCycles] = useState<Assessment[]>([])
  const [id, setId] = useState<number | null>(null)
  const [participation, setParticipation] = useState<Participation | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [scope, setScope] = useState('')
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10))
  const [endDate, setEndDate] = useState('')
  const [minGroup, setMinGroup] = useState(5)
  const [categories, setCategories] = useState<Category[]>(['mgmt', 'npp', 'cadets', 'staff'])
  const [category, setCategory] = useState<Category>('mgmt')
  const [count, setCount] = useState(10)
  const [codes, setCodes] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const selected = cycles.find(c => c.id === id)
  const endDateTooEarly = Boolean(startDate && endDate && endDate < startDate)

  async function refresh(selectId?: number) {
    const list = await getAssessments()
    setCycles(list)
    setId(current => selectId ?? current ?? list[0]?.id ?? null)
    const nextCycle = list.find(c => c.id === selectId)
    if (nextCycle?.categories?.length && !nextCycle.categories.includes(category)) setCategory(nextCycle.categories[0])
  }
  useEffect(() => { void refresh().catch(e => setError(e instanceof Error ? e.message : 'Не вдалося завантажити цикли')) }, [])
  useEffect(() => {
    if (!id) return
    let active = true
    getParticipation(id).then(value => { if (active) setParticipation(value) })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : 'Не вдалося завантажити участь') })
    return () => { active = false }
  }, [id, cycles])

  async function run(action: () => Promise<unknown>, selectId?: number) {
    setError(''); setBusy(true)
    try { const result = await action(); await refresh(typeof result === 'number' ? result : selectId) }
    catch (e) { setError(e instanceof Error ? e.message : 'Операцію не виконано') }
    finally { setBusy(false) }
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!categories.length) { setError('Оберіть принаймні одну категорію.'); return }
    void run(async () => {
      const created = await createCycle({ name, description, scope, start_date: startDate,
        end_date: endDate || null, categories, min_group_size: minGroup, questionnaire_version: 'demo-v1' })
      setName(''); setDescription(''); setScope(''); setEndDate('')
      return created.id
    })
  }
  return (
    <section className="cycle-manager" aria-labelledby="cycle-manager-title">
      <header className="cycle-manager__masthead">
        <h2 id="cycle-manager-title">Цикли оцінювання</h2>
        <p>Налаштовуйте цикли та переглядайте участь в анонімному опитуванні.</p>
      </header>

      {error && <p className="cycle-manager__error" role="alert">{error}</p>}

      <div className="cycle-manager__layout">
        <form className="v2-card cycle-manager__form" onSubmit={submit} aria-labelledby="new-cycle-title">
          <h3 id="new-cycle-title">Новий цикл</h3>
          <div className="cycle-manager__fields">
            <label className="cycle-manager__field cycle-manager__wide">Назва
              <input required maxLength={50} value={name} onChange={e => setName(e.target.value)} />
            </label>
            <label className="cycle-manager__field">Опис
              <input maxLength={2000} value={description} onChange={e => setDescription(e.target.value)} />
            </label>
            <label className="cycle-manager__field">Обсяг
              <input maxLength={200} value={scope} onChange={e => setScope(e.target.value)} />
            </label>
            <label className="cycle-manager__field">Початок
              <input required type="date" value={startDate} onChange={e => setStartDate(e.target.value)} />
            </label>
            <div className="cycle-manager__field">
              <label htmlFor="cycle-end-date">Кінець</label>
              <input
                id="cycle-end-date"
                type="date"
                min={startDate || undefined}
                value={endDate}
                onChange={e => setEndDate(e.target.value)}
                aria-invalid={endDateTooEarly || undefined}
                aria-describedby={endDateTooEarly ? 'cycle-end-date-error' : undefined}
              />
              {endDateTooEarly && (
                <p id="cycle-end-date-error" className="cycle-manager__field-error">
                  Дата завершення не може бути раніше дати початку.
                </p>
              )}
            </div>
            <label className="cycle-manager__field cycle-manager__wide">Мінімальний розмір групи
              <input required type="number" min={5} max={1000} value={minGroup} onChange={e => setMinGroup(Number(e.target.value))} />
            </label>
          </div>

          <fieldset className="cycle-manager__categories">
            <legend>Категорії</legend>
            <div className="cycle-manager__choices">
              {(Object.keys(categoryLabels) as Category[]).map(item => (
                <label className="cycle-manager__choice" key={item}>
                  <input type="checkbox" checked={categories.includes(item)} onChange={e => setCategories(previous => e.target.checked ? [...previous, item] : previous.filter(x => x !== item))} />
                  <span>{categoryLabels[item]}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <footer className="cycle-manager__form-footer">
            <p><strong>Анкета demo-v1</strong><br />Демонстраційна шкала. Методика не затверджена.</p>
            <button className="v2-button v2-button-primary" disabled={busy}>Створити чернетку</button>
          </footer>
        </form>

        <section className="v2-card cycle-manager__overview" aria-labelledby="cycle-overview-title">
          <h3 id="cycle-overview-title">Огляд циклу</h3>
          <label className="cycle-manager__field">Цикл
            <select value={id ?? ''} onChange={e => { const next = cycles.find(c => c.id === Number(e.target.value)); setId(next?.id ?? null); setCategory(next?.categories?.[0] ?? 'mgmt'); setCodes([]); setParticipation(null) }}>
              {cycles.map(c => <option key={c.id} value={c.id}>{c.name} · {c.status}</option>)}
            </select>
          </label>

          {selected ? (
            <>
              <div className="cycle-manager__summary">
                <p className="cycle-manager__status" data-status={selected.status}>Статус: {selected.status}</p>
                <dl className="cycle-manager__details">
                  <div className="cycle-manager__wide">
                    <dt>Період</dt>
                    <dd>{selected.start_date} — {selected.end_date ?? 'без кінцевої дати'}</dd>
                  </div>
                  <div>
                    <dt>Поріг групи</dt>
                    <dd>{selected.min_group_size}</dd>
                  </div>
                  <div>
                    <dt>Версія анкети</dt>
                    <dd>{selected.questionnaire_version ?? 'demo-v1'}</dd>
                  </div>
                  <div className="cycle-manager__wide">
                    <dt>Категорії</dt>
                    <dd className="cycle-manager__category-list">
                      {(selected.categories ?? Object.keys(categoryLabels) as Category[]).map(item => (
                        <span key={item}>{categoryLabels[item]}</span>
                      ))}
                    </dd>
                  </div>
                </dl>
                {selected.status === 'draft' && <button className="v2-button" disabled={busy} type="button" onClick={() => void run(() => activateCycle(selected.id))}>Активувати</button>}
                {selected.status === 'open' && <button className="v2-button" disabled={busy} type="button" onClick={() => void run(() => closeCycle(selected.id))}>Закрити цикл</button>}
              </div>

              <section className="cycle-manager__participation" aria-labelledby="cycle-participation-title">
                <h4 id="cycle-participation-title">Участь</h4>
                <dl className="cycle-manager__metrics">
                  <div><dt>Видано кодів:</dt>{' '}<dd>{participation?.tokens_issued ?? '—'}</dd></div>
                  <div><dt>Невикористаних:</dt>{' '}<dd>{participation?.tokens_unused ?? 'приховано'}</dd></div>
                  <div><dt>Анкет:</dt>{' '}<dd>{participation?.responses_total ?? 'приховано'}</dd></div>
                  <div className="cycle-manager__metric-accent"><dt>Рівень участі:</dt>{' '}<dd>{participation?.participation_percent == null ? 'приховано' : `${participation.participation_percent}%`}</dd></div>
                </dl>
              </section>

              {selected.status === 'open' && (
                <section className="cycle-manager__codes" aria-labelledby="cycle-codes-title">
                  <h4 id="cycle-codes-title">Коди доступу</h4>
                  <div className="cycle-manager__fields">
                    <label className="cycle-manager__field">Категорія кодів
                      <select value={category} onChange={e => setCategory(e.target.value as Category)}>
                        {(selected.categories ?? Object.keys(categoryLabels) as Category[]).map(item => (
                          <option key={item} value={item}>{categoryLabels[item as Category]}</option>
                        ))}
                      </select>
                    </label>
                    <label className="cycle-manager__field">Кількість кодів
                      <input type="number" min={1} max={500} value={count} onChange={e => setCount(Number(e.target.value))} />
                    </label>
                  </div>
                  <button className="v2-button" disabled={busy} type="button" onClick={() => void run(async () => { const result = await issueAccessTokens(selected.id, count, category); setCodes(result.tokens) })}>Видати коди</button>
                  {codes.length > 0 && (
                    <div className="cycle-manager__issued" role="status">
                      <p>Коди показуються лише зараз. Передайте їх респондентам окремо.</p>
                      <textarea aria-label="Видані коди" readOnly value={codes.join('\n')} />
                    </div>
                  )}
                </section>
              )}
            </>
          ) : <p className="cycle-manager__empty">Оберіть цикл зі списку, щоб переглянути його параметри.</p>}
        </section>
      </div>
    </section>
  )
}
