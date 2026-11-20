# Попередній контракт API

Це проєктний контракт Integrity Management Dashboard. Він описує точки інтеграції для команди, а не готові маршрути. Стан реалізації позначено в таблиці. Перед реалізацією власники модулів погоджують точні поля, ролі, помилки й версію методики.

## Спільні правила

- Локальна адреса backend — `http://127.0.0.1:8000`. Маршрути продукту мають префікс `/api`.
- Дані передаються як JSON у UTF-8. Ідентифікатори в прикладах нижче умовні.
- API повертає лише дозволені ролі дані. Агрегати приховуються, коли кількість відповідей менша за налаштований мінімум. Сирі анонімні відповіді не входять у відповіді Dashboard, аналітики та експорту.
- Демонстраційні запити й відповіді використовують синтетичні дані. Формула, ваги, правила пропусків і поріг групи мають бути затверджені й версіоновані до запуску відповідних маршрутів.
- Сторінки списків, порядок сортування та механізм авторизації ще потребують погодження.
- **Роль у прототипі передається заголовком `X-Role` — лише для демо.** Це не автентифікація: сервер довіряє заголовку. У реальному розгортанні роль надходить із відомчої системи входу, а заголовок вимикається. Матриця доступу нижче від цього не змінюється.

## Маршрути та власність модулів

| Модуль | Метод і попередній шлях | Основні структури | Стан |
| --- | --- | --- | --- |
| Технічна перевірка | `GET /api/health` | `Health` | Реалізовано |
| Assessment Manager | `GET /api/assessments`; `GET /api/assessments/{assessment_id}`; `POST /api/assessments/{assessment_id}/tokens`; `GET /api/assessments/{assessment_id}/participation` | `Assessment`, `TokenBatch`, `Participation` | Реалізовано (PR #4) |
| Assessment Manager | `POST /api/assessments/{assessment_id}/close`; `GET /api/units` | `Assessment`, довідник підрозділів | Реалізовано (backend-results) |
| Assessment Manager | `POST /api/assessments` | `AssessmentCreate` | Заплановано |
| Агреговані результати (вхід для Index Engine і Dashboard) | `GET /api/assessments/{assessment_id}/results` | `AssessmentResults` | Реалізовано (backend-results) |
| Digital Questionnaire | `GET /api/assessments/{assessment_id}/questionnaires`; `POST /api/assessments/{assessment_id}/submissions` | `Questionnaire`, `AnonymousSubmission` | Реалізовано (PR #4) |
| Integrity Index Engine | `GET /api/assessments/{assessment_id}/index`; `GET /api/index-methodologies/{version}` | `IndexResult`, `IndexMethodology` | Реалізовано у пропозиції №4, synthetic opt-in |
| Executive Dashboard | `GET /api/assessments/{assessment_id}/dashboard` | `DashboardSummary` | Заплановано |
| Comparative Analytics | `GET /api/analytics/comparisons` | `Comparison` | Реалізовано у пропозиції №4, synthetic opt-in |
| Recommendations Engine | `GET /api/assessments/{assessment_id}/recommendations` | `RecommendationProposal` | Реалізовано у пропозиції №4, GET лише пропонує |
| Recommendations Tracker | `GET /api/assessments/{assessment_id}/tracker`; `POST /api/assessments/{assessment_id}/tracker/decisions`; `POST /api/tracker/{action_id}/transition` | `TrackedRecommendation` | Реалізовано (розділ «Recommendations Tracker» нижче) |
| Audit Trail | `GET /api/audit-events` | `AuditEvent` | Реалізовано (backend-audit) |
| Reporting Module V2 | `GET /v2/admin/reports/{id}`; `GET /v2/admin/reports/{id}/export?format=pdf\|xlsx`; `GET /v2/admin/reports/{id}/maturity-export?format=pdf\|xlsx` | Дозволені агрегати, PDF або XLSX; звіт зрілості за Додатком В | Локальна реалізація V2, [контракт](V2_INTEGRATION_CONTRACT.md#33-analytics-формати-без-змін) |

Шляхи зі статусом «Заплановано» є пропозицією для обговорення. Жоден з них зараз не повинен вважатися доступним API. Зовнішні інтеграції та формат експорту команда визначить окремо.

## Структури даних для узгодження

| Структура | Потрібний зміст | Відкрите рішення |
| --- | --- | --- |
| `Health` | `status: "ok"` | Реалізовано як `200 {"status":"ok"}` |
| `Assessment` | Ідентифікатор, організаційний контекст, цикл, стан, період, мінімальний розмір групи, категорії учасників | Довідники й допустимі стани |
| `Questionnaire` | Версія, категорія респондента, питання, типи відповідей, шкали, обов’язковість | Джерело анкет і правила версіонування |
| `AnonymousSubmission` | Цикл, категорія, відповіді без персональних ідентифікаторів | Захист від повторного подання без деанонімізації |
| `ObjectiveIndicator` | Показник, період, одиниця виміру, джерело підтвердження | Правила верифікації |
| `IndexMethodology` | Версія, критерії, ваги, агрегація, правила пропусків і рівні зрілості | Формула та ваги команди |
| `IndexResult` | Версія методики, підсумок, компоненти, внесок індикаторів, кількість відповідей або статус приховування | Формат пояснення і точність чисел |
| `DashboardSummary`, `Comparison` | Дозволені агрегати за компонентами, періодами й джерелами | Мінімальний розмір групи для кожного зрізу |
| `RecommendationProposal` | Підстава, пріоритет, пояснення, пов’язаний показник | Правила генерації та затвердження |
| `TrackedRecommendation` | Прийняте рішення, відповідальна роль чи особа, строк, статус, перевірка наступним циклом | Рольовий доступ і допустимі переходи станів |
| `AuditEvent`, `Report` | Дія, час, роль, об’єкт; тип звіту, цикл і формат | Безпечний склад журналу та експорту |

Для кожного запланованого маршруту перед реалізацією слід додати приклади запиту, успішної відповіді, помилки й матрицю доступу. Збереження анонімності перевіряється на рівні зберігання, агрегування та експорту.

## Документація API (Swagger) — лише адміністратор V2

| Маршрут | Без входу | Сесія без 2FA | Сесія `user` | Сесія `admin` (2FA) |
| --- | --- | --- | --- | --- |
| `GET /docs` (Swagger UI) | `401` | `401` | `403` | `200`, HTML |
| `GET /openapi.json` (схема) | `401` | `401` | `403` | `200`, JSON |
| `GET /docs/swagger-ui/swagger-ui-bundle.js`, `…/swagger-ui.css` | `401` | `401` | `403` | `200`, файл |
| `GET /docs/swagger-ui/<інший файл>` | `401` | `401` | `403` | `404` |
| `GET /redoc`, `GET /docs/oauth2-redirect` | `404` | `404` | `404` | `404` |

- Доступ визначає **лише** серверна сесія V2 (`require_v2_role("admin")`). Демонстраційний `X-Role` не відкриває документацію навіть у development.
- Відповіді мають `Cache-Control: no-store`.
- Swagger UI роздає сам backend, без CDN і без зовнішніх запитів під час роботи. Файли `swagger-ui-bundle.js` і `swagger-ui.css` взято без змін з офіційного npm-пакета `swagger-ui-dist@5.17.14` (Apache-2.0, `LICENSE` і `NOTICE` поруч). Вони лежать у `backend/app/static/swagger-ui/`, в `.gitattributes` позначені як `binary`, а їхні SHA-256 звіряють тести. Роздаються лише два файли з фіксованого переліку.
- **Execute** у Swagger надсилає звичайні запити з cookie сесії. Кожен захищений endpoint сам перевіряє сесію і роль; інтерфейс нічого не дозволяє.
- Заголовок `X-CSRF-Token` (схема безпеки `csrfToken`, кнопка **Authorize**) у схемі вказано **лише** для операцій, де його справді перевіряє backend. Вимогу визначено з залежностей маршруту, а не з HTTP-методу; поле `x-csrf` операції показує, який саме токен потрібен:

  | Операції | `x-csrf` | Токен з `GET /v2/auth/csrf` |
  | --- | --- | --- |
  | `POST /api/assessments/{id}/submissions` (анонімна анкета) | — | не потрібен (лише одноразовий код) |
  | `POST /v2/auth/register`, `/login`, `/password-reset/request`, `/password-reset/confirm` | `preauth` | pre-auth токен (до входу) або токен сесії |
  | `POST /v2/auth/2fa/verify`, `/2fa/resend`, `/logout` | `session` | токен сесії, зокрема ще без 2FA |
  | `POST /api/assessments/{id}/tokens`, `/close`; `POST`/`PATCH /v2/user/attempts…` | `session` | токен сесії після 2FA |

  Без потрібного токена backend відповідає `403`. Операції `GET` CSRF не потребують.
- Тести: `backend/tests/test_v2_api_docs.py`. Серед іншого:
  - доступ до документації за ролями;
  - **кожна** захищена операція зі схеми без сесії (і з підробленим `X-Role`) отримує `401`/`403`;
  - сесія `user` не має доступу до `/api/*` і `/v2/admin/*`, сесія `admin` — до `/v2/user/*`;
  - запит на зміну без CSRF → `403`, з CSRF → успіх;
  - CSRF у схемі збігається з фактичними правилами (перелік вище). Кожна позначена операція без токена справді отримує `403`, а анонімна анкета CSRF не потребує.

## Реалізовані маршрути (PR #4)

У базі цикл оцінювання зберігається в таблиці `cycles`; в API він називається `assessment`.

### Матриця доступу

| Маршрут | admin | respondent | expert | data_officer | manager | anticorruption | auditor |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `GET /api/assessments`, `GET /api/assessments/{id}`, `GET /api/assessments/{id}/questionnaires`, `GET /api/units` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `POST /api/assessments/{id}/submissions` | | ✓ | | | | | |
| `POST /api/assessments/{id}/tokens` | ✓ | | | ✓ | | | |
| `POST /api/assessments/{id}/close` | ✓ | | | | | | |
| `GET /api/assessments/{id}/participation`, `GET /api/assessments/{id}/results` | ✓ | | | | ✓ | ✓ | ✓ |
| `GET /api/audit-events` | ✓ | | | | | | ✓ |

Помилки доступу: `401` — роль не вказана або невідома; `403` — у ролі немає прав.

### `GET /api/assessments`

```json
[{"id": 3, "name": "2026-II", "start_date": "2026-11-01", "status": "open", "min_group_size": 5}]
```

`GET /api/assessments/{id}` повертає один такий об'єкт або `404`.

### `GET /api/assessments/{id}/questionnaires`

Компоненти з вагами (сума ваг = 1) і питаннями анкети персоналу.

```json
[{"code": "C1", "name": "Лідерство й тон керівництва", "weight": 0.15,
  "questions": [{"id": 1, "text": "…", "scale": [1, 5]}]}]
```

### `POST /api/assessments/{id}/submissions`

Запит (`respondent_category`: `mgmt`, `npp`, `cadets` або `staff`; рівно одна відповідь на кожне питання анкети):

```json
{"token": "9f2c…", "respondent_category": "cadets", "unit": "Факультет 1",
 "answers": [{"question_id": 1, "value": 4}]}
```

Для налаштованого циклу (створеного через Assessment Manager, з `cycle_configs`) поле `questionnaire_version` обов'язкове й має збігатися з версією анкети циклу (зараз лише `demo-v1`); категорія має бути серед дозволених для циклу:

```json
{"token": "9f2c…", "questionnaire_version": "demo-v1", "respondent_category": "cadets",
 "unit": "Факультет 1", "answers": [{"question_id": 1, "value": 4}]}
```

Додаткові помилки налаштованого циклу: `403` — категорія недоступна для цього циклу; `409` — версія анкети не відповідає циклу, строк ще не розпочався або вже завершився.

Відповідь `201 {"status": "accepted"}` — без номера анкети, щоб її не можна було зіставити з кодом. Помилки: `403` — недійсний, чужий або вже використаний код (одне повідомлення для всіх випадків); `409` — оцінювання закрите; `422` — неповна анкета, значення поза шкалою, невідома категорія або підрозділ не з довідника (код при цьому не витрачається).

`unit` — лише назва з `GET /api/units` (`["Кафедра загальних дисциплін", "Факультет 1", "Факультет 2"]`). Довільний текст база відхиляє: так у неї не потрапляють прізвища чи інші ознаки особи.

### Контракт шкали і формату анкети (backend ↔ frontend)

Спільні правила для `GET …/questionnaires` і `POST …/submissions` (`backend/app/questionnaire_contract.py`):

| Правило | Значення |
| --- | --- |
| `scale` | масив рівно з двох безпечних цілих `[min, max]` (`Number.isSafeInteger`, не bool), `min <= max` |
| Кількість значень `max − min + 1` | від **1** до **10** включно |
| Стандартна шкала | `[1, 5]` |
| Шкала з 1 значенням | допустима, але не впливає на бал компонента (формула `(value − min) / (max − min)` для неї не визначена) |
| `question.id` | безпечне ціле ≥ 1, **унікальне між усіма компонентами** анкети |

Де перевіряється:

- **БД:** модель `Question` не дає записати некоректну шкалу (seed і майбутні адреси створення анкет).
- **`GET …/questionnaires`:** відповідь перевіряється перед видачею. Якщо дані в БД порушують контракт, повертається `500` (помилка налаштування сервера), і фронтенд некоректної анкети не отримує.
- **`POST …/submissions` → `422`**, і код доступу при цьому не витрачається:
  - `question_id` або `value` не строге ціле (`"4"`, `4.0`, `4.5`, `true`), поза безпечним цілим, `question_id < 1`;
  - повторний `question_id` у `answers`, порожній список або не список;
  - не на всі питання анкети є відповідь, або значення поза `scale` питання.

Код погашається атомарно разом зі збереженням анкети. Зв'язку код ↔ анкета в базі немає.

### `POST /api/assessments/{id}/tokens?count=10`

`201 {"tokens": ["…", "…"]}`; `409` — оцінювання закрите. Коди роздаються учасникам анонімно.

### `POST /api/assessments/{id}/close`

Лише `admin`. Завершує оцінювання: `200` з оновленим `Assessment` (`"status": "closed"`); `409` — вже закрите. Після закриття анкети й нові коди не приймаються, а `results` і розбивка `participation` стають доступними.

### `GET /api/assessments/{id}/results`

Вхідні дані для Integrity Index і Dashboard. Доступно **лише для закритого** оцінювання (`409` для відкритого). Бал = середнє відповідей у шкалі 0–100: `(відповідь − min) / (max − min) × 100`.

```json
{"assessment": {"id": 1, "name": "2025-II", "status": "closed"},
 "min_group_size": 5, "responses_total": 268,
 "categories": [{"category": "cadets", "responses": 210, "hidden": false},
                {"category": "mgmt", "responses": null, "hidden": true},
                {"category": "npp", "responses": 48, "hidden": false},
                {"category": "staff", "responses": null, "hidden": true}],
 "components": [{"code": "C1", "name": "Лідерство й тон керівництва", "weight": 0.15, "score": 51.3,
                 "by_category": [{"category": "cadets", "score": 47.0, "hidden": false},
                                 {"category": "mgmt", "score": null, "hidden": true}],
                 "objective_indicators": [{"name": "Виконання заходів, закріплених за керівництвом, %",
                                           "value": 52.0, "confirmed": true}]}]}
```

Числа в прикладі умовні. Приховування категорій те саме, що в `participation`: первинне (< k) і вторинне (сума прихованих ≥ k), однакове для всіх компонентів. Окремі анкети й відповіді не повертаються. Розрахунок Integrity Index (ваги × бали, рівні зрілості) виконує Index Engine поверх цих даних.

### `GET /api/audit-events?assessment_id=&limit=100`

Лише `admin` і `auditor`. Записи адміністративних дій, найновіші першими; `limit` від 1 до 500 (інакше `422`); `assessment_id` необов'язковий фільтр.

```json
[{"id": 2, "created_at": "2026-11-17T08:15:02.123456Z", "actor_role": "admin",
  "action": "assessment.close", "assessment_id": 3, "details": {}},
 {"id": 1, "created_at": "2026-11-17T08:10:40.654321Z", "actor_role": "admin",
  "action": "tokens.issue", "assessment_id": 3, "details": {"count": 20}}]
```

Журналюються: `tokens.issue` (лише кількість, без кодів) і `assessment.close`. Запис зберігається в одній транзакції з самою дією. Невдалі спроби (`401`, `403`, `409`, `422`) не журналюються. **Не журналюються ніколи:** коди доступу, відповіді, категорія й підрозділ респондента, подання анкет (час подання міг би розкрити автора). Див. `docs/anonymity.md`.

### `GET /api/assessments/{id}/participation?by_unit=false`

```json
{"status": "closed", "tokens_issued": 288, "responses_total": 268,
 "groups": [{"category": "cadets", "responses": 210, "hidden": false},
            {"category": "mgmt", "responses": null, "hidden": true},
            {"category": "npp", "responses": 48, "hidden": false},
            {"category": "staff", "responses": null, "hidden": true}]}
```

Політика агрегації:

- Поки оцінювання **відкрите**, `groups = null`: показується лише загальна кількість. Інакше порівняння двох запитів «до/після» розкрило б категорію щойно поданої анкети.
- Первинне приховування: група з кількістю менше `min_group_size` (k).
- Вторинне приховування: у межах кожного відомого підсумку сума прихованих груп має бути 0 або не менше k. Інакше додатково приховується найменша видима група. Тому «підсумок − сума видимих» не розкриває розмір малої групи (у прикладі `mgmt` приховано саме з цієї причини).
- `by_unit=true` повертає клітинки «категорія × підрозділ» з тим самим правилом відносно підсумку категорії. Категорія, прихована в загальній розбивці, приховується і в усіх своїх клітинках.
- `responses_total = null`, якщо загальна кількість менша за k. Кількість використаних кодів не повертається, бо вона дорівнює підсумку.

## Аналітика №4: інтеграційна пропозиція поверх `/results`

**Версія `team-results-demo-0.1`, авторська, неофіційна, `approval_status=proposed`.**
Окрема методика для семи вигаданих компонентів чинного seed, не заміна `demo-0.2` з трьома компонентами та питаннями додатка В. До командного прийняття показувати статус і обмеження поруч із результатом.

Оператор явно вмикає її змінною середовища `INTEGRITY_ANALYTICS_DEMO=1` **лише для синтетичної БД**. За замовчуванням обчислення вимкнені. `.env.example` сам не завантажується Python-застосунком. Оператор відповідає за походження бази: прапорець не перевіряє синтетичність кожного запису.

`INTEGRITY_ANALYTICS_DEMO=1` — лише дозвіл на запуск обчислень: він **не перевіряє походження даних**. Запускайте модуль тільки з **окремим файлом синтетичної SQLite-БД**, заданим через `INTEGRITY_DB`, а не з типовою чи спільною БД. `synthetic_only=true` у відповіді позначає призначення демометодики, а не результат перевірки записів.

Усі маршрути нижче мають ту саму матрицю доступу, що `/results`: admin, manager, anticorruption, auditor. Без ролі — 401, інші ролі — 403. `X-Role` залишається суто демонстраційним, не автентифікацією.

| Метод | Шлях | Результат |
| --- | --- | --- |
| GET | `/api/index-methodologies/team-results-demo-0.1` | Формула, точні ваги, пороги, версія, статус та обмеження |
| GET | `/api/assessments/{id}/index?methodology=team-results-demo-0.1` | Індекс, компоненти, внески, видимі категорії та хеші |
| GET | `/api/assessments/{id}/recommendations?methodology=team-results-demo-0.1` | Пояснювані пропозиції й окремий фактичний контекст |
| GET | `/api/analytics/comparisons?assessment_id=1&comparison_assessment_id=2&methodology=team-results-demo-0.1` | Розриви категорій і необов’язкове зіставлення двох циклів |

`methodology` обов’язковий для трьох обчислювальних маршрутів. Немає параметра чи версія невідома — 422. Деморежим вимкнено — 503. Невідомий цикл — 404; відкритий — 409. Непогоджений набір компонентів/ваг — 409. Однакові ID у порівнянні циклів — 422. Метадані невідомої версії — 404.

Приклад запиту:

```bash
curl -H 'X-Role: manager' 'http://127.0.0.1:8000/api/assessments/1/index?methodology=team-results-demo-0.1'
```

Успішна відповідь має assessment, source=survey, synthetic_only=true, methodology_version, approval_status, official=false, status, index, index_exact, components, by_category, coverage, expert, audit, precision, warnings. Для умовного випадку, де всі 7 компонентів мають 50 балів:

```json
{"methodology_version":"team-results-demo-0.1","approval_status":"proposed",
 "official":false,"source":"survey","synthetic_only":true,
 "status":"ok","index":50.0,"index_exact":"50"}
```

Це скорочений приклад. Компонент C1 у повній відповіді:

```json
{"code":"C1","name":"Синтетичний компонент","score":50.0,
 "weight":0.15,"weight_exact":"3/20","contribution":7.5,
 "contribution_exact":"15/2","status":"ok"}
```

Приклад помилки 409:

```json
{"detail":"Results do not match the selected demo methodology"}
```

Приклад помилки 503:

```json
{"detail":"Set INTEGRITY_ANALYTICS_DEMO=1 only for a synthetic database"}
```

Формула: **II = Σ(Ci × wi)**. Ваги C1..C7: 0.15, 0.15, 0.15, 0.20, 0.10, 0.15, 0.10; точна сума 1. Це числа з поточного демо-seed, **не офіційні ваги МОУ/НАЗК**. Їхня нерівність ще потребує змістовного обґрунтування командою; поточна реалізація забезпечує лише прозорість та інтеграційну сумісність. Інші ваги чи компоненти потребують нової версії й людського рішення.

Джерело — вже нормалізовані до 0–100 й округлені до 0.1 бали `/results`. Повторного перетворення шкали немає. `Fraction` зберігає точні десяткові вхідні числа. Поля exact стосуються цих агрегатів, а не сирих анкет. За коректного upstream-округлення похибка індексу від округлення не перевищує 0.05 бала; статистична похибка не оцінюється. Для порогових сигналів теж використовуються наявні округлені агрегати.

Немає компонента — `index=null`, `status=insufficient_data`, без перерозподілу ваг. Прихована загальна кількість — `index=null`, `status=suppressed`; похідні групові значення також приховані. Приховані категорії/клітинки не відновлюються ні індексом, ні порівнянням, ні рекомендацією. k береться з `/results`. coverage.response_rate=null, бо немає знаменника запланованих учасників.

Усі survey-категорії залишаються категоріями самооцінювання: mgmt не перетворюється на незалежних експертів. expert.status=not_available, index=null.

Для видимих категорій gap=left−right; abs(gap)>=25 — авторський сигнал перегляду, не доказ нечесності чи статистична значущість. Для прихованих gap_points=null, flag=null, status=unavailable.

Для двох циклів change=after−before. assessment_id — before, comparison_assessment_id — after; порядок задає клієнт. Повертається limited_comparability, бо upstream не фіксує історичні версії анкет, популяції та методики. Це числове зіставлення, не доведене поліпшення. У разі зміни змісту анкет висновок про динаміку не обґрунтований.

Рекомендації: DATA_QUALITY_V1, LOW_SCORE_LT_50_V1, CATEGORY_GAP_GE_25_V1. Кожна має відтворюваний id, assessment_id, rule_id, component_code, basis, text, audit, status=proposed, owner_role/due_date=null, requires_human_decision=true. Умова низького бала — строго <50; розрив — >=25. Обидва пороги авторські.

Фактичні показники повертаються окремим context_only. Непідтверджене значення — null; навіть підтверджені не віднімаються від бала зрілості, бо `/results` не надає погоджених metric_id, одиниць та посилань на докази. Індекс фактами не коригується.

Детерміновані GET-маршрути не записують пропозиції у recommendations, не приймають їх і не призначають строки. Рішення посадової особи й історію заходів зберігає окремий Tracker (розділ «Recommendations Tracker» нижче) у таблиці `recommendation_actions`; застаріла seed-таблиця recommendations зі статусами done/overdue ним не використовується й автоматично не змінюється.

Tracker порівнює ID циклів після приведення числа та його десяткового рядка до одного значення і відхиляє перевірку тією ж оцінкою. Він **не перевіряє хронологію циклів**: числовий порядок ID не гарантує часовий порядок. Перед реальним статусом `verified` інтеграційний сервіс має окремо перевірити дати та незмінну версію оцінювання в БД.

## Recommendations Tracker

Рішення щодо рекомендацій ухвалює посадова особа, а не система. Пропозиції не зберігаються: сервер щоразу заново формує їх правилами `team-results-demo-0.1` і приймає рішення лише щодо `recommendation_id`, який є серед актуальних пропозицій закритого циклу. Текст, правило й компонент бере сервер, а не клієнт. Заходи зберігаються в таблиці `recommendation_actions` (схема БД версії 4). Відповідальним вказують посаду або підрозділ, не ПІБ і не контакти. Кожна зміна записується в журнал дій (`tracker.accepted`, `tracker.rejected`, `tracker.in_progress`, `tracker.completed`, `tracker.verified`) лише з роллю й циклом.

| Метод | Маршрут | Доступ | Призначення |
|---|---|---|---|
| GET | `/api/assessments/{id}/tracker` | ролі аналітики | Заходи циклу, історія рішень, дозволені переходи, підсумок і ознака прострочення |
| POST | `/api/assessments/{id}/tracker/decisions` | admin, сесія + CSRF, `INTEGRITY_ANALYTICS_DEMO=1` | Прийняти або відхилити пропозицію |
| POST | `/api/tracker/{action_id}/transition` | admin, сесія + CSRF | Змінити статус прийнятого заходу |

Тіло рішення: `{recommendation_id, decision: accepted|rejected, owner?, due_date?, reason}`. Для `accepted` потрібні `owner` (3–120 символів, посада чи підрозділ) і `due_date` (РРРР-ММ-ДД, не раніше сьогодні й не далі ніж за 5 років); для `rejected` вони заборонені. `reason` обов'язкове (до 1000 символів). Відповіді: 201 — створено захід; 404 — циклу немає або пропозиції немає серед актуальних; 409 — цикл відкритий або рішення щодо пропозиції вже ухвалено; 422 — дані не пройшли перевірку; 503 — аналітичний демо-режим вимкнено.

Тіло переходу: `{status: in_progress|completed|verified, reason, evidence_refs?, verified_in_assessment_id?}`. Дозволені переходи: прийнято → в роботі → виконано → перевірено; з «виконано» можна повернути «в роботу». Для «виконано» й «перевірено» потрібні посилання на докази (до 10, кожне до 200 символів). «Перевірено» вказує пізніше закрите оцінювання з тією самою версією анкети: результат заходу перевіряє наступний цикл. Відповіді: 200 — оновлений захід; 404 — заходу немає; 409 — перехід недозволений або захід щойно змінено іншим запитом; 422 — дані не пройшли перевірку.

Прострочення не є окремим статусом: захід прострочений, якщо строк минув, а статус не «виконано» чи «перевірено».

## Зрілість за Додатком В (`annex-v-maturity-0.1`)

Синтетична демонстрація; Integrity Index (`team-results-demo-0.1`) не змінюється. Схема БД версії 6 додає лише нові таблиці: `annex_v_responses`, `annex_v_answers`, `annex_v_expert_assessments`, `checklist_entries`, `maturity_indicators`. Код: `backend/app/annex_v.py` (каталог), `services/maturity.py` (рушій), `routes/annex_v.py` (маршрути).

| Метод | Маршрут | Доступ | Призначення |
|---|---|---|---|
| POST | `/api/assessments/{id}/annex-v/responses` | публічний, лише одноразовий код | Анонімна анкета Додатка В |
| POST | `/api/assessments/{id}/annex-v/expert` | admin, сесія + CSRF | Експертна оцінка за формою 1 |
| GET | `/api/assessments/{id}/annex-v/expert` | admin (сесія з 2FA) | Внесені експертні оцінки циклу й підсумок за критеріями |
| GET | `/api/assessments/{id}/checklist` | admin, data_officer, ролі аналітики | 20 пунктів чек-листа (Додаток Б, адаптовано) зі станом |
| PUT | `/api/assessments/{id}/checklist/{code}` | data_officer або admin, сесія + CSRF | Внести стан пункту; скидає підтвердження |
| POST | `/api/assessments/{id}/checklist/{code}/confirm` | admin, сесія + CSRF | Підтвердити пункт (інший користувач) |
| GET | `/api/assessments/{id}/objective-indicators` | admin, data_officer, ролі аналітики | Об'єктивні показники критеріїв |
| POST | `/api/assessments/{id}/objective-indicators` | data_officer або admin, сесія + CSRF | Внести показник |
| POST | `/api/objective-indicators/{indicator_id}/confirm` | admin, сесія + CSRF | Підтвердити показник (інший користувач) |
| GET | `/api/assessments/{id}/maturity` | ролі аналітики, `INTEGRITY_ANALYTICS_DEMO=1` | Рівні, розриви, індекси й рекомендації закритого циклу |
| GET | `/v2/admin/reports/{id}/maturity-export?format=pdf\|xlsx` | лише сесія V2 `admin` (2FA), `INTEGRITY_ANALYTICS_DEMO=1` | Звіт зрілості PDF/XLSX з того самого розрахунку, що й `/maturity` |

### Каталог і правило рівня

Ідентифікатори дзеркалять `frontend/src/official/catalog-v2.ts`, шаблони версії `2.0.0`: питання `av-f{форма}-{culture|system|accountability|maturity}-{n}`, варіант `{id питання}-{a..e}` (у питаннях про викривачів є ще `f`). Форма 1 — 12 питань, форма 2 — 10 (без `leadership`). Критерій — ключ набору варіантів: `leadership`, `ethics`, `education`, `openness`, `officer`, `strategy`, `risks`, `checks`, `whistleblowers`, `audit`, `maturity`.

Рівень варіанта: a=1, b=2, c=3, d=4, e=5. Для питань про викривачів (`whistleblowers`, 6 варіантів) — за Додатком Г, с. 73: a=1, b=2, c=3, d=4, e=4, f=5. Таблиця — `annex_v.LEVEL_MAPS`; у відповіді `/maturity` — рядок `level_rule`.

Рівень критерію в одній анкеті — середнє її відповідей на питання критерію. У формі 1 `openness` має два питання (№4 і №5 — те саме питання джерела): вони усереднюються в межах анкети, тож анкета враховується один раз. Критерій `maturity` (заявлений загальний рівень) показується окремо (`overall_self_declared`) і в індекс не входить.

Відповідність компонентам (лише для показу): leadership, ethics → C1; strategy, officer → C2; risks, checks → C3; education → C5; whistleblowers → C6; openness, audit → C7. C4 не має критерію в Додатку В.

### `POST /api/assessments/{id}/annex-v/responses`

Тіло: `{access_token, category: mgmt|npp|cadets|staff, form: 1|2, version: "2.0.0", answers: {questionId: optionId}}`; потрібна відповідь на кожне питання форми, зайві поля заборонені. Код — той самий одноразовий код циклу, що й для `/submissions` (видають admin або data_officer). Категорія коду має збігатися з `category`; після подання код використаний для обох анкет.

Відповіді: 201 `{"status": "accepted"}` без id і відповідей; 404 — циклу немає або він чернетка; 409 — цикл не відкритий, строк не настав чи минув, або код недійсний, використаний чи іншої категорії (одне повідомлення для всіх випадків); 422 — некоректні дані, інша версія або категорія не з цього циклу.

Анонімність така сама, як для `/submissions`. Маршрут не читає сесію. Анкета зберігає лише категорію, форму й версію: без облікового запису, коду, підрозділу й часу подання. Подання не журналюється й не потрапляє в журнал доступу uvicorn.

### `POST /api/assessments/{id}/annex-v/expert`

Тіло: `{expert_label, form: 1, version: "2.0.0", answers}`. `expert_label` — посада або роль, 3–120 символів; ознаки ПІБ, email чи телефону → 422. Відповіді: 201 `{id}`; 404 — циклу немає; 409 — цикл чернетка; 422 — некоректні дані. Журнал: `annex_v.expert_create`.

### `GET /api/assessments/{id}/annex-v/expert`

Перегляд внесених експертних оцінок (Анкета 1) для адміністратора. Доступ: лише `admin` із сесією після 2FA; `data_officer`, ролі аналітики й `user` → 403; без сесії (або сесія до 2FA) → 401; некоректний id → 422; циклу немає → 404. Чернетка повертає порожній перелік. Читання не журналюється.

```text
{ assessment_id, form: 1, version: "2.0.0", count,
  items: [{ id, expert_label, form, version, created_at: "РРРР-ММ-ДДTгг:хх:ссZ", entered_role, entered_by_user_id|null,
            answers: [{ question_id, question, criterion, option_id, option, level }] }],
  by_criterion: [{ criterion, title, levels: [...], mean|null }] }
```

- `items` — за `created_at` (потім за `id`); `expert_label` — посада або роль, без ПІБ; email, імен і інших персональних полів відповідь не містить. `entered_by_user_id` — id облікового запису адміністратора, що вніс (у демо-режимі X-Role — `null`).
- `answers` — у порядку питань форми 1. Тексти питань і варіантів (`question`, `option`) і `level` береться з серверного каталогу `annex_v` (`QUESTION_TEXTS`, `OPTION_TEXTS`, `LEVEL_MAPS` — дзеркало `catalog-v2.ts`, редакція 2.0.0), а не з БД. Для варіанта поза каталогом `option` і `level` — `null`.
- `by_criterion` — 11 критеріїв форми 1 у порядку каталогу, `title` — `CRITERIA[...].name_uk`. `levels` — рівні критерію в кожному записі (у порядку `items`; для `openness` — середнє двох питань запису), `mean` — середнє, округлене «половина вгору» до 0,01; без записів — `levels: []`, `mean: null`. Записи іншої версії каталогу показуються в `items`, але до підсумку не входять.

### Чек-лист

Пункти `B-01`…`B-20` — стислі адаптації завдань і індикаторів Додатка Б з номером пункту джерела (`source_item`). Кожен пункт прив'язаний до одного з 10 критеріїв. Прив'язку обрала команда; вона потребує методичного погодження.

Пункт: `{code, criterion, text, source: "Додаток Б (адаптовано)", source_item, status: yes|partial|no|null, evidence, entered_role, entered_at, confirmed, confirmed_role, confirmed_at}`. Ідентифікаторів користувачів відповідь не містить.

`PUT` приймає `{status: yes|partial|no, evidence?: string ≤ 1000}`, повертає пункт і скидає підтвердження. `confirm` повертає пункт.

Помилки: 404 — невідомий код; 409 — пункт не заповнено, уже підтверджено або підтверджує той самий користувач, що вніс (порівнюються id сесій V2; у демо-режимі X-Role — роль).

Журнал: `checklist.update` і `checklist.confirm`, лише з роллю й циклом.

### Об'єктивні показники

Тіло `POST`: `{criterion (один із 10, не maturity), name: 3–200, value: 0–100, target: 0–100, period: 1–50}`. Відповідь — 201 і показник `{id, criterion, name, unit: "%", value, target, period, entered_role, entered_at, confirmed, confirmed_role, confirmed_at}`.

`confirm`: 404 — показника немає; 409 — уже підтверджено або той самий користувач. Журнал: `objective.create`, `objective.confirm`.

### `GET /api/assessments/{id}/maturity`

Порядок перевірок: 401/403 — роль, 503 — демо-режим вимкнено, 404 — циклу немає, 409 — цикл не закрито.

```text
{ assessment:{id,name,status}, methodology_version:"annex-v-maturity-0.1",
  level_rule:"a=1…e=5; викривачі: a=1, b=2, c=3, d=4, e=4, f=5 (Додаток Г, с. 73)",
  min_group_size:k, synthetic_only:true, official:false,
  visible_categories:[...], suppressed:bool,
  criteria:[{ key, name_uk, component_code|null,
              self:{level|null, responses|null, status:"ok"|"suppressed"|"missing"},
              self_by_category:[{category, level|null, hidden:bool}],      // лише видимі категорії
              expert:{level|null, experts, status:"ok"|"missing"},
              checklist:{level|null, items_total, items_confirmed, status:"ok"|"missing"},
              objective:[{name, value, target, confirmed}],
              gaps:[{rule_id, left:"self", right:"expert"|"checklist", diff|null, flag}] }],   // 10 критеріїв
  overall_self_declared:{level|null, responses|null, status, expert_level|null},
  indices:{self|null, expert|null, checklist|null},
  recommendations:[{id, rule_id, criterion, component_code, basis:{...}, text, requires_human_decision:true}] }
```

Формули (точна арифметика, `Fraction`):

- `self` — середнє рівнів критерію по анкетах.
- `expert` — середнє по експертних оцінках.
- `checklist` = 1 + 4 × (yes + 0,5 · partial) / підтверджені пункти; враховуються лише підтверджені пункти.

Рівні показуються з 1 знаком після коми (округлення половини вгору).

Індекс джерела = (середній рівень 10 критеріїв − 1) / 4 × 100, з рівними вагами. Його рахують із точних рівнів, не з округлених до 0,1, і лише потім округлюють до 2 знаків. Якщо для джерела бракує або приховано хоч один критерій, індекс дорівнює `null`; ваги не перерозподіляються, а `null` ніколи не стає 0.

Правила (їх порівнюють із показаними рівнями з 1 знаком, тому прапорці збігаються з числами на екрані):

- `MAT_LOW_LEVEL_LT_3` — рівень експерта, а без нього самооцінка, < 3.
- `MAT_SELF_EXPERT_GAP_GE_1` — self − expert ≥ 1,0.
- `MAT_SELF_CHECKLIST_GAP_GE_1` — self − checklist ≥ 1,0.
- `MAT_OBJECTIVE_BELOW_TARGET` — підтверджений показник має value < target, а self ≥ 3,5.
- `MAT_OBJECTIVE_UNCONFIRMED` — self ≥ 4, а підтверджених показників критерію немає.

Рекомендація — пропозиція з `requires_human_decision: true`; `id` детермінований.

k-анонімність (як `/results`):

- Категорії з < k анкетами приховуються. Діє вторинне приховування (`anonymity.hidden_flags`).
- Приховані категорії не перелічуються ніде (D4).
- Для кожного критерію категорії додатково проходять те саме приховування за кількістю анкет із цим критерієм.
- Загальний рівень критерію показується, лише якщо таких анкет ≥ k і приховану частину не можна приписати одній категорії.
- Окремі анкети й варіанти відповідей API ніколи не повертає.

### `GET /v2/admin/reports/{id}/maturity-export?format=pdf|xlsx`

Звіт зрілості за Додатком В для адміністратора (за мотивами шаблону звіту Додатка Г). Код: `services/maturity_report.py` (подання), дані — `services/maturity.calculate`, тобто рівно та сама відповідь, що й `GET /api/assessments/{id}/maturity`; формул у звіті немає.

Порядок перевірок: 401 — немає сесії V2 (демо `X-Role` не діє), 403 — роль не `admin` (`user`, `data_officer`), 503 — демо-режим вимкнено (`INTEGRITY_ANALYTICS_DEMO`, у release — ще й позначка синтетичної БД), 404 — циклу немає, 409 `"Зрілість доступна після закриття оцінювання"` — цикл не закрито; 422 — `format` не `pdf`/`xlsx` або id поза `1..2^63-1`.

Відповідь 200: `Content-Type: application/pdf` або `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `Content-Disposition: attachment; filename="maturity-report-{id}.{pdf|xlsx}"` (лише ASCII), `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`.

Вміст (одні таблиці для обох форматів; XLSX — аркуші «Зрілість», «Розриви й пропозиції», «Джерела»; PDF — ті самі розділи, шрифт DejaVuSans для кирилиці):

- **Підсумок:** назва й id циклу, дата формування (UTC), версія методики, позначка «СИНТЕТИЧНІ ДАНІ», якщо `instance_meta.dataset = synthetic`, k, чи є приховані групи, три індекси джерел, заявлений загальний рівень (окремо, не в індексі).
- **Рівні за критеріями:** назва, `self` і кількість анкет, `expert` і кількість експертів, `checklist` і «підтверджено N з M», підсумковий рівень за правилом методики (`maturity.base_level`: рівень експерта, без нього — самооцінка) і його джерело.
- **Розриви** `self − expert`, `self − checklist` з позначкою (≥ 1,0); **пропозиції** — `rule_id` і текст; **правила методики** — коди з умовами.
- **Джерела даних і обмеження:** k-анонімність (малі групи не показуються й не перелічуються), експерт — посада, а не особа, тексти пропозицій — чернетка для робочої групи, правило рівнів, статус методики.

Приховане значення — «Приховано», відсутнє — «Немає даних»; `null` ніколи не стає 0. Текст циклу в XLSX записується літерально (без формул).

Журнал: дія `report.maturity_export` — роль `admin`, `actor_user_id`, `assessment_id`, `details: {}`. Невдалі спроби не журналюються.

## Результати підрозділу для користувача (`GET /v2/user/unit-results?assessment_id={id}`)

Сесія V2 з роллю `user` після 2FA (інші ролі → 403, без сесії → 401). Підрозділ визначає лише сервер
(таблиця `user_units`, призначає власник сервера: `python -m app.v2_unit_cli set-unit --email … --unit … --confirm`);
будь-які параметри підрозділу чи категорії від клієнта ігноруються. `404` — циклу немає, `409` — цикл не закрито,
`404` також для чернетки циклу, `422` — id поза 1..2^63−1.

```json
{"assessment": {"id": 1, "name": "2025-II", "status": "closed"}, "unit": "Факультет 1",
 "methodology_version": "unit-mean-0-100-v1", "min_group_size": 5,
 "privacy_status": "available", "responses": 90,
 "components": [{"code": "C1", "name": "…", "score": 52.3, "status": "available"}]}
```

`privacy_status`: `available` (`responses` округлено вниз до кратного 5) | `suppressed` (у підрозділі < k анкет або в
циклі є клітинка «категорія × підрозділ» з 1…k−1 анкет; `responses` і всі `score` — null) | `no_unit` (`unit` = null). Розрізу за категоріями немає. Деталі й обґрунтування —
`docs/USER_UNIT_RESULTS_API_PROPOSAL.md`, `docs/anonymity.md` §4.6.

## V2 Hardening — зміни за аудитом backend (20.11.2026)

Повний робочий контракт і обґрунтування: `docs/V2_HARDENING_CONTRACT.md`. Схеми: V2_AUTH_DB `user_version = 2`, INTEGRITY_DB `user_version = 5` (4 — Recommendations Tracker).

### Ролі
`user` (самореєстрація), `admin` (цикли, результати, аналітика, журнал, звіти, трекер, перегляд користувачів і завершення сесій, а також усі права `data_officer`: видача кодів і участь), `data_officer` (лише видача кодів доступу й участь). Ролі `admin` і `data_officer` призначає й знімає **лише власник сервера** командою на сервері; у вебі ролі не змінюються. Роль читається з БД на кожен запит; одна роль на акаунт. Ризик n−1 (admin видає коди й бачить результати) свідомо прийнято власником — див. `docs/V2_HARDENING_CONTRACT.md`, розділ 1.1.

| Маршрут | Доступ | Примітки |
|---|---|---|
| `POST /api/assessments/{id}/tokens` | `admin`, `data_officer` + CSRF | інші ролі → 403. Подія журналу `tokens.issue` з `actor_role`, `actor_user_id` і `count` (без кодів). Відповідь `{"tokens":[…]}` — відкриті коди лише один раз, у БД зберігається SHA-256 |
| `GET /api/assessments/{id}/participation` | `admin`, `data_officer` | у відкритому циклі `responses_total`/`tokens_unused` округлені вниз до кратного 5 (лише якщо ≥ k), `counts_exact:false`, `by_unit` = null; у закритому — точні, `counts_exact:true` |
| `GET /api/assessments`, `GET /api/assessments/{id}` | публічні | чернетки бачить лише сесія admin; для аноніма/user draft → 404 |
| `POST /v2/auth/logout-all` | сесія з 2FA + CSRF | `{"status":"logged_out_all"}`, видаляє всі сесії користувача |
| `GET /v2/admin/users` | admin | `[{id, name, role, email_masked, created_at}]`, до 500; параметри ігноруються |
| `POST /v2/admin/users/lookup` | admin + CSRF | тіло `{"email"}` → `{id, name, email, role, created_at}` або 404. Email не передається в URL |
| `POST /v2/admin/users/{user_id}/role` | admin + CSRF | тіло `{"expected_role","new_role"}` — у вебі ролі не змінюються. `new_role` або `expected_role` = `admin`, а також поточна роль цілі `admin` (перевіряється й усередині транзакції BEGIN IMMEDIATE) → **403 `{"detail":"admin_role_server_only"}`**; те саме для `data_officer` → **403 `{"detail":"data_officer_role_server_only"}`**; без жодних змін. Інші коди: 403 `self_change`, 404 `user_not_found`, 409 `role_conflict` (`user` → `user`), 422. Frontend цей маршрут не викликає |
| `POST /v2/admin/users/{user_id}/revoke-sessions` | admin + CSRF | `{"revoked": n}`; гасить і відкриті коди 2FA. Для `user` і `data_officer` — дозволено. Ціль з роллю `admin` (крім себе) → 403 `admin_role_server_only`; власні сесії — як і раніше (а також `POST /v2/auth/logout-all`) |
| `GET /v2/admin/role-changes` | admin | `{id, actor_user_id, target_user_id, old_role, new_role, changed_at}`, до 500; `actor_user_id = 0` — серверна команда власника сервера |

#### Ролі admin і data_officer — лише власник сервера

Ролі адміністратора й відповідального за коди (`data_officer`) у вебі не призначає й не знімає ніхто, зокрема інший адміністратор. Їх призначає й знімає лише власник сервера командою на сервері (з каталогу backend):

```
python -m app.v2_role_cli set-role --email <email> --role admin|user|data_officer            # план, без змін
python -m app.v2_role_cli set-role --email <email> --role admin|user|data_officer --confirm  # виконати
```

На сервері Windows — `installer/windows-v2/ops/Set-V2UserRole.ps1`, запуск з каталогу, куди скопійовано скрипт (неінтерактивно, придатно для SSH від адміністратора; шляхи БД і робочий каталог — з XML служби `integrity-v2-backend`, секрети не читаються й не виводяться):

```
powershell -NoProfile -ExecutionPolicy Bypass -File .\Set-V2UserRole.ps1 -Email <email> -Role admin           # план
powershell -NoProfile -ExecutionPolicy Bypass -File .\Set-V2UserRole.ps1 -Email <email> -Role admin -Apply    # виконати
```

- Одна транзакція: роль, видалення всіх сесій цілі, гасіння відкритих кодів 2FA, запис у `v2_role_changes` з `actor_user_id = 0` («сервер»: колонка NOT NULL без FK/CHECK, id користувачів починаються з 1). Після коміту — подія основного журналу `user.role_change` з `actor_role = "server"`, `actor_user_id = null`, без email.
- Останнього адміністратора не знімає (лишається щонайменше один `admin`).
- Не мігрує БД (лише перевірка схем), не потребує `V2_SECRET_KEY`; зі змінних середовища читає `INTEGRITY_DB`, `V2_AUTH_DB` (у release обов'язкові) і `APP_ENV`. Backend зупиняти не потрібно.
- Email у виводі лише замаскований. Коди виходу: `0` — виконано або план, `2` — відмова (немає користувача, та сама роль, останній адміністратор, неправильні аргументи), `1` — помилка.

#### Синтетичний демо-цикл (серверна команда)

`python -m app.demo_cycle --responses 150 --seed 2026 [--name "..."] [--confirm]` (на сервері — `installer/windows-v2/ops/New-V2DemoCycle.ps1 [-Apply]`; опис — `docs/DEMO_DATA.md`). Нових маршрутів API немає: створений закритий цикл читається наявними `GET /api/assessments/{id}/results`, `/participation` і чернетками LM. Лише БД з позначкою `instance_meta.dataset = 'synthetic'` (інакше відмова), назва циклу унікальна, схема лише перевіряється. Одна транзакція; журнал — дія `demo.cycle_generated` з `actor_role = "server"`, `actor_user_id = null`, `details: {"count": N}`. Коди виходу: `0` — виконано або план, `2` — відмова, `1` — помилка.

### Чернетки текстів звіту локальною ШІ (llama-server)
Опис, налаштування й ручна перевірка — `docs/LOCAL_LM.md`. Усі маршрути — сесія `admin` з 2FA; POST — з CSRF. Факти для моделі беруться лише з `/results` (без прихованих груп), підсумків участі й лічильників трекера; тексти ніде не зберігаються і не потрапляють у трекер.

| Маршрут | Доступ | Примітки |
|---|---|---|
| `POST /v2/admin/reports/{assessment_id}/narrative` | admin + CSRF | тіло `{"kind":"summary"\|"recommendations"}` → 202 `{"job_id","status":"queued"}`; 404 — циклу немає; 409 — цикл не закритий; 422 — інше тіло/зайві поля/id поза `1..2^63-1`; 429 — черга заповнена (5 завдань); 503 `"Локальна LM не налаштована"` — не задано `V2_LM_URL` |
| `POST /v2/admin/reports/compare/narrative` | admin + CSRF | тіло `{"base_assessment_id","target_assessment_id"}` (base — попередній, target — поточний) → 202 як вище; однакові id → 422; будь-який цикл відсутній → 404, не закритий → 409 |
| `GET /v2/admin/lm/jobs/{job_id}` | admin (лише автор завдання) | `{job_id, status: queued\|running\|done\|failed, kind: summary\|recommendations\|compare, assessment_ids, created_at, finished_at?, text?, verified?, unverified_numbers?, error?}`; `text` — простий текст без HTML; `verified=false` — у тексті є числа, яких немає у фактах (`unverified_numbers`); `error` — загальне повідомлення без деталей сервера. 404 — немає, чуже або минуло 1 год після завершення; некоректний `job_id` → 422 |
| `GET /v2/admin/lm/status` | admin | `{enabled, reachable, model}`; `enabled=false` — `V2_LM_URL` не задано (`model: null`); `reachable` — `GET /health` llama-server за 3 с повернув 200 |

Журнал: дія `report.narrative` — роль, `actor_user_id`, `assessment_id` (для порівняння — target) і `details: {"count": 1|2}` (кількість циклів); тексту, виду й промпту в журналі немає. Черга одна на процес (один фоновий виконавець), завдання в пам'яті: перезапуск сервісу їх втрачає.

### Формати відповідей
- Результати й участь: приховані групи не повертаються взагалі; булеве `suppressed` на верхньому рівні (і в розрізах компонентів). Поле `hidden` лишено для сумісності й завжди `false`.
- 413 `{"detail":"Request body too large"}` — тіло понад `V2_MAX_BODY_BYTES` (типово 65536).
- 422 — лише `loc`, `msg`, `type` (без `input` і `ctx`).
- Цілі параметри шляху й запиту — `1..2^63-1`, поза межами 422.
- Журнал дій (`GET /api/audit-events`): нове поле `actor_user_id` (id з V2_AUTH_DB, без email/імен); нові дії `auth.logout`, `auth.logout_all`, `auth.password_reset`, `auth.2fa_lockout`, `user.role_change`, `user.sessions_revoke`.

### Поведінка автентифікації
- 2FA: перевірка коду, його споживання й ротація сесії — одна транзакція; не більше 5 перевірок на код навіть паралельно; 10 невдалих кодів за 24 год → 429 (`auth.2fa_lockout`).
- Сесія до 2FA — 15 хв, після 2FA — 12 год.
- Скидання пароля: не більше 5 кодів на акаунт за 24 год і 10 невдалих підтверджень; підтвердження атомарне й відкликає всі сесії.
- Час відповіді входу, реєстрації й запиту коду скидання пароля не залежить від існування email: запит скидання лише ставить лист у фонову чергу (один воркер, обмежена черга; при переповненні завдання відкидається без зміни відповіді).
- OTP зберігається як HMAC-SHA256 з `V2_SECRET_KEY`; паролі — scrypt N=2^17 з переобчисленням старих хешів після входу.
