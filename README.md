# Integrity Management Dashboard

**Командний проєкт для Building Integrity Hackathon 2026 · Завдання 3. Integrity Management Dashboard.**

Цифрова система оцінювання стану й зрілості системи доброчесності та підтримки управлінських рішень: анонімне опитування, аналіз результатів в агрегованому вигляді, Integrity Index, рекомендації та звіти. Оцінювання призначене для розвитку системи, а не для оцінки окремих посадових осіб. Проєкт розробляється з акцентом на конфіденційність відповідей, розмежування прав доступу та прозорість методології.

## Команда

Назва команди та GitHub-логіни учасників будуть додані перед фінальним поданням.

## Проблема

Організаціям потрібні інструменти, які допомагають збирати анонімний зворотний зв'язок, аналізувати його в агрегованому вигляді та виявляти напрями для вдосконалення без розкриття особистості респондентів.

## Наше рішення

- Анонімне опитування Survey з одноразовими кодами.
- Assessment Manager: створення циклів, категорії респондентів, мінімальний розмір групи, видача кодів, участь, закриття циклу.
- Кабінет користувача та адміністративні можливості з розмежуванням прав.
- Вхід із додатковою перевіркою OTP/2FA.
- Executive Dashboard: бали компонентів C1–C7, порівняння категорій, об'єктивні показники, динаміка закритих циклів.
- Integrity Index, рекомендації та порівняльна аналітика за демонстраційною методикою на синтетичних даних.
- Звіти PDF/XLSX за закритими циклами.
- Журнал аудиту адміністративних дій.
- Персональний модуль тестувань.

Модельним об'єктом демонстрації є вищий військовий навчальний заклад. Дані демонстрації виключно синтетичні. Анкети, критерії та індикатори мають допускати адаптацію для інших органів сектору безпеки й оборони.

## Технології

- Frontend: React, TypeScript, Vite, Chart.js.
- Backend: Python, FastAPI, SQLAlchemy.
- Дані: SQLite.
- HTTPS reverse proxy: Caddy.
- Тести: pytest, node:test, Playwright.
- Контроль версій: Git і GitHub.

**Примітка:** демонстраційні показники базуються на синтетичних даних. Їх не слід трактувати як висновки про реальну організацію.

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
- [docs/security.md](docs/security.md) — правила роботи з даними.
- [docs/anonymity.md](docs/anonymity.md) — механізм захисту анонімності респондентів.
- [docs/API_CONTRACT.md](docs/API_CONTRACT.md) і [docs/V2_INTEGRATION_CONTRACT.md](docs/V2_INTEGRATION_CONTRACT.md) — контракти API.
- [docs/DOCKER_DEMO.md](docs/DOCKER_DEMO.md) — локальна демонстрація в Docker.

Нові маршрути, схеми даних і формулу індексу команда погоджує до реалізації.

## Використання ШІ

Див. [docs/ai.md](docs/ai.md).

## Ліцензія

MIT — див. [LICENSE](LICENSE).
