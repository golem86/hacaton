# Локальна мовна модель (LM) для Integrity Management Dashboard V2

Статус: інфраструктура (Docker-сервіс і Windows-служба) та інтеграція в backend/UI (розділ 3). Що й де перевірено:

- **Реальна модель, локально без Docker (21.11.2026, macOS, Apple M1 Pro).** llama.cpp build 12359 (Metal) і
  Qwen3-8B-Q4_K_M (SHA256 збігається з таблицею нижче), `llama-server` лише на `127.0.0.1:8200`, backend з `main` і
  синтетичною БД. Резюме — 24 с, рекомендації — 24 с, порівняння — 32 с; у всіх трьох `verified=true`, назв прихованих
  категорій у текстах немає, у трекер нічого не потрапило. UI «Звіти» показує позначку чернетки; без моделі
  `lm/status` → `reachable: false`, завдання → `failed` із загальним повідомленням, звіти й Index працюють; журнал — лише
  `report.narrative` без тексту.
- **Docker, профіль `lm` (21.11.2026, OrbStack, linux/arm64).** Стек `backend` + `frontend` + `lm` зібрано й запущено,
  усі три сервіси healthy, модель завантажилась за ≈ 41 с. Через Caddy (`:8080`): резюме — 104 с, рекомендації — 88 с,
  порівняння — 213 с, усі `verified=true` (лише CPU, 4 потоки). Порт LM на хост не публікується, з контейнера LM
  інтернету немає (`lm_net` internal), файлова система лише для читання; без LM — та сама коректна відмова.
  **Увага:** закріпленого в `compose.yaml` образу `ghcr.io/ggml-org/llama.cpp:server-b12180` у реєстрі не існує
  (`manifest unknown`); перевірку виконано з `LM_IMAGE` (див. розділ 1).
- **Реальна модель, локально на Windows без Docker (21.11.2026, лише CPU, 6 потоків).** Справжній
  `llama-b12180-bin-win-cpu-x64.zip` і Qwen3-8B-Q4_K_M (SHA256 обох збігаються з таблицею нижче), ті самі параметри,
  що й у службі, лише `127.0.0.1`, ключ API з файлу; backend з `main` (`c718c60`) і синтетична БД з
  `app.demo_cycle --seed 2026`. Резюме — 111 с, рекомендації — 86 с, порівняння — 223 с; у всіх трьох `verified=true`.
- **Windows-служба на робочому сервері.** Розгорнуто 20.11.2026 як службу `integrity-v2-lm`. Того ж дня на сервері тим
  самим кодом, що й кнопки «(ШІ)» у «Звітах», згенеровано три чернетки на демо-циклі зі 150 анкет: резюме — 109 с, рекомендації — 85 с, порівняння — 169 с,
  усі `verified=true`. Перевірка 21.11.2026: служба Running з автозапуском, слухає лише `127.0.0.1:8200`, `/health` = ok,
  SHA256 моделі збігається, backend підключено через `V2_LM_URL`.
- **Скрипти встановлення служби.** `test-lm-service.ps1` (L0–L13: розбір PowerShell, шаблон, сухі прогони `-Simulate`,
  відкати, невірний SHA, зайнятий порт, слухач поза loopback) — 21 з 21 PASS зі справжньою збіркою
  `llama-server.exe` b12180 (21.11.2026).

| Що | Значення |
|---|---|
| Рушій | llama.cpp `llama-server` (OpenAI-сумісний API: `/v1/chat/completions`, `/v1/models`, `/health`) |
| Модель | Hugging Face `Qwen/Qwen3-8B-GGUF`, файл `Qwen3-8B-Q4_K_M.gguf` (5,03 ГБ), SHA256 `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Бінарник (сервер) | `llama-b12180-bin-win-cpu-x64.zip` (24,7 МБ, b12180, commit bcb015287), SHA256 `b272cddf0e9c0692df0587b6f4cb8de4296e2d136b1b5b095ac0fe9807deeb20` |
| Образ (локально) | у `compose.yaml` закріплено `ghcr.io/ggml-org/llama.cpp:server-b12180`, але такого тегу в реєстрі немає; перевірено з `server-b12182` за digest `sha256:6d581c788abba2dfa23ff78dba37ea0abfc7d838c49bcc98f4be2103df9772b3` (через `LM_IMAGE`) |
| Параметри | контекст 8192, один слот (`--parallel 1`), thinking вимкнено (`--reasoning off`), кеш промптів у RAM вимкнено (`--cache-ram 0`, типово 8192 МіБ), без Web UI (`--no-webui`), без `/slots` (`--no-slots`, там видно вміст промптів), `--jinja` |

## 1. Docker (локальна робота)

Сервіс `lm` у `compose.yaml` має профіль `lm`: без `--profile lm` він не стартує, і стек працює як раніше.

```sh
# 1) модель у ./models (5 ГБ; SHA256 перевіряється; .partial докачується при повторі; models/ у .gitignore)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fetch-lm-model.ps1      # Windows
sh scripts/fetch-lm-model.sh                                                        # Linux/macOS
# 2) образ LM: тегу server-b12180 у реєстрі немає — задайте перевірений образ (server-b12182, amd64 і arm64) за digest
export LM_IMAGE=ghcr.io/ggml-org/llama.cpp@sha256:6d581c788abba2dfa23ff78dba37ea0abfc7d838c49bcc98f4be2103df9772b3
#    (PowerShell: $env:LM_IMAGE = "ghcr.io/ggml-org/llama.cpp@sha256:6d581c788abba2dfa23ff78dba37ea0abfc7d838c49bcc98f4be2103df9772b3")
# 3) запуск усього стеку разом із LM
docker compose --profile lm up --build
# стан: docker compose ps   (lm healthy після завантаження моделі, start_period 180 с)
```

- Мережа: `lm` лише в мережі `lm_net` (`internal: true` — без виходу в інтернет); порт на хост **не публікується**.
  Backend під'єднаний до `demo_net` і `lm_net` та отримує `V2_LM_URL=http://lm:8080`; frontend до LM доступу не має.
- Модель монтується лише для читання (`./models:/models:ro`), контейнер `read_only`, `cap_drop: ALL`, `no-new-privileges`.
- Ключ API в Docker не задається: доступ має лише backend у внутрішній мережі. Якщо потрібен — `compose.override.yaml` з
  `--api-key-file /run/secrets/lm_api_key` (Docker secret) і `V2_LM_API_KEY` у backend; не передавайте ключ через `--api-key`.
- Змінні (`.env`, див. `.env.example`): `LM_THREADS` (типово 4; не більше фізичних ядер, відданих Docker), `LM_MEM_LIMIT`
  (типово `8g`), `LM_IMAGE` (тег або `ghcr.io/ggml-org/llama.cpp@sha256:<digest>` після `docker pull`), `V2_LM_URL`.
- Docker Desktop: віртуальній машині потрібно щонайменше ~8 ГБ RAM, інакше `lm` завершиться через OOM.
- Без профілю `lm` ім'я `lm` не резолвиться — backend має вважати LM недоступною (без падіння).
- **Перевірено на образі `server-b12182` (21.11.2026):** entrypoint — `llama-server` (`command:` — лише аргументи), `curl`
  для healthcheck є, сервер працює з `read_only: true` (лише `/tmp` як tmpfs). Процес у контейнері працює від root (uid 0) —
  зважаючи на `cap_drop: ALL`, `no-new-privileges`, `read_only` і внутрішню мережу ризик малий, але варто задати `user:`.
- Ручна перевірка: `docker compose exec backend python -c "import urllib.request;print(urllib.request.urlopen('http://lm:8080/health').status)"`.

## 2. Сервер (Windows-служба `integrity-v2-lm`)

### 2.1 Що встановлюється

| Шлях | Вміст | ACL |
|---|---|---|
| `C:\srv\integrity-v2\lm\` | корінь LM | лише Administrators/SYSTEM (без успадкування) |
| `lm\bin\` | увесь вміст ZIP (52 файли: `llama-server.exe`, `ggml-*.dll`, бекенди `ggml-cpu-*.dll` вибираються автоматично під CPU) | + `NT SERVICE\integrity-v2-lm` RX |
| `lm\LM-BIN-SHA256.txt` | SHA256 кожного файлу `bin` (копія — у `backups\lm-install-<stamp>\`) | лише адміни |
| `lm\models\Qwen3-8B-Q4_K_M.gguf` | модель (SHA256 копії перевірено) | + служба LM RX |
| `lm\secrets\api-key.txt` | ключ API (48 випадкових байтів, base64) | адміни + служба LM **лише R** |
| `services\lm\` | `integrity-v2-lm.exe` (копія WinSW 2.12.0 backend, SHA = еталон) + `integrity-v2-lm.xml` (без секретів) | + служба LM RX |
| `logs\lm\` | журнали WinSW (`integrity-v2-lm.out.log`, `.err.log`, `.wrapper.log`) | + служба LM M |
| `services\backend\integrity-v2-backend.xml` | **додаються рядки** `V2_LM_URL=http://127.0.0.1:8200`, `V2_LM_API_KEY=<ключ>` | без змін ACL |

Служба: WinSW 2.12.0, `NT SERVICE\integrity-v2-lm`, Automatic (Delayed Start), onfailure restart 10 с / 30 с, пріоритет
процесу **BelowNormal** (`<priority>` WinSW і `--prio -1` llama.cpp), 8 потоків. Аргументи (шаблон
`installer\windows-v2\integrity-v2-lm.xml.template`):

```
-m C:\srv\integrity-v2\lm\models\Qwen3-8B-Q4_K_M.gguf --host 127.0.0.1 --port 8200 -c 8192 -t 8 --parallel 1 --jinja
--reasoning off --cache-ram 0 --prio -1 --no-webui --no-slots --api-key-file C:\srv\integrity-v2\lm\secrets\api-key.txt
```

**Ключ API — файлом, не в командному рядку.** `--api-key <ключ>` видно в `Win32_Process.CommandLine` (будь-який адмін/моніторинг,
дампи процесів) і в журналі WinSW. `--api-key-file` (підтримується b12180, «ключі по рядку») тримає ключ у файлі з ACL лише
служба LM + адміни. Резерв, якщо колись бінарник не знатиме `--api-key-file`: інсталятор кладе ключ у змінну `LLAMA_API_KEY`
XML служби LM (ACL як у XML backend). Режим визначається автоматично з `--help` і пишеться в доказ (`KeyMode`).

**Мережа / Firewall.** Слухач лише `127.0.0.1:8200`: інсталятор перевіряє, що на порту 8200 слухає лише дерево процесів служби
і лише на `127.0.0.1`, а в усього дерева немає інших TCP/UDP точок (`Endpoints` у доказі); `/health` → 200; `/props` без
ключа → 401, з ключем → 200. Правил Firewall скрипти **не додають**; кількість наявних правил для `llama-server.exe` лише
записується (`FirewallRulesForBinary`, очікується 0).

### 2.2 Ресурси (оцінка для Ryzen 7 5700X, 24 ГБ, CPU-збірка)

- Пам'ять: модель ≈4,7 ГіБ (mmap) + KV-кеш 8192 токени ≈1,2 ГіБ (36 шарів × 8 KV-голів × 128 × 2 × f16) + буфери ≈0,3–0,6 ГіБ →
  **≈6–7 ГБ**. Інсталятор вимагає ≥ 8 ГБ вільної пам'яті (`-MinFreeMemoryGB`). Вільно ≈12,7 ГБ — запас ≈5 ГБ.
- Диск: ≈5,1 ГБ (модель + бінарники) + 1 ГБ запасу.
- Швидкість (оцінка, перевірити пробою): генерація ≈6–9 токенів/с (обмежена пропускною здатністю DDR4), обробка промпту
  ≈30–60 токенів/с при 8 потоках. Промпт 1000 токенів + відповідь 300 токенів ≈ 50–70 с. Один запит за раз (`--parallel 1`):
  наступні чекають у черзі — backend має задавати тайм-аут і ліміт довжини.
- Холодний старт (завантаження моделі з диска): ≈10–60 с; `/health` до того → 503.
- GPU RX 5500 XT не використовується (CPU-збірка).

### 2.3 Команди через SSH (неінтерактивно, від адміністратора)

Набір інсталятора (увесь каталог `installer\windows-v2` цієї гілки) — напр. у `C:\srv\V2-lm-kit-<sha7>\installer\windows-v2`
(`lm\V2-lm-lib.ps1` підключає `upgrade\V2-upgrade-lib.ps1` і `V2-install-common.ps1`). Артефакти —
`C:\srv\V2-lm-artifacts-20261120\` (поза `C:\srv\integrity-v2`; інсталятор це вимагає).

```powershell
# 1) Звіт (нічого не змінює): адмін, служби, пам'ять, місце, SHA256 ZIP і моделі, склад ZIP, порт 8200, XML backend
ssh <admin>@<сервер> powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\srv\V2-lm-kit-<sha7>\installer\windows-v2\lm\Install-V2LmService.ps1 `
  -LlamaZip C:\srv\V2-lm-artifacts-20261120\llama-b12180-bin-win-cpu-x64.zip -ModelPath C:\srv\V2-lm-artifacts-20261120\Qwen3-8B-Q4_K_M.gguf

# 2) Встановлення (SHA256 за замовчуванням — закріплені вище; або -LlamaZipSha256/-ModelSha256, або -ApprovedSums <файл "<sha>  <ім'я>">)
ssh <admin>@<сервер> powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\srv\V2-lm-kit-<sha7>\installer\windows-v2\lm\Install-V2LmService.ps1 `
  -LlamaZip C:\srv\V2-lm-artifacts-20261120\llama-b12180-bin-win-cpu-x64.zip -ModelPath C:\srv\V2-lm-artifacts-20261120\Qwen3-8B-Q4_K_M.gguf `
  -Apply -DecisionRef '<рішення №…>' [-HealthTimeoutSec 300] [-MinFreeMemoryGB 8]

# 3) Перевірка після встановлення (на сервері)
sc.exe qc integrity-v2-lm; sc.exe query integrity-v2-lm
Get-NetTCPConnection -State Listen -LocalPort 8200        # лише 127.0.0.1
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8200/health   # 200

# 4) Видалення: звіт → застосування (рядки V2_LM_* з XML backend + перезапуск backend; служба; services\lm; ключ)
ssh <admin>@<сервер> powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\srv\V2-lm-kit-<sha7>\installer\windows-v2\lm\Uninstall-V2LmService.ps1
ssh <admin>@<сервер> powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\srv\V2-lm-kit-<sha7>\installer\windows-v2\lm\Uninstall-V2LmService.ps1 `
  -Apply -DecisionRef '<рішення №…>' [-RemoveFiles [-RemoveModel]]
```

Кроки й коди виходу Install: `lm.preflight.*` (exit **3**, нічого не змінено) → `lm.backup-dir`, `lm.files`, `lm.binary`
(`--help`: прапорці й режим ключа), `lm.secret`, `lm.service` (реєстрація WinSW, NT SERVICE, Manual, Stopped), `lm.acl` (після реєстрації — акаунт служби вже існує),
`lm.start` (слухач, `/health`, ключ, мережеві точки, пріоритет, Firewall), `lm.startmode` (Automatic Delayed) →
`backend.xml` (копія + 2 рядки), `backend.restart` (+ `/api/health` 200). Доказ: `backups\lm-install-<stamp>\LM-INSTALL-EVIDENCE.json`
(без секретів). Backend перезапускається один раз (≈5–10 с 502 через Caddy); Caddy не чіпається.

### 2.4 Що робити при збої

- **exit 3 (BLOCKED)**: нічого не змінено — виправити причину з виводу (SHA256, пам'ять, порт зайнятий, служба вже є, залишок
  `services\lm`).
- **exit 1 (FAILED_ROLLED_BACK)**: автоматично — XML backend побайтово з копії, перезапуск backend, `/api/health` 200; служба LM
  зупинена й видалена; `services\lm`, `lm\bin`, `lm\secrets` видалено. **Лишаються** `lm\models\…gguf` (перевірена копія —
  повтор не копіює 5 ГБ) і `logs\lm` (діагностика). Причина — `Error` у доказі; журнали `logs\lm\integrity-v2-lm.err.log`
  (типово: нестача пам'яті, `/health` 503 за `-HealthTimeoutSec`, бінарник не стартує — DLL/VC++ runtime).
- **exit 2 (ROLLBACK_INCOMPLETE)**: див. `Rollback[]` у доказі. Вручну: зупинити `integrity-v2-backend`; повернути
  `backups\lm-install-<stamp>\integrity-v2-backend.xml.orig` побайтово (звірити SHA256 з `BackendXmlSha256Before`);
  стартувати backend, `curl http://127.0.0.1:8100/api/health`; потім `Uninstall-V2LmService.ps1 -Apply -DecisionRef …`.
- Служба LM впала в роботі: WinSW перезапускає (10 с, 30 с, далі — ні; лічильник скидається за 1 год). Backend на час простою LM
  має повертати контрольовану помилку. `sc.exe start integrity-v2-lm` — ручний старт.
- Нестача пам'яті під навантаженням: зменшити контекст неможливо без зміни шаблону (`-c`); альтернатива — модель меншого
  квантування (окреме рішення, див. 2.5).

### 2.5 Оновлення моделі або бінарника

Скрипти не оновлюють «на місці»: Uninstall → Install з новими артефактами (простій LM ≈1–3 хв, backend перезапускається двічі).

1. Отримати й звірити SHA256 нових файлів (окремим каналом, як `APPROVED-SHA256.txt`), покласти в новий
   `C:\srv\V2-lm-artifacts-<дата>\`.
2. Нова збірка llama.cpp: спершу локально `llama-server.exe --help` — прапорці з шаблону мають бути (інсталятор однаково зупиниться,
   якщо ні). Новий ZIP → `-LlamaZip … -LlamaZipSha256 <sha>` (або `-ApprovedSums`).
3. Нова модель того ж імені (`Qwen3-8B-Q4_K_M.gguf`, інша ревізія) → `-ModelSha256 <sha>`. Інше ім'я файлу/модель — змінити
   `$V2LmModelFile`/`$V2LmModelSha256` у `lm\V2-lm-lib.ps1` і `-m` у шаблоні, прогнати `lm\test-lm-service.ps1`.
4. `Uninstall-V2LmService.ps1 -Apply -DecisionRef … -RemoveFiles [-RemoveModel]` → `Install-V2LmService.ps1 … -Apply -DecisionRef …`.
   Ключ API генерується заново (backend отримує новий автоматично).

### 2.6 Тести

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installer\windows-v2\lm\test-lm-service.ps1 [-WorkDir <temp>] [-RealBin <каталог розпакованого b12180>]
```

L0 розбір усіх `.ps1` (і BOM), L1 шаблон (Test-V2LmXml, loopback, NT SERVICE, без секретів), L2 звіт без змін, L3 успіх
(рядки XML backend, решта байтів незмінна, ключ у файлі = ключу backend, ключ не у виводі/доказі), L4–L5 видалення
(XML побайтово = оригінал), L6 невірний SHA моделі / не той ZIP → exit 3 без змін, L7 `/health` 503 → відкат (+ повтор),
L8 збій перезапуску backend → XML назад; збій і відкату → exit 2, L9 режим `LLAMA_API_KEY`, L10 бінарник без прапорця,
L11 порт зайнятий, L12 слухач поза loopback, L13 без `-DecisionRef`. Адаптери симуляції: `lm\sim\V2-lm-sim.ps1`
(поверх `upgrade\sim\V2-upgrade-sim.ps1`).

### 2.7 Обмеження й що перевірити на сервері

- WinSW 2.12.0 `<priority>`: доказ `Priority` має бути `BelowNormal` (інсталятор зупиняється й відкочує, якщо ні).
- `/props` без ключа → 401 (очікувано: без ключа відкриті лише `/health` і `/models`; на b12180 не перевірено); якщо інакше — інсталятор
  зупиниться на `lm.start`; тоді перевірити вручну іншою кінцевою точкою.
- `Wait-V2Listener` чекає слухача 8200 до 120 с; `/health` 200 — до `-HealthTimeoutSec` (300 с).
- `Assert-V2AclMatrix` (лише `clean-install.ps1`) не знає каталогу `lm\` — для чистого встановлення з LM його треба доповнити.
- Швидкість виміряно на справжній моделі (розділ 3.5): лише CPU — 1,5–4 хв на чернетку, macOS з Metal — 24–32 с.
  Пам'ять: модель ≈ 5 ГБ + кеш контексту 8192 ≈ 1,2 ГБ.

## 3. Backend


### 3.1 Змінні середовища

| Змінна | Типово | Призначення |
|---|---|---|
| `V2_LM_URL` | — (вимкнено) | База `llama-server`, напр. `http://127.0.0.1:8200`. Не задано → кнопки в UI неактивні, POST → 503 «Локальна LM не налаштована». У `release` — лише `127.0.0.1`, `::1` або `localhost`, інакше сервер не стартує; у `development` дозволено й ім'я сервісу Docker (`http://llama:8200`) |
| `V2_LM_API_KEY` | — | Необов'язковий ключ: надсилається як `Authorization: Bearer …` (той самий, що `--api-key` у llama-server). Не зберігати в репозиторії |
| `V2_LM_MODEL` | `qwen3-8b` | Ім'я моделі в запиті (llama-server з однією моделлю приймає будь-який рядок) |
| `V2_LM_TIMEOUT_S` | `300` | Таймаут одного запиту генерації, 1–3600 с |
| `V2_LM_MAX_TOKENS` | `900` | Верхня межа токенів відповіді, 1–8192. Фактичний бюджет за видом: резюме 450, рекомендації 800, порівняння 500 (≈ 9 ток/с на CPU → 45–90 с) |

URL з обліковими даними, query чи fragment відхиляється в будь-якому режимі (ключ — лише у `V2_LM_API_KEY`).

### 3.2 Як це працює
1. `POST /v2/admin/reports/{id}/narrative` (`summary`/`recommendations`) або `POST /v2/admin/reports/compare/narrative` одразу збирає факти й повертає 202 з `job_id`; 404/409 — так само, як для звіту.
2. Факти — компактний JSON лише з агрегатів звіту (`/results` без прихованих груп, підсумки участі, лічильники трекера) з готовими похідними значеннями: ранжування компонентів, різниці між усіма парами видимих категорій, зміни між циклами. Категорії — українськими назвами, як в UI; приховування — текстовою приміткою (`hidden_groups_note`), а не булевим прапорцем. Імен, email, IP, кодів доступу, сирих відповідей і відповідальних із трекера у фактах немає.
3. Промпт: системні правила (лише факти, нічого не обчислювати, не робити висновків про людей, не відновлювати приховані групи) і дані між маркерами `<<<ДАНІ_JSON … ДАНІ_JSON>>>` з вказівкою, що це дані, а не інструкції. Назви з БД очищуються від керівних символів і маркерів і обрізаються до 120 символів.
4. Запит: `/v1/chat/completions`, `temperature 0.2`, `chat_template_kwargs: {"enable_thinking": false}` і `/no_think`; `<think>…</think>` і HTML-теги з відповіді вирізаються, текст обрізається до 8000 символів.
5. Звірка чисел: кожне число тексту має бути серед чисел фактів (ціле — ±0.5, з одним знаком — ±0.05; знак не враховується; коди `C1` і номери пунктів «1.» — не числа). Інакше `verified=false` і `unverified_numbers`; UI показує попередження.
6. Один фоновий виконавець, до 5 завдань у черзі/роботі (далі 429), завершені завдання живуть 1 год у пам'яті процесу. Завдання бачить лише його автор.
7. Журнал: `report.narrative` з `count` (1 або 2 цикли), без тексту.

### 3.3 Обмеження
- Черга в пам'яті процесу: запускайте backend одним worker-процесом uvicorn; перезапуск втрачає завдання.
- Звірка чисел ловить вигадані числа, але не неправильні формулювання без чисел — тому текст завжди є чернеткою.
- Модель може помилятися в оцінних судженнях; рекомендації автоматично в трекер не потрапляють.

### 3.4 Ручна перевірка з реальним llama-server
Передумова: llama-server слухає лише loopback, модель завантажена (див. розділ про службу нижче).

1. `curl http://127.0.0.1:8200/health` → `{"status":"ok"}` (503 — модель ще завантажується).
2. Задайте у конфігурації backend `V2_LM_URL=http://127.0.0.1:8200` (і `V2_LM_API_KEY`, якщо llama-server запущено з `--api-key`), перезапустіть backend.
3. Увійдіть адміністратором (2FA) → «Звіти»: під закритим циклом є блок «Текст звіту (ШІ)» з активними кнопками. Якщо кнопки неактивні — прочитайте пояснення (не налаштовано / недоступна).
4. «Резюме (ШІ)» → статус «у черзі» / «генеруємо текст» (опитування кожні 4 с), за 1–2 хв — текст з позначкою «Чернетка, згенерована локальною ШІ. Перевірте перед використанням.» Перевірте, що числа збігаються з таблицями звіту, а попередження про неперевірені числа з'являється лише за потреби. «Копіювати» копіює текст.
5. «Чернетки рекомендацій (ШІ)» → 3–6 пунктів для найслабших компонентів; у трекері нічого нового не з'явилося.
6. «Порівняння циклів (ШІ)»: оберіть два різні закриті цикли → текст про зміни.
7. Зупиніть llama-server і запустіть генерацію → завдання `failed` із загальним повідомленням «Локальна ШІ недоступна…»; `GET /v2/admin/lm/status` → `reachable: false`.
8. «Журнал дій»: записи «Чернетка тексту звіту (локальна ШІ)» з роллю й циклом, без тексту.
9. Переконайтеся, що в тексті немає назв прихованих категорій (у демо-даних це «Персонал» і «Керівництво» в циклі 2025-II).


### 3.5 Перевірено на реальній моделі

Скрізь Qwen3-8B Q4_K_M, у всіх запусках `verified=true` (вигаданих чисел немає).

| Де і коли | Рушій | Резюме | Рекомендації | Порівняння |
|---|---|---|---|---|
| Локально, 20.11 | llama-server b12180, CPU, синтетична БД | 95 с | 97 с | 167 с |
| Робочий сервер, 20.11 | служба `integrity-v2-lm`, b12180, CPU; демо-цикл 150 анкет | 109 с | 85 с | 169 с |
| Windows, 21.11 (`main` `c718c60`) | b12180, CPU, 6 потоків; той самий демо-цикл | 111 с | 86 с | 223 с |
| macOS M1 Pro, 21.11 (`main`) | build 12359, Metal | 24 с | 24 с | 32 с |
| Docker, профіль `lm`, 21.11 (OrbStack, linux/arm64) | образ `server-b12182`, CPU, 4 потоки | 104 с | 88 с | 213 с |

21.11 також перевірено: коректна відмова без моделі (`lm/status` → `reachable: false`, завдання `failed` із загальним повідомленням, звіти й Index працюють), назв прихованих категорій у текстах немає, у трекер нічого не потрапляє, у журналі лише подія `report.narrative` без тексту.
