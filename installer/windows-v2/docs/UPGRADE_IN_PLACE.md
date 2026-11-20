# V2: оновлення на місці, відкат, резервні копії, секрети

Статус: інструменти для потоку «Caddy, інсталятор, оновлення на місці, резервне копіювання» (V2_HARDENING_CONTRACT.md, розділи 2 і 5).
Перевірено лише локально: статичний розбір, `caddy adapt/validate`, pytest `v2_db_tool`, сухий прогін `-Simulate` на синтетичному
стенді. На сервері DESKTOP-JTGC2SG нічого не запускалося.

Усі скрипти — у `installer\windows-v2\upgrade\`, Windows PowerShell 5.1, від адміністратора, **неінтерактивно** (придатні для SSH):
жодних `Read-Host`, підтвердження — ключами (`-ConfirmVerifiedBackup`, `-ConfirmRestoreFromBackup`, `-Apply`, `-DecisionRef`).
Значення секретів із XML служби ніколи не виводяться і не пишуться в журнали чи докази (лише SHA256 файла цілком).

| Скрипт | Призначення |
|---|---|
| `Update-V2InPlace.ps1` | оновлення коду, venv, БД (явна міграція), dist, Caddyfile; автоматичний відкат |
| `Rollback-V2InPlace.ps1` | відкат успішного оновлення до копії `pre-upgrade-<stamp>` |
| `Register-V2BackupTask.ps1` + `Invoke-V2DailyBackup.ps1` | щоденна копія БД (SYSTEM, 03:30, 14 копій) |
| `Protect-V2Leftovers.ps1` | ACL лише Administrators/SYSTEM для `integrity-v2-abandoned-*`, `V2-tls-staging-*` (без видалення) |
| `Disable-V2InstallLeftoverTasks.ps1` | експорт, зупинка й вимкнення завдань `Codex-V2-*` (без видалення) |
| `Rotate-V2SecretKey.ps1` | ротація `V2_SECRET_KEY` |
| `V2-upgrade-lib.ps1` | спільні функції й адаптери (SCM, ACL, мережа) |
| `sim\*`, `test-upgrade-inplace.ps1`, `test-ops-scripts.ps1` | лише тести (`-Simulate`, `%TEMP%`) |

## 1. Пакет оновлення (готує інтегратор)

```
<PackageDir>\
  backend-src.zip            записи <ReleaseId>/backend/... (увесь backend релізу)
  BACKEND-SHA256.txt         "<sha256>  backend/<шлях>" для КОЖНОГО файлу ZIP — маніфест релізу
  dist.zip + DIST-SHA256.txt (необов'язково) записи dist/...; "<sha256>  dist/<шлях>"
  Caddyfile                  (необов'язково) ШАБЛОН installer\windows-v2\deploy\Caddyfile
  requirements-hashed.txt    (необов'язково) "ім'я==версія --hash=sha256:..." лише для НОВИХ пакетів
  wheels\*.whl               (необов'язково) колеса для requirements-hashed.txt
<APPROVED-SHA256.txt>        окремим каналом: "<sha256>  <ім'я>" для backend-src.zip, BACKEND-SHA256.txt, dist.zip,
                             DIST-SHA256.txt, Caddyfile, requirements-hashed.txt (колеса звіряє pip --require-hashes)
```

Маніфест релізу (байти LF, як у Git):

```powershell
git -c core.autocrlf=false archive --format=zip --prefix=integrity-v2-<sha7>/ -o backend-src.zip <commit> backend
# BACKEND-SHA256.txt — з тих самих байтів (не з робочого каталогу з CRLF):
python -I -c "import zipfile,hashlib,sys; z=zipfile.ZipFile(sys.argv[1]); p=sys.argv[2]+'/'; [print(hashlib.sha256(z.read(n)).hexdigest()+'  '+n[len(p):]) for n in sorted(z.namelist()) if not n.endswith('/')]" backend-src.zip integrity-v2-<sha7> > BACKEND-SHA256.txt
```

Модулі bootstrap (`app/v2_bootstrap_admin.py`, `app/v2_clean_bootstrap_admin.py`) лишаються в ZIP і маніфесті, але **не
розгортаються** в `app\<ReleaseId>` (контракт §5). Зайвий `app\v2_clean_bootstrap_admin.py` у поточному релізі дозволений і не
переноситься.

## 2. Перед запуском

1. `v2_db_tool.py bind-check` на зібраному backend (див. розділ 9): таблиця очікувань = DDL коду.
2. Сухий прогін на стенді: `powershell -File upgrade\test-upgrade-inplace.ps1 -Py <python із trustme> -Caddy <caddy.exe 2.11.9>`.
3. На сервері: обидві служби Running; немає Machine-змінних `UVICORN_*`, `V2_*`, `INTEGRITY_*`, `APP_ENV`, `TRUSTED_PROXIES`,
   `FRONTEND_ORIGINS`, `FORWARDED_ALLOW_IPS`; вільно ≥ 3 ГБ; `C:\Program Files\Python313\python.exe` (для `v2_db_tool`, stdlib, `-I`).
4. Не чіпати `C:\srv\V2-release-TLSFIX5-20261120` — звідти працює завдання `Integrity-V2-TLS-Renewal` (SYSTEM, 04:15).

## 3. Запуск через SSH (неінтерактивно)

```powershell
# оновлення (за замовчуванням обидві служби → Automatic (Delayed Start); -KeepManualStart — залишити Manual)
ssh <admin>@<сервер> powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\srv\V2-release-<id>\installer\windows-v2\upgrade\Update-V2InPlace.ps1 `
  -PackageDir C:\srv\V2-release-<id>\package -ApprovedSums C:\srv\V2-release-<id>\APPROVED-SHA256.txt -ReleaseId integrity-v2-<sha7> `
  -WheelDir C:\srv\V2-release-<id>\package\wheels -Requirements C:\srv\V2-release-<id>\package\requirements-hashed.txt `
  -DecisionRef '<рішення №5>' -ConfirmVerifiedBackup

# перелік кроків (нічого не змінює)
... Update-V2InPlace.ps1 -ListSteps

# відкат успішного оновлення (дані після оновлення ВТРАЧАЮТЬСЯ — БД повертаються до копії перед міграцією)
ssh <admin>@<сервер> powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\srv\V2-release-<id>\installer\windows-v2\upgrade\Rollback-V2InPlace.ps1 `
  -BackupDir C:\srv\integrity-v2\backups\pre-upgrade-<stamp> -DecisionRef '<рішення №5>' -ConfirmRestoreFromBackup [-RestoreStartMode] [-RemoveNewRelease]
```

Версії схем за замовчуванням: з `integrity 3 / auth 1` (сервер TLSFIX5) до `integrity 5 / auth 2` (`-FromIntegrityVersion`,
`-FromAuthVersion`, `-ToIntegrityVersion`, `-ToAuthVersion`). Поточний код — integrity 6 / auth 2: для сервера, встановленого
`clean-install.ps1` поточного релізу ([CLEAN_INSTALL_CURRENT.md](CLEAN_INSTALL_CURRENT.md)), версії передаються явно
(`-FromIntegrityVersion 6 -FromAuthVersion 2 -ToIntegrityVersion <нова> -ToAuthVersion <нова>`).

## 4. Кроки, точки зупинки й коди виходу

| Фаза | Кроки | Що змінюється | Збій |
|---|---|---|---|
| A preflight | `preflight.identity` (адмін, хост, ACL кореня, служби Running, NT SERVICE, залежність Caddy → Tailscale, XML валідний, `--no-proxy-headers` + `TRUSTED_PROXIES`); `preflight.package` (суми з окремого каналу, ZIP = маніфест, вимоги з хешами); `preflight.current-code` (поточний код = маніфест `pkg\<реліз>-backend-src.zip` / `-BACKEND-SHA256.txt`); `preflight.db` (verify + строга схема 3/1, read-only); `preflight.env` (лише імена Machine-змінних); `preflight.space` | нічого | exit **3** |
| B підготовка | `stage.backup-dir` (`backups\pre-upgrade-<stamp>`, лише Administrators/SYSTEM, TEMP дочірніх процесів — тут); `stage.code` (`app\<ReleaseId>` за маніфестом, без bootstrap, явний ACE backend RX, перевірка дерева ACL); `stage.bind-check`; `stage.dist` (`app\frontend\dist.new-<stamp>`, явний ACE Caddy RX); `stage.caddyfile` (`New-V2TargetConfig -UseFileTls` → форма TLSFIX5; `caddy validate`); `stage.venv-copy` (`venv.zip` + маніфест); `stage.config-copies` (байти XML і Caddyfile) | лише нові каталоги/копії | створене прибирається; exit **1** |
| C простій | `stop.caddy`, `stop.backend` (доведена зупинка: дерево процесів, порт, файли БД вільні); `backup.db` (обидві БД: backup API + тест відновлення + строга схема); `xml.workdir` (лише `<workingdirectory>`); `venv.pip` (`pip --isolated install --no-index --require-hashes`, `pip check`, версії, імпорт усіх модулів `app` у release без секрету й без живих БД); `db.migrate` (`python -m app.migrations --apply --confirm-verified-backup`, `APP_ENV=release`, `INTEGRITY_DB`, `V2_AUTH_DB`, **без** `V2_SECRET_KEY`; власні копії міграції з `data\` → `mig\` (і при відкаті теж)); `db.verify` (5/2 строго, відбиток seed-таблиць і ролі без змін); `start.backend` + smoke (`/api/health` 200, `/docs` 401, `/redoc` 404, POST logout 403, `/api/assessments` 200, версії); `swap.dist`; `caddyfile.replace` (на місці — ACL файла зберігається); `start.caddy` + HTTPS smoke за точним SNI (і заголовки CSP / Permissions-Policy / без Server); `startmode`; `finalize` | живий стан | автоматичний відкат: exit **1** (успішно) або **2** (CRITICAL) |

Доказ: `backups\pre-upgrade-<stamp>\UPGRADE-EVIDENCE.json` (кроки, тривалість, результат, SHA256, версії, рядки, `pip freeze` до
оновлення — без секретів) і `UPGRADE-STATE.json` (для `Rollback-V2InPlace.ps1`).

## 5. Які дані змінюються

- `services\backend\integrity-v2-backend.xml`: лише `<workingdirectory>` (перевіряється довжина й read-back; решта байтів, зокрема
  секрети, незмінна; копія — `integrity-v2-backend.xml.orig`).
- `app\<ReleaseId>\backend` — новий каталог; старий `app\<попередній>` лишається (для відкату).
- `venv` — нові колеса (копія до змін — `venv.zip` + `venv-SHA256.txt`).
- `data\integrity_v2.db` 3→5, `data\v2_auth.db` 1→2 (копії до міграції — у каталозі `pre-upgrade-<stamp>`).
- `app\frontend\dist` (попередній — `dist.prev-<stamp>`), `caddy\Caddyfile` (копія — `Caddyfile.orig`).
- Режим запуску обох служб: Automatic (Delayed Start) — після перезавантаження сайт піднімається сам; залежність Caddy → Tailscale зберігається.
  Завдання TLS-поновлення (`Integrity-V2-TLS-Renewal`) приймає Auto і Manual і не залежить від версій БД. Операторські
  `tls\Restart-V2Tlsfix5Verified.ps1` / `tls\Verify-V2Tlsfix5Runtime.ps1` оновлено: Auto (зокрема Delayed) або Manual, версії БД — з
  файлів (`v2_db_tool user-version`, лише записи `SCHEMA_SPECS`) + строга схема, служба `integrity-v2-lm` (якщо є) перевіряється й не
  зупиняється; common і `v2_db_tool.py` беруться з каталогу інсталятора релізу (`-CommonSha256`/`-DbToolSha256` — необов'язкове закріплення).

## 6. Відкат і що робити при збої

- **exit 1, `FAILED_ROLLED_BACK`**: зворотний порядок — режим запуску, зупинка служб, Caddyfile, dist, БД з перевіреної копії
  (`RESTORE-IN-PROGRESS` → `RESTORE-OK`; на час відновлення backend `Disabled`), venv із ZIP, XML із копії, старт backend + smoke,
  старт Caddy + HTTPS smoke, видалення створеного (`app\<ReleaseId>`, `dist.new-*`, маніфест у `pkg`). Причина — у `Error` доказу.
- **exit 1, `FAILED_NOTHING_CHANGED`** (фаза B): живий стан не змінювався.
- **exit 2, `ROLLBACK_INCOMPLETE`** (CRITICAL): служби, які небезпечно запускати, лишаються зупиненими. Порядок дій:
  1. `UPGRADE-EVIDENCE.json` → `Rollback[]`: який крок упав.
  2. `data\RESTORE-FAILED-*.txt` — БД у частковому стані; backend `Disabled`. Відновити вручну:
     `python -I -B v2_db_tool.py restore <pre-upgrade>\integrity_v2.db data\integrity_v2.db --expect-version 3 --sha256 <з UPGRADE-STATE> --kind integrity --strict`
     (ціль має не існувати: поточні файли перейменувати на `*.manual-<час>`), те саме для `v2_auth.db` (версія 1);
     після перевірки маркер `RESTORE-FAILED` → `RESTORE-OK-<час>.txt`; `sc.exe config integrity-v2-backend start= demand`.
  3. XML: побайтова копія `integrity-v2-backend.xml.orig` (звірити SHA256 з `UPGRADE-STATE.json`).
  4. venv: `venv.zip` → `venv` (маніфест `venv-SHA256.txt`), `icacls C:\srv\integrity-v2\venv /grant "NT SERVICE\integrity-v2-backend:(OI)(CI)RX"`.
  5. Старт backend, потім Caddy; smoke як у кроці `start.*`.
  Або повторити `Rollback-V2InPlace.ps1` (він перевіряє всі копії до змін).
- **exit 3**: нічого не змінено; виправити причину з виводу.

`Rollback-V2InPlace.ps1` після успішного оновлення: preflight перевіряє копії (SHA256, строга схема, маніфест venv) до будь-яких змін;
далі зупинка, XML, Caddyfile, dist, venv, БД, старт, smoke. Збій → exit 2, fail-closed. `-RemoveNewRelease` прибирає `app\<новий>`
і `dist.failed-<stamp>`; `-RestoreStartMode` повертає режим запуску, зафіксований перед оновленням.

## 7. Щоденне резервне копіювання

```powershell
... upgrade\Register-V2BackupTask.ps1                                   # план, нічого не змінює
... upgrade\Register-V2BackupTask.ps1 -Apply -DecisionRef '<…>' -RunNow  # реєстрація + пробний запуск
```

Завдання `Integrity-V2-DB-Backup`: SYSTEM, щодня 03:30, StartWhenAvailable, без паралельних запусків, ліміт 1 год. Скрипт і
`v2_db_tool.py` копіюються в `C:\srv\integrity-v2\pkg\ops-backup\` (лише Administrators/SYSTEM; корінь V2 не отримує нових
каталогів), SHA256 `v2_db_tool.py` закріплено в аргументах завдання. Кожен запуск: `backups\daily\<yyyyMMdd-HHmmss>\`
(захищений ACL), обидві БД через backup API з тестом відновлення і строгою схемою (версія визначається автоматично —
завдання переживає оновлення схем), `SHA256SUMS.txt`, `DAILY-BACKUP.json`; лишаються 14 останніх **вдалих** копій; журнал
`backups\daily\daily-backup.log` — лише версії, кількість рядків, SHA256. Відновлення з щоденної копії — як у розділі 6, п. 2
(`v2_db_tool restore … --expect-version <з DAILY-BACKUP.json>`), при зупиненому backend.

## 8. Залишки встановлення

- `Protect-V2Leftovers.ps1` — звіт (імена каталогів і принципалів); `-Apply -DecisionRef`: корінь кожного `C:\srv\integrity-v2-abandoned-*`
  і `C:\srv\V2-tls-staging-*` → лише Administrators + SYSTEM без успадкування, власник Administrators; нащадки — `icacls /reset /T`,
  `/setowner /T`; повторна інвентаризація кожного об'єкта. Нічого не видаляється. `V2-release-TLSFIX5-*`, `V2-tls-maintenance`,
  `V1-recovery-*`, живий корінь — ніколи. Reparse point у дереві → ціль пропускається.
- `Disable-V2InstallLeftoverTasks.ps1` — звіт; `-Apply -DecisionRef`: експорт XML у `backups\tasks-<stamp>\`, `Stop-ScheduledTask`
  (закриває вікно `Codex-V2-TLSFIX5-Interactive-*`), `Disable-ScheduledTask`. Лише `Codex-V2-*`; `Integrity-V2-*` заборонено.
- Видалення залишків (зокрема копій живого TLS-ключа) — окреме рішення людини після `Protect-V2Leftovers`.

## 9. Таблиця очікувань схем і закріплені SHA

`v2_db_tool.py` починається з `SCHEMA_SPECS`: `integrity` 3 (dde86e6), 4 (main-final), 5 (посилення — фактичний DDL, bind-check OK на 0221a70), `auth` 1
(dde86e6), 2 (фактичний _SCHEMA, bind-check OK). Твердження контракту (`contract`) перевіряються незалежно від DDL, функціональні — на копії в пам'яті
(ролі `data_officer`, append-only тригери, `instance_meta`). SHA256 файлів-джерел схеми **не закріплено в коді**: `bind-check`
бере їх із маніфесту релізу (`BACKEND-SHA256.txt`) і звіряє DDL коду (auth — `_SCHEMA` через ast; integrity — `create_all` коду
релізу через `--release-py`) з таблицею:

```powershell
python -I -B installer\windows-v2\v2_db_tool.py bind-check --kind auth --expect-version 2 --release-backend <...\backend> --release-manifest BACKEND-SHA256.txt
python -I -B installer\windows-v2\v2_db_tool.py bind-check --kind integrity --expect-version 5 --release-backend <...\backend> --release-manifest BACKEND-SHA256.txt --release-py <python із SQLAlchemy>
```

Для довідки (історично закріплене значення release dde86e6): `backend/app/v2_auth.py` SHA256 `cbb529ce…a92086` — тепер лише з
маніфесту. Міграція, що перебудовує таблицю, має робити це 12-кроковою процедурою SQLite (нова таблиця → копія → DROP старої →
RENAME нової): `ALTER TABLE <стара> RENAME` переписує FK інших таблиць на тимчасове ім'я — це ловить перевірка I08/A08.
`mark-synthetic` пише `instance_meta('dataset','synthetic')` лише за критеріями інсталятора (маркер `CREATED-BY-V2-INSTALL.txt`,
відбиток seed = еталону, напр. `--reference-db backups\integrity_v2-initial-<ts>.db`, у `v2_auth` лише адміністратори).

## 10. CSP і Caddy

- SPA: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; manifest-src 'self';
  worker-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'` — перевірено на
  dist schema3 і dist main-final 759ce5c (`/sysmints-emblem.svg` — звичайний файл dist, `image/svg+xml`, `nosniff`; inline-скриптів,
  стилів і data:-ресурсів немає). Нова збірка: `test-caddy-config.ps1 -DistZip <zip>` (C10).
- `/docs`: `script-src 'self' 'sha256-j26QUmdeIv6qLr1lMyU70hyt2TXZ/RrAZkwhSPlhaUA='` — хеш вбудованого скрипта сторінки
  `get_swagger_ui_html` FastAPI 0.163.1 з параметрами `api_docs.swagger_ui`; `style-src 'self' 'unsafe-inline'` (Swagger UI).
  Зміна FastAPI або параметрів Swagger → перерахувати (`test-caddy-config.ps1` C7 друкує фактичний хеш) і оновити шаблон.
- Журнал `default` без `http.log.error`, `http.handlers.reverse_proxy`, `http.stdlib` (IP і URI запитів, TLS handshake від IP);
  access log не вмикається. `request_body max_size 256KB` для `/api/*`, `/v2/*` (backend має власний ліміт 64 KiB).
  `reverse_proxy … transport http { keepalive 4s }` — коротше за keep-alive uvicorn (5 с), щоб не повторювати рідкісні 502 на POST.
- Генератор: `New-V2TargetConfig` читає й пише Caddyfile як UTF-8 без BOM (раніше cp1251 → подвійне кодування коментарів у
  живому файлі SHA256 D4DFF6…5ABF; на роботу Caddy не впливало).

## 11. Секрети

**Рішення щодо DPAPI — не застосовувати.** `V2_SECRET_KEY` і `V2_SMTP_*` лишаються в XML служби з ACL: Administrators/SYSTEM —
FullControl, `NT SERVICE\integrity-v2-backend` — лише читання.
- DPAPI LocalMachine: розшифрувати може будь-який процес на машині; захист зводиться до ACL файла з блобом — не більший за ACL XML.
- DPAPI CurrentUser віртуального облікового запису служби: блоб треба створити в контексті служби (окремий запуск від
  `NT SERVICE\integrity-v2-backend`), backend мусить уміти розшифровувати (зміна коду поза цим потоком), WinSW передає змінні з XML
  відкритим текстом, а відновлення на іншій машині/профілі неможливе без повторного шифрування — ускладнює DR без реального виграшу
  проти адміністратора, який однаково керує службою.
- Компенсація: суворий ACL XML; копії XML лише в каталогах Administrators/SYSTEM; `Protect-V2Leftovers.ps1` для старих XML;
  ротація нижче; значення ніколи не виводяться скриптами.

**Ротація `V2_SECRET_KEY`** (`Rotate-V2SecretKey.ps1 -Apply -DecisionRef '<…>'`): 48 випадкових байтів → base64; заміна лише значення
в XML; перезапуск backend; smoke. Ефект: недійсні CSRF-токени й незавершені OTP (2FA, скидання пароля), сесії лишаються. Збій →
XML повертається побайтово, старий ключ. Після перевірки видаліть `backups\secret-rotation-<stamp>\integrity-v2-backend.xml.orig`
(містить старий ключ) — окремим рішенням.

**Ротація облікових даних SMTP** (провайдер пошти; значення не передаються через SSH-аргументи й журнали):
1. У провайдера створити новий пароль застосунку для скриньки `V2_SMTP_USER` (старий поки не відкликати).
2. На сервері в **інтерактивній** консолі адміністратора (не SSH-команда з аргументами): прочитати пароль як `SecureString`
   (`Read-Host -AsSecureString`), перетворити в BSTR лише в пам'яті, XML-екранувати (`[Security.SecurityElement]::Escape`),
   замінити ТІЛЬКИ значення `V2_SMTP_PASSWORD` у `services\backend\integrity-v2-backend.xml` (той самий принцип, що
   `Set-V2UpXmlEnvValue`: решта байтів незмінна), обнулити BSTR (`ZeroFreeBSTR`). Перед заміною — копія XML у `backups\` (ACL адмінів).
3. Перезапустити backend (`Stop-Service`/`Start-Service` або `Rotate`-подібна послідовність), перевірити надсилання коду 2FA
   тестовому адміністратору.
4. Відкликати старий пароль у провайдера. Старі XML (копії, `integrity-v2-abandoned-*` — там чинний на 20.11 пароль SMTP) після
   цього містять відкликане значення; захистити/видалити за розділом 8.

## 12. Обмеження

- На реальному сервері не запускалося; адаптери SCM/ACL/HTTP перевірені лише симуляцією та попереднім кодом TLSFIX5.
- `SCHEMA_SPECS` для integrity 5 і auth 2 звірено з кодом (bind-check OK); БД, створені кодом релізу 3/1 і мігровані новим кодом у release, проходять строгі перевірки 14/14.
- Clean Install оновлено під поточний реліз ([CLEAN_INSTALL_CURRENT.md](CLEAN_INSTALL_CURRENT.md)): пакет того самого формату, що й
  пакет оновлення (`deploy\Build-V2CleanPackage.ps1`), БД integrity 6 / auth 2 (`$V2ReleaseSchema`, `$V2DbSet`), `mark-synthetic`,
  маніфест коду в `pkg\<ReleaseId>-BACKEND-SHA256.txt` (його бере `preflight.current-code`), служби Automatic (Delayed Start),
  Gmail SMTP, `-WithLm`. Справжнього прогону на Windows-хості ще не було.
- Відкат БД повертає стан на момент `backup.db`: дані, записані після оновлення, втрачаються (саме тому `-ConfirmRestoreFromBackup`).
- Шляхи pip у venv близькі до MAX_PATH; на сервері (`C:\srv\integrity-v2`) запас достатній, у тестах — короткі імена каталогів.
