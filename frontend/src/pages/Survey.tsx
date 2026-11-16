import { useEffect, useState } from 'react'
import SurveyForm from '../components/SurveyForm'
import { getQuestionnaire, getUnits } from '../api/assessments'
import type { Questionnaire } from '../types/questionnaireApi'
import './Survey.css'

interface SurveyProps {
  // The current main.tsx renders Survey without an ID. Integration supplies a real one.
  assessmentId?: number
}

type LoadState =
  | { status: 'loading'; assessmentId?: number }
  | { status: 'error'; assessmentId: number; message: string }
  | { status: 'ready'; assessmentId: number; questionnaire: Questionnaire; units: string[] }

export default function Survey({ assessmentId }: SurveyProps) {
  const [load, setLoad] = useState<LoadState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const validId = Number.isInteger(assessmentId) && (assessmentId ?? 0) > 0
  const currentLoad = load.assessmentId === assessmentId

  useEffect(() => {
    if (!validId || assessmentId === undefined) return
    const controller = new AbortController()
    setLoad({ status: 'loading', assessmentId })
    Promise.all([
      getQuestionnaire(assessmentId, controller.signal),
      getUnits(controller.signal),
    ]).then(([questionnaire, units]) => {
      if (!controller.signal.aborted) setLoad({ status: 'ready', assessmentId, questionnaire, units })
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) {
        setLoad({ status: 'error', assessmentId, message: error instanceof Error ? error.message : 'Не вдалося завантажити анкету.' })
      }
    })
    return () => controller.abort()
  }, [assessmentId, attempt, validId])

  return (
    <section className="module-panel survey-api" aria-labelledby="survey-title">
      <h2 id="survey-title">Цифрове анкетування</h2>
      {!validId && <p role="status">Оберіть цикл оцінювання, щоб відкрити анкету. Для цього модулю потрібен ID циклу від командної навігації.</p>}
      {validId && (!currentLoad || load.status === 'loading') && <p role="status">Завантаження анкети й підрозділів…</p>}
      {validId && currentLoad && load.status === 'error' && (
        <div>
          <p role="alert">{load.message}</p>
          <button className="survey-api-button" type="button" onClick={() => setAttempt(value => value + 1)}>Спробувати ще раз</button>
        </div>
      )}
      {validId && currentLoad && load.status === 'ready' && (
        load.questionnaire.flatMap(component => component.questions).length === 0 || load.units.length === 0
          ? <p role="status">Анкету поки неможливо заповнити: немає питань або підрозділів. Зверніться до відповідального за оцінювання.</p>
          : <SurveyForm
              key={`${assessmentId}-${attempt}`}
              assessmentId={assessmentId!}
              questionnaire={load.questionnaire}
              units={load.units}
            />
      )}
    </section>
  )
}
