# V2 Hardening — спільний контракт змін (auth schema 2, integrity schema 5)

> Контракт написано для integrity schema 5. Далі схема зросла до 6 (Додаток В) і 7 (`user_units` для «Результатів підрозділу»); правила ролей і захисту з цього документа діють і в чинній версії (`6629c74`).

Статус: робочий контракт для паралельних потоків виправлень за аудитом backend 20.11.2026.
База: `feature/integration` = стан сервера TLSFIX5 + злиття `integration/main-final` (frontend, Recommendations Tracker, звіти PDF/XLSX).
Після інтеграції зміст переноситься в `docs/API_CONTRACT.md`. Потоки самі `API_CONTRACT.md` не редагують.

## 1. Ролі

| Роль | Хто | Може | Не може |
|---|---|---|---|
| `user` | самореєстрація | власний кабінет `/v2/user/*` | усе адміністративне |
| `admin` | bootstrap або **лише власник сервера** командою на сервері | цикли (створення, активація, закриття), результати, аналітика, журнал, звіти, `/docs`, перегляд користувачів та історії ролей, завершення сесій `user` і `data_officer`, **а також усі права `data_officer`**: видача кодів доступу й участь | змінювати будь-чиї ролі у вебі; завершувати сесії іншого `admin` |
| `data_officer` | **лише власник сервера** командою на сервері | видавати коди (`POST /api/assessments/{id}/tokens`), бачити участь (`GET …/participation`) | результати, аналітику, журнал, звіти, `/docs`, `/v2/user/*` |

Обидві привілейовані ролі (`admin` і `data_officer`) призначає й знімає лише власник сервера:
`python -m app.v2_role_cli set-role --email … --role admin|data_officer|user [--confirm]` або
`installer/windows-v2/ops/Set-V2UserRole.ps1 -Email … -Role … [-Apply]`. Запис `v2_role_changes` з `actor_user_id = 0`
і подія `user.role_change` з `actor_role = "server"`. У вебі `POST /v2/admin/users/{id}/role` для будь-якої зміни, де стара
або нова роль `admin` → 403 `admin_role_server_only`, `data_officer` → 403 `data_officer_role_server_only` (перевірка в
маршруті й повторно в транзакції). Оскільки третя роль лише `user`, зміна ролі у вебі фактично недоступна; UI показує роль
лише для читання. Один акаунт має одну роль. Роль читається з `v2_users` на кожен запит.

### 1.1. Атака n−1: що закрито і що свідомо прийнято (рішення власника)

Атака n−1: той, хто знає, кому видано коди, і бачить результати групи з n відповідей, може дізнатися відповіді однієї
людини (наприклад, видати k−1 кодів собі чи підставним особам, заповнити їх відомими відповідями й відняти їх від
агрегату). Захист від неї вимагав би, щоб коди видавав той, хто не бачить результатів.

- **Закрито — самопідвищення у вебі.** Адміністратор не може через веб створити собі чи іншому акаунту роль
  `data_officer` або `admin`: зареєструвати другий акаунт, підвищити його до `data_officer` і видавати коди «чужими
  руками» неможливо — другий акаунт нічого не дає. Сценарій «адмін реєструє другий акаунт → підвищує до data_officer →
  видає собі k−1 кодів → відновлює відповіді відніманням» закрито.
- **Не закрито й свідомо прийнято власником.** `admin` має всі права `data_officer`: сам видає коди й бачить
  результати. Отже, атака n−1 **доступна будь-якому адміністратору**. Власник прийняв цей ризик, щоб не залежати від
  окремої ролі під час роздачі кодів.
- **Запобіжники (залишковий захист):**
  - адмінів (і відповідальних за коди) призначає лише власник сервера — контрольоване коло людей;
  - кожна видача кодів — подія журналу `tokens.issue` з роллю, `actor_user_id` і кількістю (без самих кодів),
    видно, хто, коли й скільки кодів видав для циклу;
  - append-only журнал `v2_role_changes` (хто й коли отримав роль);
  - поріг k (`min_group_size`, ≥ 5) і первинне/вторинне приховування малих груп; у відкритому циклі участь округлена;
  - організаційна вимога: власник сервера й адміністратори — різні люди; змова адміністратора з власником сервера —
    залишковий ризик поза межами технічного захисту.

Самореєстрація завжди створює `user`.

## 2. Схеми БД

### V2_AUTH_DB → `user_version = 2`
- `v2_users.role CHECK (role IN ('user','admin','data_officer'))` — перебудова таблиці в одній транзакції з перевірками кількості рядків, `foreign_key_check`, `integrity_check`.
- Нова таблиця `v2_role_changes(id, actor_user_id, target_user_id, old_role, new_role, changed_at)` з тригерами append-only (UPDATE/DELETE заборонені).
- Інших змін структури немає. Ліміти зберігаються в наявній `v2_rate_limits`.
- Міграція 1→2 виконується лише явно: `python -m app.migrations --apply --confirm-verified-backup`. `init_auth_db()` та bootstrap у release існуючу БД не мігрують.
- Захист від майбутньої схеми: версія > 2 → відмова без змін.

### INTEGRITY_DB → `user_version = 5`
- Версія 4 уже зайнята гілкою `integration/main-final` (таблиця `recommendation_actions`, Recommendations Tracker, створюється через create_all). Посилення — це крок 4→5; ланцюжок 0→1→2→3→4→5 має працювати.
- `access_tokens.token` → `access_tokens.token_hash` (SHA-256 hex коду). Наявні коди хешуються під час міграції 4→5.
- `audit_events.actor_user_id INTEGER NULL` (id з V2_AUTH_DB, без email та імені).
- Нова таблиця `instance_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)`. Seed пише `('dataset','synthetic')`.
- Міграція 4→5: резервна копія, одна транзакція, перевірки кількості рядків, FK та integrity, відкат при помилці.

## 3. API

### Нове або змінене в auth
- `POST /v2/auth/logout-all` — сесія + CSRF; видаляє всі сесії поточного користувача. Відповідь 200 `{"status":"logged_out_all"}`.
- `GET /v2/admin/users` — admin, без параметрів: `[{id, name, role, email_masked, created_at}]` (до 500).
- `POST /v2/admin/users/lookup` — admin + CSRF; тіло `{"email": "..."}` (extra=forbid) → 200 `{id, name, email, role, created_at}` або 404. Email навмисно передається в тілі, а не в URL, щоб не потрапляти в журнали й історію.
- `POST /v2/admin/users/{id}/role` — admin + CSRF; тіло `{"expected_role","new_role"}`, ролі `user|admin|data_officer`, `extra=forbid`.
  Успішної зміни у вебі фактично немає: ролі `admin` і `data_officer` призначає лише власник сервера (розділ 1).
  - 403 `admin_role_server_only`: стара або нова роль (або поточна роль цілі в транзакції) — `admin`; без змін.
  - 403 `data_officer_role_server_only`: те саме для `data_officer`; без змін.
  - 403 `self_change`: спроба змінити власну роль.
  - 409: `expected_role` не збігся або роль уже така сама.
  - 404: користувача немає.
  - 422: id поза межами `1..2^63-1`.
  - Серверна зміна ролі (і будь-яка дозволена) — в одній транзакції `BEGIN IMMEDIATE`: оновлення ролі, видалення ВСІХ сесій цілі (включно з pending), гасіння відкритих challenge цілі, запис `v2_role_changes`.
- `POST /v2/admin/users/{id}/revoke-sessions` — admin + CSRF → 200 `{"revoked": n}` для `user`, `data_officer` і власних сесій; для іншого `admin` → 403 `admin_role_server_only`.
- `GET /v2/admin/role-changes` — admin, до 500 останніх записів.

### Поведінка auth
- Pending-сесія до 2FA живе 15 хвилин. Verified-сесія — 12 годин (абсолютний строк).
- `2fa/verify` атомарний: одна транзакція `BEGIN IMMEDIATE`, у якій:
  - pending-сесія існує й не verified;
  - `UPDATE … SET consumed=1 WHERE id=? AND consumed=0 AND attempts<5` із rowcount 1;
  - pending-сесія видаляється з rowcount 1;
  - створюється verified-сесія.

  Для одного challenge — не більше 5 перевірок коду навіть за паралельних запитів.
- Блокування 2FA для акаунта: 10 невдалих кодів за 24 год → 429 на verify, resend і на видачу коду під час login. Подія `auth.2fa_lockout`.
- Скидання пароля:
  - Не більше 5 кодів на акаунт за 24 год (плюс наявний ліміт 3/15 хв на email|IP).
  - Не більше 10 невдалих підтверджень на акаунт за 24 год.
  - Підтвердження атомарне: в одній транзакції споживається код, оновлюється пароль, видаляються всі сесії й гасяться інші challenge.
  - Відповідь на запит коду однакова й однаково швидка для всіх випадків, щоб не розкривати акаунт: маршрут лише ставить завдання у фонову чергу (`app/v2_mail_queue.py`, один воркер, обмежена черга — при переповненні завдання відкидається); пошук акаунта, ліміти, лист і збереження коду виконує воркер, помилки SMTP лише логуються назвою класу (без email).
- Час відповіді login і register не залежить від існування email: для невідомого email виконується фіктивне обчислення scrypt.
- OTP зберігається як `HMAC-SHA256(V2_SECRET_KEY, "otp:{purpose}:{user_id}:{code}")`.
- scrypt: N=2^17, r=8, p=1, maxmem 256 MiB. Старі хеші перевіряються за параметрами з рядка й переобчислюються після успішного входу.
- `rotate_session_after_2fa` без наявної pending-сесії не видає нову сесію.

### Поведінка даних
- `POST /api/assessments/{id}/tokens` — `admin` і `data_officer` (інші → 403; ризик n−1 для admin прийнято, розділ 1.1). Подія `tokens.issue` з `actor_role`, `actor_user_id` і `count`. Відповідь не змінюється (`{"tokens":[…]}`): відкриті коди повертаються один раз і зберігаються лише як хеш.
- `GET /api/assessments/{id}/participation` — `admin` і `data_officer`.
  - У відкритому циклі `responses_total` і `tokens_unused` округлюються вниз до кратного 5 (і лише якщо ≥ k), прапорець `counts_exact: false`.
  - У закритому циклі значення точні, `counts_exact: true`.
- Результати й участь за підрозділами: приховані клітинки не перелічуються взагалі (ні назви категорії, ні підрозділу). У кожному розрізі є булеве `suppressed: true|false`.
- `GET /api/assessments` і `GET /api/assessments/{id}`: анонімний користувач і `user` не бачать `draft` (для чернетки — 404). Сесія `admin` бачить усе.
- Ліміт тіла запиту: 64 KiB для JSON (`V2_MAX_BODY_BYTES`), понад ліміт — 413 до читання всього тіла. Відповіді 422 не повертають `input` і `ctx`.
- Цілі параметри шляху й запиту обмежені `1..2^63-1`; поза межами — 422, а не 500.
- Аналітика демо в release працює лише за `INTEGRITY_ANALYTICS_DEMO=1` і `instance_meta.dataset = synthetic`, інакше 503.
- `python -m app.seed` у release відмовляє. Перевірка версії виконується до `drop_all`. `--reset` робить перевірену резервну копію.
- `check_schema` не створює файл БД і звіряє колонки з моделями.
- `create_engine(..., hide_parameters=True)`.

### Налаштування release (`settings.validate_release_config`)
- `TRUSTED_PROXIES` має бути непорожнім.
- `V2_CATALOG_NOW` заборонено.

## 4. Журнал дій (`audit.record`)

Сигнатура: `record(db, actor_role, action, assessment_id=None, actor_user_id=None, **details)`.

Нові дозволені дії: `auth.logout`, `auth.logout_all`, `auth.password_reset`, `auth.2fa_lockout`, `user.role_change`, `user.sessions_revoke`. Деталі — лише дозволені числові поля. Email, імена, коди й IP у журнал не потрапляють.

Тимчасово, до злиття потоку даних, `actor_user_id` приймається, але не зберігається. Потік даних додає колонку й прибирає цю заглушку.

## 5. Інфраструктура
- Caddy:
  - журнали не містять IP і URI анонімних подань (вимкнено `http.log.error` або відфільтровано поля);
  - CSP для SPA, окремий CSP для `/docs`;
  - `request_body max_size` для `/api/*` і `/v2/*`;
  - `transport http { keepalive 4s }` до backend.
- Оновлення на місці:
  - `Update-V2InPlace.ps1`: preflight, перевірена резервна копія, зупинка служби, розгортання за SHA-маніфестом, явна міграція, строгі перевірки, старт, smoke;
  - `Rollback-V2InPlace.ps1`.
- `v2_db_tool.py`: перевірки auth schema 2 та integrity schema 4, backup і restore з новими версіями, команда `mark-synthetic`.
- Щоденне резервне копіювання робочих БД із перевіркою відновлення й ротацією.
- Модулі bootstrap не розгортаються в `app\`.
- Каталоги покинутої спроби та TLS-staging: доступ лише для Administrators і SYSTEM (без видалення).
- Секрети лишаються в XML служби із суворим ACL; додається процедура ротації. Обґрунтування відмови від DPAPI — у документації інсталятора.

## 6. Recommendations Tracker і звіти (з `integration/main-final`)
- `GET /api/assessments/{id}/tracker` — ролі аналітики (admin). Зміни `POST …/tracker/decisions` і `POST /api/tracker/{action_id}/transition` — лише admin + CSRF (як і раніше).
- Цілі параметри шляху цих маршрутів також обмежуються `1..2^63-1` (потік даних).
- Події трекера в журналі передають `actor_user_id`, якщо principal — сесія.
- `GET /v2/admin/reports/{id}/export?format=pdf|xlsx` — admin (потік auth зберігає цю поведінку під час змін `v2_admin.py`).
- Нові залежності backend: `reportlab==5.1.0`, `xlsxwriter==3.3.3`. Їх треба встановити у venv сервера з перевіреними хешами.
