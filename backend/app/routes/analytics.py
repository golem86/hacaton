"""Real DB integration through the existing /results service; synthetic demo only."""
import os
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..roles import ANALYTICS_ROLES, require_role
from ..services.scoring import VERSION, calculate_index, methodology
from ..services.analytics import compare_categories, compare_periods
from ..services.recommendations import generate_recommendations
from .results import assessment_results

router = APIRouter(prefix='/api', tags=['Аналітика — синтетична демонстрація'],
                   dependencies=[Depends(require_role(*ANALYTICS_ROLES))])
MethodologyVersion = Literal['team-results-demo-0.1']


def demo_enabled():
    if os.environ.get('INTEGRITY_ANALYTICS_DEMO') != '1':
        raise HTTPException(503, 'Set INTEGRITY_ANALYTICS_DEMO=1 only for a synthetic database')


def results(assessment_id, db):
    # Direct call reuses the same read-only query, closed-cycle and suppression rules.
    # Our router separately enforces the same role dependencies as /results.
    data = assessment_results(assessment_id, db)
    try:
        calculate_index(data)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, 'Results do not match the selected demo methodology') from exc
    return data


@router.get('/index-methodologies/{version}')
def read_methodology(version: str):
    if version != VERSION:
        raise HTTPException(404, 'Unknown methodology version')
    return methodology()


@router.get('/assessments/{assessment_id}/index', dependencies=[Depends(demo_enabled)])
def read_index(assessment_id: int, methodology: MethodologyVersion = Query(...),
               db: Session = Depends(get_db)):
    return calculate_index(results(assessment_id, db))


@router.get('/assessments/{assessment_id}/recommendations', dependencies=[Depends(demo_enabled)])
def read_recommendations(assessment_id: int, methodology: MethodologyVersion = Query(...),
                         db: Session = Depends(get_db)):
    return generate_recommendations(results(assessment_id, db))


@router.get('/analytics/comparisons', dependencies=[Depends(demo_enabled)])
def read_comparisons(assessment_id: int, methodology: MethodologyVersion = Query(...),
                      comparison_assessment_id: int | None = None, db: Session = Depends(get_db)):
    data = results(assessment_id, db)
    trend = None
    if comparison_assessment_id is not None:
        try:
            trend = compare_periods(data, results(comparison_assessment_id, db))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return {'assessment': data['assessment'], 'methodology_version': VERSION,
            'category_comparisons': compare_categories(data), 'period_comparison': trend}
