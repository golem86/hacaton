import { useEffect, useRef, useState } from 'react'
import { getAssessments, getManagedAssessments, type Assessment } from '../api/assessments'
import { ANNEX_V_VERSION, AnnexVOutcomeUnknownError, submitAnnexVResponse, submitExpertAssessment, type AnnexVForm } from '../api/annexV'
import { ALL_CATEGORIES, categoryLabel } from '../components/categories'
import ExpertAssessmentList from '../v2/ExpertAssessmentList'
import { getOfficialTemplate } from './catalog'
import {
  ACCESS_CODE_MAX, EXPERT_LABEL_MAX, answersForTemplate, validateAccessCode, validateExpertLabel, validateOfficialAnswers, type OfficialAnswers,
} from './validation'
import '../v2/annex-v.css'

type Mode = 'self' | 'expert'
type CycleLoad = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: Assessment[] }
type Submission = { status: 'idle' } | { status: 'pending' } | { status: 'done'; message: string } | { status: 'error'; message: string }

/** Робочі позначки з каталогу (WIP Preview, preview) не показуємо користувачу; сам каталог не змінюється. */
export function presentableText(text: string) {
  return text.replace(/\s*Це WIP Preview без серверного збереження\./g, '').replace(/\bpreview\b/gi, 'перегляд')
}

export const ANONYMITY_NOTE = 'Анкета надсилається без cookie сесії й не пов’язується з вашим обліковим записом. Одноразовий код діє лише для одного подання й після нього стає недійсним. Особистий рівень не обчислюється й не показується — лише агреговані результати груп від k відповідей.'
export const LEVEL_RULE_NOTE = 'Варіанти впорядковано за Додатком В від початкового до оптимізуючого рівня: a = 1, b = 2, c = 3, d = 4, e = 5; у питанні про викривачів (6 варіантів) — a = 1, b = 2, c = 3, d = 4, e = 4, f = 5 (Додаток Г, с. 73). Рівні рахує сервер лише в агрегатах.'
export const FORM_LABELS: Readonly<Record<AnnexVForm, string>> = { 1: 'Анкета 1 — робоча група', 2: 'Анкета 2 — особовий склад' }

/** Помилки налаштування подання (цикл, категорія, код або посада експерта). */
export function setupErrors(mode: Mode, setup: { cycleId: number | null; category: string; code: string; label: string }): Record<string, string> {
  const errors: Record<string, string> = {}
  if (setup.cycleId === null) errors.cycle = 'Оберіть цикл оцінювання.'
  if (mode === 'self') {
    if (!setup.category) errors.category = 'Оберіть категорію респондента.'
    const code = validateAccessCode(setup.code)
    if (code) errors.code = code
  } else {
    const label = validateExpertLabel(setup.label)
    if (label) errors.label = label
  }
  return errors
}

const cyclesFor = (mode: Mode, list: Assessment[]) => list.filter(cycle => mode === 'self' ? cycle.status === 'open' : cycle.status !== 'draft')

export default function OfficialAssessment({ mode, cycles: preset }: { mode: Mode; cycles?: Assessment[] }) {
  const [cycles, setCycles] = useState<CycleLoad>(preset ? { status: 'ready', data: cyclesFor(mode, preset) } : { status: 'loading' })
  const [reload, setReload] = useState(0)
  const [cycleId, setCycleId] = useState<number | null>(() => {
    const ready = preset ? cyclesFor(mode, preset) : []
    return ready.length === 1 ? ready[0].id : null
  })
  const [category, setCategory] = useState('')
  const [form, setForm] = useState<AnnexVForm>(mode === 'expert' ? 1 : 2)
  const [code, setCode] = useState('')
  const [label, setLabel] = useState('')
  const [answers, setAnswers] = useState<OfficialAnswers>({})
  const [index, setIndex] = useState(0)
  const [showErrors, setShowErrors] = useState(false)
  const [showSetupErrors, setShowSetupErrors] = useState(false)
  const [review, setReview] = useState(false)
  const [notice, setNotice] = useState('')
  const [submission, setSubmission] = useState<Submission>({ status: 'idle' })
  const [savedExperts, setSavedExperts] = useState(0)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    if (preset) return
    const abort = new AbortController()
    setCycles({ status: 'loading' })
    const load = mode === 'self' ? getAssessments(abort.signal) : getManagedAssessments(abort.signal)
    load.then(list => {
      if (abort.signal.aborted) return
      const available = cyclesFor(mode, list)
      setCycles({ status: 'ready', data: available })
      setCycleId(current => current !== null && available.some(cycle => cycle.id === current) ? current : available.length === 1 ? available[0].id : null)
    }).catch(error => { if (!abort.signal.aborted) setCycles({ status: 'error', message: error instanceof Error ? error.message : 'Не вдалося завантажити цикли оцінювання.' }) })
    return () => abort.abort()
  }, [mode, preset, reload])
  useEffect(() => () => controller.current?.abort(), [])

  const template = getOfficialTemplate(`appendix-v-form-${form}`, ANNEX_V_VERSION)
  if (!template) return <section className="v2-card" role="alert">Версію анкети не знайдено.</section>

  const list = cycles.status === 'ready' ? cycles.data : []
  const cycle = list.find(item => item.id === cycleId) ?? null
  const categories = cycle?.categories?.length ? cycle.categories : ALL_CATEGORIES
  const questions = template.questions
  const question = questions[index]
  const errors = validateOfficialAnswers(template, answers)
  const answered = questions.length - Object.keys(errors).length
  const sections = [...new Set(questions.map(item => item.source.section))]
  const setup = setupErrors(mode, { cycleId, category, code, label })
  const locked = submission.status === 'pending' || submission.status === 'done'
  const expert = mode === 'expert'

  const resetAnswers = () => { setAnswers({}); setShowErrors(false); setIndex(0); setReview(false) }
  const selectForm = (next: AnnexVForm) => {
    if (next === form) return
    const hadAnswers = Object.keys(answers).length > 0
    setForm(next); resetAnswers(); setSubmission({ status: 'idle' })
    setNotice(hadAnswers ? 'Анкету змінено: відповіді попередньої анкети очищено.' : '')
  }
  const jump = (next: number) => { setIndex(next); setReview(false); setNotice('') }
  const check = () => {
    setShowErrors(true)
    if (Object.keys(errors).length) {
      setNotice(`Пропущено обов'язкових відповідей: ${Object.keys(errors).length}. Перейдіть до позначених питань.`)
      setReview(false)
    } else {
      setReview(true)
      setNotice('Усі обов’язкові відповіді заповнено. Перевірте їх і надішліть анкету.')
    }
  }
  const submit = async () => {
    setShowSetupErrors(true); setShowErrors(true)
    if (Object.keys(errors).length) { setReview(false); setNotice(`Пропущено обов'язкових відповідей: ${Object.keys(errors).length}.`); return }
    if (Object.keys(setup).length || cycleId === null) { setNotice('Заповніть позначені поля над анкетою, щоб надіслати відповіді.'); return }
    controller.current?.abort()
    const abort = new AbortController()
    controller.current = abort
    setSubmission({ status: 'pending' }); setNotice('')
    const payload = answersForTemplate(template, answers)
    try {
      if (expert) {
        const result = await submitExpertAssessment(cycleId, { expert_label: label.trim(), form: 1, version: ANNEX_V_VERSION, answers: payload }, abort.signal)
        setSavedExperts(value => value + 1)
        setSubmission({ status: 'done', message: `Експертну оцінку збережено${typeof result?.id === 'number' ? ` (запис № ${result.id})` : ''}. Позначка: «${label.trim()}».` })
      } else {
        await submitAnnexVResponse(cycleId, { access_token: code.trim(), category, form, version: ANNEX_V_VERSION, answers: payload }, abort.signal)
        setCode('')
        setSubmission({ status: 'done', message: 'Анкету прийнято. Дякуємо за участь! Код доступу використано, тож повторне подання з ним неможливе. Відповідь збережено без прив’язки до облікового запису.' })
      }
    } catch (error) {
      if (abort.signal.aborted) return
      setSubmission({ status: 'error', message: error instanceof AnnexVOutcomeUnknownError || error instanceof Error ? error.message : 'Не вдалося надіслати анкету.' })
    }
  }
  const startNextExpert = () => { resetAnswers(); setLabel(''); setShowSetupErrors(false); setSubmission({ status: 'idle' }); setNotice('') }
  const fieldError = (key: string) => showSetupErrors && submission.status !== 'done' && setup[key] ? <p id={`official-${key}-error`} className="annex-field-error" role="alert">{setup[key]}</p> : null
  const described = (key: string) => showSetupErrors && submission.status !== 'done' && setup[key] ? `official-${key}-error` : undefined

  return <section className="v2-card official-assessment" aria-label={expert ? 'Експертне оцінювання' : 'Офіційна анкета'}>
    <h2>{expert ? 'Експертне оцінювання (Додаток В, анкета 1)' : 'Офіційна анкета (Додаток В)'}</h2>
    <p>Джерело: Додаток В, друковані с. 53–66. У PDF: Анкета 1 — 12 питань, Анкета 2 — 10 питань. Ця версія охоплює всі питання відповідної анкети в адаптованому викладі (редакція {ANNEX_V_VERSION}).</p>
    {expert
      ? <p className="official-demo-note">Експертну оцінку вносить адміністратор від імені експерта. Вкажіть посаду або роль експерта, а не прізвище та ім’я: позначка видна в агрегатах.</p>
      : <p className="official-demo-note annex-anonymity" role="note"><strong>Анонімно.</strong> {ANONYMITY_NOTE}</p>}
    {expert && <details className="annex-details"><summary>Як відповіді перетворюються на рівні зрілості</summary><p>{LEVEL_RULE_NOTE}</p></details>}

    <fieldset className="annex-setup" disabled={locked}>
      <legend>{expert ? 'Крок 1. Цикл і експерт' : 'Крок 1. Цикл, категорія, анкета й код'}</legend>
      {cycles.status === 'loading' && <p role="status">Завантажуємо цикли оцінювання…</p>}
      {cycles.status === 'error' && <div className="v2-inline-error" role="alert"><p>{cycles.message}</p><button type="button" className="v2-button" onClick={() => setReload(value => value + 1)}>Спробувати ще раз</button></div>}
      {cycles.status === 'ready' && list.length === 0 && <p className="v2-empty" role="status">{expert ? 'Немає відкритих або закритих циклів для експертної оцінки.' : 'Зараз немає відкритих циклів. Коли опитування стане доступним, цикл з’явиться тут.'}</p>}
      <div className="annex-setup-grid">
        {cycles.status === 'ready' && list.length > 0 && <label htmlFor="official-cycle">Цикл оцінювання
          <select id="official-cycle" value={cycleId ?? ''} aria-invalid={!!described('cycle')} aria-describedby={described('cycle')}
            onChange={event => { setCycleId(Number(event.target.value) || null); setCategory(''); setSubmission({ status: 'idle' }) }}>
            <option value="">Оберіть цикл</option>
            {list.map(item => <option key={item.id} value={item.id}>{item.name}{expert ? ` · ${item.status === 'open' ? 'відкритий' : 'закритий'}` : ''}</option>)}
          </select>
          {fieldError('cycle')}
        </label>}
        {!expert && <label htmlFor="official-category">Категорія респондента
          <select id="official-category" value={category} aria-invalid={!!described('category')} aria-describedby={described('category')}
            onChange={event => setCategory(event.target.value)}>
            <option value="">Оберіть категорію</option>
            {categories.map(item => <option key={item} value={item}>{categoryLabel(item)}</option>)}
          </select>
          {fieldError('category')}
        </label>}
        {!expert && <label htmlFor="official-form">Анкета
          <select id="official-form" value={form} onChange={event => selectForm(Number(event.target.value) === 1 ? 1 : 2)}>
            <option value={2}>{FORM_LABELS[2]}</option>
            <option value={1}>{FORM_LABELS[1]}</option>
          </select>
          <small className="v2-form-hint">Анкета 2 (10 питань) — для особового складу; анкета 1 (12 питань) — для членів робочої групи.</small>
        </label>}
        {!expert && <label htmlFor="official-code">Одноразовий код доступу
          <input id="official-code" type="password" autoComplete="off" spellCheck={false} maxLength={ACCESS_CODE_MAX} value={code}
            aria-invalid={!!described('code')} aria-describedby={described('code') ?? 'official-code-hint'} onChange={event => setCode(event.target.value)} />
          <small id="official-code-hint" className="v2-form-hint">Код видає відповідальний за коди; він має відповідати обраній категорії й використовується лише раз.</small>
          {fieldError('code')}
        </label>}
        {expert && <label htmlFor="official-expert-label">Посада або роль експерта
          <input id="official-expert-label" autoComplete="off" maxLength={EXPERT_LABEL_MAX} value={label} placeholder="Наприклад, «Заступник начальника з навчальної роботи»"
            aria-invalid={!!described('label')} aria-describedby={described('label') ?? 'official-label-hint'} onChange={event => setLabel(event.target.value)} />
          <small id="official-label-hint" className="v2-form-hint">3–{EXPERT_LABEL_MAX} символів. Не вказуйте ПІБ, email чи телефон.</small>
          {fieldError('label')}
        </label>}
      </div>
      {fieldError(cycles.status === 'ready' && list.length > 0 ? '' : 'cycle')}
    </fieldset>

    <p>{template.audienceNote}</p>
    {template.contentNote && <p>{presentableText(template.contentNote)}</p>}
    {template.sourceUrl && <p><a href={template.sourceUrl} target="_blank" rel="noreferrer">Офіційне джерело (PDF)</a></p>}
    <div className="official-progress" role="status" aria-live="polite">
      <span>Заповнено {answered} з {questions.length}</span>
      <progress value={answered} max={questions.length} aria-label="Прогрес заповнення" />
    </div>
    <nav className="official-question-nav" aria-label="Питання за розділами">
      {sections.map(section => <div key={section} className="official-section">
        <h3>{section}</h3>
        <div className="official-question-buttons">{questions.map((item, position) => item.source.section === section &&
          <button key={item.id} type="button" aria-current={!review && position === index ? 'step' : undefined}
            aria-label={`Питання ${position + 1}${showErrors && errors[item.id] ? ', відповідь обов’язкова' : ''}`}
            className={showErrors && errors[item.id] ? 'is-missing' : ''} onClick={() => jump(position)}>{position + 1}{answers[item.id] ? ' ✓' : ''}</button>)}</div>
      </div>)}
    </nav>
    {review ? <div className="official-review" aria-label="Перегляд відповідей">
      <h3>Перегляд заповненої форми</h3>
      <p>{expert ? 'Перевірте відповіді й надішліть експертну оцінку.' : 'Перевірте відповіді. Після надсилання змінити їх неможливо, а код стане недійсним.'}</p>
      {questions.map((item, position) => <div key={item.id} className="official-review-item">
        <strong>{position + 1}. {item.text}</strong>
        <p>{item.options.find(option => option.id === answers[item.id])?.text}</p>
        <button type="button" className="v2-button" disabled={locked} onClick={() => jump(position)}>Змінити відповідь {position + 1}</button>
      </div>)}
      <div className="official-actions">
        <button type="button" className="v2-button" disabled={locked} onClick={() => jump(index)}>Повернутися до питань</button>
        <button type="button" className="v2-button v2-button-primary" disabled={locked} aria-busy={submission.status === 'pending'} onClick={() => void submit()}>
          {submission.status === 'pending' ? 'Надсилаємо…' : expert ? 'Зберегти експертну оцінку' : 'Надіслати анкету'}
        </button>
      </div>
    </div> : <div aria-live="polite">
      <p>Питання {index + 1} з {questions.length} · {question.source.section} · Додаток {question.source.appendix}, с. {question.source.page}, № {question.source.number}{question.wording === 'adapted' ? ' · адаптоване формулювання' : ''}{question.source_duplicate ? ' · дублікат у джерелі' : ''}</p>
      <fieldset disabled={locked} aria-invalid={showErrors && !!errors[question.id]} aria-describedby={showErrors && errors[question.id] ? 'official-question-error' : undefined}>
        <legend>{question.text} <span className="official-required">(обов’язково)</span></legend>
        {question.options.map(option => <label key={option.id} className="official-option"><input type="radio" name={question.id} value={option.id} checked={answers[question.id] === option.id}
          onChange={() => { setAnswers(previous => ({ ...previous, [question.id]: option.id })); setNotice('') }} />{option.text}</label>)}
      </fieldset>
      {showErrors && errors[question.id] && <p id="official-question-error" role="alert">{errors[question.id]}</p>}
      <div className="official-actions">
        <button type="button" className="v2-button" disabled={index === 0} onClick={() => jump(index - 1)}>Назад</button>
        <button type="button" className="v2-button" disabled={index === questions.length - 1} onClick={() => jump(index + 1)}>Далі</button>
        <button type="button" className="v2-button v2-button-primary" disabled={locked} onClick={check}>Перевірити відповіді</button>
      </div>
    </div>}
    {notice && <p role="status" aria-live="polite">{notice}</p>}
    {submission.status === 'error' && <p className="v2-inline-error" role="alert">{submission.message}</p>}
    {submission.status === 'done' && <div className="v2-success annex-success" role="status">
      <strong>{expert ? 'Збережено' : 'Надіслано'}</strong><span>{submission.message}</span>
      {expert && <button type="button" className="v2-button" onClick={startNextExpert}>Внести ще одну експертну оцінку</button>}
    </div>}
    {expert && <ExpertAssessmentList assessmentId={cycleId} refreshKey={savedExperts} />}
  </section>
}

/** Публічна сторінка анкети Додатка В (без входу): та сама форма в оболонці анонімного опитування. */
export function PublicOfficialAssessment() {
  return <div className="survey-app">
    <header className="survey-masthead">
      <a className="survey-brand" href="/survey" aria-label="Анонімне опитування — назад">
        <img className="survey-brand-mark survey-brand-logo" src="/sysmints-emblem.svg" alt="" width={43} height={43} />
        <span><strong>Integrity<br />Management</strong><small>Sys&amp;Mints · Building Integrity 2026</small></span>
      </a>
      <a className="survey-admin-link" href="/login">Вхід <span aria-hidden="true">↗</span></a>
    </header>
    <main className="survey-main annex-public"><OfficialAssessment mode="self" /></main>
  </div>
}
