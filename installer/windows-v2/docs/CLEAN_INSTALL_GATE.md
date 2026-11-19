# CLEAN INSTALL V2 — GATE (окремий сценарій першого встановлення)

| | |
| --- | --- |
| Для | капітана №5; погодження критеріїв і незалежна перевірка — №4 |
| Підготував | №2, 19.11.2026 |
| Підстава | рішення №5 «CLEAN INSTALL V2 — ПЕРЕХІД ДО РЕАЛІЗАЦІЇ» (обидва висновки: GO WITH CONDITIONS) |
| Кандидат | `candidate/` = ревізія **CI-FIX1** (AUDITFIX3 + Clean Install + Caddy `Job` + CI-01); оркестратор `clean-install.ps1` |
| Статус | **локальна частина готова; C3 (ізольований Windows-хост) — BLOCKED**, C2/C4/C6/C7/C8 — за №5/№4. **Production NO-GO** |

## 1. Що таке Clean Install

Перше встановлення V2 на Windows-сервер з **новими порожніми SQLite**:
- `clean-install.ps1` виконує етапи 4.0–4.7 і автоматичну частину smoke;
- розділу 6.2 (відновлення БД) у сценарії **немає**;
- WinSW і Caddy беруться **лише** з артефакту V2 `integrity-v2-tools` із закріпленими SHA256;
- V1 не обов'язкова: якщо присутня — контроль «без змін» після кожного етапу; якщо відсутня — це фіксується.

## 2. Чому Clean Install не використовує Upgrade/Rollback (вимога 7)

Доказ — `static-clean-install.ps1`: граф викликів від `clean-install.ps1` через усі функції `V2-install-common.ps1`. Журнал прогону містить перелік усіх досяжних функцій.

| ID | Твердження | Як перевіряється |
| --- | --- | --- |
| CI-S1 | недосяжні: `Invoke-V2DbRestore`, `Invoke-V2DbRestoreCore`, `Assert-V2RestorePermitted`, `Assert-V2RestoreItems`, `Assert-V2RestoreReady`, `Import-V2Identities`, `Assert-V2SqliteSidecars` | граф викликів (AST) |
| CI-S2 | Job Object (`Get-V2JobReport`, `Start-V2JobHolder`, `Invoke-V2JobTool`) запускається лише в `Stop-V2ServiceCore` за умови `$V2Services.Job ≠ $null`; обгортки лише звільняють наявну lease; G0 `clean-install.ps1` вимагає `Job = $null` і вимкнений режим репетиції | граф + текст умов |
| CI-S3 | жодних шляхів/імен V1 (`HacatonServer`, `HacatonBackend`, `C:\Users\Public`) у рядках `clean-install.ps1` і в досяжних функціях, окрім read-only `Get-V1Baseline`/`Assert-V1Unchanged`; `Get-V1Baseline` лише з `-AllowAbsent` | AST рядків |
| CI-S4 | WinSW і Caddy копіюються лише з `$V2Root\pkg\tools` після `Expand-V2Tools` без перевизначення еталонів | AST `Copy-Item` |
| CI-S5 | нові БД — лише `Initialize/Complete-V2CleanDatabases`; старт backend — стандартний PreCheck (`Assert-V2DataReady`) | граф + AST |
| CI-S6 | **CI-01:** етапи 4.0–5 в одному `try`. `catch` лише за `$Owned` (корінь створено цим запуском) викликає `Invoke-V2CleanInstallFailClosed`. `Set-V2ServiceStartMode` — лише `-Mode Disabled` і лише звідти. У fail-closed немає видалення | AST |

Мутації MCS1 (виклик `Invoke-V2DbRestore` у `clean-install.ps1`), MCS2 (WinSW із каталогу V1), MCS3 (catch без fail-closed), MCS4 (fail-closed без `$Owned`) мають давати FAIL.

`Set-V2ServiceStartMode` — сервісна функція SCM (лише служби V2). У Clean Install вона тільки **вимикає** служби під час fail-closed; механізм відкату (W1–W5) недосяжний.

## 3. Механізми Clean Install

| Вимога №5 | Реалізація (`V2-install-common.ps1`) | Локальні докази |
| --- | --- | --- |
| 2. Незалежність від V1 | `New-V2ToolsArtifact` (збирання артефакту з перевірених джерел), `Expand-V2Tools` (рівно 2 записи, без виходу за каталог, SHA256 = `05b82d46…` / `2622e239…`, WinSW — версія 2.12.0); `Get-V1Baseline -AllowAbsent` | CI.tools-ok/-tamper/-extra/-missing/-traversal/-default, CI.v1-absent, CI.v1-present |
| 3. Строгий auth-schema | `Initialize-V2CleanDatabases`: seed → verify → відбиток = 5а → backup → migrations → `check_schema` → **`auth-schema` нової `v2_auth.db`**. `Complete-V2CleanDatabases` (після bootstrap): **`auth-schema` робочої БД**, рівно 1 адміністратор, DEMO-умова, початкові копії, **`auth-schema` фінальної копії**, `SHA256SUMS` | CI.complete-ok/-badauth/-noadmin/-badbackup/-state; R10a/R10b (справжній backend) |
| 4. Часткове встановлення | маркери `CLEAN-INIT-IN-PROGRESS / FAILED / OK`. Старт backend (`Assert-V2DataReady`) — лише з **позитивним** маркером `CLEAN-INIT-OK` або `RESTORE-OK` і без жодного `IN-PROGRESS`/`FAILED`. Будь-який STOP оркестратора → маркер `CLEAN-INSTALL-FAILED`, зупинка встановлених служб V2. Далі — свідомо `clean-install.ps1 -Abort`: служби V2 зупинено й видалено, корінь → `…-abandoned-<ts>`, БД позначено `CLEAN-INIT-FAILED-ABANDONED`. Ніколи не використовуються повторно | CI.ready-* (9), CI.start-blocked, CI.init-notempty, CI.abort-ok/-stuck/-job; R10b, R10c |

**Знайдено й виправлено:**
- **Дефект auditfix2/auditfix3:** запис служби Caddy не мав поля `Job`. `Stop-V2ServiceCore` читає `$V2Services[$Name].Job`, тож під `Set-StrictMode` зупинка Caddy (автозупинка, переривання, 6.1) завжди падала б. Тепер `Job = $null` задано явно (CI.stop-caddy, мутація MC8).
- У нових функціях `$a` перезаписувала `$A`: імена змінних PowerShell нечутливі до регістру. Знайдено тестом CI.complete-ok, змінні перейменовано.

## 4. Умови C1–C8 (критерії PASS/FAIL, відповідальні)

| № | Умова | PASS | FAIL | Відповідальний | Стан |
| --- | --- | --- | --- | --- | --- |
| C1 | Формально окремий сценарій Clean Install без відновлення БД | `clean-install.ps1` + цей документ; `static-clean-install` CI-S1…CI-S5 PASS; мутації MCS1/MCS2 KILLED | будь-який CI-S* FAIL або мутація вижила | №2 (готує), №4 (погоджує) | **локально PASS — на погодження №4** |
| C2 | Рішення щодо `C:\srv` (4.1а) | номер/дата рішення №5 → `-SrvDecisionRef`; `New-V2ProtectedDirectory` лише `C:\srv`, `O:BA D:PAI` | рішення немає → `clean-install.ps1` STOP на 4.1 | №5 | **очікує рішення** |
| C3 | Прогін на ізольованому Windows-хості (Windows Services, ACL, TLS, 2FA, bootstrap, завершення процесів) | `clean-install.ps1 -TestHost` (етапи 4.0–4.7, smoke) — `CLEAN INSTALL PASS`; ручні S1–S8; примусова помилка на 4.5 і 4.6 → STOP + маркери → `-Abort` PASS; повторний Clean Install після `-Abort` PASS; журнали з exit code | будь-який STOP, FAIL, NOT RUN | №5 (хост, дозвіл), №2 (прогін), №4 (перевірка) | **BLOCKED — немає тест-хоста** |
| C4 | Read-only preflight сервера + артефакт інструментів | звіт preflight без секретів (служби, порти, SHA бінарників, ACL, ОС, Tailscale, Python 3.13.14); `integrity-v2-tools-*.zip` з WinSW (SHA `05b82d46…`, 2.12.0) і Caddy (SHA `2622e239…`, офіційний 2.11.9) з підтвердженим походженням; `Expand-V2Tools` PASS | розбіжність SHA/версії; походження WinSW не підтверджено офіційним релізом | №4 (preflight, артефакт), №5 (затвердження) | **очікує №4** |
| C5 | Строгий auth-schema нової `v2_auth.db` і фінальної копії | у `clean-install.ps1` через Initialize/Complete; CI.complete-*, R10a/R10b PASS; мутація MC3 KILLED | інакше | №2 | **локально PASS** |
| C6 | V1 не видаляється до завершення smoke V2 | процедура (V1, якщо є, — лише контроль «без змін»); окреме рішення №5 щодо виведення V1 | видалення V1 до smoke | №5 | **організаційне** |
| C7 | Пілот / staging: синтетичні дані, Mailtrap Sandbox; відновлення БД недоступне | рішення №5; DEMO-умова (`Assert-V2SyntheticDb`) PASS | цінні дані до закриття Rollback-gate без рішення №5 | №5 | **очікує рішення** |
| C8 | Targeted audit №4 сценарію Clean Install | висновок №4 GO | NO-GO | №4 | **очікує** |

## 5. Для C3: що потрібно на тест-хості

Windows тієї ж збірки, що й сервер, VM без V1/V2. Потрібно:
- права адміністратора;
- Python 3.13.14 (базовий, x64);
- `integrity-v2-dde86e6-deploy.zip` (SHA `62363714…`);
- `integrity-v2-tools-winsw2.12.0-caddy2.11.9.zip` (SHA `abce6a9c…`, CI-02);
- збірка Windows сервера з read-only preflight (`-ExpectedWindowsBuild`);
- облікові дані Mailtrap Sandbox (вводяться приховано);
- tailnet-вузол (для 4.7; без нього 4.7 і smoke HTTPS — NOT RUN, тобто C3 не PASS).

Команда (PowerShell 5.1 від адміністратора):
```
powershell.exe -NoProfile -File candidate\clean-install.ps1 -DecisionRef "<дозвіл №5 на тест-хост>" -TestHost -ToolsZip <tools.zip> -DeployZip <deploy.zip> -PyBase <python 3.13.14> -SrvDecisionRef "<рішення C:\srv>" -AdminEmail <скринька> -TlsHost <ім'я вузла> -TlsAddresses <IP вузла> -ExpectedWindowsBuild <збірка>
```

**Увага:** C1–C8 у розділі 4 — це **стара нумерація №2** з `V2_CLEAN_INSTALL_FEASIBILITY.md`. Оцінка за критеріями №4 — у `C1_C8_MATRIX_BY_AUDITOR4.md` (тільки вона чинна).
Переривання: той самий скрипт із `-Abort -AbortReason "<причина>"`.
