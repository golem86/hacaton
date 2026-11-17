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
| Integrity Index Engine | `GET /api/assessments/{assessment_id}/index`; `GET /api/index-methodologies/{version}` | `IndexResult`, `IndexMethodology` | Заплановано |
| Executive Dashboard | `GET /api/assessments/{assessment_id}/dashboard` | `DashboardSummary` | Заплановано |
| Comparative Analytics | `GET /api/analytics/comparisons` | `Comparison` | Заплановано |
| Recommendations Engine | `GET /api/assessments/{assessment_id}/recommendations` | `RecommendationProposal` | Заплановано |
| Recommendations Tracker | `GET /api/recommendations`; `PATCH /api/recommendations/{recommendation_id}` | `TrackedRecommendation` | Заплановано |
| Audit Trail | `GET /api/audit-events` | `AuditEvent` | Реалізовано (backend-audit) |
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
