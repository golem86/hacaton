# Docker Compose V2: локальна синтетична демонстрація

Це середовище призначене **лише для одного локального розробника/демонстратора**. Воно не є production deployment: використовується HTTP на `127.0.0.1`, не-Secure cookie й локальна dev-скринька для тестового 2FA. 2FA, CSRF, перевірка Origin і права доступу залишаються ввімкненими. Жодна робоча БД або зовнішній SMTP не підключається.

## Вимоги та підготовка

- Docker Engine / Docker Desktop із плагіном Compose v2 та доступом до Docker Hub. На хості Python, Node і pnpm не потрібні.
- Вільний локальний TCP-порт 8080 (або змініть `DOCKER_DEMO_PORT` у `.env`). Перед запуском перевірте, що немає чужого Compose-проєкту з іменем `integrity-v2-local-demo`; цей пакет не керує чужими контейнерами чи volumes.
- Працюйте з **окремою копією коду**, не з production-сервером. Не копіюйте робочі SQLite, ключі, OTP чи SMTP credentials.

У корені копії створіть локальний `.env` із шаблону:

```powershell
Copy-Item .env.example .env
$demoBytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($demoBytes)
$demoSecret = ([BitConverter]::ToString($demoBytes)).Replace('-', '').ToLowerInvariant()
(Get-Content .env) -replace '^V2_SECRET_KEY=.*$', "V2_SECRET_KEY=$demoSecret" | Set-Content .env
Remove-Variable demoBytes, demoSecret
```

`V2_SECRET_KEY` є обов'язковим і має бути випадковим (щонайменше 32 символи). Зберігайте той самий ключ для повторного запуску, щоб чинні локальні сесії не втратили CSRF-підпис. `.env` уже ігнорується Git і виключений із Docker build contexts. Не передавайте його іншому розробнику: він створює власний. `VITE_API_BASE_URL` лишається порожнім — браузер звертається до відносних `/api/*` і `/v2/*` на тому самому origin. `VITE_API_PROXY_TARGET` у шаблоні стосується лише окремого запуску Vite без Docker; у Docker build `.env` не копіюється.

## Перший запуск

```powershell
docker compose config --quiet
docker compose up --build
```

`config --quiet` перевіряє Compose без виведення розгорнутих значень `V2_SECRET_KEY`. Не зберігайте повний `docker compose config` у загальнодоступному журналі. Backend під час старту виконує чинний `python -m app.seed` **без `--reset`**: він заповнює тільки нову порожню синтетичну БД в окремому named volume. За наявності даних seed відмовляється їх перезаписувати, після чого стартує FastAPI з чинними міграціями development. У volume `demo_data` зберігаються дві незалежні SQLite: `/data/integrity.db` і `/data/v2_auth.db`. Frontend чекає на healthcheck backend.

Відкрийте `http://127.0.0.1:8080/` (або ваш порт); Survey — `/survey`. Перевірте з іншого термінала:

```powershell
(Invoke-WebRequest 'http://127.0.0.1:8080/api/health').StatusCode
(Invoke-WebRequest 'http://127.0.0.1:8080/api/assessments').StatusCode
(Invoke-WebRequest 'http://127.0.0.1:8080/api/units').StatusCode
```

Очікується HTTP 200. Список циклів, анкета й підрозділи — публічні GET. `/docs` і `/openapi.json` без підтвердженої admin-сесії мають відмовляти за чинним контрактом (у базовому V2 — 401); через Caddy вони проксовані на backend зі збереженням шляху. Caddy також проксує `/v2/*`. Жодного backend-порту на хості немає.

## Локальний адміністратор і тестовий 2FA

Після запуску в окремому терміналі створіть **лише вигаданий** admin-акаунт через чинний CLI. Він приховано запитає пароль двічі:

```powershell
docker compose exec backend python -m app.v2_bootstrap_admin --name 'Local Demo Admin' --email 'demo-admin@example.test'
```

У браузері відкрийте `http://127.0.0.1:8080/login`, введіть цей локальний email і пароль. Backend видає справжній тестовий OTP через чинний dev-mail механізм (лише `APP_ENV=development` і `V2_AUTH_DEV_MAIL=1`). Код можна прочитати **тільки всередині власного backend-контейнера**:

```powershell
docker compose exec backend python -c "from app.v2_auth import latest_dev_mail; print(latest_dev_mail('demo-admin@example.test')['body'])"
```

Не копіюйте OTP в issue, чат, загальний журнал чи URL. Це не обхід 2FA: введіть отриманий код у звичайну форму підтвердження. Публічний запит через proxy до `/v2/auth/dev-mail/latest` не повинен відкривати тестову пошту: backend приймає його лише від локального peer. Перевірте, що Dashboard доступний лише після 2FA, а Swagger `/docs` — тільки admin із завершеною 2FA.

## Survey та перевірка анонімності

Відкрийте `/survey` у приватному вікні без сесійних cookie. Виберіть відкритий синтетичний цикл, категорію й підрозділ, заповніть 14 питань. Одноразовий **синтетичний** код видає чинний admin-інтерфейс «Тестування» після 2FA; передайте його тестовому респонденту поза браузерним URL. Код передається лише в JSON-тілі POST, не вводиться в query string або журнали. Успіх — HTTP 201 зі `status: accepted`; повторне використання коду має відхилятися. Якщо підтвердження POST втрачено, не повторюйте його без окремої перевірки: UI блокує повтор у цьому екземплярі форми.

Керування кодами й закриттям циклу потребує admin-сесії та чинного CSRF-токена. Caddy обслуговує браузер з одного origin, тому cookie є host-only, а `Origin` збігається з `FRONTEND_ORIGINS`. Без HTTPS у цьому **локальному HTTP** режимі cookie не мають прапорця Secure; не відкривайте порт поза `127.0.0.1` і не використовуйте це налаштування в release.

## Перезапуск, збереження та очищення

```powershell
docker compose down
docker compose up --build
```

`down` без `--volumes` зберігає **лише цей проєктний named volume**; повторний seed без `--reset` не перезаписує дані. Перевірте, що синтетичний цикл і створений локальний admin залишилися. Для звичайної зупинки контейнерів використовуйте `docker compose down`.

**Необоротне очищення тільки власного демо-volume:** перевірте `docker compose ls` і `docker volume ls`, що проєкт `integrity-v2-local-demo` та його `demo_data` створені саме цією копією. Лише після цього, якщо ці синтетичні дані більше не потрібні:

```powershell
docker compose down --volumes
```

Команда видалить обидві SQLite та локальні admin-сесії з **цього** volume. Не запускайте її для чужого Compose-проєкту або будь-якої робочої БД. Не підключайте production bind mounts.

## Маршрути, proxy і обмеження

Мінімальний runtime Caddy подає зібраний Vite frontend і проксує `/api/*`, `/v2/*`, `/docs*` та `/openapi.json` без зняття префікса. За [документацією Caddy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) `reverse_proxy` передає `Host`, формує `X-Forwarded-For/Proto/Host` і за замовчуванням ігнорує підроблені вхідні `X-Forwarded-*`. Backend має `TRUSTED_PROXIES` порожнім: він **не довіряє** довільному forwarded IP. Наслідок — rate limiting може сприймати всіх локальних браузерів за IP Caddy; це залишкове обмеження багатокористувацького демо. Не встановлюйте широкі trusted-proxy CIDR без окремого проєктування.

Локальні базові образи Docker задані тегами, а не незмінними digest; образи та Docker Engine відсутні на машині автора пакета, тому фактичні `docker compose config/build/up`, права запису named volume й проксування в контейнерах **не перевірені**. Перед командним прийняттям пакет слід прогнати на Docker-хості. Не використовуйте його для production.

### Troubleshooting

| Симптом | Що перевірити |
|---|---|
| `docker` не знайдено / daemon недоступний | Встановити й запустити Docker Engine/Desktop та Compose plugin; на машині автора Docker не був доступний. |
| `V2_SECRET_KEY` відсутній | Створити локальний `.env` і випадковий ключ за інструкцією вище. Не вставляти ключ у Compose або Dockerfile. |
| Порт 8080 зайнятий | Перевірити чужі процеси, не зупиняти їх; змінити `DOCKER_DEMO_PORT` у `.env` і відкрити нову адресу. |
| Backend unhealthy / немає прав на `/data` | Переглянути `docker compose ps` та локальні logs без копіювання кодів; перевірити власника тільки цього named volume. Без Docker-хоста цю поведінку не було перевірено. |
| Після restart seed не змінив БД | Очікувано: seed без `--reset` не чіпає непорожню БД. Не застосовувати `--reset` до збереженого volume. |
| 2FA-пошта не відкривається через браузерний `/v2/auth/dev-mail/latest` | Очікувано: маршрут лише для local peer backend. Використати `docker compose exec backend` як вище. |
| CSRF/Origin 403 | Використати ту саму локальну адресу для браузера й `FRONTEND_ORIGINS`; перевірити CSRF після входу та не ставити сторонній proxy перед Caddy. Не вимикати CSRF/Origin. |
| `/survey` або Dashboard показує старі дані | Переконатися, що браузер відкритий на поточному `127.0.0.1:DOCKER_DEMO_PORT`, а не на чужому сервері; перевірити `docker compose ps`. |
