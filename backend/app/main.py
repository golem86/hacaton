import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from . import api_docs, audit, settings
from .database import engine
from .migrations import check_schema, migrate
from .request_limits import BodySizeLimitMiddleware, max_body_bytes, validation_error_handler
from .routes import analytics, assessments, results, v2_admin, v2_auth, v2_user
from .routes import tracker  # Recommendations Tracker
from .v2_auth import check_auth_schema, migrate_auth_db


class DropSurveySubmissionAccessLog(logging.Filter):
    """
    S10: журнал доступу uvicorn не містить запитів подання анонімних анкет —
    інакше IP і час подання можна було б зіставити з людиною.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        return not any("/submissions" in str(arg) for arg in (record.args or ()))


def prepare_databases() -> None:
    """
    MIG-1: у development БД доводяться до поточної схеми автоматично;
    у release застосунок лише ПЕРЕВІРЯЄ схему і не стартує, якщо вона не відповідає —
    міграція виконується окремою явною командою після перевіреної резервної копії.
    """
    if settings.auto_migrate():
        report = migrate(engine)
        if report["action"] == "migrated":
            print(f"База оновлена до нової схеми. Резервна копія: {report['backup']}")
        migrate_auth_db()
    else:
        check_schema(engine)
        check_auth_schema()


def create_app() -> FastAPI:
    settings.validate_release_config()
    max_body_bytes()                          # некоректний V2_MAX_BODY_BYTES — сервер не стартує
    settings.check_lm_config()                # некоректні V2_LM_* — сервер не стартує
    prepare_databases()

    access_log = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, DropSurveySubmissionAccessLog) for f in access_log.filters):
        access_log.addFilter(DropSurveySubmissionAccessLog())

    # Стандартні /docs, /redoc, /openapi.json вимкнено: Swagger і схема — лише для адміністратора (api_docs.py)
    application = FastAPI(title="Integrity Dashboard API", docs_url=None, redoc_url=None, openapi_url=None)
    # D2: 422 без input/ctx; ліміт тіла до маршрутизації й автентифікації (request_limits.py).
    # Ліміт додається ДО CORS, тож CORS лишається зовнішнім і 413 отримує CORS-заголовки.
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_middleware(BodySizeLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(settings.frontend_origins()),
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        allow_credentials=True,
    )
    application.include_router(audit.router)  # журнал дій: GET /api/audit-events

    # Адреси модулів підключаються тут; самі адреси лежать у backend/app/routes/
    application.include_router(assessments.router)
    application.include_router(results.router)
    application.include_router(analytics.router)
    application.include_router(tracker.router)  # трекер рекомендацій: рішення, строки, статуси
    application.include_router(v2_auth.router)
    application.include_router(v2_user.router)
    application.include_router(v2_admin.router)
    if settings.dev_mail_enabled():           # S3: у release маршрут не існує взагалі
        application.include_router(v2_auth.dev_router)
    api_docs.install(application)             # GET /docs і /openapi.json — лише сесія admin з 2FA

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/")
    def hello():
        return {"message": "Integrity Dashboard працює"}

    return application


app = create_app()
