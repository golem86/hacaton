# V2 INSTALLATION FINAL PLAN — REV3 + P1–P6 + дельта 1–7 + B1/B3 + комплексна валідація + auditfix2 + auditfix3 (кандидат)

| | |
| --- | --- |
| Для | капітана №5; незалежний цільовий перегляд — №4 |
| Підготував | №2, 18.11.2026 |
| Підстава | наказ №5 «INSTALLER V2 — COMPREHENSIVE VALIDATION & REMEDIATION» (19.11) — розділ 0.000; наказ №5 «INSTALLER V2 — FINAL BLOCKER REMEDIATION» (19.11) — розділ 0.00; наказ №5 «TARGETED DELTA FIXES AFTER №4 RE-REVIEW» (19.11) — розділ 0.0; раніше — наказ №5 «V2 INSTALLATION REV3 TARGETED FIXES» (19.11) за цільовим аудитом №4 `REV3_FINAL_TARGETED_AUDIT_FOR_COMMANDER_5.md`: лише P1–P6, PID 4, P7-timeout. Кандидат installer-а **без присвоєння назви REV4**. База — оригінальний REV3 (plan `1771f285…`, common `46bd947b…`) |
| Код | `feature/v2-integration` @ `f1554942f00497a38765337fe227232dbb306ba7`; backend і frontend побайтно = `dde86e6`. Код, CI/CD, B1 REV6 і deployment ZIP **не змінювались** |
| Пакет | `integrity-v2-dde86e6-deploy.zip` `62363714278da539db295bc809bd29bf0cc9bbde073ca8a26ff65f5211052559`; SERVER PREFLIGHT PASS (preflight `be6a0585…`) |
| Статус | **план; на сервері нічого не виконано.** Встановлення — лише після DEPLOYMENT GO №5 |
| Межі | V1 (`HacatonBackend`, чинна служба Caddy, БД V1), ACL `C:\` і `C:\srv`, Windows Firewall, Tailscale — **не змінюються** |

Секретів у документі немає. Супровідні файли (каталог `integrity-v2-install-templates`):

| Файл | Призначення |
| --- | --- |
| `V2-install-common.ps1` | спільні функції fail-closed: коди завершення, HTTP, ACL, служби, baseline V1, секрети, репетиція, умова DEMO |
| `v2_db_tool.py` | перевірки БД (лише stdlib): `verify`, `fingerprint`, `backup` (SQLite backup API + тест відновлення), `users` |
| `integrity-v2-backend.xml.template`, `integrity-v2-caddy.xml.template` | WinSW: **Manual**, віртуальний акаунт `NT SERVICE\…`, без секретів (без змін у REV3) |
| `test-rev3-negative.ps1` | ізольовані негативні й контрольні тести (P*, D* — усе фейкове; Q* — лише власні дочірні процеси python); код завершення 1 при будь-якому FAIL |
| `rehearse-rev3.ps1` | позитивна репетиція етапів 2, 5а, 5б, секретів; код завершення 1 при FAIL |
| `static-rev3.ps1` | статична перевірка плану й функцій; код завершення 1 при FAIL |
| `v2_job_launcher.py` | **ЕКСПЕРИМЕНТ (не затверджено):** launcher Job Object + `proof` / `terminate` / `hold` / `snapshot` |
| `test_v2_auth_schema.py`, `test_v2_job.py`, `job_child.py` | тести строгого checker-а `v2_auth.db` (A*/N*) і Job Object (J*); фікстура дочірнього процесу |
| `mutate.py`, `run-all.ps1` | відтворюваний mutation runner; прогін усього комплекту з журналами |
| `runtime-harness.ps1`, `integrity-v2-jobtest.TEST-ONLY.xml.template` | етап 5: лише ізольований тест-хост за погодженням №5 (тестова служба `integrity-v2-jobtest`) |

---

## 0.00000 AUDITFIX3 — sidecar-и SQLite (P0), Windows runtime gate (19.11)

Підстава — аудит №4 auditfix2: B-03 ACCEPT WITH CONDITIONS; B-01/B-02/B-04/AUTH PASS static; GO до ізольованих SCM/WinSW тестів. **Production NO-GO.**

| Пункт | Що змінено |
| --- | --- |
| P0 sidecar-и | W5 перед `RESTORE-OK`: для обох БД — режим журналу із заголовка (1/1 rollback, 2/2 WAL); `-journal` і `-wal` відсутні або 0 B; `-shm` у rollback-режимі заборонений, у WAL — лише за порожнього/відсутнього `-wal`; каталог замість файлу, невідомий режим, помилка читання → `RESTORE-FAILED` |
| Власний holder | процес утримання lease (PID + час створення) не вважається «процесом V2» евристикою (раніше давав би хибний STOP на сервері) |
| J09.env | увесь набір J* виконується у зовнішньому job детерміновано; виправлено обрізання псевдо-handle у перевірці |
| Runtime gate | `runtime-harness.ps1`: Disabled → `sc start` = 1058; відкат на синтетичних БД зі справжньою службою (W1 на справжньому SCM, sidecar-и, FAILED → Disabled → 1058, старт після успішного відкату). Виконується лише на ізольованому тест-хості |

## 0.0000 AUDITFIX2 — B-03 (виключення конкурентних writer SQLite, життєвий цикл lease) і Windows PowerShell 5.1 (19.11)

Підстава — наказ №5 за повторним аудитом №4: B-01, B-02, B-04, AUTH SCHEMA прийнято статично; **B-03 — BLOCKED**. Дизайн — `SQLITE_WRITER_EXCLUSION_DESIGN.md` (зафіксовано до реалізації). **Gate BLOCKED, DEPLOYMENT NO-GO.**

| Пункт | Що змінено |
| --- | --- |
| Lease lifetime | `Invoke-V2DbRestore` = обгортка + ядро: на **кожному** шляху (успіх, будь-яка відмова до чи після мутації) proof видаляється, holder звільняється; помилки cleanup додаються до повідомлення. `Stop-V2Service` = обгортка: будь-яка відмова → holder звільнено, доказу немає |
| Конкурентні writer | W1 `start type → Disabled` **до** фінального scan (SCM не запускає вимкнену службу) → W2 job proof + scan service SID → W3 `FileShare.None` → мутація → W5 (стан служби, scan, файли, SHA256 відновлених БД) **до** `RESTORE-OK`; невідповідність → FAILED. Успіх → `Manual`; відмова до мутації → `Manual`; FAILED після мутації → лишається `Disabled` |
| stop → start | `Invoke-V2ServiceStart` інвалідує proof і звільняє lease **до** PreCheck/старту |
| scan | BLOCKED лише через scan (job порожній) → до 5 спостережень × 400 мс; стійкий процес → BLOCKED |
| 5.1 / BOM / run-all | рушій тестів за замовчуванням — Windows PowerShell 5.1 (`pwsh` — лише явно); UTF-8 BOM у `.ps1`; `test-audit-gate` без подвійних лапок у нативних аргументах; журнал репетиції — багаторядкові повідомлення одним рядком |
| інше | мертвий дубль `Get-V2ServiceSid` прибрано (static P21); R9 репетиції — свіжий справжній job-proof із lease для кожного відкату |

## 0.000 COMPREHENSIVE VALIDATION & REMEDIATION (19.11, той самий кандидат)

Підстава — наказ №5. Статус: **LOCAL DEVELOPMENT / VALIDATION; PRODUCTION NO-GO; DEPLOYMENT NO-GO.** P3/P4 — **BLOCKED** до затвердження №5, аудиту №4 і runtime-gates. Повна матриця — `FINAL_VALIDATION_MATRIX.md`, ризики й NOT RUN — `REMAINING_RISKS.md`.

| Етап | Що зроблено | Стан |
| --- | --- | --- |
| 1 Auth schema | `v2_db_tool.py auth-schema`: строгий read-only checker `v2_auth.db` (A01–A13), DDL закріплено дослівно з release `v2_auth.py` (SHA `cbb529ce…`). У відкаті — для копії **до** мутації і для відновленого файлу **до** `RESTORE-OK` | локально PASS |
| 2 Job Object | `v2_job_launcher.py` (експеримент): JOB_LIST + CREATE_SUSPENDED, перевірка членства до ResumeThread, HANDLE_LIST, неуспадковуваний handle job, без breakaway, перевірка лімітів, захист імені; `proof` (SD, ліміти, ActiveProcesses = 0, PID-list, сканування за SID служби) | локально PASS; WinSW / служба — NOT RUN |
| 3 Stop / rollback | `Stop-V2Service`: за наявності `Job` — утримання handle, членство й ліміти до `sc stop`, `terminate` лише цього job, доказ `Completeness = job`, блокування DB/WAL/SHM. **Відкат дозволено лише з доказом рівня job** | у production-конфігурації `Job = $null` → відкат backend **BLOCKED** (P4) |
| 4 Regression / mutation | повтор P1–P6, дельти, B1/B3; мутації M1–M8 + нові MA*/MJ*/MS* | див. матрицю |
| 5 Runtime | `runtime-harness.ps1` — лише ізольований тест-хост за окремим погодженням; на ПК №2 перевірено лише відмову (RH0) | NOT RUN |

**Знайдено й виправлено під час цього наказу:**
- `v2_db_tool.py` писав у канал cp1251, а installer читає UTF-8 — кирилиця в STOP була пошкоджена; тепер stdout/stderr — UTF-8;
- launcher: успадкований режим «ігнорувати Ctrl+C»; коди виходу ≥ 0x80000000 перетворювались на −1;
- `Stop-V2Service`: перевірка дерева до terminate job дала б хибний BLOCKED — порядок виправлено.

**Конфлікт вимог (зафіксовано, рішення №5):** release `migrate_auth_db` може створити `v2_auth.db` двома шляхами — «чисто» (точний DDL) або міграцією прототипу v0 через `ALTER TABLE` (інший текст DDL і порядок колонок). Checker приймає **лише** «чисту» release-схему; для нового встановлення V2 БД прототипу не існує.

## 0.00 FINAL BLOCKER REMEDIATION — B1, B3; B2 лише проєкт (19.11, той самий кандидат)

Підстава — наказ №5 за TARGETED DELTA REVIEW №4. **P3/P4 — BLOCKED** до затвердження й реалізації моделі повноти процесів (B2). **DEPLOYMENT NO-GO.** P1, P2, P5, P6 не змінювались.

| # | Статус | Що змінено | Тести |
| --- | --- | --- | --- |
| B1 помилка handle нащадка | **CLOSED** (локально, фейкові процеси) | `Add-V2TreeIdentities`: мовчазний `catch { continue }` прибрано. Помилка відкриття handle **нащадка** → одразу повторна перевірка CIM. Процесу з тим PID і часом створення немає → вихід доведено. Інакше — **нерозв’язаний нащадок** (PID, PID батька, час створення, причина): у `Stop-V2Service` → **CRITICAL BLOCKED**, `$V2StopProof` не створюється, нащадки нерозв’язаного шукаються як пізні; на шляху старту, репетиції й очищення → STOP / проблема | H1–H9; static P16 |
| B3 набір БД для відкату | **CLOSED** (локально) | `Assert-V2RestoreItems` — **перша** дія `Invoke-V2DbRestore`, до будь-якої мутації. Перевіряє: рівно 2 БД; `integrity_v2.db` → `user_version` 2, `v2_auth.db` → 1 (ціле число); без дублікатів БД (і з іншим регістром) і шляхів копій (після нормалізації); копія — абсолютний шлях до наявного файлу поза `data\`; SHA256 — 64 hex. Відкат **лише** з валідним доказом `Stop-V2Service` у цій сесії: без нерозв’язаних нащадків, служба зараз Stopped. Ще виправлено: перевірка схеми після відновлення запускається з `INTEGRITY_DB`/`V2_AUTH_DB` = відновлені файли (раніше backend перевіряв би БД за замовчуванням) | K1–K16, D3a–D3k; rehearse R9a–R9c (справжня `check_schema`/`check_auth_schema`, примусові часткові помилки); static P14, P16 |
| B2 повнота дерева (Job Object) | **PENDING — рішення №5** | лише проєкт `JOB_OBJECT_DESIGN.md`; launcher не реалізовано | J1–J12 (заплановано) |
| P3 зупинка служби / P4 відкат | **BLOCKED** | fail-closed: недоведене → BLOCKED; повноту доводить лише B2 | — |

**Знахідка (backend не змінювався):** справжня `check_auth_schema` перевіряє лише `user_version` `v2_auth.db`. БД без жодної таблиці V2 з `user_version = 1` проходить (спостереження в R9). `check_schema` для `integrity_v2.db` перевіряє і таблиці. Рішення — за №5: зміна backend поза межами наказу.

## 0.0 Дельта-виправлення після повторного перегляду №4 (19.11, той самий кандидат)

Підстава — наказ №5 «TARGETED DELTA FIXES AFTER №4 RE-REVIEW». Кандидат **не перейменовано на REV4**. База для diff — уже перевірений кандидат P1–P6. P1 і P6 не змінювались. Сервер, `C:\srv`, ACL, служби, Git, V1, backend/frontend, CI і release ZIP не чіпали. **DEPLOYMENT NO-GO.**

Позначення тестів: **P\*/D\*** — частина A, усе фейкове (процеси, служби, CIM, мережа, ACL); **Q\*** — частина Q, лише власні дочірні процеси `python` і тимчасові файли. **Q\* — локальні тести на ПК №2; це НЕ B1-QA** (прогін комплекту у Windows Sandbox). B1-QA для цього кандидата — **NOT RUN**.

| # | Дефект (№4) | Статус | Що змінено (`V2-install-common.ps1`, якщо не вказано інше) | Нові тести |
| --- | --- | --- | --- | --- |
| 1 | `Invoke-V2Native`: виняток першого `Wait-V2Handle` не оброблявся | **CLOSED** | Три результати першого очікування: `exited` / `timeout` / `error`. Для timeout і error — зупинка через збережений handle; помилка Kill фіксується окремо; завершення підтверджується другим очікуванням. Якщо завершення не підтверджено (або друге очікування кинуло виняток) — стан **НЕВІДОМИЙ → CRITICAL STOP** з усіма помилками. Підтверджене завершення після timeout/error — теж STOP (не PASS) | Q12 (перший wait кидає виняток), Q13, Q14 |
| 2 | `Stop-V2Service`: дерево процесів — лише збережене при старті | **CLOSED** у межах чинного механізму · **P3 BLOCKED** до B2 (розділ 0.00) | Безпосередньо перед `sc stop`: заново встановлюється актуальне дерево (`Get-V2ServiceTree`, handle кожного доступного процесу, owner = `NT SERVICE\<id>` з `ReturnValue 0`); корінь звіряється зі збереженим (PID + час створення); живі збережені ідентичності додаються. Після Stopped: вихід **усього** актуального дерева, повторний пошук **пізніх нащадків** (`Get-V2LateDescendants`: батько в дереві, створені після батька, рекурсивно, зокрема осиротілі), евристики (`--port`, exe під коренем V2), слухачі. Будь-яка недоведеність (дерево не встановлено, помилка handle/owner, корінь змінився, живий процес/нащадок, слухач) → **CRITICAL BLOCKED**, доказу зупинки немає. PASS лише з доказом `$V2StopProof[<служба>]` | D2a–D2g, P3j |
| 3 | Rollback не прив’язаний до доведеного завершення дерева; немає fail-fast процедури DB/WAL/SHM | **CLOSED** (локально) · **P4 BLOCKED** до B2; доповнено B3 (розділ 0.00) | Нова `Invoke-V2DbRestore` (розділ 6.2). Дозвіл (`Assert-V2RestorePermitted`) — лише з доказом `Stop-V2Service` або зі збережених ідентичностей, кожна з яких доведено завершилась, і без пізніх нащадків. Далі `Assert-V2RestoreReady` для **всіх** копій до змін. Маркер `RESTORE-IN-PROGRESS-<ts>.txt` → перейменування `<db>`, `-journal`, `-wal`, `-shm` у `*.broken-<ts>` (нічого не видаляється) → `backup` → `verify` → перевірка схем. Будь-яка помилка → маркер `RESTORE-FAILED-<ts>.txt` із переліком виконаного, `.broken-*` зберігаються, STOP. Маркер IN-PROGRESS/FAILED блокує старт backend (стандартний `PreCheck` `Invoke-V2ServiceStart`) і повторне відновлення — лише рішенням №5. Успіх → `RESTORE-OK-<ts>.txt` | D3a–D3j |
| 4 | `New-V2ProtectedDirectory` приймав довільні SDDL/TrustedSids | **CLOSED** (локально) · створення `C:\srv` — **PENDING рішення №5** | Production-функція має **лише** `-Path` і `-DecisionRef`: шлях — точно `C:\srv` (регістрозалежно, без `\`, `..`, варіацій), SDDL — затверджений `O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)`, власник — Administrators, дозволені SID — лише Administrators і SYSTEM, жодних TrustedSids. Перевірки — у `New-V2ProtectedDirectoryCore` **до створення каталогу**: розбір SDDL, D:P, власник, кожен SID ⊆ дозволених і лише FullControl, наявні всі обов’язкові записи, успадковувані записи = записам об’єкта. План викликає лише production-функцію; ядро з явними параметрами — тільки в локальних тестах | D4a–D4e (сторонній SID, надмірний ACL, неправильний owner, не FullControl, без D:P, без SYSTEM, невідповідність успадковуваних), P5p–P5u |
| 5 | Static P12: байт 0x08 замість `\b` — PID 4 не виявлявся | **CLOSED** | `static-rev3.ps1`: P12 = `(?i)(-Id\s+\|Known\s*@\([^)]*?)\b[0-9]{1,3}\b\|PID\s+4\b`; новий P15 — жодного керівного байта (крім TAB/LF/CR) у файлах комплекту | S12 ×3: копія комплекту з навмисно вставленим сценарієм `-Known @(…, 4)` і `Stop-Process -Id 4` → static код 1, P12 FAIL; контрольна копія → код 0 |
| 6 | Неоднозначна кількість позитивних репетицій; плутанина B1–B11 / B1-QA | **CLOSED** | У всіх документах: **один доказаний прогін** на кожен стан кандидата (є журнал). Попередні записи про кількаразові прогони без журналів знято. Локальні B1–B11 перейменовано на **Q1–Q11** | — |
| 7 | Шумний diff | **CLOSED** | Усі файли — LF, без CRLF-шуму; diff від кандидата P1–P6 із відтворюваною командою `--stat` (див. звіт) | — |

**Знайдено тестами під час дельти й виправлено:** у `Invoke-V2DbRestore` вираз `$kn = if (…) { … } else { $Known }` розгортав одноелементний масив у скаляр, і під `Set-StrictMode` `.Count` падав. Замінено присвоєнням. Регресію ловлять D3d і D3i (дерево з одного процесу).

**Межа повноти дерева (п. 2, чесно).** Чинний механізм — знімок CIM (`ParentProcessId` + час створення) і handle. Він **не гарантує** повноти, якщо онук пізнього нащадка з’явився, а його батько завершився до знімка: такий процес за `ParentProcessId` з деревом не пов’язується. Додаткові gates — евристики, слухачі портів, `FileShare.None` на файлах БД — зменшують ризик, але не доводять повноту. Тому будь-яка недоведеність → BLOCKED, а не PASS. **Мінімальний варіант для рішення №5 (не реалізовано, архітектуру не змінено):** запускати backend у Windows Job Object з `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Усі нащадки автоматично потрапляють у job; зупинка — `TerminateJobObject`; доказ — `QueryInformationJobObject` → `ActiveProcesses = 0`. Потрібен невеликий launcher або підтвердження, що WinSW 2.12.0 дає ту саму гарантію, — окреме рішення №5 і окремий аудит №4.

## 0. Адресні виправлення P1–P6 (19.11, кандидат)

Перевірено на ПК №2 (Windows PowerShell 5.1, без прав адміністратора, сервер не чіпали):
- `test-rev3-negative.ps1` — ізольовані mock-тести: **90 PASS, 0 FAIL, код 0**, спроб реальних викликів 0 (стан P1–P6; поточний стан — розділ 7);
- `rehearse-rev3.ps1` — обмежена позитивна репетиція: **11/11 PASS**, один доказаний прогін (журнал);
- `static-rev3.ps1` — розділ 7.

Мутаційна перевірка: 8 навмисно повернених дефектів дають код 1.

| # | Статус | Що змінено (`V2-install-common.ps1`) | Тести |
| --- | --- | --- | --- |
| P1 identity/listener | **DONE** | Єдиний запис ідентичності `Pid, StartUtcTicks, Exe, CommandLine, ParentPid, ParentStartUtcTicks, Owner, Handle`. Owner — з `GetOwner.ReturnValue = 0`. Час створення handle звіряється з CIM (±2 мс). Нащадок, старший за батька, не приймається. Handle запущеного процесу та кожного нащадка зберігається одразу. `Wait-V2Listener` перевіряє власника слухача **до першого HTTP**. Чужий слухач, PID reuse, зміна exe/owner або невідома ідентичність → STOP | P1a–P1j |
| P2 cleanup | **DONE** | Зупинка лише через збережені handle (`Stop-V2Handle`), спершу нащадки; `Stop-Process` за PID не використовується. Процес, що завершився сам, не вбивається — і PID reuse не зачіпає чужий процес. `Invoke-V2Cleanup` накопичує помилки зупинки, temp і порту. Тимчасовий каталог із БД **зберігається**, якщо вихід дерева не доведено. `Use-V2Env` звітує про помилки відновлення env. Handle реєструється в launcher одразу після `Start` — cleanup спрацьовує й тоді, коли помилка сталася до присвоєння `$proc` (дефект REV3). Тайм-аут `Invoke-V2Native` не приховує помилку Kill і підтверджує завершення | P2a–P2l, Q6, Q7 |
| P3 service owners/stop | **DONE** | `Assert-V2ServiceRunning`: owner wrapper і **кожного** нащадка = `NT SERVICE\<id>` (ReturnValue 0); слухач у дереві служби до HTTP; ідентичності зберігаються в пам'яті й у `pkg\identities\<служба>.json`. `Invoke-V2ServiceStart`: відмова `PreCheck` до старту нічого не зупиняє; **будь-яка** помилка після спроби старту, зокрема всередині `Starter`, → stop-and-verify. `Stop-V2Service`: `sc stop` лише цієї служби → Stopped → доведений вихід збережених процесів → порт вільний; інакше **CRITICAL BLOCKED** без «зупинки про всяк випадок» | P3a–P3j |
| P4 SQLite rollback | **DONE** | `Assert-V2RestoreReady` — **до** перейменування чи копіювання. Основний доказ — вихід збережених ідентичностей (з handle або з файлу): той самий час створення = процес ще живий → STOP; інший = PID зайнятий іншим процесом, оригінал завершився, чужий не чіпається. Додаткові gates: евристики, порти, `FileShare.None` для `*.db`, `-journal`, `-wal`, `-shm`. Далі SHA256 копії і `v2_db_tool verify` (integrity + `user_version`) | P4a–P4h, Q8–Q11 |
| P5 ACL/path | **DONE** (локально) · сервер **PENDING** | Маска предка: + WriteEA, WriteAttributes, GenericWrite. `-IncludeInheritable` показує InheritOnly-записи предка, які отримав би незахищений нащадок. Канонічний шлях (без `.`/`..`, без 8.3, containment із `\`) і reparse **кожного** компонента. Карта прав для самого об'єкта **і** для майбутніх файлів/каталогів. Рекурсивне зчитування `Assert-V2AclTree` кожного нащадка; ролі: `code` — RX/R, власник Administrators; `data` — Modify, власник Administrators або служба; `admin` — без служб. `Grant-V2`: перевірки до `icacls`, точне зчитування після. Склад кореня V2 фіксований. `C:\srv` (немає на сервері) не створюється; `New-V2ProtectedDirectory` — лише документований варіант для рішення №5 | P5a–P5u |
| P6 WinSW | **DONE** | Ціль — **WinSW 2.12.0**, SHA256 `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da` (факт №4). `Assert-V2Winsw` звіряє SHA і FileVersion (нормалізація 2.12.0.0 → 2.12.0) у джерела і **кожної копії** (також усередині `Install-V2Service` до `install`). `Test-V2WinswXml`: лише 2.12.0, `serviceaccount` = рівно `domain` + `user`; `username`, `password`, Automatic, інший domain → STOP. Підтримки 3.x немає | P6a–P6j |
| PID 4 | **MOCK SAFE** | Небезпечний сценарій прибрано: у тестах немає жодного PID системних чи сторонніх процесів. Частина A: усі 15 OS-адаптерів підмінено; 12 cmdlet-ів перекрито запобіжниками. Частина Q (раніше «B»; не плутати з B1-QA): лише власні процеси, створені `Invoke-V2Native`. I0 перевіряє ізоляцію до тестів (інакше тести не виконуються); I9 — 0 спроб реальних викликів | I0, I9 |
| P7 native | **VERIFIED** | `Process.Start/ExitCode` без змін. Виправлено лише тайм-аут (див. P2) | Q1–Q7 |

**Важливо (чесно):** до 19.11 №2 кілька разів запускав старий `test-rev3-negative.ps1` (рядок 56). Його сценарій N2b справді викликав `Stop-Process` для PID 4. Спроба провалилась з Access denied, бо PowerShell працював без прав адміністратора, тож наслідків не було. Але за задумом тест був небезпечний, і висновок №4 правильний.

**Нові дефекти, знайдені тестами під час P1–P6 і виправлені:**
- `.Add($x -replace 'a', '')` PowerShell розбирав як два аргументи;
- `@($list)` для `List[object]` у PS 5.1 кидає «Argument types do not match»;
- обов'язковий `-Known` не приймав порожній масив;
- `WaitForExit` на недоступному процесі кидав виняток замість проблеми;
- процес, що завершився сам, хибно рахувався проблемою.

---

## 0.1 Матриця R2-01–R2-06 (REV3, історична)

Формулювання — за рішенням №5. Кожне виправлення має негативний тест у `test-rev3-negative.ps1`. Результат на ПК №2: **42 PASS, 0 FAIL, код завершення 0**; при будь-якому FAIL скрипт повертає 1.

| # | Дефект REV2 | Виправлення REV3 | Негативні тести (STOP) |
| --- | --- | --- | --- |
| R2-01 | слухач 8199 не прив'язаний до процесу репетиції — відповідь міг дати сторонній процес на тому ж порту | `Assert-V2ListenerInTree`: власник кожного слухача порту (`OwningProcess`) має належати дереву процесу, запущеного цією репетицією (корінь + нащадки: venv-перенаправлювач → `python.exe`); адреса — лише `127.0.0.1`. Те саме для служб: 8100 і 443 — дерево PID служби (`Assert-V2ServiceRunning`) | N1a сторонній процес на порту → STOP; N1c інша адреса → STOP; N1d порт ніхто не слухає → STOP; N1b/N1e (контроль) слухач у дереві, зокрема дочірній процес → PASS |
| R2-02 | очищення з `-ErrorAction SilentlyContinue` і `WARN` приховувало збої | `Invoke-V2Cleanup` повертає **всі** проблеми: дерево процесів, тимчасовий каталог (`-ErrorAction Stop`), порт. `Stop-V2ProcessTree` звітує про кожен процес, що не зупинився або не дочекався завершення, і не плутає його з процесом, що вже завершився сам. `Invoke-V2Rehearsal`: якщо очищення не чисте → STOP, разом з основною помилкою, якщо вона була | N2b процес, який не можна зупинити, → проблема повертається; N2c заблокований тимчасовий каталог → проблема; N2d порт досі слухається → проблема; N2a (контроль) дерево зупинено повністю |
| R2-03 | після старту служби провал перевірки лишав службу запущеною | `Invoke-V2ServiceStart`: перевірка `Stopped/Manual/StartName` **до** старту → `sc start` → блок перевірок (`Assert-V2ServiceRunning`, HTTP, TLS, порти, `Assert-V1Unchanged`). **Будь-який** виняток у блоці → `Stop-V2Service` автоматично → STOP. Якщо автозупинка не вдалась — STOP з явним «АВТОЗУПИНКА НЕ ВДАЛАСЯ» | N3a провал перевірки → автозупинка + STOP; N3b неочікуваний виняток → автозупинка; N3c збій автозупинки → явний STOP; N3e провал перевірки до старту (LocalSystem) → старту немає; N3d (контроль) успіх → служба не зупиняється |
| R2-04 | `Invoke-V2Native` міг прочитати застарілий `$LASTEXITCODE`, якщо процес не запустився | `System.Diagnostics.Process`: абсолютний шлях і наявність файлу перевіряються до запуску; `Start()` має повернути `true`; код — `Process.ExitCode` саме цього процесу; stdout/stderr читаються асинхронно; тайм-аут → `Kill` + STOP. Аргументи екрануються за правилами `CommandLineToArgvW`. Інтерактивний `bootstrap_admin` — `Invoke-V2Interactive` (`Start-Process -Wait -PassThru`, `ExitCode`) | N4a неіснуючий exe при `$LASTEXITCODE=0` → STOP; N4b відносний шлях → STOP; N4c код 3 → STOP; N4f тайм-аут → STOP; N4d код 0 при застарілому 7 → PASS; N4e аргументи з пробілами/лапками/`\`/порожні — точно |
| R2-05 | перед відкатом SQLite відстежувались лише процеси з `C:\srv\integrity-v2\…` — дочірній базовий `python.exe` venv (інший шлях) пропускався | `Assert-V2NoProcesses -DataDir`: процеси за шляхом **або** командним рядком (`C:\srv\integrity-v2`, `--port 8100/8199`), крім поточної сесії; слухачі 8100/443/8199; **монопольне відкриття** кожного `*.db`, `-journal`, `-wal`, `-shm` (`FileShare.None`) — доказ, що файли БД ніким не відкриті. `Stop-V2Service` перевіряє, що все дерево процесів служби завершилось | N5b БД утримує сторонній процес → STOP; N5c процес з командним рядком V2 поза `C:\srv` → STOP; N5a/N5d (контроль) після зупинки → PASS |
| R2-06 | ACL / Effective Access, WinSW XML, еталон SHA256 Caddy | **ACL:** `Assert-V2AclExact`/`Assert-V2AclMatrix` — на кожному об'єкті дерева V2 точний набір: Administrators F, SYSTEM F, + рівно один SID служби з точними правами (M / RX / R); жодного Deny, власник Administrators. Ефективні права: токен віртуального акаунта містить Users, Authenticated Users, Everyone, SERVICE. Матриця забороняє будь-які записи цих груп у дереві V2, тож ефективні права служби = записи її SID. **WinSW:** `Test-V2WinswXml` до `install` — лише документовані елементи, `id`, Manual, `NT SERVICE\<id>` без пароля, `executable` у `C:\srv\integrity-v2`, без заборонених змінних; версія — **лише фактична від №4** (невідома → STOP). **Caddy:** еталон SHA256 `caddy.exe` = `2622e239c79df700b0eb92cbd950d1edee365e155a7859f358f0e55f002df591` з офіційного `caddy_2.11.9_windows_amd64.zip` (SHA-512 архіву = `caddy_2.11.9_checksums.txt`) | N6b зайвий Users → STOP; N6c Modify замість RX → STOP; N6d Deny → STOP; N6e власник → STOP; N6f SYSTEM лише InheritOnly → STOP; N6g `caddy.exe` ≠ еталону → STOP; N6i версія WinSW невідома → STOP; N6j незаповнені секрети → STOP; N6k мутації XML (Automatic, NT AUTHORITY, password, недокументований елемент, заборонена змінна) → STOP; N6m/N6n `Grant-V2` лише для акаунтів служб і всередині кореня → STOP; N6a/N6h/N6l (контроль) → PASS |

Тест знайшов і допоміг виправити два дефекти REV3: `WaitForExit` на системному процесі кидав виняток, а не повертав проблему; процес, що вже завершився сам, хибно рахувався проблемою.

**Залежить від №4 (не припускається):** фактична версія WinSW і ACL `C:\srv`. До їх отримання `Test-V2WinswXml` не пропускає невідому версію, а `Assert-V2Ancestors` дає STOP на небезпечних правах `C:\srv`.

---

## 1. Матриця I01–I07 (REV2; чинна)

FIXED — виправлено в плані/функціях і перевірено локальною репетицією на ПК №2 (тимчасовий каталог, без прав адміністратора: **11/11 PASS**). PENDING — потребує виконання на сервері.

| # | Блокер | Стан | Доказ |
| --- | --- | --- | --- |
| I01 | WinSW Manual; коди завершення; StartName/PathName/StartMode/State до старту; без LocalSystem | **FIXED** (план, шаблони) · **PENDING** (сервер) | XML: `<startmode>Manual</startmode>`, `<serviceaccount>` `NT SERVICE`. `Install-V2Service` → `Assert-V2Service … Stopped` (точні `StartName`, `PathName`, `Manual`, `Stopped`). `Start-V2Service` стартує **лише** після цієї перевірки й підтверджує власника процесу. Будь-який нативний виклик — через `Invoke-V2Native` (код ≠ 0 → STOP). LocalSystem/LocalService не використовуються. Локально: R8 (XML Manual + NT SERVICE). Служби на ПК №2 не створювались |
| I02 | безпека `C:\srv` і предків; захищений корінь до створення решти й до секретів; без змін спільних ACL | **FIXED** · **PENDING** (результат на сервері) | `Assert-V2Ancestors` (лише читання `C:\`, `C:\srv`: власник, DELETE/DELETE_CHILD/WRITE_DAC/WRITE_OWNER/GENERIC_ALL для сторонніх, reparse point) → `New-V2Root` (атомарне створення з SDDL `O:BA D:P` — лише Administrators і SYSTEM) → `Assert-V2Root` → лише потім підкаталоги, ACL служб, секрети. Локально: R1 — 7 сценаріїв SDDL, зокрема **`C:\srv` з успадкованим AU Modify → STOP** |
| I03 | секрети: `ZeroFreeBSTR` у `finally`, мінімальний час життя, не в логах | **FIXED** | `Set-V2Secrets`: BSTR → `ZeroFreeBSTR` у `finally`; `SecureString.Dispose()`; масив ключа `Array.Clear`; текст XML лише в одній змінній, `finally` її скидає. Нічого не друкується; порожнє значення → STOP; лише в `C:\srv\integrity-v2\services\`. Локально: R8/R8b/R8c. Залишок: керовані рядки .NET не можна обнулити (відкритий текст до збирання сміття) — мінімізовано, не усунуто |
| I04 | джерело синтетичних даних; backup **до** `--confirm-verified-backup`; відновлення копії; integrity/схема/коди | **FIXED** · **PENDING** (сервер) | джерело — лише `app.seed` пакета `dde86e6` (детерміновано, `random.seed(2026)`; випадкові лише коди доступу). Порядок 4.6: `verify` v2 → відбиток → **`backup` + тест відновлення** → лише тоді `migrations --apply --confirm-verified-backup` → `check_schema`/`check_auth_schema` → адміністратор → фінальні копії. Локально: R6 |
| I05 | репетиція: `try/finally` для uvicorn, PID, env, temp; автоматичні HTTP-критерії | **FIXED** · 5а на сервері **PENDING** | `Invoke-V2Rehearsal`: env через `Use-V2Env` (відновлення в `finally`); зупинка всього дерева процесів (venv-перенаправлювач + дочірній `python.exe`); тимчасовий каталог видаляється у `finally`; 8 перевірок `Assert-V2Http`/`Wait-V2Http` (200/401/404/403). Локально: R5 — 9 PASS, env відновлено, temp 0, порт 8199 вільний, процесів 0 |
| I06 | `INTEGRITY_ANALYTICS_DEMO=1` лише для перевіреної синтетичної БД | **FIXED** · **PENDING** (сервер) | `Assert-V2SyntheticDb` перед стартом служби: маркер свіжої БД цього встановлення + відбиток = відбитку репетиції 5а **на цьому ж сервері** + у `v2_auth` лише адміністратори. Інакше STOP — служба не стартує. Локально: R6 PASS, R7a (інший відбиток) і R7b (без маркера) → STOP |
| I07 | TLS fail-closed; без `curl -k` і LocalSystem; зупинка саме V2; порти; SQLite | **FIXED** · **PENDING** (сервер) | етап 7: `curl.exe` **без `-k`**, код завершення ≠ 0 або HTTP ≠ 200 → зупинка лише `integrity-v2-caddy` → STOP (fallback cert/key — лише за новим дозволом). `Stop-V2Service` + `Assert-V2NoProcesses` (немає процесів із `C:\srv\integrity-v2\…`, 8100/443 вільні) + `Assert-V1Unchanged`. SQLite: WAL у коді не вмикається (rollback-журнал); відновлення 6.2 переносить БД разом із `-journal`/`-wal`/`-shm`, якщо вони є |
| — | baseline служб V1 | **FIXED** · **PENDING** | `Get-V1Baseline`: `HacatonBackend` і чинна служба Caddy V1 (стан, режим, акаунт, шлях, **PID**, порти). Немає будь-якої з них → STOP. `Assert-V1Unchanged` після етапів 2, 3, 5б, 6, 7, 8 і при відкаті (незмінний PID = не перезапускалась). Локально: R2 (без служб V1 → STOP) |

**Важливе очікування для I02:** якщо `C:\srv` створювався адміністратором у корені диска, він, найімовірніше, успадкував від `C:\` правило *Authenticated Users: Modify*. Тоді `Assert-V2Ancestors` дасть **STOP**. Причина: будь-який автентифікований користувач може перейменувати `C:\srv` і підмінити шлях до V2, а ті самі шляхи використовують служби. ACL `C:\srv` план **не змінює**. Потрібне рішення №5: дозволити звуження ACL `C:\srv` (вплив на V1 перевіряє №4) або інше розташування V2. Друге змінює `Caddyfile` і шаблони, тобто потрібен новий пакет.

---

## 2. Gates і рішення D0–D5

| | Рішення №5 | Як у плані |
| --- | --- | --- |
| D0 | G1 умовно: CI й preflight — докази | CI V2 #1/#2 (Python 3.13.14 Windows, 348) і SERVER PREFLIGHT PASS зараховано. **Етап 3, 5а і smoke — PENDING до реального PASS.** **B1-QA — NOT RUN; R-04 — NOT RUN** (не видаються за виконані) |
| D1 | спершу автоматичний TLS | пакетний `Caddyfile`; помилка TLS → зупинка Caddy V2 і STOP; fallback cert/key — лише за новим дозволом |
| D2 | лише віртуальні акаунти, Manual, fail-closed | `NT SERVICE\integrity-v2-backend`, `NT SERVICE\integrity-v2-caddy`; LocalService не використовується |
| D3 | фактичні версії/джерела/SHA256 WinSW і Caddy; сумісність XML | розділ 3 |
| D4 | адміністратор команди + Mailtrap Sandbox | 4.6 |
| D5 | вікно — після прийняття REV2 | — |

## 3. Версії, джерела, SHA256 (D3)

| Компонент | Джерело | Що фіксує №4 до встановлення | Умова |
| --- | --- | --- | --- |
| WinSW | **факт №4:** `C:\Users\Public\HacatonServer\tools\services\HacatonBackend.exe`, FileVersion 2.12.0.0 | `Assert-V2Winsw` для джерела і кожної копії: SHA256 = `05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`, версія = 2.12.0 | `Test-V2WinswXml -WinswVersion 2.12.0` до `install`: лише документовані елементи WinSW 2.12, `serviceaccount` = `domain` + `user`. Інша версія/сума/схема → STOP. Підтримки 3.x немає |
| Caddy | **факт №4:** `C:\Users\Public\HacatonServer\tools\caddy\caddy.exe` 2.11.9 — SHA256 **MATCH** з еталоном | `Assert-V2FileHash` до копіювання і копії | еталон `2622e239…f591` — `caddy.exe` з офіційного `caddy_2.11.9_windows_amd64.zip` (без змін) |
| Python | `python.exe` 3.13.14 з preflight (підпис PSF) | повний шлях | — |
| Пакет | `integrity-v2-dde86e6-deploy.zip` | `62363714…` | — |

---

## 4. Порядок встановлення (після DEPLOYMENT GO)

Одне вікно Windows PowerShell 5.1 від адміністратора. **Без** `Start-Transcript`; перед стартом — лише читання політики транскрипції (`HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription`). Якщо вона ввімкнена, секрети однаково не виводяться: значення вводяться лише через `-AsSecureString`. Будь-який `STOP:` → не продовжувати, відкат лише поточного етапу (розділ 6), доповідь №5.

```powershell
Set-Location '<каталог integrity-v2-install-templates>'          # звірка SHA256 файлів із сумами з окремого каналу — вручну
. .\V2-install-common.ps1
$Pkg = '<шлях до integrity-v2-dde86e6-deploy.zip>'; $PyBase = '<python.exe 3.13.14 з preflight>'
$CaddySrc = 'C:\Users\Public\HacatonServer\tools\caddy\caddy.exe'; $WinswVersion = '2.12.0'; $DbTool = (Resolve-Path .\v2_db_tool.py).Path   # факти №4, 19.11
```

### 4.0 Baseline V1 (лише читання)

```powershell
$Base = Get-V1Baseline; $Base.Services; $Base.Ports                # HacatonBackend і служба Caddy V1 — обов'язково
$WinSWSrc = ((Get-CimInstance Win32_Service -Filter "Name='HacatonBackend'").PathName).Trim().Trim('"')
Assert-V2Winsw -Path $WinSWSrc -Label 'WinSW джерело (HacatonBackend.exe)'   # P6: 2.12.0 і SHA 05b82d46… — інакше STOP
Assert-V2FileHash -Path $CaddySrc -Sha256 $CaddyRefSha256 -Label 'caddy.exe сервера'      # еталон офіційного 2.11.9
Test-V2WinswXml -XmlPath .\integrity-v2-backend.xml.template -Name integrity-v2-backend -WinswVersion $WinswVersion -AllowPlaceholders
Test-V2WinswXml -XmlPath .\integrity-v2-caddy.xml.template -Name integrity-v2-caddy -WinswVersion $WinswVersion
Assert-V2Http -Url 'http://127.0.0.1:8080/api/health' -Expected 200   # або Tailscale-IP:8080, як у preflight
```

### 4.1 Етап 1 — предки й корінь V2 (I02)

```powershell
Assert-V2Ancestors          # C:\ і C:\srv — лише читання. ФАКТ №4: C:\srv ВІДСУТНІЙ → тут STOP до рішення №5 (див. 4.1а)
New-V2Root                  # атомарно: O:BA, D:P, лише Administrators і SYSTEM; потім Assert-V2Root
foreach ($d in 'pkg','app','app\frontend','venv','data','backups','logs\backend','logs\caddy','services\backend','services\caddy','caddy\bin','caddy\data','caddy\config') {
  $null = New-Item -ItemType Directory -Path "$V2Root\$d"          # успадковують захищений ACL кореня
}
Assert-V2Root; Assert-V1Unchanged -Baseline $Base
```

### 4.1а Відсутній `C:\srv` — лише документований варіант, на рішення №5 (НЕ виконується)

Факт №4: `C:\srv` не існує. `C:\` належить TrustedInstaller, DACL захищений, у Authenticated Users немає Delete/DeleteChild/WriteDac/WriteOwner на самому корені. Але є InheritOnly-запис `GR/GW/GX + Delete` для нащадків, тож новий каталог зі звичайним успадкуванням отримав би права на зміну. Варіант для рішення №5 — атомарне створення із захищеним DACL з перевіркою read-back:

```powershell
New-V2ProtectedDirectory -Path 'C:\srv' -DecisionRef '<номер/дата рішення №5>'   # дельта 4: лише цей шлях і затверджений SDDL O:BA D:PAI — Administrators і SYSTEM (F); інших параметрів немає
Assert-V2Ancestors                                                              # повторна перевірка C:\ і нового C:\srv
```

Функція відмовляє **до створення каталогу**, якщо:
- шлях не точно `C:\srv` (інший регістр, `\` у кінці, `..`, інший каталог);
- затверджений SDDL не проходить перевірку: не D:P, власник ≠ Administrators, сторонній або надмірний запис, права не FullControl, немає обов’язкового запису, успадковувані записи ≠ записам об’єкта;
- `C:\srv` уже існує;
- батьківський каталог має reparse point;
- предок має небезпечні права;
- SDDL не захищений від успадкування;
- права після створення не збігаються із заданими.

ACL самого `C:\` не змінюється. Альтернатива (інший шлях) потребує узгодження всіх шляхів V2 і `Caddyfile` — не обирається самостійно.

### 4.2 Етап 2 — пакет

```powershell
if ((Get-FileHash $Pkg -Algorithm SHA256).Hash.ToLower() -ne '62363714278da539db295bc809bd29bf0cc9bbde073ca8a26ff65f5211052559') { Stop-V2 'транспортний ZIP' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($Pkg, "$V2Root\pkg")
foreach ($l in Get-Content "$V2Root\pkg\SHA256SUMS.txt") { $h, $n = $l -split '\s+', 2; if ((Get-FileHash "$V2Root\pkg\$n" -Algorithm SHA256).Hash.ToLower() -ne $h) { Stop-V2 $n } }
[IO.Compression.ZipFile]::ExtractToDirectory("$V2Root\pkg\integrity-v2-dde86e6-backend-src.zip", "$V2Root\app")
[IO.Compression.ZipFile]::ExtractToDirectory("$V2Root\pkg\integrity-v2-dde86e6-dist.zip", "$V2Root\app\frontend")
foreach ($l in Get-Content "$V2Root\pkg\DIST-SHA256.txt") { $h, $n = $l -split '\s+', 2; if ((Get-FileHash "$V2Root\app\frontend\$n" -Algorithm SHA256).Hash.ToLower() -ne $h) { Stop-V2 $n } }
$Backend = "$V2Root\app\integrity-v2-dde86e6\backend"
if (@(Get-ChildItem $Backend -Recurse -File).Count -ne 52) { Stop-V2 'код ≠ 52 файли' }
Assert-V1Unchanged -Baseline $Base
```

### 4.3 Етап 3 — venv і офлайн-залежності (PENDING до реального PASS)

```powershell
$null = Invoke-V2Native -Exe $PyBase -ArgList @('-E', '-s', '-m', 'venv', "$V2Root\venv") -What 'venv'
$Py = "$V2Root\venv\Scripts\python.exe"; $W = "$V2Root\pkg\wheelhouse"
[IO.Compression.ZipFile]::ExtractToDirectory("$V2Root\pkg\wheelhouse-cp313-win_amd64.zip", $W)
$null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-m', 'pip', 'install', '--no-index', '--find-links', "$W\wheelhouse-cp313-win_amd64", '-r', "$Backend\requirements.txt") -What 'pip install'
$null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-m', 'pip', 'check') -What 'pip check'
$freeze = @(Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-m', 'pip', 'freeze') -What 'pip freeze' | ForEach-Object { $_.ToLower().Replace('_', '-') } | Sort-Object)
$req = @(Get-Content "$Backend\requirements.txt" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim().ToLower().Replace('_', '-') } | Sort-Object)
if (@(Compare-Object $freeze $req).Count) { Stop-V2 'pip freeze ≠ requirements.txt (15 закріплених пакетів)' }
Assert-V1Unchanged -Baseline $Base
```

### 4.4 Етап 5а — репетиція release на копії (PENDING до реального PASS)

```powershell
$Reh = @(Invoke-V2Rehearsal -Py $Py -Backend $Backend -DbTool $DbTool -Port 8199); $Reh
$Fp5a = ($Reh | Where-Object { $_.StartsWith('FINGERPRINT ') }) -replace '^FINGERPRINT ', ''
if ($Fp5a -notmatch '^[0-9a-f]{64}$') { Stop-V2 'немає відбитка 5а' }
```

Що робить функція: seed на тимчасовій копії → відбиток → backup + тест відновлення → migrations → перевірка схем → uvicorn на `127.0.0.1:8199`. Далі автоматично: health 200; `/docs`, `/openapi.json` 401; `/redoc` 404; X-Role 401; logout без CSRF 403; dev-mail 404; Survey 200. Після цього, у `finally`: дерево процесів зупинено, env відновлено, тимчасові файли видалено, порт 8199 перевірено.

### 4.5 Етап 5б — ініціалізація нових БД (I04)

Нові БД створюються **лише** в порожньому `data\`, з даних `app.seed` пакета. Робочі БД V1 не відкриваються.

```powershell
$D = "$V2Root\data"
Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$D\integrity_v2.db"; V2_AUTH_DB = "$D\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey) } -Body {
  if (@(Get-ChildItem -LiteralPath $D -Force).Count) { Stop-V2 'data\ не порожній' }
  Set-Content -LiteralPath "$D\CREATED-BY-V2-INSTALL.txt" -Value "created $(Get-Date -Format s) by app.seed (package dde86e6)" -Encoding UTF8
  $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.seed') -What 'seed'
  Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('verify', "$D\integrity_v2.db", '--expect-version', '2')
  if ((Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('fingerprint', "$D\integrity_v2.db")) -ne $Fp5a) { Stop-V2 'відбиток ≠ 5а' }
  # резервна копія і тест відновлення — ДО підтвердження --confirm-verified-backup
  Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', "$D\integrity_v2.db", "$V2Root\backups\integrity_v2-pre-migration.db", '--expect-version', '2')
  $null = Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-m', 'app.migrations', '--apply', '--confirm-verified-backup') -What 'migrations'
  @(Invoke-V2Py -Py $Py -Backend $Backend -ArgList @('-c', 'from app.migrations import check_schema; from app.database import engine; check_schema(engine); from app.v2_auth import check_auth_schema; check_auth_schema(); print(''SCHEMA OK'')') -What 'schema')[-1]
  Invoke-V2Interactive -Exe $Py -WorkingDirectory $Backend -What 'bootstrap admin' -ArgList @('-E', '-s', '-X', 'utf8', '-m', 'app.v2_bootstrap_admin', '--name', 'Staging Admin', '--email', '<скринька адміністратора команди>')   # пароль ≥ 10, приховано
}
Assert-V2SyntheticDb -Py $Py -DbTool $DbTool -DataDir $D -ReferenceFingerprint $Fp5a
Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', "$D\integrity_v2.db", "$V2Root\backups\integrity_v2-initial.db", '--expect-version', '2')
Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('backup', "$D\v2_auth.db", "$V2Root\backups\v2_auth-initial.db", '--expect-version', '1')
Get-FileHash "$V2Root\backups\*.db" -Algorithm SHA256 | ForEach-Object { '{0}  {1}' -f $_.Hash.ToLower(), (Split-Path $_.Path -Leaf) } | Set-Content "$V2Root\backups\SHA256SUMS.txt" -Encoding ASCII
Assert-V1Unchanged -Baseline $Base
```

`bootstrap_admin` — єдиний інтерактивний крок (`getpass`): `Invoke-V2Interactive` бере код завершення із самого процесу (`Start-Process -Wait -PassThru`), а не з `$LASTEXITCODE`. `v2_db_tool backup` для кожної копії: `integrity_check = ok`, `user_version` (2 / 1), кількість рядків = джерелу, тест відновлення (копія копії → відкриття → integrity/відбиток) → SHA256.

### 4.6 Етап 6 — служба backend (I01, I03, I06)

```powershell
Copy-Item $WinSWSrc "$V2Root\services\backend\integrity-v2-backend.exe"
Assert-V2Winsw -Path "$V2Root\services\backend\integrity-v2-backend.exe" -Label 'WinSW копія backend'   # P6: копія = еталон
Copy-Item .\integrity-v2-backend.xml.template "$V2Root\services\backend\integrity-v2-backend.xml"     # ще без секретів
Test-V2WinswXml -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Name integrity-v2-backend -WinswVersion $WinswVersion -AllowPlaceholders
Install-V2Service -Name integrity-v2-backend                 # Manual, NT SERVICE\integrity-v2-backend, Stopped — інакше STOP
$B = 'NT SERVICE\integrity-v2-backend'
Grant-V2 "$V2Root\app\integrity-v2-dde86e6" $B '(OI)(CI)RX'; Grant-V2 "$V2Root\venv" $B '(OI)(CI)RX'
Grant-V2 "$V2Root\data" $B '(OI)(CI)M';                      Grant-V2 "$V2Root\logs\backend" $B '(OI)(CI)M'
Grant-V2 "$V2Root\services\backend" $B '(OI)(CI)RX'
Set-V2Secrets -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml"   # V2_SECRET_KEY генерується; SMTP Sandbox — приховане введення
Test-V2WinswXml -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Name integrity-v2-backend -WinswVersion $WinswVersion   # без плейсхолдерів
Assert-V2AclMatrix                                           # R2-06: точна матриця дерева V2 (Admins F, SYSTEM F, SID служби)
Assert-V2SyntheticDb -Py $Py -DbTool $DbTool -DataDir "$V2Root\data" -ReferenceFingerprint $Fp5a   # умова DEMO=1 (I06)
Invoke-V2ServiceStart -Name integrity-v2-backend -Checks {    # R2-03: будь-який провал нижче → автоматична зупинка служби
  Assert-V2ServiceRunning -Name integrity-v2-backend -Addresses @('127.0.0.1')     # Running, Manual, StartName, власник, слухач 8100 у дереві PID
  Wait-V2Http -Url 'http://127.0.0.1:8100/api/health'
  Assert-V2Http -Url 'http://127.0.0.1:8100/docs' -Expected 401
  Assert-V2Http -Url 'http://127.0.0.1:8100/api/assessments/1/participation' -Headers @{ 'X-Role' = 'manager' } -Expected 401
  Assert-V1Unchanged -Baseline $Base
}
```

Порядок для I02/I03: захищений корінь → перевірка XML → служба Manual (зупинена) → ACL → **лише потім** секрети → повторна перевірка XML → точна матриця ACL → перевірка DEMO → старт із автозупинкою при провалі.

### 4.7 Етап 7 — Caddy V2, приватний HTTPS (I07)

```powershell
Copy-Item $CaddySrc "$V2Root\caddy\bin\caddy.exe"
Assert-V2FileHash -Path "$V2Root\caddy\bin\caddy.exe" -Sha256 $CaddyRefSha256 -Label 'копія caddy.exe'
Copy-Item "$V2Root\pkg\Caddyfile" "$V2Root\caddy\Caddyfile"
$null = Invoke-V2Native -Exe "$V2Root\caddy\bin\caddy.exe" -ArgList @('adapt', '--config', "$V2Root\caddy\Caddyfile", '--adapter', 'caddyfile') -What 'caddy adapt'
Copy-Item $WinSWSrc "$V2Root\services\caddy\integrity-v2-caddy.exe"
Assert-V2Winsw -Path "$V2Root\services\caddy\integrity-v2-caddy.exe" -Label 'WinSW копія caddy'
Copy-Item .\integrity-v2-caddy.xml.template "$V2Root\services\caddy\integrity-v2-caddy.xml"
Test-V2WinswXml -XmlPath "$V2Root\services\caddy\integrity-v2-caddy.xml" -Name integrity-v2-caddy -WinswVersion $WinswVersion
Install-V2Service -Name integrity-v2-caddy
$C = 'NT SERVICE\integrity-v2-caddy'
Grant-V2 "$V2Root\app\frontend\dist" $C '(OI)(CI)RX'; Grant-V2 "$V2Root\caddy\bin" $C '(OI)(CI)RX'; Grant-V2 "$V2Root\caddy\Caddyfile" $C 'R'
Grant-V2 "$V2Root\caddy\data" $C '(OI)(CI)M';          Grant-V2 "$V2Root\caddy\config" $C '(OI)(CI)M'
Grant-V2 "$V2Root\logs\caddy" $C '(OI)(CI)M';          Grant-V2 "$V2Root\services\caddy" $C '(OI)(CI)RX'
Assert-V2AclMatrix
Invoke-V2ServiceStart -Name integrity-v2-caddy -Checks {      # R2-03 / I07: TLS або будь-яка перевірка не пройшла → Caddy V2 зупиняється автоматично
  Assert-V2ServiceRunning -Name integrity-v2-caddy -Addresses @('192.0.2.10', '2001:db8::10')   # 443 лише Tailscale-IP, у дереві PID
  $code = @(Invoke-V2Native -Exe "$env:SystemRoot\System32\curl.exe" -ArgList @('-sS', '-o', 'NUL', '-w', '%{http_code}', '--max-time', '20', 'https://v2-host.tailnet.example/') -What 'HTTPS (без -k)')[-1]
  if ($code -ne '200') { Stop-V2 "HTTPS → HTTP $code; fallback cert/key — лише за новим дозволом №5" }   # помилка TLS = код curl ≠ 0 → STOP вище
  if (@(Get-NetUDPEndpoint -LocalPort 443 -ErrorAction SilentlyContinue).Count) { Stop-V2 'UDP 443' }
  if (@(Get-NetTCPConnection -State Listen -LocalPort 80 -ErrorAction SilentlyContinue).Count) { Stop-V2 ':80 слухається' }
  Assert-V1Unchanged -Baseline $Base
}
```

Windows Firewall не змінюється. Якщо локально HTTPS працює, а з іншого пристрою tailnet — ні, це **NO-GO** і рішення №5 (R-14).

---

## 5. Перший smoke-тест (етап 8; PENDING до реального PASS)

Автоматична частина — на сервері, після етапу 7:

```powershell
$H = 'https://v2-host.tailnet.example'
Assert-V2Http -Url "$H/" -Expected 200; Assert-V2Http -Url "$H/login" -Expected 200; Assert-V2Http -Url "$H/api/health" -Expected 200
Assert-V2Http -Url "$H/docs" -Expected 401; Assert-V2Http -Url "$H/openapi.json" -Expected 401; Assert-V2Http -Url "$H/redoc" -Expected 404
Assert-V2Http -Url "$H/api/assessments/1/participation" -Headers @{ 'X-Role' = 'manager' } -Expected 401
Assert-V2Http -Url "$H/v2/auth/logout" -Method POST -Expected 403
Assert-V2Http -Url "$H/assets/missing.js" -Expected 404
Assert-V1Unchanged -Baseline $Base
```

Браузер учасника команди в tailnet:

| # | Крок | PASS |
| --- | --- | --- |
| S1 | HTTPS | замок без попереджень; сертифікат на `v2-host.tailnet.example` |
| S2 | Login (адміністратор 4.5) | форма OTP; cookie `__Host-v2_session` — `Secure`, `HttpOnly`, `SameSite=Lax` |
| S3 | 2FA (код у Mailtrap Sandbox) | вхід виконано; у `logs\backend` немає коду й email |
| S4 | Swagger `/docs` | відкривається; ресурси лише `/docs/swagger-ui/*`; в іншому браузері без входу → 401 |
| S5 | Survey | адміністратор створює одноразовий код (UI або Swagger з `X-CSRF-Token`); у приватному вікні анкета з кодом → 201; повторно той самий код → відхилено; у журналах немає IP і `/submissions` |
| S6 | Dashboard | результати й аналітика синтетичних циклів (DEMO=1 підтверджено умовою I06); Audit Trail |
| S7 | Logout | після виходу `/v2/user/attempts` → 401 |
| S8 | V1 | `Assert-V1Unchanged` PASS |

---

## 6. Зупинка й відкат лише V2

### 6.1 Зупинка / відкат служб

```powershell
Stop-V2Service -Name integrity-v2-caddy; Stop-V2Service -Name integrity-v2-backend   # P3 + дельта 2: актуальне дерево перед sc stop, пізні нащадки після; недоведене → CRITICAL BLOCKED; PASS → доказ \$V2StopProof
$Known = @(Import-V2Identities -Path "$V2Root\pkg\identities\integrity-v2-backend.json")   # збережені при старті (працює й у новій сесії)
Assert-V2NoProcesses -DataDir "$V2Root\data" -Known $Known   # P4: доведений вихід збережених ідентичностей + евристики + FileShare.None
Assert-V1Unchanged -Baseline $Base
# видалення служб (за потреби):
$null = Invoke-V2Native -Exe "$V2Root\services\caddy\integrity-v2-caddy.exe" -ArgList @('uninstall') -What 'uninstall caddy'
$null = Invoke-V2Native -Exe "$V2Root\services\backend\integrity-v2-backend.exe" -ArgList @('uninstall') -What 'uninstall backend'
if ((Get-V2Service integrity-v2-caddy) -or (Get-V2Service integrity-v2-backend)) { Stop-V2 'служби V2 не видалено' }
```

### 6.2 Відновлення БД V2 (SQLite) — fail-fast (дельта 3)

Дозвіл на відновлення є **лише** з валідним доказом `Stop-V2Service` backend у цій сесії (`$V2StopProof`: без нерозв’язаних нащадків; служба зараз Stopped; **повнота рівня Job Object** — `Completeness = job`, `ActiveProcesses = 0`, процесів акаунта служби 0). Без затвердженого Job Object (production: `Job = $null`) відкат backend **BLOCKED**. Дерево для повторної перевірки береться з доказу, а якщо служба вже була зупинена — зі збережених ідентичностей. Кожен процес доведено завершився, живих пізніх нащадків немає. Інакше — STOP, файли не змінюються (B3). **P4 лишається BLOCKED до B2.**

```powershell
$Items = @(
  @{ Db = 'integrity_v2.db'; Backup = "$V2Root\backups\<копія integrity_v2>.db"; Sha256 = '<сума з backups\SHA256SUMS.txt>'; Version = 2 },
  @{ Db = 'v2_auth.db';      Backup = "$V2Root\backups\<копія v2_auth>.db";      Sha256 = '<сума з backups\SHA256SUMS.txt>'; Version = 1 })
Invoke-V2DbRestore -DataDir "$V2Root\data" -Known $Known -Py $Py -DbTool $DbTool -Items $Items
# усередині, ДО будь-якої зміни: Assert-V2NoRestoreBlock → Assert-V2RestorePermitted → Assert-V2RestoreReady для КОЖНОЇ копії
```

Порядок усередині `Invoke-V2DbRestore` (auditfix2: увесь відкат — в одному try/finally; proof одноразовий, lease звільняється завжди):
0. **B3 — набір копій, до будь-якої дії** (далі для `v2_auth.db` — строгий `v2_db_tool.py auth-schema` копії, A01–A13): рівно `integrity_v2.db` (`Version = 2`) і `v2_auth.db` (`Version = 1`), без дублікатів БД і шляхів копій, копії — наявні файли поза `data\`, SHA256 — 64 hex.
1. Немає маркерів `RESTORE-IN-PROGRESS-*`/`RESTORE-FAILED-*` у `data\` (інакше STOP — лише рішенням №5).
2. Дозвіл (див. вище).
3. Для **кожної** копії, до змін: процеси й евристики, порти вільні, кожен `*.db`/`-journal`/`-wal`/`-shm` відкривається монопольно, SHA256 копії = записаній, `verify` копії (integrity + `user_version`).
3а. **W1–W3 (auditfix2):** служба backend Stopped і Manual → `sc config start= disabled` (зчитано `Disabled`) → **після цього** фінальний job proof + scan service SID = 0 → `FileShare.None` для всіх файлів БД.
4. Маркер `RESTORE-IN-PROGRESS-<ts>.txt`.
5. Для кожної БД: `<db>`, `-journal`, `-wal`, `-shm` (що існують) → `*.broken-<ts>`. Нічого не видаляється.
6. `v2_db_tool backup <копія> <data\db> --expect-version N` (SQLite API + тест відновлення) → `verify` → перевірка схем (`check_schema`/`check_auth_schema`) з `INTEGRITY_DB`/`V2_AUTH_DB` = відновлені файли в `data\`. Для `v2_auth.db` додатково — строгий `auth-schema` відновленого файлу (A01–A13) **до** `RESTORE-OK`: `check_auth_schema` backend перевіряє лише `user_version` (розділ 0.00).
7. Будь-яка помилка на кроках 5–6 → маркер перейменовується на `RESTORE-FAILED-<ts>.txt` (причина + перелік виконаного). `.broken-*` і частково відновлені файли зберігаються. STOP. Автоматичного «відкату відкату» немає — подальші дії лише за рішенням №5.
7а. **W5 (auditfix2), до `RESTORE-OK`:** служба досі `Disabled`/`Stopped`, scan = 0, файли вільні, SHA256 відновлених БД = зафіксованим після копіювання; **sidecar-и (auditfix3):** `-journal`/`-wal` відсутні або 0 B, `-shm` — відповідно до режиму журналу; інакше FAILED (start type лишається `Disabled`).
8. Успіх → `RESTORE-OK-<ts>.txt` → start type `Manual`; далі `Assert-V2SyntheticDb` (маркер лишається, відбиток = еталону).
9. `Invoke-V2ServiceStart -Name integrity-v2-backend -Checks { … }` — ті самі перевірки, що в 4.6. Стандартний `PreCheck` **забороняє старт**, поки в `data\` є маркер IN-PROGRESS або FAILED.

### 6.3 Що не робиться при відкаті

Каталог `C:\srv\integrity-v2\` і дані не видаляються (окреме рішення №5). V1, ACL спільних каталогів, Firewall і Tailscale не змінюються. Немає переходу на LocalSystem/LocalService і `curl -k`.

---

## 7. Локальні перевірки кандидата P1–P6 + дельта + B1/B3 + комплексна валідація (ПК №2, 19.11)

Поточний стан — `FINAL_VALIDATION_MATRIX.md` і журнали `run-all.ps1` (`integrity-v2-install-candidate-logs-final`): фактична кількість тестів, команди, exit code, SHA256. Нижче — історичні стани.

Поточний стан (після B1/B3), по одному зарахованому прогону, журнали в `integrity-v2-install-candidate-logs-b1b3`:

| Скрипт | Результат | Код | Статус |
| --- | --- | --- | --- |
| `test-rev3-negative.ps1 -Py <Python 3.12>` (P1–P6, D2–D4, H1–H9, K1–K16, D3a–D3k, Q1–Q14, S12, I0, I9) | **154 PASS, 0 FAIL**; спроб реальних викликів 0 | 0 | RUN |
| `static-rev3.ps1` (P1–P16) | **16 PASS, 0 FAIL** | 0 | RUN |
| `rehearse-rev3.ps1 -Py <backend\.venv>` (R1–R9c; R9 — відновлення зі справжньою перевіркою схеми) | **14 PASS, 0 FAIL**, один доказаний прогін | 0 | RUN |
| мутаційна перевірка B1/B3 (8 повернених дефектів) | 8/8 виявлено | 1 (кожна мутація) | RUN |
| Job Object (B2), B1-QA (Windows Sandbox), сервер | — | — | **NOT RUN** |

Стан після дельти (до B1/B3, історично), журнали в `integrity-v2-install-candidate-logs-delta`:

| Скрипт | Результат | Код | Статус |
| --- | --- | --- | --- |
| `test-rev3-negative.ps1 -Py <Python 3.12>` (P1–P6, D2–D4, Q1–Q14, S12, I0, I9) | **128 PASS, 0 FAIL**; спроб реальних викликів 0 | 0 | RUN |
| `static-rev3.ps1` (P1–P15) | **15 PASS, 0 FAIL** | 0 | RUN |
| `rehearse-rev3.ps1 -Py <backend\.venv>` | **11/11 PASS**, один доказаний прогін. Спроба 1 з неправильним `-Py` (глобальний Python без залежностей backend) → STOP на `seed`, не зарахована, журнал збережено | 0 | RUN |
| мутаційна перевірка дельти | — | — | **NOT RUN** |
| Офлайн-встановлення на Python 3.13.14, служби, `icacls`, Effective Access, TLS, smoke, B1-QA (Windows Sandbox) | — | — | **NOT RUN** (сервер / Sandbox, PENDING) |

Стан P1–P6 (до дельти, історично):

| Скрипт | Результат | Код | Статус |
| --- | --- | --- | --- |
| `test-rev3-negative.ps1` (ізольовані mock-тести P1–P6, PID 4, P7) | **90 PASS, 0 FAIL**; спроб реальних викликів 0 | 0 | RUN |
| мутаційна перевірка (8 повернених дефектів P1–P6 у копії common) | кожна → FAIL | 1 | RUN |
| `rehearse-rev3.ps1` (позитивна обмежена: власні процеси, порт 8199, тимчасові БД) | **11/11 PASS** (один доказаний прогін) | 0 | RUN |
| `static-rev3.ps1` (розбір 13 блоків плану й функцій; P1–P14, зокрема P11 — зупинка лише через адаптер, P12 — без PID 4, P13 — WinSW 2.12.0, P14 — restore gate) | **14 PASS, 0 FAIL** | 0 | RUN |
| Офлайн-встановлення на Python 3.13.14, служби, `icacls`, Effective Access, TLS, smoke | — | — | **NOT RUN** (сервер, PENDING) |

## 7.0 Локальні перевірки REV3 (18.11, історично)

| Скрипт | Результат | Код завершення |
| --- | --- | --- |
| `test-rev3-negative.ps1` (R2-01–R2-06, розділ 0) | **42 PASS, 0 FAIL** | 0 (при FAIL — 1) |
| `rehearse-rev3.ps1` (позитивний шлях: ACL-сценарії, baseline, HTTP, пакет, 5а, 5б, DEMO, секрети) | **11 PASS, 0 FAIL** (один доказаний прогін) | 0 |
| `static-rev3.ps1` (розбір 11 блоків плану й функцій; без `$LASTEXITCODE` і прямих нативних викликів; без SilentlyContinue в очищенні; старт лише через `Invoke-V2ServiceStart`; `Assert-V2AclMatrix`, `Test-V2WinswXml`, еталон Caddy; `Assert-V2NoProcesses -DataDir`) | **10 PASS, 0 FAIL**. Контроль: на плані REV2 — 3 FAIL, код 1 | 0 |

### 7.1 Репетиція REV2 (для довідки; функції оновлено в REV3)

Тимчасовий каталог, локальний venv Python 3.12 (wheelhouse cp313 тут не встановлюється), без прав адміністратора. Служби, ACL і Caddy не створювались.

| # | Перевірка | Результат |
| --- | --- | --- |
| R1 | `Get-V2AclRisk`: 7 сценаріїв SDDL (типовий `C:\`; `C:\srv` з успадкованим AU Modify; `C:\srv` лише для адміністраторів; власник — користувач; корінь V2 захищений / без захисту / з читанням Users) | PASS |
| R2 | `Get-V1Baseline` без `HacatonBackend` і Caddy V1 → STOP | PASS |
| R3 | `Assert-V2Http`: інший статус або немає з'єднання → STOP | PASS |
| R4 | пакет: суми, 52 файли коду | PASS |
| R5 | `Invoke-V2Rehearsal`: 9 автоматичних перевірок; env відновлено; тимчасових каталогів 0; порт 8199 вільний; процесів `python` 0 | PASS |
| R6 | 5б: seed → verify → відбиток = 5а → backup + тест відновлення → migrations → SCHEMA OK → умова DEMO → фінальні копії | PASS |
| R7a/b | DEMO: інший відбиток → STOP; без маркера → STOP | PASS |
| R8/b/c | секрети: XML валідний, `<&>` екрановано, плейсхолдерів 0, Manual + NT SERVICE; порожній секрет → STOP; XML поза `services\` → STOP | PASS |

Підсумок: **11 PASS, 0 FAIL**. Під час репетиції виправлено:
- у Python-командах, які передаються PowerShell 5.1, лише одинарні лапки (подвійні обрізаються);
- змінні PowerShell перед `:` — у формі `${…}`;
- `venv\Scripts\python.exe` запускає дочірній `python.exe`, тож зупиняється все дерево процесів.

Статична перевірка (`static-rev2.ps1`, ПК №2): **6/6 PASS**.
- P1: усі 11 блоків PowerShell цього плану розбираються без помилок.
- P2: `V2-install-common.ps1` розбирається без помилок.
- P3: немає `Set-Acl`, `*-Service`, змін Firewall і `Start-Transcript`.
- P4: у коді немає `curl -k`, LocalSystem і LocalService.
- P5: `icacls` — лише в `Grant-V2` з обмеженням `C:\srv\integrity-v2`; `sc.exe` — лише config/start/stop.
- P6: XML — Manual, `NT SERVICE\…`, без пароля і небезпечних змінних.

Скрипти репетиції (`rehearse-rev2.ps1`) і статичної перевірки передаються разом із планом для відтворення №4.

**Не перевірено локально (PENDING, сервер):** офлайн-встановлення на Python 3.13.14; `Assert-V2Ancestors`/`New-V2Root` на реальних `C:\srv` і `C:\` (потрібні права адміністратора); WinSW `install` з `<serviceaccount>` `NT SERVICE`; `sc.exe config`; `icacls`; служби й власник процесів; TLS Caddy через Tailscale; smoke S1–S8.
