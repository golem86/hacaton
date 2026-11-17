from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine
from .migrations import migrate
from .routes import assessments, results, analytics, v2_admin, v2_auth, v2_user, v2_anonymous

# Доводить базу до поточної схеми: створює нову або безпечно оновлює стару
# (з резервною копією і перевірками; дані не стираються). Див. docs/DATABASE_UPGRADE.md
_migration = migrate(engine)
if _migration["action"] == "migrated":
    print(f"База оновлена до нової схеми. Резервна копія: {_migration['backup']}")

app = FastAPI(title="Integrity Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:5176", "http://localhost:5176"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Адреси модулів підключаються тут; самі адреси лежать у backend/app/routes/
app.include_router(assessments.router)
app.include_router(results.router)
app.include_router(analytics.router)
app.include_router(v2_auth.router)
app.include_router(v2_admin.router)
app.include_router(v2_user.router)
app.include_router(v2_anonymous.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello():
    return {"message": "Integrity Dashboard працює"}
