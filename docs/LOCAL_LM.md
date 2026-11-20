# Локальна мовна модель (LM) для Integrity Management Dashboard V2

Статус: інфраструктура (Docker-сервіс і Windows-служба). Інтеграцію в backend/UI робить окремий потік (розділ 3).
Перевірено лише локально: розбір PowerShell, статичні перевірки шаблону, сухі прогони `-Simulate`, `--help` справжнього
`llama-server.exe` b12180 і розпакування справжнього ZIP. Справжня модель через ці скрипти не запускалась, Docker-образ не
завантажувався, на сервері нічого не виконувалось.

| Що | Значення |
|---|---|
| Рушій | llama.cpp `llama-server` (OpenAI-сумісний API: `/v1/chat/completions`, `/v1/models`, `/health`) |
| Модель | Hugging Face `Qwen/Qwen3-8B-GGUF`, файл `Qwen3-8B-Q4_K_M.gguf` (5,03 ГБ), SHA256 `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Бінарник (сервер) | `llama-b12180-bin-win-cpu-x64.zip` (24,7 МБ, b12180, commit bcb015287), SHA256 `b272cddf0e9c0692df0587b6f4cb8de4296e2d136b1b5b095ac0fe9807deeb20` |
| Образ (локально) | `ghcr.io/ggml-org/llama.cpp:server-b12180` (тег; digest закріплює інтегратор через `LM_IMAGE`) |
| Параметри | контекст 8192, один слот (`--parallel 1`), thinking вимкнено (`--reasoning off`), кеш промптів у RAM вимкнено (`--cache-ram 0`, типово 8192 МіБ), без Web UI (`--no-webui`), без `/slots` (`--no-slots`, там видно вміст промптів), `--jinja` |

## 1. Docker (локальна робота)

Сервіс `lm` у `compose.yaml` має профіль `lm`: без `--profile lm` він не стартує, і стек працює як раніше.

```sh
# 1) модель у ./models (5 ГБ; SHA256 перевіряється; .partial докачується при повторі; models/ у .gitignore)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\fetch-lm-model.ps1      # Windows
sh scripts/fetch-lm-model.sh                                                        # Linux/macOS
# 2) запуск усього стеку разом із LM
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
- **Перевірити на образі** (Docker тут не було): що entrypoint образу — `llama-server` (тоді `command:` — лише аргументи), що
  в образі є `curl` для healthcheck, що сервер працює з `read_only: true` (лише `/tmp` як tmpfs).
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
- Оцінки швидкості й пам'яті — до проби інтегратора на справжній моделі.

## 3. Backend (заготовка — заповнює потік інтеграції)

Інфраструктура дає backend:

| Змінна | Docker | Сервер |
|---|---|---|
| `V2_LM_URL` | `http://lm:8080` | `http://127.0.0.1:8200` |
| `V2_LM_API_KEY` | не задається (внутрішня мережа) | 64 символи base64; заголовок `Authorization: Bearer <ключ>` |

Рекомендації для інтеграції: OpenAI-сумісний `POST /v1/chat/completions` (модель одна, поле `model` довільне); thinking уже
вимкнено на сервері (`--reasoning off`); тайм-аут запиту й ліміт `max_tokens`; один запит за раз — черга/відмова 503; не
логувати промпти й відповіді (там можуть бути відповіді анкет); LM недоступна (`/health` ≠ 200) → контрольована помилка.

_TODO (потік backend): API-контракт (`docs/API_CONTRACT.md`), промпти, обробка помилок, тести._
