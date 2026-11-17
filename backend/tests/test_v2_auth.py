from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.v2_auth import create_user, latest_dev_mail


def client_with_csrf() -> tuple[TestClient, dict[str, str]]:
    client = TestClient(app)
    token = client.get('/v2/auth/csrf').json()['csrf_token']
    return client, {'X-CSRF-Token': token}


def test_public_registration_always_creates_user_and_rejects_duplicate():
    client, csrf = client_with_csrf()
    email = f'{uuid4().hex}@example.test'
    payload = {'name': 'Local User', 'email': email, 'password': 'StrongPass123!', 'password_confirmation': 'StrongPass123!', 'role': 'admin'}

    response = client.post('/v2/auth/register', json=payload, headers=csrf)
    assert response.status_code == 201
    assert response.json()['role'] == 'user'
    assert client.post('/v2/auth/register', json=payload, headers=csrf).status_code == 409


def test_login_session_and_user_cannot_access_admin_api():
    client, csrf = client_with_csrf()
    email = f'{uuid4().hex}@example.test'
    client.post('/v2/auth/register', json={'name': 'User', 'email': email, 'password': 'StrongPass123!', 'password_confirmation': 'StrongPass123!'}, headers=csrf)

    assert client.post('/v2/auth/login', json={'email': email, 'password': 'wrong'}, headers=csrf).status_code == 401
    login = client.post('/v2/auth/login', json={'email': email, 'password': 'StrongPass123!'}, headers=csrf)
    assert login.status_code == 200
    assert login.json()['requires_2fa'] is True
    code = latest_dev_mail(email)['body'].split(': ')[1].split('.')[0]
    assert client.post('/v2/auth/2fa/verify', json={'code': code}, headers=csrf).json()['role'] == 'user'
    assert client.get('/v2/auth/me').json()['user']['email'] == email
    assert client.get('/v2/user/profile').status_code == 200
    assert client.get('/v2/admin/assessments').status_code == 403


def test_admin_session_can_access_v2_admin_but_not_user_api():
    email = f'{uuid4().hex}@example.test'
    create_user('Local Admin', email, 'StrongPass123!', role='admin')
    client, csrf = client_with_csrf()
    assert client.post('/v2/auth/login', json={'email': email, 'password': 'StrongPass123!'}, headers=csrf).status_code == 200
    assert client.get('/v2/admin/assessments').status_code == 401
    code = latest_dev_mail(email)['body'].split(': ')[1].split('.')[0]
    assert client.post('/v2/auth/2fa/verify', json={'code': code}, headers=csrf).status_code == 200
    assert client.get('/v2/admin/assessments').status_code == 200
    assert client.get('/v2/user/profile').status_code == 403
    assert client.post('/v2/auth/logout', headers=csrf).status_code == 200
    assert client.get('/v2/auth/me').status_code == 401


def test_login_rate_limit_blocks_repeated_failures():
    client, csrf = client_with_csrf()
    email = f'{uuid4().hex}@example.test'
    client.post('/v2/auth/register', json={'name': 'Rate Limited', 'email': email, 'password': 'StrongPass123!', 'password_confirmation': 'StrongPass123!'}, headers=csrf)

    statuses = [client.post('/v2/auth/login', json={'email': email, 'password': 'wrong'}, headers=csrf).status_code for _ in range(6)]
    assert statuses[:5] == [401, 401, 401, 401, 401]
    assert statuses[5] == 429


def test_two_factor_resend_rate_limit_is_scoped_to_user():
    email = f'{uuid4().hex}@example.test'
    create_user('Rate Limited 2FA', email, 'StrongPass123!')
    client, csrf = client_with_csrf()
    assert client.post('/v2/auth/login', json={'email': email, 'password': 'StrongPass123!'}, headers=csrf).status_code == 200
    assert client.post('/v2/auth/2fa/resend', headers=csrf).status_code == 200
    assert client.post('/v2/auth/2fa/resend', headers=csrf).status_code == 200
    assert client.post('/v2/auth/2fa/resend', headers=csrf).status_code == 429


def test_personal_attempts_are_server_owned_and_completed_attempts_are_immutable():
    email_a = f'{uuid4().hex}@example.test'
    email_b = f'{uuid4().hex}@example.test'
    create_user('User A', email_a, 'StrongPass123!')
    create_user('User B', email_b, 'StrongPass123!')

    client_a, csrf_a = client_with_csrf()
    client_a.post('/v2/auth/login', json={'email': email_a, 'password': 'StrongPass123!'}, headers=csrf_a)
    code_a = latest_dev_mail(email_a)['body'].split(': ')[1].split('.')[0]
    assert client_a.post('/v2/auth/2fa/verify', json={'code': code_a}, headers=csrf_a).status_code == 200

    catalog = client_a.get('/v2/user/assessments')
    assert catalog.status_code == 200
    assert catalog.json()[0]['questions']
    attempt = client_a.post('/v2/user/attempts', json={
        'id': 'attempt-owned-by-a',
        'assessment_id': 'personal-2026-q4',
        'answers': {'q1': 3},
    })
    assert attempt.status_code == 201

    client_b, csrf_b = client_with_csrf()
    client_b.post('/v2/auth/login', json={'email': email_b, 'password': 'StrongPass123!'}, headers=csrf_b)
    code_b = latest_dev_mail(email_b)['body'].split(': ')[1].split('.')[0]
    assert client_b.post('/v2/auth/2fa/verify', json={'code': code_b}, headers=csrf_b).status_code == 200
    assert client_b.get('/v2/user/attempts/attempt-owned-by-a').status_code == 404
    assert client_b.patch('/v2/user/attempts/attempt-owned-by-a', json={'answers': {'q1': 5}}).status_code == 404

    completed = client_a.post('/v2/user/attempts/attempt-owned-by-a/complete', json={'answers': {
        'q1': 3, 'q2': 3, 'q3': 3, 'q4': 3, 'q5': 3, 'q6': 3, 'q7': 3,
    }})
    assert completed.status_code == 200
    assert client_a.post('/v2/user/attempts/attempt-owned-by-a/complete', json={'answers': {
        'q1': 3, 'q2': 3, 'q3': 3, 'q4': 3, 'q5': 3, 'q6': 3, 'q7': 3,
    }}).status_code == 409
    assert client_a.patch('/v2/user/attempts/attempt-owned-by-a', json={'answers': {'q1': 1}}).status_code == 409
    assert client_a.get('/v2/user/stats').json()['completed_tests'] == 1
