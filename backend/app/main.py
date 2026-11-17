from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import audit
from .database import engine
from .migrations import migrate
from .routes import assessments, results, analytics

# Доводить базу до поточної схеми: створює нову або безпечно оновлює стару
# (з резервною копією і перевірками; дані не стираються). Див. docs/DATABASE_UPGRADE.md
_migration = migrate(engine)
if _migration["action"] == "migrated":
    print(f"База оновлена до нової схеми. Резервна копія: {_migration['backup']}")

app = FastAPI(title="Integrity Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(audit.router)  # журнал дій: GET /api/audit-events

# Адреси модулів підключаються тут; самі адреси лежать у backend/app/routes/
app.include_router(assessments.router)
app.include_router(results.router)
app.include_router(analytics.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello():
    return {"message": "Integrity Dashboard працює"}
