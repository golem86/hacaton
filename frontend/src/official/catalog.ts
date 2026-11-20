import { fullTemplates } from './catalog-v2'

export type OfficialOption = { id: string; text: string }
export type OfficialQuestion = {
  id: string
  kind: 'single_choice'
  required: true
  wording?: 'adapted'
  text: string
  source: { appendix: 'В'; form?: 1 | 2; page: number; section: string; number: number }
  options: readonly OfficialOption[]
}
export type OfficialTemplate = {
  id: string
  version: string
  title: string
  audience: 'working_group' | 'ambiguous'
  audienceNote: string
  sourceUrl?: string
  contentNote?: string
  questions: readonly OfficialQuestion[]
}

// Verified against the published PDF, Appendix В, printed pages 53 and 60.
// Option IDs represent selections only. Their order does not define Integrity Index scores.
const legacyTemplates: readonly OfficialTemplate[] = [
  {
    id: 'appendix-v-form-1', version: '1.0.0', title: 'Анкета 1 · робоча група',
    audience: 'working_group', audienceNote: 'Заголовок на с. 53 прямо вказує членів робочої групи.',
    questions: [{
      id: 'av-f1-culture-1', kind: 'single_choice', required: true,
      text: 'Яку роль відіграє керівник (начальник) у розбудові доброчесності в у ВВНЗ (ВНП ЗВО):',
      source: { appendix: 'В', page: 53, section: 'Розділ 1. Культура.', number: 1 },
      options: [
        { id: 'av-f1-culture-1-a', text: 'Не приділяє уваги розбудові інфраструктури доброчесності (антикорупції) в ВВНЗ (ВНП ЗВО).' },
        { id: 'av-f1-culture-1-b', text: 'Наголошує на загальних нарадах і в комунікації з особовим складом про важливість використання доброчесних практик та застосування принципу “нульової толерантності до корупції” та розбудови інфраструктури доброчесності (антикорупції) в ВВНЗ (ВНП ЗВО), проте не долучається до цього процесу безпосередньо.' },
        { id: 'av-f1-culture-1-c', text: 'Активно долучається до промоції культури доброчесності та запобігання корупції, налагоджуючи співпрацю між антикорупційним уповноваженим в ВВНЗ (ВНП ЗВО) (далі – Уповноважений) та іншими структурними одиницями в ВВНЗ (ВНП ЗВО), та під час комунікації до особового складу.' },
        { id: 'av-f1-culture-1-d', text: 'Встановлює чіткі цілі та вимоги для Уповноваженого, які можна виміряти і оцінити як кількісно, так і якісно та регулярно проводить оцінку виконання поставлених цілей разом з Уповноваженим.' },
        { id: 'av-f1-culture-1-e', text: 'Активно промотує досягнення у сфері розбудови доброчесності (запобігання корупції) назовні для партнерів і заохочує впровадження нових ініціатив, проєктів, процедур у розбудові доброчесності (запобігання корупції).' },
      ],
    }],
  },
  {
    id: 'appendix-v-form-2', version: '1.0.0', title: 'Анкета 2 · призначення потребує уточнення',
    audience: 'ambiguous', audienceNote: 'Заголовок на с. 60 теж вказує членів робочої групи; Додаток Г згадує анкету 2 для особового складу. Потрібне рішення власника методики.',
    questions: [{
      id: 'av-f2-culture-1', kind: 'single_choice', required: true,
      text: 'Яку цінність відіграє доброчесність і корпоративна культура у ВВНЗ (ВНП ЗВО) щодо запобігання та виявлення корупції (оберіть один варіант, який найбільше підходить):',
      source: { appendix: 'В', page: 60, section: 'Розділ 1. Культура.', number: 1 },
      options: [
        { id: 'av-f2-culture-1-a', text: 'У ВВНЗ (ВНП ЗВО) не ведеться робота над формуванням корпоративної етики (немає кодексу етики чи аналогічного документа).' },
        { id: 'av-f2-culture-1-b', text: 'У ВВНЗ (ВНП ЗВО) затверджено базовий документ щодо етичної поведінки особового складу (“Положення”, “Загальні правила”, “Кодекс професійної етики” тощо), однак цей документ формальний і не повністю інтегрований до процесів ВВНЗ (ВНП ЗВО).' },
        { id: 'av-f2-culture-1-c', text: 'У ВВНЗ (ВНП ЗВО) затверджено документ доброчесної, етичної поведінки, з яким ознайомлений весь особовий склад (в тому числі, і новопризначені) та налагоджено процес вирішення порушень вимог етичного документа шляхом створення незалежної комісії з розгляду випадків їх порушення, який погоджений з особовим складом ВВНЗ (ВНП ЗВО).' },
        { id: 'av-f2-culture-1-d', text: 'У ВВНЗ (ВНП ЗВО) збирається інформація щодо порушень етики, вирішення конкретних випадків порушень і налагоджена форма зворотного зв’язку від особового складу щодо закріплених цінностей та застосування етичного документа організації на практиці.' },
        { id: 'av-f2-culture-1-e', text: 'Складові корпоративної культури постійно закріплюються у ВВНЗ (ВНП ЗВО) відповідно до зібраної всередині ВВНЗ (ВНП ЗВО)статистики та кращих світових і українських практик і доброчесність має вирішальне значення під час процедур добору працівників (військовослужбовців) як найважливіший критерій.' },
      ],
    }],
  },
]

const sourceUrl = 'https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf'

// 1.0.0 remains unchanged. New descriptive choices below are concise adaptations
// of the cited PDF passages, not verbatim official wording or numeric scores.
export const officialTemplates: readonly OfficialTemplate[] = [
  ...legacyTemplates,
  {
    ...legacyTemplates[0], version: '1.1.0', title: 'Анкета 1 · робоча група · розширений preview',
    sourceUrl, contentNote: 'Частковий каталог. Нове питання та варіанти стисло адаптовано за джерелом; звіряйте з PDF перед офіційним застосуванням.',
    questions: [legacyTemplates[0].questions[0], {
      id: 'av-f1-system-2', kind: 'single_choice', required: true,
      text: 'Який стан стратегії доброчесності закладу найточніше описує практику?',
      source: { appendix: 'В', page: 56, section: 'Розділ 2. Система.', number: 2 },
      options: [
        { id: 'av-f1-system-2-a', text: 'Внутрішніх політик немає; заходи переважно реактивні.' },
        { id: 'av-f1-system-2-b', text: 'Програму й основні внутрішні політики затверджено.' },
        { id: 'av-f1-system-2-c', text: 'Політики доведено до працівників і впроваджують.' },
        { id: 'av-f1-system-2-d', text: 'Політики регулярно вдосконалюють за зібраними даними.' },
        { id: 'av-f1-system-2-e', text: 'Політики оновлюють з огляду на дані, законодавство, практики й причини порушень.' },
      ],
    }],
  },
  {
    ...legacyTemplates[1], version: '1.1.0', title: 'Анкета 2 · аудиторія не визначена · розширений preview',
    sourceUrl, contentNote: 'Частковий каталог. Нове питання та варіанти стисло адаптовано за джерелом; аудиторію та формулювання має затвердити №5.',
    questions: [legacyTemplates[1].questions[0], {
      id: 'av-f2-system-2', kind: 'single_choice', required: true,
      text: 'Як Ви оцінюєте стан стратегії доброчесності закладу?',
      source: { appendix: 'В', page: 62, section: 'Розділ 2. Система.', number: 2 },
      options: [
        { id: 'av-f2-system-2-a', text: 'Внутрішніх політик немає; заходи переважно реактивні.' },
        { id: 'av-f2-system-2-b', text: 'Програму й основні внутрішні політики затверджено.' },
        { id: 'av-f2-system-2-c', text: 'Політики доведено до працівників і впроваджують.' },
        { id: 'av-f2-system-2-d', text: 'Політики регулярно вдосконалюють за зібраними даними.' },
        { id: 'av-f2-system-2-e', text: 'Політики оновлюють з огляду на дані, законодавство, практики й причини порушень.' },
      ],
    }],
  },
  ...fullTemplates,
]

for (const template of officialTemplates) {
  for (const question of template.questions) {
    Object.freeze(question.source)
    for (const option of question.options) Object.freeze(option)
    Object.freeze(question.options)
    Object.freeze(question)
  }
  Object.freeze(template.questions)
  Object.freeze(template)
}
Object.freeze(officialTemplates)

export function getOfficialTemplate(id: string, version: string): OfficialTemplate | undefined {
  return officialTemplates.find(template => template.id === id && template.version === version)
}
