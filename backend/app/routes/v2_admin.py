"""
Адміністративні маршрути V2 — лише Reporting (V2 Integration Contract, розділ 3.3).

Дані циклів, результатів і порівнянь frontend отримує з канонічних /api/* (сесія admin).
Дублікати прототипу (/v2/admin/assessments*, /v2/admin/comparisons) вилучено,
щоб на ті самі дані не було двох контрактів.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..routes.results import assessment_results
from .v2_auth import require_v2_role

router = APIRouter(prefix="/v2/admin", tags=["Dashboard V2 Admin — Reporting"])


@router.get("/reports/{assessment_id}")
def admin_report(assessment_id: int, _: dict = Depends(require_v2_role("admin")), db: Session = Depends(get_db)):
    results = assessment_results(assessment_id, db)
    return {
        "status": "available",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "/api/assessments/{assessment_id}/results",
        "assessment": results["assessment"],
        "aggregates": results,
        "official_index": None,
        "exports": {"pdf": "unavailable", "xlsx": "unavailable"},
    }


@router.get("/reports/{assessment_id}/export")
def admin_report_export(assessment_id: int, format: str = Query(..., pattern="^(pdf|xlsx)$"),
                        _: dict = Depends(require_v2_role("admin")), db: Session = Depends(get_db)):
    # Файли не генеруються до окремого погодженого контракту Reporting.
    assessment_results(assessment_id, db)
    raise HTTPException(status_code=501, detail=f"Експорт {format.upper()} очікує погодженого Reporting API")
