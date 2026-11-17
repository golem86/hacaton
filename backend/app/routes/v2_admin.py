from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..routes.assessments import list_assessments, read_assessment
from ..routes.results import assessment_results
from .v2_auth import require_role

router = APIRouter(prefix="/v2/admin", tags=["Dashboard V2 Admin"])


@router.get("/assessments")
def admin_assessments(_: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return list_assessments(db)


@router.get("/assessments/{assessment_id}")
def admin_assessment(assessment_id: int, _: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return read_assessment(assessment_id, db)


@router.get("/assessments/{assessment_id}/results")
def admin_results(assessment_id: int, _: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return assessment_results(assessment_id, db)


@router.get("/comparisons")
def admin_comparison(
    assessment_id: int = Query(..., ge=1),
    comparison_assessment_id: int = Query(..., ge=1),
    _: dict = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if assessment_id == comparison_assessment_id:
        raise HTTPException(status_code=422, detail="Потрібно обрати два різні цикли")
    left = assessment_results(assessment_id, db)
    right = assessment_results(comparison_assessment_id, db)
    right_by_code = {item["code"]: item for item in right["components"]}
    components = []
    for item in left["components"]:
        other = right_by_code.get(item["code"])
        if other is None:
            continue
        score_delta = None if item["score"] is None or other["score"] is None else round(item["score"] - other["score"], 1)
        other_categories = {entry["category"]: entry for entry in other["by_category"]}
        by_category = []
        for entry in item["by_category"]:
            counterpart = other_categories.get(entry["category"])
            hidden = bool(entry.get("hidden") or (counterpart or {}).get("hidden"))
            by_category.append({
                "category": entry["category"],
                "score_delta": None if hidden or entry.get("score") is None or (counterpart or {}).get("score") is None else round(entry["score"] - counterpart["score"], 1),
                "hidden": hidden,
            })
        components.append({"code": item["code"], "name": item["name"], "score_delta": score_delta, "by_category": by_category})
    return {
        "status": "ok",
        "assessments": [left["assessment"], right["assessment"]],
        "components": components,
        "methodology": None,
        "official_index": None,
    }


@router.get("/reports/{assessment_id}")
def admin_report(assessment_id: int, _: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
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
def admin_report_export(assessment_id: int, format: str = Query(..., pattern="^(pdf|xlsx)$"), _: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    # Не генеруємо фальшивий файл без погодженого серверного формату та бібліотеки.
    assessment_results(assessment_id, db)
    raise HTTPException(status_code=501, detail=f"Експорт {format.upper()} очікує погодженого Reporting API")
