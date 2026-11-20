"""
Адміністративні маршрути V2 — Reporting (V2 Integration Contract, розділ 3.3).
Керування користувачами, ролями й сесіями — у routes/v2_admin_users.py (підключено наприкінці файлу).

Дані циклів, результатів і порівнянь frontend отримує з канонічних /api/* (сесія admin).
Дублікати прототипу (/v2/admin/assessments*, /v2/admin/comparisons) вилучено,
щоб на ті самі дані не було двох контрактів.
"""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..request_limits import BoundedId
from ..routes.results import assessment_results
from ..services.reporting import render_pdf, render_xlsx, report_tables
from .v2_auth import require_v2_role

router = APIRouter(prefix="/v2/admin", tags=["Dashboard V2 Admin — Reporting"])


@router.get("/reports/{assessment_id}")
def admin_report(assessment_id: BoundedId, response: Response,
                 _: dict = Depends(require_v2_role("admin")), db: Session = Depends(get_db)):
    results = assessment_results(assessment_id, db)
    response.headers["Cache-Control"] = "no-store"
    return {
        "status": "available",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "/api/assessments/{assessment_id}/results",
        "assessment": results["assessment"],
        "aggregates": results,
        "official_index": None,
        "exports": {"pdf": "available", "xlsx": "available"},
    }


PDF_TYPE = "application/pdf"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/reports/{assessment_id}/export", response_class=Response,
            responses={200: {"content": {PDF_TYPE: {}, XLSX_TYPE: {}}}})
def admin_report_export(assessment_id: BoundedId, format: Literal["pdf", "xlsx"],
                        _: dict = Depends(require_v2_role("admin")), db: Session = Depends(get_db)):
    results = assessment_results(assessment_id, db)
    tables = report_tables(results, datetime.now(timezone.utc))
    content, media_type = (render_pdf(tables), PDF_TYPE) if format == "pdf" else (render_xlsx(tables), XLSX_TYPE)
    return Response(content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="integrity-report-{assessment_id}.{format}"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })


# Керування користувачами, ролями й сесіями (docs/V2_HARDENING_CONTRACT.md, розділ 3) — окремий модуль
# з тим самим префіксом /v2/admin; підключається тут, тому main.py змінювати не потрібно.
from .v2_admin_users import router as users_router  # noqa: E402

router.include_router(users_router)
