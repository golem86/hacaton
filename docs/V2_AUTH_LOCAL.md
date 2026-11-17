# Dashboard V2: локальна автентифікація

Це експериментальний auth-шар лише для worktree `codex/dashboard-v2-prototype`.
Він не змінює контракти `/api/*`, `demo-dashboard.db` або production.

## Запуск

Backend використовує окрему базу, яку задає `V2_AUTH_DB`:

```powershell
$env:INTEGRITY_DB = "C:\Users\User\hacaton-dashboard\backend\demo-dashboard.db"
$env:V2_AUTH_DB = "C:\Users\User\hacaton-dashboard-v2-prototype\backend\v2-auth-local.db"
python -m uvicorn app.main:app --app-dir C:\Users\User\hacaton-dashboard-v2-prototype\backend --host 127.0.0.1 --port 8012
```

Для HTTPS можна встановити `$env:V2_AUTH_SECURE_COOKIE = "1"`; локально на HTTP значення має бути `0`.

## Експериментальні endpoints

- `GET /v2/auth/csrf` — видає double-submit CSRF cookie.
- `POST /v2/auth/register` — створює лише роль `user`.
- `POST /v2/auth/login` — створює серверну сесію в HttpOnly cookie.
- `POST /v2/auth/2fa/verify`, `POST /v2/auth/2fa/resend` — підтвердження входу одноразовим кодом.
- `POST /v2/auth/logout` — відкликає сесію.
- `GET /v2/auth/me` — повертає поточного користувача.
- `POST /v2/auth/password-reset/request`, `POST /v2/auth/password-reset/confirm` — локальне відновлення паролю.
- `GET /v2/auth/dev-mail/latest` — лише при `V2_AUTH_DEV_MAIL=1`, перегляд останнього dev-листа.
- `GET /v2/admin/assessments`, `GET /v2/admin/assessments/{id}`, `GET /v2/admin/assessments/{id}/results` — лише для серверної ролі `admin`.
- `GET /v2/user/profile`, `/assessments`, `/attempts`, `/history`, `/results`, `/stats` — лише для серверної ролі `user`.
- `POST /v2/user/attempts`, `PATCH /v2/user/attempts/{id}`, `POST /v2/user/attempts/{id}/complete` — серверні чернетки та завершення тестування.
- `GET /v2/anonymous/assessments`, `POST /v2/anonymous/assessments/{id}/responses` — окремий анонімний режим без cookie credentials.
- `GET /v2/anonymous/assessments/{id}/results` — агрегати лише для `admin` із захистом малих груп.
- `GET /v2/admin/comparisons`, `/reports/{id}` — дозволені агрегати; PDF/XLSX export повертає `501` до погодження Reporting API.

Перший admin створюється локально CLI-командою з прихованим введенням пароля:

```powershell
python -m app.v2_bootstrap_admin --name "Local Admin" --email admin@example.test
```

Публічна реєстрація не приймає й не встановлює роль `admin`. Старий `X-Role` залишається тільки для сумісності існуючого `/api/*` демо-контракту і не використовується V2 Dashboard.

У персональному тестуванні `Розпочати` одразу відкриває питання, `Завершити` повертає до списку, а доступність і дедлайни надходять із локального V2 endpoint `/v2/user/assessments`. Персональні чернетки й результати зберігаються в окремій V2 auth-БД.

Без `V2_SMTP_HOST` коди OTP/reset записуються в `v2_dev_mail` та консоль backend. Для реальної пошти потрібен погоджений SMTP/transactional-mail провайдер, секрети поза репозиторієм і rate limiting.
