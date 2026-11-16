from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routes import assessments, results

# Створює таблиці, якщо їх ще немає (дані при цьому не стираються)
Base.metadata.create_all(engine)

app = FastAPI(title="Integrity Dashboard API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Адреси модулів підключаються тут; самі адреси лежать у backend/app/routes/
app.include_router(assessments.router)
app.include_router(results.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def hello():
    return {"message": "Integrity Dashboard працює"}
