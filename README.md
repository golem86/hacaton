# Integrity Management Dashboard

Цифрова система оцінювання стану й зрілості системи доброчесності та підтримки управлінських рішень. Джерело вимог — наданий командою актуальний PDF «Завдання 3 — Integrity Management Dashboard». Оцінювання призначене для розвитку системи, а не для оцінки окремих посадових осіб.

## Стан проєкту

Реалізовано Executive Dashboard на React + TypeScript + Vite з Assessment Manager API та агрегованими результатами закритих циклів. Dashboard показує KPI, C1–C7, категорії респондентів, об’єктивні показники й безпечні стани відкритих циклів. Backend Analytics API вже містить Integrity Index, порівняння циклів і пояснювані пропозиції рекомендацій для синтетичної демонстрації. Поточний Dashboard звертається до `/results` і ще потребує підключення до маршрутів Analytics. Збереження та прийняття рекомендацій, а також серверний Reporting API залишаються запланованими.

## Напрями розробки

Assessment Manager керує циклами оцінювання. Digital Questionnaire забезпечує самооцінювання й експертне оцінювання. Integrity Index Engine розраховує показники за документованою авторською демометодикою. Executive Dashboard показує агреговані результати; API Comparative Analytics обчислює обмежено порівнювану динаміку. Recommendations Engine пропонує пояснювані заходи. Доменний прототип Recommendations Tracker є, але його збереження та HTTP-маршрути ще не інтегровані. Audit Trail уже реалізовано та інтегровано через PR #7; Reporting Module залишається запланованим. Поточні та заплановані точки інтеграції наведено в [API-контракті](docs/API_CONTRACT.md).

Модельним об’єктом демонстрації є вищий військовий навчальний заклад. Дані демонстрації мають бути виключно синтетичними. Анкети, критерії та індикатори мають допускати адаптацію для інших органів сектору безпеки й оборони.

## Analytics для синтетичної демонстрації

Методика `team-results-demo-0.1` — авторська пропозиція зі статусом `approval_status=proposed`, а не офіційна або затверджена оцінка. Її ваги C1–C7 взято з поточного синтетичного seed. Розрахунок використовує округлені агрегати `/results`; експертний індекс відсутній, приховані категорії не відновлюються, а порівняння циклів має статус `limited_comparability` через відсутність зафіксованих історичних версій анкет і популяцій.

Для локального показу задайте `INTEGRITY_DB` як шлях до **окремої нової синтетичної SQLite-БД**, створіть її через `python -m app.seed` з каталогу `backend`, а потім встановіть `INTEGRITY_ANALYTICS_DEMO=1` перед запуском backend. Прапорець лише вмикає обчислювальні маршрути й не перевіряє походження записів; `synthetic_only=true` у відповіді також не є перевіркою БД. Не використовуйте спільну або робочу БД. Без прапорця обчислювальні маршрути повертають `503`; маршрут опису методики доступний окремо. Деталі — в [сценарії показу](docs/ANALYTICS_DEMO.md) та [API-контракті](docs/API_CONTRACT.md).

## Запуск на Windows

Потрібні Node.js 22 або новіший з npm та Python 3.11 або новіший. Команди виконуються у PowerShell з кореня репозиторію.

Backend у першому вікні:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Перевірка доступності API — `http://127.0.0.1:8000/api/health`. Схема поточного API — `http://127.0.0.1:8000/docs`.

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

`VITE_API_BASE_URL` має пріоритет над proxy. Після зміни змінних перезапустіть Vite. У запитах Dashboard використовуються `GET /api/assessments`, `GET /api/assessments/{id}` і `GET /api/assessments/{id}/results`; для деморежиму клієнт передає `X-Role: manager`.

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

Архітектурні домовленості — у [docs/architecture.md](docs/architecture.md), правила роботи з даними — у [docs/security.md](docs/security.md). Нові маршрути, схеми даних і формулу індексу команда погоджує до реалізації.
