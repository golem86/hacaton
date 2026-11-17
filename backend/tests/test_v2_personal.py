import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.v2_anonymous import ANONYMOUS_DB_PATH, aggregate_submissions
from app.v2_auth import create_user, latest_dev_mail


def test_anonymous_submission_is_separate_and_small_group_is_hidden():
    client = TestClient(app)
    survey = client.get('/v2/anonymous/assessments')
    assert survey.status_code == 200
    survey_id = survey.json()[0]['id']
    response = client.post(f'/v2/anonymous/assessments/{survey_id}/responses', json={
        'submission_id': uuid4().hex,
        'answers': {'a1': 4, 'a2': 3, 'a3': 5},
    })
    assert response.status_code == 201
    assert client.post(f'/v2/anonymous/assessments/{survey_id}/responses', json={
        'submission_id': response.json()['submission_id'],
        'answers': {'a1': 4, 'a2': 3, 'a3': 5},
    }).status_code == 409

    aggregate = aggregate_submissions(survey_id, ['a1', 'a2', 'a3'], 5)
    assert aggregate['responses_total'] is None
    assert aggregate['questions']['a1'] == {'score': None, 'hidden': True}
    with sqlite3.connect(ANONYMOUS_DB_PATH) as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info(v2_anonymous_submissions)')}
    assert 'user_id' not in columns
    assert 'session_id' not in columns


def test_admin_comparison_and_report_expose_only_allowed_aggregates():
    email = f'{uuid4().hex}@example.test'
    create_user('Report Admin', email, 'StrongPass123!', role='admin')
    client = TestClient(app)
    csrf = {'X-CSRF-Token': client.get('/v2/auth/csrf').json()['csrf_token']}
    assert client.post('/v2/auth/login', json={'email': email, 'password': 'StrongPass123!'}, headers=csrf).status_code == 200
    code = latest_dev_mail(email)['body'].split(': ')[1].split('.')[0]
    assert client.post('/v2/auth/2fa/verify', json={'code': code}, headers=csrf).status_code == 200

    comparison = client.get('/v2/admin/comparisons?assessment_id=1&comparison_assessment_id=2')
    assert comparison.status_code == 200
    assert comparison.json()['official_index'] is None
    report = client.get('/v2/admin/reports/1')
    assert report.status_code == 200
    assert report.json()['exports'] == {'pdf': 'unavailable', 'xlsx': 'unavailable'}
    assert client.get('/v2/admin/reports/1/export?format=pdf').status_code == 501
