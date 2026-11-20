# Security review та результати тестів прототипу анкет

> **Prompt 14 update (2026-11-20):** The latest authoritative status is in [`QUESTIONNAIRE_INTEGRATION_READINESS.md`](QUESTIONNAIRE_INTEGRATION_READINESS.md). The test-only schema-3 adapter keeps the existing token plaintext and consumes it in the same transaction that writes official answers. No respondent ID or token FK is stored, but DB/WAL transaction timing remains correlatable by a privileged observer; absolute anonymity is **not** claimed. Full backend suite: 427 passed, 1 OS-denied symlink skip, when run with `PYTHONUTF8=1`. Browser E2E: all 13 cases printed `ok`, but the Windows runner did not return a process exit/aggregate summary, so aggregate PASS is **not claimed**. PR #25 Actions has not run because its base is outside the workflow trigger. The previous sections below record historical results and must not be used as current status.

**Стан:** ізольований prototype / Draft PR #25 / DO NOT MERGE. Огляд коду та тестові дані — синтетичні. Production schema 3, `backend/app`, авторизація, Analytics та Integrity Index не змінювалися.

## Анонімні описи

| Контроль | Висновок за кодом | Статус / межа |
| --- | --- | --- |
| Зв’язок людина → відповідь | У `official_response_sets` немає user/principal/respondent ID; у відповідях немає FK до особи. Код зберігається окремо як HMAC digest, без `response_set_id`; клієнт не отримує response ID. | PASS за ізольованою схемою/кодом; production DDL не реалізовано. |
| Одноразове використання, replay, expiry | Digest, цикл, категорія, expiry і `used` перевіряються в транзакції; відмова має загальне повідомлення. | **PASS** — включно з повним backend pytest цього запуску. |
| Атомарність submit/close | `BEGIN IMMEDIATE` серіалізує перевірку відкритого циклу, запис response set/answers і використання коду; close бере той самий write lock. | **PASS** — конкурентні submit і close/submit HTTP тести пройшли в backend suite. |
| Ізоляція cycle/template/version | Submission приймає лише версію, прив’язану до циклу; question/option перевіряються за fixture каталогом. Prototype fixture наразі містить лише 2.0.0. | PASS за оглядом коду; синхронізацію fixture з новим 2.1.0 треба додати до backend prototype до спільного тесту каталогів. |
| IP, user agent, timestamp, логи | У response schema немає IP, user agent, точного часу, email або user ID. Але proxy/access/error logs не є частиною test app. | NOT VERIFIED у deployed ingress/logging; перед production потрібні інтеграційні тести журналів. |
| Малі групи / differencing | Production participation endpoint і suppression запитів в isolated prototype відсутні. | BLOCKED до затвердження k, категорій та complementary suppression №5; raw rows не показувати. |
| Retention / безпечне видалення | Немає purge API/job або політики retention; prototype DB disposable вручну. SQLite/WAL/backup фізичне стирання не перевірено. | BLOCKED до затвердження строків і purge/restore runbook. Пропозиція — `docs/OFFICIAL_RESPONSE_RETENTION_SUPPRESSION_PROPOSAL.md`. |
| Rate limiting | Відсутній у test app. | NOT IMPLEMENTED; потрібна production ingress-політика без зайвого IP збирання. |

## Експертні записи

- Test-only session лежить у пам’яті, має expiry, 2FA прапорець і CSRF; mutating routes перевіряють Origin/Referer і CSRF. Перевірка server-side permission/assignment відбувається на кожному GET/PUT/finalize. `X-Role` і клієнтські role-поля не надають доступ.
- Зберігання експертних відповідей окреме від `official_answers`. Власник assessment визначається server fixture; завершення draft вимагає повних відповідей; revision захищає конкурентне оновлення; повторний finalize відхиляється.
- У цьому WIP додано `created_at` до прототипного `expert_audit_events`; audit insert виконується в тій самій SQLite-транзакції, що й зміна відповідей/revision або finalize. Значення часу є для експертного audit, не для анонімних відповідей.
- Відкликання `expert_permissions.enabled` відсікає наступний запит, оскільки grant перевіряється щоразу. Окремого active/revoked assignment workflow, production grant/revoke API або автоматичного інвалідування чинної V2 сесії немає.
- Прототип не інтегрований із реальною V2 сесією чи 2FA, не має session rotation, persistent cookie policy або production audit sink. Адміністратор не стає експертом; серверне призначення на конкретну оцінку потрібне.

## Фактичні перевірки цього запуску

| Команда/перевірка | Результат |
| --- | --- |
| `frontend/npm test` | **PASS — 45/45**, 0 skipped; у виводі були нешкідливі попередження Vite WebSocket про зайнятий порт 24678. |
| `frontend/npm run build` | **PASS** — `tsc --noEmit` і Vite production build. |
| `backend/python -m pytest -q` системним Python | **NOT RUN** — системний Python 3.14 не має pytest. |
| Backend prototype/full pytest через `work/audit-venv` | **PASS — 384 passed, 1 Starlette/httpx deprecation warning, 69.83s** з `PYTHONUTF8=1`, поза socket-restricted sandbox; тільки тимчасові синтетичні БД. |
| Browser E2E | **PASS — 12/12** із локальними Uvicorn/Vite, Chromium та синтетичними БД; включено Official UI і каталог 2.1.0. |
| Прямі безмережеві synthetic smoke check | **PASS** — перевірено відсутність user/token/IP/timestamp поля у response set, відсутність code→response посилання, одноразовий replay reject, окреме збереження 12 офіційних та 12 експертних відповідей, час і дії audit та фіналізацію. Усі створені дані були синтетичними й лежали у тимчасовій БД. |
| Production schema/migration, ingress logs, live suppression, retention purge | **NOT RUN / BLOCKED** — навмисно не торкалися production і немає затвердженого спільного контракту. |

## Відкриті P0/P1 ризики та рішення №5

1. Технічно затвердити окремий DDL/API та нову міграцію після schema 3; перевірити реальні ключі `assessments` на конкретному release baseline.
2. Затвердити retention, k, дозволені зрізи, complementary suppression, доступ до агрегатів і purge/backup/WAL runbook.
3. Визначити anonymous rate-limit/ingress logging без запису сирих IP чи відповідей.
4. Для expert інтеграції затвердити зв’язок із V2 session/2FA, grant/revoke lifecycle, активний assignment на кожен запит, інвалідацію сесій, optimistic concurrency та audit allowlist/retention.
5. Узгодити каталог fixture з 2.1.0 після методичного затвердження; 2.0.0 лишається незмінним.

Пропозиції: [`OFFICIAL_QUESTIONNAIRE_DDL_API_PROPOSAL.md`](OFFICIAL_QUESTIONNAIRE_DDL_API_PROPOSAL.md), [`OFFICIAL_RESPONSE_RETENTION_SUPPRESSION_PROPOSAL.md`](OFFICIAL_RESPONSE_RETENTION_SUPPRESSION_PROPOSAL.md), [`QUESTIONNAIRE_SCHEMA3_COMPATIBILITY_REPORT.md`](QUESTIONNAIRE_SCHEMA3_COMPATIBILITY_REPORT.md), [`EXPERT_ROLE_API_CONTRACT.md`](EXPERT_ROLE_API_CONTRACT.md).
