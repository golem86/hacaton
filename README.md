<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/branding/sysmints-logo-dark.svg">
  <img src="docs/branding/sysmints-logo.svg" alt="Sys&Mints" width="420">
</picture>

# Integrity Management Dashboard

**Команда «Sys&Mints» · Building Integrity Hackathon 2026 · Завдання 3. Integrity Management Dashboard.**

Цифрова система оцінювання стану й зрілості системи доброчесності та підтримки управлінських рішень: анонімне опитування, аналіз результатів в агрегованому вигляді, Integrity Index, рекомендації та звіти. Оцінювання призначене для розвитку системи, а не для оцінки окремих посадових осіб. Проєкт розробляється з акцентом на конфіденційність відповідей, розмежування прав доступу та прозорість методології.

## Команда

Команда «Sys&Mints». Логотип і правила його використання — у [docs/branding](docs/branding/README.md).

## Проблема

Організаціям потрібні інструменти, які допомагають збирати анонімний зворотний зв'язок, аналізувати його в агрегованому вигляді та виявляти напрями для вдосконалення без розкриття особистості респондентів.

## Наше рішення

- Анонімне опитування Survey з одноразовими кодами.
- Assessment Manager: створення циклів, категорії респондентів, мінімальний розмір групи, видача кодів, участь, закриття циклу.
- Кабінет користувача та адміністративні можливості з розмежуванням прав.
- Екран «Результати підрозділу» в кабінеті користувача (`GET /v2/user/unit-results`): бали C1–C7 свого підрозділу за закритий цикл. Підрозділ призначає лише власник сервера; користувач і адміністратор його не обирають. Якщо в циклі є хоч одна мала група «категорія × підрозділ» (менше k відповідей), результати підрозділів за цей цикл приховуються. Деталі — [docs/USER_UNIT_RESULTS_API_PROPOSAL.md](docs/USER_UNIT_RESULTS_API_PROPOSAL.md).
- Вхід із додатковою перевіркою OTP/2FA.
- Головний екран керівника («Огляд»): Integrity Index із зоною та рівнем зрілості, зміна до попереднього циклу, радар C1–C7, сильні сторони й проблемні зони, перехід від індексу до картки компонента.
- Executive Dashboard: бали компонентів C1–C7 з кольоровим кодуванням за явним правилом зон, порівняння категорій, об'єктивні показники, динаміка закритих циклів.
- Integrity Index, рекомендації та порівняльна аналітика за демонстраційною методикою на синтетичних даних; кожна рекомендація пояснює, яке правило й які значення її спричинили.
- Порівняння самооцінки з об'єктивними показниками з позначенням «Потребує перевірки» за видимим правилом.
- Трекер рекомендацій: посадова особа приймає або відхиляє пропозицію, призначає відповідального (посаду, не ПІБ) і строк; статуси «прийнято → в роботі → виконано → перевірено» з доказами та перевіркою наступним циклом.
- Звіти PDF/XLSX за закритими циклами.
- Журнал дій користувачів без змісту анонімних відповідей.
- Персональний модуль тестувань.

Модельним об'єктом демонстрації є вищий військовий навчальний заклад. Дані демонстрації виключно синтетичні. Анкети, критерії та індикатори мають допускати адаптацію для інших органів сектору безпеки й оборони.

## Демонстрація

Відео (до 3 хв): посилання буде додано до 23.11.2026

## Технології

- Frontend: React, TypeScript, Vite, Chart.js.
- Backend: Python, FastAPI, SQLAlchemy.
- Дані: SQLite.
- HTTPS reverse proxy: Caddy.
- Тести: pytest, node:test, Playwright.
- Контроль версій: Git і GitHub.

**Примітка:** демонстраційні показники базуються на синтетичних даних. Їх не слід трактувати як висновки про реальну організацію.

## Як влаштовано

- Стек: frontend React + TypeScript + Vite (`frontend/src`), backend Python + FastAPI + SQLAlchemy (`backend/app`), дві SQLite-бази (`INTEGRITY_DB` — цикли, анкети, агрегати, трекер, аудит; `V2_AUTH_DB` — користувачі, сесії, 2FA).
- Компоненти: браузер → Caddy (HTTPS, статичний frontend, проксі `/api/*` і `/v2/*`) → FastAPI → SQLite; необов'язково — локальна LM (llama.cpp) лише через loopback. На сервері Windows кожен процес — окрема служба WinSW. Схема й потоки даних — у [docs/architecture.md](docs/architecture.md).
- Основна логіка: маршрути `backend/app/routes/`, розрахунки — у `backend/app/services/` (індекс, рекомендації, зрілість і звіти — без БД і мережі); анонімність і приховування малих груп (k) — `backend/app/anonymity.py`.
- Висновки рахують явні правила, а не ШІ: Integrity Index — `services/scoring.py`, рекомендації — `services/recommendations.py` ([docs/methodology.md](docs/methodology.md)); зони й рівні зрілості — [docs/maturity-levels.md](docs/maturity-levels.md) і `services/maturity.py` ([docs/maturity-annex-v.md](docs/maturity-annex-v.md)). Локальна модель лише пише чернетки текстів з агрегатів ([docs/ai.md](docs/ai.md)).

## Що використали

- Backend (`backend/requirements.txt`): FastAPI 0.163.1, Starlette 1.10.0, Uvicorn 0.54.0, SQLAlchemy 2.1.8, Pydantic 2.14.3, ReportLab 5.1.0 (PDF), XlsxWriter 3.3.3 (XLSX), Pillow 13.0.0. Тести (`backend/requirements-dev.txt`): pytest, httpx, trustme.
- Frontend (`frontend/package.json`): React 19, React DOM 19, Chart.js 4.6.1; збірка й тести — Vite 7, TypeScript 5.9, `@vitejs/plugin-react`, Playwright, node:test.
- Шрифт PDF-звітів: DejaVu Sans (`backend/app/static/report-font/DejaVuSans.ttf`, ліцензія Bitstream Vera / DejaVu — `backend/app/static/report-font/LICENSE`).
- Swagger UI 5.17.14 з пакета `swagger-ui-dist`, локально без CDN (`backend/app/static/swagger-ui/`, Apache-2.0 — `LICENSE` і `NOTICE` там само).
- HTTPS reverse proxy: Caddy (`installer/windows-v2/deploy/Caddyfile`); служби Windows: WinSW 2.12.0.
- Локальна мовна модель (необов'язково, працює на сервері): llama.cpp `llama-server` b12180 і модель `Qwen3-8B-Q4_K_M.gguf` (Hugging Face `Qwen/Qwen3-8B-GGUF`); завантаження, контрольні суми й параметри — [docs/LOCAL_LM.md](docs/LOCAL_LM.md). Ліцензії llama.cpp і моделі в репозиторії не зберігаються — звіряйте їх на сторінках джерел.

## Analytics для синтетичної демонстрації

Методика `team-results-demo-0.1` — авторська пропозиція зі статусом `approval_status=proposed`, а не офіційна або затверджена оцінка. Її ваги C1–C7 взято з поточного синтетичного seed. Розрахунок використовує округлені агрегати `/results`; експертний індекс відсутній, приховані категорії не відновлюються, а порівняння циклів має статус `limited_comparability` через відсутність зафіксованих історичних версій анкет і популяцій.

Для локального показу задайте `INTEGRITY_DB` як шлях до **окремої нової синтетичної SQLite-БД**, створіть її через `python -m app.seed` з каталогу `backend`, а потім встановіть `INTEGRITY_ANALYTICS_DEMO=1` перед запуском backend. Прапорець лише вмикає обчислювальні маршрути й не перевіряє походження записів; `synthetic_only=true` у відповіді також не є перевіркою БД. Не використовуйте спільну або робочу БД. Без прапорця обчислювальні маршрути повертають `503`; маршрут опису методики доступний окремо. Деталі — в [сценарії показу](docs/ANALYTICS_DEMO.md) та [API-контракті](docs/API_CONTRACT.md).

## Запуск

### Docker (рекомендовано для демонстрації)

Покрокова інструкція — [docs/DOCKER_DEMO.md](docs/DOCKER_DEMO.md). Коротко: скопіюйте `.env.example` у `.env`, задайте випадковий `V2_SECRET_KEY`, виконайте `docker compose up --build` і відкрийте `http://127.0.0.1:8080/`.

### Запуск на Windows без Docker

Потрібні Node.js 22 або новіший з npm та Python 3.11 або новіший. Команди виконуються у PowerShell з кореня репозиторію.

Backend у першому вікні:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Перевірка доступності API — `http://127.0.0.1:8000/api/health`. Схема API (`/docs`, `/openapi.json`) доступна лише адміністратору V2 після входу з 2FA; див. `docs/API_CONTRACT.md`, розділ «Документація API (Swagger)».

Frontend у другому вікні (пряме підключення до backend):

```powershell
cd frontend
npm install
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev
```

Відкрийте `http://127.0.0.1:5173`. Якщо PowerShell блокує `npm.ps1`, використайте `npm.cmd` без зміни політики виконання Windows.

Для backend на іншому порту, наприклад `8001`, змініть лише значення змінної:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8001"
```

Альтернатива — Vite proxy. У цьому режимі Dashboard звертається до відносних `/api` маршрутів, а proxy пересилає їх на backend:

```powershell
cd frontend
$env:VITE_API_BASE_URL = ""
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8001"
npm run dev
```

`VITE_API_BASE_URL` має пріоритет над proxy. Після зміни змінних перезапустіть Vite.

Секрети, паролі й реальні файли `.env` не публікуються; змінні середовища перелічено в `.env.example`.

## Перевірки

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run test
npm run build
cd ..
git diff --check
```

Ті самі перевірки автоматично виконує GitHub Actions ([`.github/workflows/v2-ci.yml`](.github/workflows/v2-ci.yml)):
- backend — Python 3.13.14 на Windows, повний pytest з контролем кількості тестів;
- frontend — pnpm `--frozen-lockfile`, тести, TypeScript і production build;
- `git diff --check` і перевірка, що в Git немає БД і секретів.

Збірка frontend зберігається як артефакт на 14 днів. CI нічого не розгортає і не підключається до сервера.

## Документація

- [docs/architecture.md](docs/architecture.md) — архітектурні домовленості.
- [docs/ai.md](docs/ai.md) — як команда використала ШІ і як працює вбудована локальна модель.
- [docs/security.md](docs/security.md) — правила роботи з даними.
- [docs/anonymity.md](docs/anonymity.md) — механізм захисту анонімності респондентів.
- [docs/methodology.md](docs/methodology.md) — методика розрахунку Integrity Index і правила рекомендацій.
- [docs/maturity-levels.md](docs/maturity-levels.md) — правило зон і рівнів зрілості для кольорового кодування.
- [docs/objective-comparison-example.md](docs/objective-comparison-example.md) — приклад порівняння самооцінки з об'єктивними показниками.
- [docs/time-savings.md](docs/time-savings.md) — розрахунок економії часу порівняно з ручним процесом.
- [docs/integration-concept.md](docs/integration-concept.md) — концепція інтеграції з іншими цифровими рішеннями у сфері доброчесності.
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md) і [docs/V2_INTEGRATION_CONTRACT.md](docs/V2_INTEGRATION_CONTRACT.md) — контракти API.
- [docs/DOCKER_DEMO.md](docs/DOCKER_DEMO.md) — локальна демонстрація в Docker.
- [docs/ANALYTICS_DEMO.md](docs/ANALYTICS_DEMO.md) — сценарій показу аналітики на синтетичних даних.
- [docs/integration-map.md](docs/integration-map.md) — карта інтеграції з наявними інформаційними системами.
- [docs/abuse-analysis.md](docs/abuse-analysis.md) — аналіз можливих зловживань і запобіжники.

Нові маршрути, схеми даних і формулу індексу команда погоджує до реалізації.

## Використання ШІ

Див. [docs/ai.md](docs/ai.md).

## Ліцензія

MIT — див. [LICENSE](LICENSE).
