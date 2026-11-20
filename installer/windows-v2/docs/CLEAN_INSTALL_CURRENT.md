# V2: Clean Install поточного релізу (новий сервер з нуля)

Статус: перевірено лише локально (статичні набори, сухий прогін `test-clean-install-current.ps1` у `%TEMP%`, `rehearse-rev3.ps1`).
Справжнє встановлення служб (WinSW, `icacls`, `sc.exe`, Caddy/HTTPS, LM) **не виконувалося** — лише на ізольованому тест-хості
(`-TestHost`) або на сервері після DEPLOYMENT GO (рішення №5).

`clean-install.ps1` ставить **одразу поточний реліз**: БД створюються версій коду (integrity **6** / auth **2**), пакет — того самого
формату, що й пакет оновлення ([UPGRADE_IN_PLACE.md](UPGRADE_IN_PLACE.md) §1), тож далі сервер оновлюється звичайним
`Update-V2InPlace.ps1`.

## 1. Що потрібно

| Що | Звідки |
|---|---|
| Windows PowerShell 5.1 x64, права адміністратора, збірка Windows = `-ExpectedWindowsBuild` | сервер |
| Python 3.13.14 x64 (базовий, не venv) | `C:\Program Files\Python313\python.exe` |
| `integrity-v2-tools-winsw2.12.0-caddy2.11.9.zip` (SHA256 WinSW і Caddy закріплені в common) | артефакт інструментів |
| Пакет релізу `package\` + `APPROVED-SHA256.txt` **окремим каналом** | `deploy\Build-V2CleanPackage.ps1` (розділ 2) |
| Каталог інсталятора того самого коміту: `installer\windows-v2\` | `git archive <commit> installer` |
| TLS-пара Tailscale у `C:\srv\V2-tls-staging-<yyyyMMdd-HHmmss>` (лише Administrators/SYSTEM) + SHA256 сертифіката | `tls\Request-V2TlsPair.ps1` |
| Скринька Gmail проєкту + пароль застосунку Google (16 літер) | Google Account → App passwords |
| (необов'язково) `llama-b12180-bin-win-cpu-x64.zip`, `Qwen3-8B-Q4_K_M.gguf` поза `C:\srv\integrity-v2` | [LOCAL_LM.md](../../../docs/LOCAL_LM.md) |

Вільні порти TCP 80/443/8100/8199, UDP 443; служб `integrity-v2-*` і каталогу `C:\srv\integrity-v2` ще немає.

## 2. Збирання пакета (робоча станція інтегратора, офлайн)

```powershell
# frontend поточного коміту (у frontend\): pnpm install --frozen-lockfile; pnpm build; запакувати dist\ з префіксом dist/
# колеса cp313 win_amd64 — заздалегідь перевірені локальні каталоги (скрипт нічого не завантажує)
powershell -NoProfile -ExecutionPolicy Bypass -File installer\windows-v2\deploy\Build-V2CleanPackage.ps1 `
  -Commit <commit> -DistZip D:\build\integrity-v2-dist-<sha7>.zip `
  -WheelSource 'D:\wheels\wheelhouse-cp313-win_amd64;D:\wheels\new' `
  -Py 'C:\Program Files\Python313\python.exe' -OutDir D:\release-<sha7>
```

Результат: `D:\release-<sha7>\package\` (`backend-src.zip`, `BACKEND-SHA256.txt`, `dist.zip`, `DIST-SHA256.txt`, `Caddyfile`,
`requirements-hashed.txt` — повний набір залежностей із sha256, `wheels\`) і `D:\release-<sha7>\APPROVED-SHA256.txt`.
`backend-src.zip` — `git archive` (байти LF), записи `integrity-v2-<sha7>/backend/…`; маніфести — з байтів ZIP, порядок ординальний.
Для 9ad616f збирач відтворює пакет оновлення `release-9ad616f` побайтово (`backend-src.zip`, `BACKEND-SHA256.txt`, `dist.zip`,
`DIST-SHA256.txt`). `APPROVED-SHA256.txt` передається окремо (інший канал, звірка SHA256 файла з інтегратором).

Перевірка пакета перед перенесенням (без прав адміністратора):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installer\windows-v2\test-clean-install-current.ps1 `
  -Py <python із залежностями backend> -PackageDir D:\release-<sha7>\package -ApprovedSums D:\release-<sha7>\APPROVED-SHA256.txt -ReleaseId integrity-v2-<sha7>
```

## 3. Встановлення (сервер, інтерактивна консоль адміністратора)

Консоль — **інтерактивна** (не SSH-команда): вводяться пароль адміністратора V2 (≥ 10, двічі) і пароль застосунку Gmail (двічі),
обидва приховано (`getpass` / `SecureString`), значення не виводяться і не пишуться в журнали.

```powershell
$R = 'C:\srv\V2-release-<sha7>'          # installer\ і package\ того самого коміту; APPROVED-SHA256.txt — окремим каналом
powershell -NoProfile -ExecutionPolicy Bypass -File $R\installer\windows-v2\clean-install.ps1 `
  -DecisionRef '<рішення №5>' -ExpectedWindowsBuild <збірка> `
  -ToolsZip $R\integrity-v2-tools-winsw2.12.0-caddy2.11.9.zip `
  -PackageDir $R\package -ApprovedSums C:\srv\V2-approved\APPROVED-SHA256.txt -ReleaseId integrity-v2-<sha7> `
  -PyBase 'C:\Program Files\Python313\python.exe' `
  -AdminName '<ім''я>' -AdminEmail <скринька адміністратора> `
  -SmtpMode Gmail -SmtpUser <скринька Gmail проєкту> `
  -TlsPairDirectory C:\srv\V2-tls-staging-<stamp> -TlsCertificateSha256 <sha256 site.crt> `
  [-WithLm -LlamaZip C:\srv\V2-lm-staging\llama-b12180-bin-win-cpu-x64.zip -ModelPath C:\srv\V2-lm-staging\Qwen3-8B-Q4_K_M.gguf]
```

Інший SMTP замість Gmail: `-SmtpMode Custom -SmtpHost smtp.example.org -SmtpPort 587 -SmtpTlsMode starttls -SmtpUser <логін> -SmtpFrom <адреса>`
(`implicit` — порт 465). Локальний relay (`localhost`, `127.*`, `*.local`) відхиляється; dev-mail у release неможливий
(`Test-V2WinswXml` забороняє `V2_AUTH_DEV_MAIL`, `INTEGRITY_DEMO_XROLE`, `V2_AUTH_SECURE_COOKIE`).

Тест-хост: додати `-TestHost -TlsHost <тестове ім'я> -TlsAddresses <тестова IP>`; TLS-пара необов'язкова; `-WithLm` заборонено
(інсталятор LM перевіряє ім'я сервера).

### Етапи

| Етап | Що відбувається | Збій |
|---|---|---|
| G0 | адмін; Job Object вимкнено; параметри; план SMTP (`Get-V2SmtpPlan`); вхідні файли LM | нічого не змінено, exit 1 |
| 4.0 preflight (лише читання) | `Assert-V2CleanPackage`: суми окремого каналу, ZIP = маніфестам, `requirements-hashed.txt` ⊇ `requirements.txt` релізу, лише `.whl`, без зайвих файлів; Python 3.13.14 x64; `SCHEMA_SPECS` має integrity/6 і auth/2; шаблони XML; служб `integrity-v2-backend/-caddy/-lm` і кореня немає; збірка, PowerShell, місце; порти; DNS/IP; TLS-пара | нічого не змінено, exit 1 |
| 4.1 | `C:\srv\integrity-v2` атомарно (лише Administrators/SYSTEM) | fail-closed |
| 4.2 | копія пакета → `pkg\<ReleaseId>\` (повторна перевірка копії); код → `app\<ReleaseId>\backend` **без** `v2_bootstrap_admin.py` / `v2_clean_bootstrap_admin.py`; маніфест → `pkg\<ReleaseId>-BACKEND-SHA256.txt`; dist → `app\frontend\dist`; WinSW і Caddy з артефакту; цільові Caddyfile (файлова TLS-пара) і XML (`workingdirectory` = `app\<ReleaseId>\backend`) | fail-closed |
| 4.3 | venv з базового Python; `pip --isolated install --no-index --require-hashes --only-binary :all:` лише з `wheels\`; `pip check`; `pip freeze` = `requirements-hashed.txt`; `bind-check` auth 2 / integrity 6 проти коду й маніфесту | fail-closed |
| 4.4 | репетиція release на копії в `%TEMP%` (порт 8199): seed → відбиток → міграції → uvicorn → 11 HTTP-перевірок | fail-closed |
| 4.5 | нові БД у порожньому `data\`: seed (`APP_ENV=development` — лише для нової БД; у release seed відмовляє) → verify 6 → відбиток = 4.4 → копія → `app.migrations --apply` (release; створює `v2_auth` v2) → `check_schema` → строгі `schema` integrity 6 / `auth-schema` 2; **перший адміністратор** — одноразово `python -I v2_clean_bootstrap_admin.py --backend app\<ReleaseId>\backend` з каталогу інсталятора (лише перевірка схеми, `require_no_admin`); рівно 1 admin; `mark-synthetic` (маркер `CREATED-BY-V2-INSTALL.txt`, відбиток = еталону, лише адміністратори) → `instance_meta.dataset = synthetic` (демо-аналітика в release); початкові копії 6/2 + `SHA256SUMS.txt`; `CLEAN-INIT-OK` | `CLEAN-INIT-FAILED`, fail-closed |
| 4.6 | служба backend (WinSW, `NT SERVICE\integrity-v2-backend`), ACL, секрети: `V2_SECRET_KEY` (48 випадкових байтів), SMTP-значення з параметрів, пароль SMTP — приховано; `Assert-V2AclMatrix`; старт; `/api/health` 200, `/docs` 401, X-Role 401, dev-mail 404 | fail-closed |
| 4.7 | Caddy (`caddy adapt`, TLS-пара, ACL), старт, HTTPS за закріпленою адресою | fail-closed |
| 5 | HTTPS smoke (9 перевірок) | fail-closed |
| 5.1 | обидві служби → **Automatic (Delayed Start)** (`Set-V2ServiceDelayedAuto`, read-back `Auto` + `DelayedAutoStart`); `-KeepManualStart` — лишити Manual | fail-closed |
| 6 (`-WithLm`) | після `CLEAN INSTALL PASS`: `lm\Install-V2LmService.ps1 -Apply` (служба `integrity-v2-lm`, 127.0.0.1:8200, Automatic (Delayed Start), `V2_LM_URL`/`V2_LM_API_KEY` у XML backend, перезапуск backend); потім `Assert-V2AclMatrix` уже з `lm\` | exit **4**: базове встановлення працює, LM відкочено інсталятором LM |

Коди виходу: **0** PASS; **1** STOP (до 4.1 — нічого не змінено; після — fail-closed виконано); **2** fail-closed не завершено (КРИТИЧНО);
**4** базове встановлення PASS, LM — ні (повторити `lm\Install-V2LmService.ps1 -LlamaZip … -ModelPath … -Apply -DecisionRef …` окремо).

## 4. Перевірки після встановлення

1. Браузер: smoke S1–S8 (вхід адміністратора, 2FA-код приходить листом від скриньки Gmail, панелі, демо-аналітика).
2. `tls\Verify-V2Tlsfix5Runtime.ps1` — read-only доказ: служби Running (Auto/Manual), версії БД з файлів 6/2 + строга схема,
   початкові копії, LM (якщо є) лише 127.0.0.1:8200.
3. `upgrade\Register-V2BackupTask.ps1 -Apply -DecisionRef '<…>' -RunNow` — щоденна копія БД (версії визначаються автоматично).
4. Завдання TLS-поновлення `Integrity-V2-TLS-Renewal` (`tls\Invoke-V2TlsScheduled.ps1` → `tls\Renew-V2TlsPair.ps1`): сумісне з
   Automatic (Delayed Start) — `Renew` приймає `Auto` і `Manual`, від версій БД не залежить, LM не зачіпає (зупиняє/стартує лише Caddy,
   backend має лишатися незмінним). На новому сервері каталог завдання й закріплені в ньому SHA256 (`Invoke-V2TlsScheduled.ps1`
   посилається на `C:\srv\V2-release-TLSFIX5-20261120\…`) треба розгорнути/оновити окремим рішенням.
5. Перезавантаження (рекомендовано у вікні обслуговування): після нього backend, Caddy (після Tailscale) і LM стартують самі.

## 5. Відкат і переривання

- Збій до 4.1 — нічого не змінено; виправити причину й повторити.
- Збій після 4.1 — fail-closed: `CLEAN-INIT-FAILED-INSTALL`, `CLEAN-INIT-OK → REVOKED`, `CLEAN-INSTALL-FAILED` у корені, служби V2
  зупинено й `Disabled`; БД і копії не видаляються. Далі лише свідомо:
  `clean-install.ps1 -DecisionRef '<…>' -Abort -AbortReason '<…>'` — служби V2 видаляються, корінь → `C:\srv\integrity-v2-abandoned-<ts>`
  (докази лишаються; `upgrade\Protect-V2Leftovers.ps1` закриває ACL залишків). Повторний Clean Install — з чистого стану.
- Невдалий LM (exit 4) — базове встановлення не відкочується; LM-інсталятор сам видаляє службу LM і повертає XML backend.
  Видалення LM пізніше — `lm\Uninstall-V2LmService.ps1`.
- Після успішного Clean Install подальші зміни — лише `Update-V2InPlace.ps1` / `Rollback-V2InPlace.ps1`
  (поточний код = `pkg\<ReleaseId>-BACKEND-SHA256.txt`; версії `-FromIntegrityVersion 6 -FromAuthVersion 2`).

## 6. Обмеження

- Не запускалося на справжньому Windows-хості: WinSW install/start, `icacls`, `sc.exe config start= delayed-auto` (read-back
  `DelayedAutoStart`), Caddy/HTTPS, інтерактивні запити паролів у консолі, LM зі справжньою моделлю.
- REV3-відкат `Invoke-V2DbRestore` (Job Object, вимкнений у production) вимагає start type `Manual`; на сервері з Automatic (Delayed Start)
  ним не користуватися — відкат БД через `Rollback-V2InPlace.ps1` або `v2_db_tool restore` (UPGRADE_IN_PLACE.md §6).
- `Update-V2InPlace.ps1` має значення за замовчуванням 3/1 → 5/2 (історія TLSFIX5); для сервера після цього Clean Install передавати
  версії явно.
- Інсталятор LM дозволений лише на сервері `DESKTOP-JTGC2SG` (перевірка хоста в `lm\`).
