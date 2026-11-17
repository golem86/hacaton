# Integrity Management Dashboard 2.0 — локальна реалізація

Документ описує ізольоване V2-рішення для цього worktree. Воно не змінює
спільні `/api/*` контракти, командну SQLite-базу або production-сервіси.

## Статус етапів

| Етап | Статус | Результат |
|---|---|---|
| 0. Аудит | PASS | Worktree, auth, БД, localStorage та тести перевірені |
| 1. Авторизація | PASS | Сесії, HttpOnly cookie, CSRF, 2FA, reset, rate limits |
| 2. Персональні API | PASS | Каталог, спроби, чернетки, завершення, історія, статистика |
| 3. Серверне збереження | PASS | Окрема V2 auth SQLite-БД; completed-спроби незмінні |
| 4. Email/2FA | PARTIAL | SMTP-конфігурація і dev outbox; production-провайдер не підключено |
| 5. Анонімний режим | PASS | Окрема БД без user/session/email полів, малий розмір приховується |
| 6. Comparative/Reporting | PARTIAL | Порівняння і JSON report; PDF/XLSX очікують погодженого API/формату |
| 7. Readiness-аудит | PASS локально | Тести проходять; production deployment ще не затверджено |

## Бази даних

- `INTEGRITY_DB` — чинна командна база для організаційних `/api/*` маршрутів.
- `V2_AUTH_DB` — окрема база акаунтів, сесій, OTP/reset challenges, rate limits
  і персональних спроб.
- `V2_ANONYMOUS_DB` — окрема база анонімних відповідей. Таблиця не містить
  `user_id`, email або session ID.

Локальні `*.db` файли виключені з Git. Тести створюють власні тимчасові БД.

## Локальні V2 API

### Auth

- `GET /v2/auth/csrf`
- `POST /v2/auth/register`
- `POST /v2/auth/login`
- `POST /v2/auth/2fa/verify`
- `POST /v2/auth/2fa/resend`
- `POST /v2/auth/password-reset/request`
- `POST /v2/auth/password-reset/confirm`
- `POST /v2/auth/logout`
- `GET /v2/auth/me`
- `GET /v2/auth/dev-mail/latest` — тільки коли `V2_AUTH_DEV_MAIL=1`

Публічна реєстрація завжди створює роль `user`. Роль `admin` створюється лише
локальним bootstrap CLI.

### User

- `GET /v2/user/profile`
- `GET /v2/user/assessments`
- `GET /v2/user/assessments/{assessment_id}`
- `GET /v2/user/attempts`
- `GET /v2/user/attempts/{attempt_id}`
- `POST /v2/user/attempts`
- `PATCH /v2/user/attempts/{attempt_id}` — тільки чернетка
- `POST /v2/user/attempts/{attempt_id}/complete`
- `GET /v2/user/history`
- `GET /v2/user/results`
- `GET /v2/user/stats`

Користувач визначається виключно серверною сесією. `user_id` з клієнта не
приймається як підстава доступу. Завершені спроби не можна змінити або повторно
завершити.

### Anonymous

- `GET /v2/anonymous/assessments`
- `GET /v2/anonymous/assessments/{survey_id}`
- `POST /v2/anonymous/assessments/{survey_id}/responses`
- `GET /v2/anonymous/assessments/{survey_id}/results` — тільки `admin`

Анонімний клієнт використовує `credentials: omit`. Сервер не записує акаунт,
сесію або email разом із відповідями. Якщо кількість відповідей менша за
`V2_ANONYMOUS_MIN_GROUP_SIZE`, кількість і середні значення приховуються.

### Admin analytics/reporting

- `GET /v2/admin/assessments`
- `GET /v2/admin/assessments/{id}`
- `GET /v2/admin/assessments/{id}/results`
- `GET /v2/admin/comparisons?assessment_id=...&comparison_assessment_id=...`
- `GET /v2/admin/reports/{id}` — дозволені агрегати у JSON
- `GET /v2/admin/reports/{id}/export?format=pdf|xlsx` — `501` до погодження
  серверного Reporting API; фальшиві файли не генеруються.

Порівняння повертає лише різниці видимих агрегатів. При `null` або `hidden`
числова різниця також залишається `null`.

## Змінні середовища

```powershell
$env:INTEGRITY_DB = 'C:\path\to\existing\demo-dashboard.db'
$env:V2_AUTH_DB = 'C:\path\to\v2-auth-local.db'
$env:V2_ANONYMOUS_DB = 'C:\path\to\v2-anonymous-local.db'
$env:V2_AUTH_SECURE_COOKIE = '0' # для локального HTTP; у HTTPS — '1'
$env:V2_AUTH_DEV_MAIL = '1'      # лише локальна діагностика
$env:V2_SMTP_HOST = '...'        # production-підключення ще не погоджено
$env:V2_SMTP_PORT = '587'
$env:V2_SMTP_USER = '...'
$env:V2_SMTP_PASSWORD = '...'
$env:V2_SMTP_FROM = 'no-reply@example.test'
```

`V2_CATALOG_NOW` використовується лише тестами для детермінованої перевірки
дедлайнів і не задається у звичайному запуску.

## Локальний запуск

Backend запускається з окремою V2-БД; `seed --reset` для робочої бази не
використовується. Frontend використовує Vite proxy або `VITE_API_BASE_URL`.

```powershell
cd C:\Users\User\hacaton-dashboard-v2-prototype\backend
$env:INTEGRITY_DB = 'C:\Users\User\hacaton-dashboard\backend\demo-dashboard.db'
$env:V2_AUTH_DB = 'C:\Users\User\hacaton-dashboard-v2-prototype\backend\v2-auth-local.db'
$env:V2_ANONYMOUS_DB = 'C:\Users\User\hacaton-dashboard-v2-prototype\backend\v2-anonymous-local.db'
$env:V2_AUTH_SECURE_COOKIE = '0'
$env:V2_AUTH_DEV_MAIL = '1'
& 'C:\Users\User\hacaton-dashboard\backend\.venv\Scripts\python.exe' -m uvicorn app.main:app --app-dir 'C:\Users\User\hacaton-dashboard-v2-prototype\backend' --host 127.0.0.1 --port 8015
```

```powershell
cd C:\Users\User\hacaton-dashboard-v2-prototype\frontend
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:8015'
npm.cmd run dev -- --host 127.0.0.1 --port 5178
```

## Тестування

- Frontend tests: `npm.cmd run test` — PASS.
- TypeScript: `node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json` — PASS.
- Production build: `npm.cmd run build` — PASS.
- Backend: `pytest -q` у тимчасових БД — PASS.
- `git diff --check` — PASS; Git може показувати стандартне LF/CRLF warning.

## Ризики та погодження

Потрібне погодження №2 для production auth, SMTP-провайдера, сесійної політики,
retention і персональних моделей. Потрібне погодження №5 для API-контрактів V2,
анонімної агрегації, Reporting PDF/XLSX, методики персональних показників і
майбутньої інтеграції у `feature/integration`.

До погодження не можна переносити локальні V2 endpoints у shared контракт,
підключати production secrets або трактувати локальні результати як офіційний
Integrity Index.
