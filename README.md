# Integrity Management Dashboard

Цифрова система оцінювання стану й зрілості системи доброчесності та підтримки управлінських рішень. Джерело вимог — наданий командою актуальний PDF «Завдання 3 — Integrity Management Dashboard». Оцінювання призначене для розвитку системи, а не для оцінки окремих посадових осіб.

## Стан проєкту

Зараз реалізовано лише стартову сторінку на React + TypeScript + Vite та FastAPI з `GET /api/health` і локальним CORS. Є мінімальний тест API. SQLite, функціональні модулі, рольовий доступ, опитування та розрахунок Integrity Index ще не реалізовані в цій гілці.

## Напрями розробки

Assessment Manager керує циклами оцінювання. Digital Questionnaire забезпечує самооцінювання й експертне оцінювання. Integrity Index Engine розраховує показники за документованою методикою. Executive Dashboard та Comparative Analytics показують агреговані результати й динаміку. Recommendations Engine пропонує пояснювані заходи, Recommendations Tracker відстежує прийняті заходи. Audit Trail фіксує дії користувачів, Reporting Module формує звіти й експорт. Усі напрями заплановані, їхні попередні точки інтеграції наведено в [API-контракті](docs/API_CONTRACT.md).

Модельним об’єктом демонстрації є вищий військовий навчальний заклад. Дані демонстрації мають бути виключно синтетичними. Анкети, критерії та індикатори мають допускати адаптацію для інших органів сектору безпеки й оборони.

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

Frontend у другому вікні:

```powershell
cd frontend
npm install
npm run dev
```

Відкрийте `http://127.0.0.1:5173`. Якщо PowerShell блокує `npm.ps1`, використайте `npm.cmd` без зміни політики виконання Windows.

## Перевірки

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run build
cd ..
git diff --check
```

Архітектурні домовленості — у [docs/architecture.md](docs/architecture.md), правила роботи з даними — у [docs/security.md](docs/security.md). Нові маршрути, схеми даних і формулу індексу команда погоджує до реалізації.
