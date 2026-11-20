# Офіційні анкети та експертний інтерфейс — WIP звіт №1

## Статус і джерело

Гілка `feature/assessment-questionnaire-v2`, Draft PR #25. Release PR #24 і його SQLite schema 3, CI, API та `demo-v1` не змінювалися. Джерело: [Рекомендації НУОУ, Додаток В, друковані с. 53–66](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf). Звірка PDF виявила **12 питань у Анкеті 1** (розділи: Культура 5, Система 2, Підзвітність 4, Рівень зрілості 1) та **10 питань у Анкеті 2** (відповідно 3, 2, 4, 1). Опубліковані питання — описовий вибір одного варіанта. Порядок опцій не є scoring.

У каталозі перенесено **2 з 12** питань Анкети 1 і **2 з 10** Анкети 2. Це частковий preview, не повні анкети.

| Шаблон | Питання і сторінки | Розділи | Статус тексту |
| --- | --- | --- | --- |
| `appendix-v-form-1@1.0.0` | №1, [с. 53](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf#page=53) | Культура | Первісний перевірений текст і 5 опцій, незмінний |
| `appendix-v-form-2@1.0.0` | №1, [с. 60](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf#page=60) | Культура | Первісний перевірений текст і 5 опцій, незмінний |
| `appendix-v-form-1@1.1.0` | №1, с. 53; №2, [с. 56](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf#page=56) | Культура, Система | №1 успадковано без змін; №2 і 5 опцій стисло адаптовано за PDF |
| `appendix-v-form-2@1.1.0` | №1, с. 60; №2, [с. 62](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf#page=62) | Культура, Система | №1 успадковано без змін; №2 і 5 опцій стисло адаптовано за PDF |

Адаптований текст `1.1.0` **не є автентичним дослівним переносом** і позначений у UI. Перед офіційним застосуванням потрібні повний перенос і редакційне затвердження №5. Сталі `question_id` і `option_id` збережені між версіями для незмінених питань. Нові ID мають посилання на додаток, сторінку, розділ і номер. Джерело PDF відкрите з інтерфейсу.

Аудиторія Анкети 1 у заголовку с. 53 — члени робочої групи. Заголовок Анкети 2 на с. 60 також називає робочу групу, але [Додаток Г, с. 67](https://nuou.org.ua/assets/documents/recommendations_transform_dobrochesnist.pdf#page=67) відносить її до особового складу. Категорію Анкети 2 автоматично не призначено.

## Реалізовано

- `/app/official`: вибір шаблону та версії, групування питань за розділами, навігація вперед/назад і прямий перехід, прогрес, збереження вибору в пам'яті під час навігації, перевірка відсутніх і чужих опцій, перегляд заповненої форми. Перемикання шаблону очищує локальні відповіді та повертає до першого питання.
- `/admin/expert`: окремий WIP preview для адміністративної сесії із вибором шаблону, локальними відповідями, перевіркою й переглядом. Доступ адміністратора до preview **не надає** серверної ролі експерта. Звичайний користувач не може відкрити `/admin/expert` після серверної перевірки сесії.
- Інтерфейс містить видимі позначки WIP, джерело, версію, labels, радіогрупи, стан помилки з `role=alert`, оголошення прогресу/стану, клавіатурну навігацію та мобільне компонування. Кнопки подання немає. Відповіді не записуються в localStorage або журнали браузера.

## Незавершені функції й рішення №5

Реальне подання та збереження відповідей **BLOCKED**. Спільні DDL і backend API для описових відповідей, окрема backend роль і сховище експертів, методика Integrity Index, остаточна аудиторія Анкети 2 не затверджені. Відповіді не змішуються з анонімним numeric API. Для наступної реалізації потрібні рішення №5 щодо точного контракту циклу/версії/`question_id`, серверної авторизації експертів і CSRF, збереження та читання окремих записів, анонімності й suppression, повного автентичного тексту, аудиторії Анкети 2 та методики scoring. Технічні варіанти наведено у `OFFICIAL_QUESTIONNAIRE_CONTRACT_PROPOSAL.md` поза репозиторієм.

## Перевірки цієї ітерації

| Перевірка | Результат |
| --- | --- |
| Frontend `npm test` | PASS: 42 тести |
| TypeScript і production build `npm run build` | PASS |
| Backend `pytest -q` | PASS: 361 тести, 1 зовнішнє deprecation warning |
| Browser E2E `npm run test:e2e` | PASS: 11 сценаріїв на headless Chromium із тимчасовими синтетичними БД |
| `git diff --check` | PASS |
| Серверне збереження official/expert | BLOCKED: контракт відсутній |

## Змінені файли

`frontend/src/official/catalog.ts`, `frontend/src/official/OfficialAssessment.tsx`, `frontend/src/v2/v2.css`, `frontend/tests/official.test.mjs`, `frontend/e2e/official-assessment.spec.ts`, `QUESTIONNAIRE_EXPERT_IMPLEMENTATION_REPORT.md`. Backend, release-гілка, scoring, Dashboard, Analytics, Docker і schema 3 не змінені.

Commit реалізації: `0504b71107684eec1c04a8dbe7d35241e612bc81`. Після push перевірено [Draft PR #25](https://github.com/golem86/hacaton/pull/25): 8 WIP-файлів, без backend, CI, SQLite та Assessment Manager. Head [Release PR #24](https://github.com/golem86/hacaton/pull/24) залишився `db70706f14cbcaba0d137151572aa996b106cd18`. Статус: **PARTIAL / DO NOT MERGE**.
