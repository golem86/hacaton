import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let server
let logic
let SurveyForm
let Survey
const questionnaire = [
  { code: 'A', name: 'Компонент А', weight: 1, questions: [
    { id: 7, text: 'Перше питання', scale: [1, 3] },
    { id: 8, text: 'Друге питання', scale: [0, 2] },
  ] },
]

before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  logic = await server.ssrLoadModule('/src/components/surveyAnswers.ts')
  SurveyForm = (await server.ssrLoadModule('/src/components/SurveyForm.tsx')).default
  Survey = (await server.ssrLoadModule('/src/pages/Survey.tsx')).default
})
after(async () => { await server?.close() })

test('answers use backend question IDs and numeric values', () => {
  assert.deepEqual(logic.collectAnswers(questionnaire, { 7: 2, 8: 0 }), [
    { question_id: 7, value: 2 }, { question_id: 8, value: 0 },
  ])
})

test('missing, noninteger, out-of-scale and duplicate answers cannot be submitted', () => {
  assert.equal(logic.collectAnswers(questionnaire, { 7: 2 }), null)
  assert.equal(logic.collectAnswers(questionnaire, { 7: 4, 8: 1 }), null)
  assert.equal(logic.collectAnswers(questionnaire, { 7: 1.5, 8: 1 }), null)
  assert.equal(logic.collectAnswers([{ ...questionnaire[0], questions: [questionnaire[0].questions[0], questionnaire[0].questions[0]] }], { 7: 2 }), null)
  assert.equal(logic.collectAnswers([{ ...questionnaire[0], questions: [] }], {}), null)
})

test('submission requires category, API unit, code and every answer', () => {
  const units = ['Факультет 1']
  const answers = { 7: 2, 8: 0 }
  assert.equal(logic.prepareSubmission(questionnaire, answers, '', units[0], 'code', units), null)
  assert.equal(logic.prepareSubmission(questionnaire, answers, 'mgmt', 'Інший', 'code', units), null)
  assert.equal(logic.prepareSubmission(questionnaire, answers, 'mgmt', units[0], ' ', units), null)
  assert.equal(logic.prepareSubmission(questionnaire, { 7: 2 }, 'mgmt', units[0], 'code', units), null)
  assert.deepEqual(logic.prepareSubmission(questionnaire, answers, 'mgmt', units[0], 'code', units), {
    token: 'code', respondent_category: 'mgmt', unit: units[0],
    answers: [{ question_id: 7, value: 2 }, { question_id: 8, value: 0 }],
  })
})

test('form renders all four backend categories, API units and numeric radio options', () => {
  const html = renderToStaticMarkup(React.createElement(SurveyForm, {
    assessmentId: 3, questionnaire, units: ['Факультет 1'],
  }))
  for (const category of ['mgmt', 'npp', 'cadets', 'staff']) {
    assert.match(html, new RegExp(`value="${category}"`))
  }
  assert.match(html, /Факультет 1/)
  assert.match(html, /Перше питання/)
  assert.match(html, /Друге питання/)
  assert.equal((html.match(/type="radio"/g) ?? []).length, 6)
  assert.match(html, /type="password"/)
  assert.equal(html.includes('Демонстраційний фрагмент'), false)
})

test('without an assessment ID Survey asks for one and does not invent it', () => {
  const html = renderToStaticMarkup(React.createElement(Survey))
  assert.match(html, /потрібен ID циклу/)
  assert.equal(html.includes('Надіслати анкету'), false)
})
