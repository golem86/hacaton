import { useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { SubmissionOutcomeUnknownError, submitQuestionnaire } from '../api/assessments'
import type { Questionnaire, RespondentCategory } from '../types/questionnaireApi'
import { isValidAnswer, prepareSubmission } from './surveyAnswers'

interface SurveyFormProps {
  assessmentId: number
  questionnaire: Questionnaire
  units: string[]
}

const categories: { value: RespondentCategory; label: string }[] = [
  { value: 'mgmt', label: 'Керівництво' },
  { value: 'npp', label: 'Науково-педагогічні працівники' },
  { value: 'cadets', label: 'Курсанти' },
  { value: 'staff', label: 'Працівники' },
]

export default function SurveyForm({ assessmentId, questionnaire, units }: SurveyFormProps) {
  const formId = useId()
  const categoryRef = useRef<HTMLSelectElement>(null)
  const unitRef = useRef<HTMLSelectElement>(null)
  const tokenRef = useRef<HTMLInputElement>(null)
  const firstOptions = useRef<Record<number, HTMLInputElement | null>>({})
  const pendingRef = useRef(false)
  const [category, setCategory] = useState<RespondentCategory | ''>('')
  const [unit, setUnit] = useState('')
  const [token, setToken] = useState('')
  const [selected, setSelected] = useState<Record<number, number>>({})
  const [attempted, setAttempted] = useState(false)
  const [pending, setPending] = useState(false)
  const [outcome, setOutcome] = useState<'editing' | 'accepted' | 'unknown'>('editing')
  const [submissionError, setSubmissionError] = useState('')
  const questions = questionnaire.flatMap(component => component.questions)
  const invalidQuestion = questions.find(question => !isValidAnswer(question, selected[question.id]))
  const locked = outcome !== 'editing'

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pendingRef.current || locked) return
    setAttempted(true)
    setSubmissionError('')
    const body = prepareSubmission(questionnaire, selected, category, unit, token, units)
    if (!category) { categoryRef.current?.focus(); return }
    if (!units.includes(unit)) { unitRef.current?.focus(); return }
    if (!token.trim()) { tokenRef.current?.focus(); return }
    if (!body) {
      if (invalidQuestion) firstOptions.current[invalidQuestion.id]?.focus()
      else setSubmissionError('Не вдалося перевірити перелік питань. Оновіть анкету.')
      return
    }

    pendingRef.current = true
    setPending(true)
    try {
      await submitQuestionnaire(assessmentId, body)
      setToken('')
      setOutcome('accepted')
    } catch (error) {
      if (error instanceof SubmissionOutcomeUnknownError) {
        setToken('')
        setOutcome('unknown')
        setSubmissionError(error.message)
      } else {
        // Only the API client's safe messages are shown; never display a raw response.
        setSubmissionError(error instanceof Error && !error.message.includes(token)
          ? error.message
          : 'Не вдалося надіслати анкету. Зверніться до відповідального за оцінювання.')
      }
    } finally {
      pendingRef.current = false
      setPending(false)
    }
  }

  return (
    <form className="survey-api-form" onSubmit={handleSubmit} noValidate>
      <p>Оберіть категорію й підрозділ, введіть одноразовий код та дайте одну відповідь на кожне питання.</p>
      <div className="survey-api-fields">
        <div>
          <label htmlFor={`${formId}-category`}>Категорія респондента</label>
          <select ref={categoryRef} id={`${formId}-category`} value={category} disabled={pending || locked}
            required aria-invalid={attempted && !category}
            onChange={event => setCategory(event.target.value as RespondentCategory | '')}>
            <option value="">Оберіть категорію</option>
            {categories.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          {attempted && !category && <p className="survey-api-error" role="alert">Оберіть категорію.</p>}
        </div>
        <div>
          <label htmlFor={`${formId}-unit`}>Підрозділ</label>
          <select ref={unitRef} id={`${formId}-unit`} value={unit} disabled={pending || locked}
            required aria-invalid={attempted && !units.includes(unit)}
            onChange={event => setUnit(event.target.value)}>
            <option value="">Оберіть підрозділ</option>
            {units.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
          {attempted && !units.includes(unit) && <p className="survey-api-error" role="alert">Оберіть підрозділ зі списку.</p>}
        </div>
        <div>
          <label htmlFor={`${formId}-token`}>Одноразовий код доступу</label>
          <input ref={tokenRef} id={`${formId}-token`} type="password" autoComplete="off" value={token}
            disabled={pending || locked} required aria-invalid={attempted && !token.trim()}
            onChange={event => setToken(event.target.value)} />
          {attempted && !token.trim() && !locked && <p className="survey-api-error" role="alert">Введіть код доступу.</p>}
        </div>
      </div>

      {questionnaire.map(component => (
        <section className="survey-api-component" key={component.code} aria-labelledby={`${formId}-${component.code}`}>
          <h3 id={`${formId}-${component.code}`}>{component.name}</h3>
          {component.questions.map(question => {
            const invalid = attempted && !isValidAnswer(question, selected[question.id])
            const values = Array.from({ length: Math.max(0, question.scale[1] - question.scale[0] + 1) }, (_, index) => question.scale[0] + index)
            return (
              <fieldset key={question.id} className="survey-api-question" aria-invalid={invalid}>
                <legend>{question.text}</legend>
                <div className="survey-api-options">
                  {values.map((value, index) => (
                    <label key={value}>
                      <input ref={index === 0 ? element => { firstOptions.current[question.id] = element } : undefined}
                        type="radio" name={`${formId}-question-${question.id}`} value={value}
                        checked={selected[question.id] === value} disabled={pending || locked} required
                        onChange={() => setSelected(previous => ({ ...previous, [question.id]: value }))} />
                      <span>{value}</span>
                    </label>
                  ))}
                </div>
                {invalid && <p className="survey-api-error" role="alert">Оберіть одне число в межах шкали.</p>}
              </fieldset>
            )
          })}
        </section>
      ))}
      <button className="survey-api-button" type="submit" disabled={pending || locked}>
        {pending ? 'Надсилання…' : 'Надіслати анкету'}
      </button>
      {outcome === 'accepted' && <p className="survey-api-success" role="status">Анкету прийнято. Повторне надсилання заблоковано.</p>}
      {submissionError && <p className="survey-api-error" role="alert">{submissionError}</p>}
    </form>
  )
}
