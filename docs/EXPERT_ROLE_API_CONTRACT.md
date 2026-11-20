# Експертна роль і API: контракт ізольованого прототипу

**Статус: PROTOTYPE CONTRACT / DO NOT MERGE.** Це контракт для окремого тестового застосунку й окремої синтетичної SQLite БД. Він **не** вводить production роль, не змінює `v2_users`, schema 3, `backend/app/main.py`, маршрути `/api/*` або Integrity Index. Майбутні production DDL, авторизація й маршрути потребують технічного затвердження №5.

## Встановлені межі поточної системи

У `backend/app/v2_auth.py` таблиця `v2_users` дозволяє лише `user` і `admin`; `create_user` має таке саме обмеження. `require_v2_role` читає серверну cookie-сесію, вимагає завершену 2FA і для мутацій перевіряє прив'язаний до сесії `X-CSRF-Token` та Origin/Referer. У `backend/app/roles.py` назва `expert` є тільки в legacy/demo-наборі: за ввімкненого development `INTEGRITY_DEMO_XROLE` заголовок `X-Role` може діяти без сесії. **Використовувати `require_role('expert')` для експертного прототипу заборонено.** Доступ до `/admin/expert` сьогодні означає лише адміністративний frontend preview, не експертне призначення.

Поточний `backend/app/audit.py` має суворий allowlist дій і числових details, у ньому немає експертних дій. Прототип веде окремий транзакційний audit у тестовій БД. Production audit можна розширювати тільки разом з погодженням №5, не вимикаючи його allowlist.

## Довірена модель прав і межі прототипу

Тестовий застосунок створюється окремою фабрикою `create_prototype_app` і **ніколи не підключається** до `backend/app/main.py`. Principal і сесію створює лише серверний test fixture, без sign-in endpoint. Дані дозволу й ознаки 2FA беруться тільки із серверної пам’яті та таблиці `expert_permissions`; заголовки, query, JSON-поля `role`, `is_expert`, `two_factor_verified`, `user_id` та `X-Role` не надають прав. Тестові credentials, cookie і БД не потрапляють до репозиторію чи production.

**Фактично реалізована тестова підмножина:** сесії з expiry зберігаються тільки в пам’яті тестового застосунку; в окремій `.prototype.sqlite` БД є `expert_permissions`, `expert_assignments`, `expert_assessments`, `expert_answers`, `expert_audit_events`. Оцінку й призначення створює лише fixture, не клієнт. Реалізовано `GET /prototype/expert/assessments/{id}`, `PUT /prototype/expert/assessments/{id}/answers` і `POST /prototype/expert/assessments/{id}/finalize`. Для мутацій потрібні завершена 2FA, допустимий Origin/Referer і CSRF. Ця фабрика не встановлює production cookie, не реалізує session rotation, reviewer, workflow видачі/відкликання призначень або production audit. Відкликання дозволу тестується через серверний fixture.

Наведена далі таблиця — **цільова модель для технічного затвердження №5**, а не список уже створених таблиць.

| Сутність цільової моделі | Поля та обмеження |
| --- | --- |
| `prototype_principals` | Серверний opaque `principal_id`, статус `active/revoked`; окремий від анонімних відповідей. |
| `prototype_sessions` | Хеш випадкового токена, `principal_id`, expiry, `two_factor_verified`; cookie HttpOnly/SameSite, secure у HTTPS. Серверна ротація після 2FA. |
| `expert_permissions` | `principal_id`, `can_assess`, grant/revoke metadata. Призначає тільки довірений адміністратор/fixture; клієнт не редагує таблицю ролей. |
| `expert_assignments` | `assignment_id`, `principal_id`, `cycle_id`, `template_id`, `version`, статус `active/revoked`; перевірка шаблону й циклу при кожному читанні та записі. |
| `expert_assessments` | Власний випадковий ID, `assignment_id`, `cycle_id`, `template_id`, `version`, `status` `draft/finalized`, `revision`, часові поля. Немає FK до `official_response_sets` або numeric submissions. |
| `expert_answers` | `(expert_assessment_id, question_id)` UNIQUE, `option_id`; FK/валідація опції у відповідній immutable версії, лише `single_choice`, без довільного тексту й балів. |
| `expert_audit_events` | Дія, actor opaque ID, assessment/assignment ID, цикл, час; **без** option ID, відповіді, email, токена чи тіла запиту. Запис в одній транзакції з мутацією. |

Прототип не може створювати призначення від імені самого експерта. Наявність `can_assess` сама по собі не дає доступу до всіх циклів: потрібне активне конкретне призначення. Ревокація діє на наступному запиті. Адміністратор не отримує права редагувати оцінку автоматично; reviewer-доступ — окреме майбутнє рішення №5.

## Пропоновані test-only маршрути

Префікс `/prototype/expert` існує лише в окремому тестовому застосунку. Наведені status codes — пропозиція, а не чинний production API. Жоден із цих маршрутів не додається до OpenAPI production-застосунку.

| Метод і шлях | Доступ | Поведінка |
| --- | --- | --- |
| `GET /prototype/expert/assignments` | Verified expert principal, completed 2FA | Лише власні активні призначення з ID циклу та immutable версією; без анонімних результатів. |
| `POST /prototype/expert/assessments` | Те саме + session CSRF, Origin; лише для власного assignment | `{assignment_id}` створює окремий `draft`, повертає ID і `revision`; заборонити дубль активної оцінки на assignment. |
| `GET /prototype/expert/assessments/{id}` | Лише призначений principal | Статус, версія, власні відповіді; чуже ID повертає 404 або 403 без підтвердження існування. |
| `PUT /prototype/expert/assessments/{id}/answers` | Власний активний `draft`, 2FA, CSRF, Origin | `{revision, answers:[{question_id, option_id}]}`; повна заміна відповідей в транзакції, optimistic concurrency через revision/`If-Match`; `409` для застарілого revision. |
| `POST /prototype/expert/assessments/{id}/finalize` | Власний активний `draft`, 2FA, CSRF, Origin | Перевірити повноту всіх required питань, атомарно змінити статус на `finalized`, записати audit; повторне завершення — `409`. |

Можлива альтернатива — одна оцінка створюється сервером при призначенні, тоді окремий POST створення не потрібен. №5 має вибрати lifecycle. У будь-якому варіанті `cycle_id`, `template_id`, `version` беруться із серверного assignment, а не з довірених клієнтських полів. `option_id` дозволений тільки в `question_id` того самого шаблону/версії. Не приймати поля, що не входять до контракту (`extra='forbid'`) і обмежувати довжину кожного ID/рядка та розмір масиву.

### Коди відповіді

`200/201` — успіх; `400/422` — форма запиту, дублікати, зайві чи чужі питання/варіанти; `401` — немає чинної сесії, `403` — 2FA не завершено або відсутній/невірний CSRF чи Origin; `404` — немає призначеної оцінки (включно з чужою); `409` — finalized, revoked, дубль створення чи конфлікт revision. Не повертати в тексті помилки опції, token, email або приватні атрибути іншої оцінки.

## Інваріанти безпеки

1. **No browser-granted role.** `X-Role: expert`, `role=expert`, підміна `principal_id` чи прапорця 2FA не змінюють серверних прав.
2. **Session + 2FA + CSRF.** Кожна мутація вимагає verified session, completed 2FA, CSRF цієї сесії та допустимого Origin/Referer. Після ротації сесії старий CSRF не працює. SameSite не замінює CSRF.
3. **Assignment ownership.** На кожному запиті перевіряти principal, permission, активне призначення, cycle/template/version і draft/finalized. Не покладатися на прихований frontend маршрут.
4. **Isolation.** Жодних FK/join до анонімних `official_response_sets`, access code чи numeric `responses`; експертні дані не входять до Integrity Index без окремої методики. Відповіді не видно в управлінському Dashboard.
5. **Atomicity.** Зміна answers/status/revision і audit — одна транзакція; `BEGIN IMMEDIATE` або еквівалентна серіалізація в SQLite для конкурентного finalize/update. Завершена оцінка незмінна.
6. **No sensitive logs.** Не логувати body, option IDs, CSRF, cookie, email, access code. Audit має allowlist полів і дій. Звернути увагу, що production-фільтр uvicorn нині приховує лише `/submissions`, тому prototype logs треба налаштувати окремо.
7. **No free text.** Поточна методика — `single_choice` з опціями. Довільний текст підвищить ризик саморозкриття й небезпечного вмісту; потребує окремого рішення про модерацію, доступ, retention та видалення.

## Негативні й конкурентні тести

| Сценарій | Очікування |
| --- | --- |
| Немає cookie, 2FA pending, прострочена сесія | 401, жодної мутації |
| `X-Role: expert`, JSON `role` чи ID чужого principal | 401/403, жодного grant |
| Адміністратор без explicit expert permission/assignment | Відмова на expert write |
| Немає CSRF, невірний/старий CSRF, чужий Origin | 403, жодної мутації чи audit-success |
| Неіснуючий, чужий, відкликаний assignment | 404/403 або 409 для revoked, без витоку даних |
| Чужа версія, question ID, option ID, дублікат питання, oversized payload | 400/422, без часткового запису |
| Порожній/неповний набір при finalize | 422, статус лишається draft |
| Два одночасні update з однаковим revision | Лише один прийнятий, інший 409 |
| Update і finalize одночасно | Лише серіалізований результат, finalized незмінний |
| Повторний finalize | 409, жодного другого audit-success |
| Пошук/читання чужого assessment ID, інший cycle | Відмова без підтвердження існування |
| Перевірка schema, логів і Dashboard | Немає FK/join до anonymous storage, відповідей у audit/логах, впливу на Index |

## Блокери інтеграції для №5

Потрібно окремо затвердити: production DDL/міграцію auth-моделі для `expert` або незалежний permission service; хто й як призначає/відкликає експертів; production endpoint namespace та payload/status contract; lifecycle draft/finalized і reviewer/reopen; retention і доступ до експертних записів; аудит і його дозволені поля; прив’язку до циклу/версії; методику scoring. До цього test-only реалізація не підключається до production UI/API й не є завершеним експертним сценарієм.
