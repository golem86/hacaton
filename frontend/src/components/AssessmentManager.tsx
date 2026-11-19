import { useEffect, useState, type FormEvent } from 'react'
import { getAssessments, type Assessment } from '../api/assessments'
import { activateCycle, closeCycle, createCycle, getParticipation, issueAccessTokens, type Participation } from '../api/admin'

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
  return <section className="v2-card"><h2>Цикли оцінювання</h2>
    {error && <p role="alert">{error}</p>}
    <form onSubmit={submit}><h3>Новий цикл</h3>
      <label>Назва<input required maxLength={50} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>Опис<input maxLength={2000} value={description} onChange={e => setDescription(e.target.value)} /></label>
      <label>Обсяг<input maxLength={200} value={scope} onChange={e => setScope(e.target.value)} /></label>
      <label>Початок<input required type="date" value={startDate} onChange={e => setStartDate(e.target.value)} /></label>
      <label>Кінець<input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} /></label>
      <label>Мінімальний розмір групи<input required type="number" min={5} max={1000} value={minGroup} onChange={e => setMinGroup(Number(e.target.value))} /></label>
      <fieldset><legend>Категорії</legend>{(Object.keys(categoryLabels) as Category[]).map(item => <label key={item}>
        <input type="checkbox" checked={categories.includes(item)} onChange={e => setCategories(previous => e.target.checked ? [...previous, item] : previous.filter(x => x !== item))} />{categoryLabels[item]}</label>)}</fieldset>
      <p>Анкета: demo-v1 (демонстраційна шкала; методика не затверджена).</p>
      <button className="v2-button" disabled={busy}>Створити чернетку</button>
    </form>
    <hr />
    <label>Цикл<select value={id ?? ''} onChange={e => { const next = cycles.find(c => c.id === Number(e.target.value)); setId(next?.id ?? null); setCategory(next?.categories?.[0] ?? 'mgmt'); setCodes([]); setParticipation(null) }}>{cycles.map(c => <option key={c.id} value={c.id}>{c.name} · {c.status}</option>)}</select></label>
    {selected && <div><p>Статус: {selected.status}. Поріг: {selected.min_group_size}. Версія: {selected.questionnaire_version ?? 'demo-v1'}.</p>
      <p>Категорії: {(selected.categories ?? Object.keys(categoryLabels)).join(', ')}. Період: {selected.start_date} — {selected.end_date ?? 'без кінцевої дати'}.</p>
      {selected.status === 'draft' && <button className="v2-button" disabled={busy} type="button" onClick={() => void run(() => activateCycle(selected.id))}>Активувати</button>}
      {selected.status === 'open' && <button className="v2-button" disabled={busy} type="button" onClick={() => void run(() => closeCycle(selected.id))}>Закрити цикл</button>}
      <h3>Участь</h3><p>Видано кодів: {participation?.tokens_issued ?? '—'}; невикористаних: {participation?.tokens_unused ?? 'приховано'}; анкет: {participation?.responses_total ?? 'приховано'}; участь: {participation?.participation_percent == null ? 'приховано' : `${participation.participation_percent}%`}.</p>
      {selected.status === 'open' && <div><label>Категорія кодів<select value={category} onChange={e => setCategory(e.target.value as Category)}>{(selected.categories ?? Object.keys(categoryLabels) as Category[]).map(item => <option key={item} value={item}>{categoryLabels[item as Category]}</option>)}</select></label>
        <label>Кількість кодів<input type="number" min={1} max={500} value={count} onChange={e => setCount(Number(e.target.value))} /></label>
        <button className="v2-button" disabled={busy} type="button" onClick={() => void run(async () => { const result = await issueAccessTokens(selected.id, count, category); setCodes(result.tokens) })}>Видати коди</button>
        {codes.length > 0 && <div role="status"><p>Коди показуються лише зараз. Передайте їх респондентам окремо.</p><textarea readOnly value={codes.join('\n')} /></div>}</div>}
    </div>}
  </section>
}
