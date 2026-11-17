# Backend V2 — реалізація за V2 Integration Contract

| | |
| --- | --- |
| Гілка | `feature/v2-backend` від `feature/v2-integration` `4e8b344` |
| Контракт | `docs/V2_INTEGRATION_CONTRACT.md` (затверджено №5) |
| Виконавець | №2 |
| Дата | 17.11.2026 |
| Тести | `cd backend` → `python -m pytest` — **246 passed** (V1-регресія + V2 + 63 негативні тести безпеки) |

Усі перевірки — лише на синтетичних тимчасових SQLite. Робочий сервер і робочу БД не змінювали. Deployment — **ON HOLD**.

## Що зроблено

- **Auth/2FA/сесії** перенесено з прототипу `4d8ccdc` контрольовано, з виправленнями аудиту: ротація сесії після 2FA, CSRF за розділом 3.0, ліміти лише невдалих спроб за `(email, IP)` і за IP, реєстрація без розкриття email.
- **Verified principal** для `/api/*` (`app/roles.py`): роль лише із серверної сесії V2 після 2FA. `X-Role` обробляється тільки в `development` з явним `INTEGRITY_DEMO_XROLE=1` (для регресійних тестів V1); якщо є сесія — ігнорується.
- **Три класи маршрутів** (розділ 2.1): публічні GET Survey; анонімний `POST …/submissions` лише за одноразовим кодом; решта — лише з сесією.
- **CSRF** (`app/request_security.py`): токен прив'язаний до сесії (HMAC), підписаний pre-auth токен, перевірка `Origin`/`Referer`, cookie `__Host-` у Secure-режимі.
- **Режими** (`app/settings.py`): `APP_ENV=development|release`; у `release` сервер не стартує з `INTEGRITY_DEMO_XROLE=1`, `V2_AUTH_DEV_MAIL=1`, `V2_AUTH_SECURE_COOKIE=0` або без `V2_SECRET_KEY` (≥ 32 символи).
- **MIG-1**: у `release` БД лише перевіряються; міграція — явною командою `python -m app.migrations --apply --confirm-verified-backup`.
- **MIG-4**: `V2_AUTH_DB` версіонується (`user_version` = 1) з резервною копією, перевірками й відкатом.
- Вилучено `/v2/anonymous/*` і дублікати `/v2/admin/assessments*`, `/v2/admin/comparisons`.
- Журнал доступу uvicorn не містить запитів подання анкет (S10).
- Audit Trail: лише `admin`; нові події `auth.login` і `user.create_admin` без email, паролів і кодів.

## Статус acceptance criteria

PASS тут означає: реалізовано і перевірено автоматичним тестом у цій гілці (а для MIG-2/3/5 — ще й ручною перевіркою на копіях БД).

| # | Вимога | Статус | Підтвердження |
| --- | --- | --- | --- |
| S1 | Три класи маршрутів; `X-Role` ні на що не впливає | **PASS** | `test_s1_*`: 4 тести + 32 параметризовані комбінації (8 захищених маршрутів × 4 ролі в `X-Role` без сесії → 401) |
| S2 | Анонімні відповіді лише через Survey API з кодом | **PASS** | `test_s2_*`: `/v2/anonymous/*` → 404; повтор / вигаданий код → 403; закритий цикл → 409; 20 одночасних запитів → рівно 1 × 201 |
| S3 | dev-mail недоступний у release | **PASS** | `test_s3_*`: release не стартує з dev-прапорцями; маршрут → 404; без SMTP вхід → 503, OTP ніде не зберігається; у development лише локальні запити |
| S4 | CSRF за розділом 3.0 | **PASS** | `test_s4_*`: без токена, токен іншої сесії, токен до ротації, непідписаний pre-auth, чужий `Origin`/`Referer`, release без `Origin`, cookie без `__Host-` → 403/401 |
| S5 | Ownership персональних спроб | **PASS** | `test_s5_*`, `test_v2_personal.py` |
| S6 | Rate limiting без обходу і без блокування чужого акаунта | **PASS** | `test_s6_*`: власник з іншого IP входить; підроблений `X-Forwarded-For` від недовіреної адреси ігнорується; довірений проксі розрізняє клієнтів; 35 успішних входів за однією IP не блокують 36-й |
| S7 | Ротація сесії після 2FA | **PASS** | `test_s7_*`: новий токен, старий → 401 |
| S8 | HTTPS-конфігурація | **PASS** (атрибути cookie) · **NOT VERIFIED** (HTTPS, HSTS, редирект на reverse proxy) | `test_s8_*`: `__Host-`, `Secure`, `HttpOnly`, `Path=/`, `SameSite=Lax`, без `Domain`; стенд з Caddy не перевірявся |
| S9 | Реєстрація не розкриває email | **PASS** | `test_s9_*`: однакова відповідь 202 |
| S10 | Журнали без IP подань | **PASS** (uvicorn) · **NOT VERIFIED** (reverse proxy) | `test_s10_*`; журнал Caddy налаштовує розгортання |
| S11 | Наскрізна анонімність | **PASS** | `test_s11_*`: подання з активною сесією і `X-Role: admin` — анкета без зв'язку з акаунтом, кодом чи сесією; без номера у відповіді; не журналюється; `V2_AUTH_DB` не має таблиць анкет |
| S12 | Захист Audit Trail | **PASS** | `test_s12_*`, `test_audit.py`: лише `admin`, вхід журналюється без email |
| MIG-1 | Без автоматичних змін БД у release | **PASS** | `test_mig1_*`; вручну: release на копії БД версії 1 не стартує, файл незмінний, `V2_AUTH_DB` не створюється |
| MIG-2 | AuditEvent і schema v2 | **PASS** | копії БД, створені кодом V0/V1/V2: схема → 2, `audit_events` є |
| MIG-3 | Наявні дані Survey/Analytics | **PASS** | на тих самих копіях: 804 анкети, 11 256 відповідей, контрольна сума збігається; `/questionnaires`, `/results`, `/index` (48.4), `/audit-events` → 200 через сесію admin |
| MIG-4 | Версіонування `V2_AUTH_DB` | **PASS** | `test_mig4_*`: БД прототипу → версія 1, резервна копія, дані збережено, повторний запуск без змін, release-перевірка відмовляє |
| MIG-5 | Лише копії | **PASS** | усі перевірки на тимчасових БД; робочу БД не відкривали |

## API для frontend (№3)

Повна таблиця — розділ 3 контракту. Що змінилося для клієнта:

| Що | Як тепер |
| --- | --- |
| Роль | **не надсилати `X-Role`**; запити з `credentials: 'include'` (cookie сесії) |
| CSRF | `GET /v2/auth/csrf` → `csrf_token`; заголовок `X-CSRF-Token` на кожен POST/PATCH/DELETE. Після `login` і `2fa/verify` відповідь містить **новий** `csrf_token` — використовувати його |
| Вхід | `POST /v2/auth/login` → `{"requires_2fa": true, "csrf_token": …}` → `POST /v2/auth/2fa/verify` з цим токеном → новий `csrf_token` |
| Реєстрація | `202 {"status": "accepted"}` для будь-якого email (не `201`) |
| Survey | `GET /api/assessments`, `/{id}`, `/{id}/questionnaires`, `/api/units` — без входу; `POST …/submissions` — з `credentials: 'omit'`, лише одноразовий код |
| Коди | `POST /api/assessments/{id}/tokens?count=N` — сесія admin + CSRF |
| Analytics, результати, журнал | ті самі формати; лише сесія `admin` |
| Звіти | `/v2/admin/reports/{id}`; експорт → 501 |
| Вилучено | `/v2/anonymous/*`, `/v2/admin/assessments*`, `/v2/admin/comparisons` |
| Origin | frontend-домен має бути в `FRONTEND_ORIGINS` |

## Налаштування

| Змінна | development (за замовчуванням) | release |
| --- | --- | --- |
| `APP_ENV` | `development` | `release` |
| `INTEGRITY_DB`, `V2_AUTH_DB` | шляхи до SQLite | шляхи до SQLite |
| `V2_SECRET_KEY` | випадковий при старті | **обов'язковий**, ≥ 32 символи |
| `V2_AUTH_SECURE_COOKIE` | `0` | завжди Secure (`0` заборонено) |
| `FRONTEND_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | домен frontend через HTTPS |
| `TRUSTED_PROXIES` | порожньо | IP reverse proxy (Caddy) |
| `INTEGRITY_DEMO_XROLE` | `0` (лише для регресійних тестів V1 — `1`) | заборонено |
| `V2_AUTH_DEV_MAIL` | `0` (для локальної 2FA — `1`) | заборонено |
| `V2_SMTP_*` | — | потрібні для 2FA; лише STARTTLS із перевіркою сертифіката (системні CA) і hostname `V2_SMTP_HOST`, інакше лист не надсилається (503) |
| `INTEGRITY_ANALYTICS_DEMO` | `1` лише на синтетичній БД | лише на синтетичній БД |

Перший адміністратор: `python -m app.v2_bootstrap_admin --name "Admin" --email admin@example.test`.

## Відкриті блокери

| # | Блокер | Для чого блокує | Хто |
| --- | --- | --- | --- |
| 1 | Frontend V2 ще надсилає `X-Role` і не працює з сесією/CSRF | інтеграцію | №3 |
| 2 | SMTP-провайдер і секрети: у release без них 2FA повертає 503 | deployment | №5 |
| 3 | HTTPS, HSTS, редирект, `TRUSTED_PROXIES` і журнал reverse proxy без IP подань (S8, S10) — не перевірено на стенді | deployment | №4, №2 |
| 4 | Release SHA і перевірена резервна копія робочої БД перед явною міграцією | deployment | №5, №4 |
| 5 | Строк зберігання персональних спроб і право видалення | персональні дані в production | №5 |
| 6 | Роль `auditor` | — (за замовчуванням лише `admin`) | №5 |
