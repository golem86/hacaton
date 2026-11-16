# Симулятор етичних дилем

Спільний технічний фундамент команди Building Integrity Hackathon 2026. [Офіційне завдання 3](https://hack.bitec.com.ua/wp-content/uploads/2025/11/%D0%97%D0%90%D0%92%D0%94%D0%90%D0%9D%D0%9D%D0%AF-3.pdf) описує симулятор етичних дилем у секторі безпеки й оборони. Функціональні модулі команда додає окремо.

## Запуск на Windows

Потрібні Node.js 22 або новіший з npm та Python 3.11 або новіший. Команди виконувати в PowerShell із кореня репозиторію.

Backend у першому вікні PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Перевірка API: `http://127.0.0.1:8000/api/health`. Інтерактивна схема: `http://127.0.0.1:8000/docs`.

Frontend у другому вікні PowerShell:

```powershell
cd frontend
npm install
npm run dev
```

Відкрити `http://127.0.0.1:5173`. Якщо PowerShell блокує `npm.ps1`, використати `npm.cmd` без зміни політики виконання Windows.

## Перевірки

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run build
cd ..
git diff --check
```

Попередній контракт API міститься в [docs/API_CONTRACT.md](docs/API_CONTRACT.md). Перед реалізацією модулів узгодьте в команді їхні маршрути, моделі даних і відповідальних.
