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
| Recommendations Tracker | `GET /api/recommendations`; `PATCH /api/recommendations/{recommendation_id}` | `TrackedRecommendation` | Заплановано |
| Audit Trail | `GET /api/audit-events` | `AuditEvent` | Заплановано |
| Reporting Module | `GET /api/assessments/{assessment_id}/reports`; `GET /api/reports/{report_id}/export` | `Report`, файл експорту | Заплановано |

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

## Реалізовані маршрути (PR #4)

У базі цикл оцінювання зберігається в таблиці `cycles`; в API він називається `assessment`.

### Матриця доступу

| Маршрут | admin | respondent | expert | data_officer | manager | anticorruption | auditor |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `GET /api/assessments`, `GET /api/assessments/{id}`, `GET /api/assessments/{id}/questionnaires`, `GET /api/units` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `POST /api/assessments/{id}/submissions` | | ✓ | | | | | |
| `POST /api/assessments/{id}/tokens`, `POST /api/assessments/{id}/close` | ✓ | | | | | | |
| `GET /api/assessments/{id}/participation`, `GET /api/assessments/{id}/results` | ✓ | | | | ✓ | ✓ | ✓ |

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

Відповідь `201 {"status": "accepted"}` — без номера анкети, щоб її не можна було зіставити з кодом. Помилки: `403` — недійсний, чужий або вже використаний код (одне повідомлення для всіх випадків); `409` — оцінювання закрите; `422` — неповна анкета, значення поза шкалою, невідома категорія або підрозділ не з довідника (код при цьому не витрачається).

`unit` — лише назва з `GET /api/units` (`["Кафедра загальних дисциплін", "Факультет 1", "Факультет 2"]`). Довільний текст база відхиляє: так у неї не потрапляють прізвища чи інші ознаки особи.

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

Детерміновані GET-маршрути не записують пропозиції у recommendations, не приймають їх і не призначають строки. Доменний Tracker у services/tracker.py вимагає явного людського рішення; збереження історії й майбутній PATCH-маршрут — окремий інтеграційний крок. Наявні seed-статуси done/overdue не змінюються автоматично.

Tracker порівнює ID циклів після приведення числа та його десяткового рядка до одного значення і відхиляє перевірку тією ж оцінкою. Він **не перевіряє хронологію циклів**: числовий порядок ID не гарантує часовий порядок. Перед реальним статусом `verified` інтеграційний сервіс має окремо перевірити дати та незмінну версію оцінювання в БД.
