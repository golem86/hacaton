"""
Негативні тести безпеки V2 (V2 Integration Contract, розділ 4: S1–S12).

У цьому файлі демо-режим X-Role ВИМКНЕНО (як у release): доступ дає лише справжня сесія.
"""
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from starlette.requests import Request

from app import request_security, settings
from app.database import SessionLocal, engine
from app.main import DropSurveySubmissionAccessLog, app, create_app
from app.models import AccessToken, AuditEvent, Question, ResponseSet
from app.v2_auth import auth_db_path, session_cookie_name, user_for_session

from v2_helpers import PASSWORD, login, make_user, new_email, preauth_client, start_login, latest_code

OPEN_ID, CLOSED_ID = 3, 1


@pytest.fixture(autouse=True)
def no_demo_xrole(monkeypatch):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")


def admin_client():
    return login(make_user("admin"))


def issue_token(client, csrf, assessment_id=OPEN_ID) -> str:
    response = client.post(f"/api/assessments/{assessment_id}/tokens", params={"count": 1}, headers=csrf)
    assert response.status_code == 201, response.text
    return response.json()["tokens"][0]


def answers():
    db = SessionLocal()
    ids = [q.id for q in db.query(Question).filter(Question.kind == "survey")]
    db.close()
    return [{"question_id": i, "value": 3} for i in ids]


def submission(token):
    return {"token": token, "respondent_category": "cadets", "unit": "Факультет 1", "answers": answers()}


def response_count() -> int:
    db = SessionLocal()
    n = db.query(ResponseSet).count()
    db.close()
    return n


# --- S1: три класи маршрутів; X-Role ні на що не впливає ------------------------

PUBLIC_GETS = ["/api/assessments", f"/api/assessments/{OPEN_ID}",
               f"/api/assessments/{OPEN_ID}/questionnaires", "/api/units", "/api/health"]
PROTECTED = [("get", f"/api/assessments/{CLOSED_ID}/results"), ("get", "/api/audit-events"),
             ("get", f"/api/assessments/{OPEN_ID}/participation"),
             ("get", "/api/index-methodologies/team-results-demo-0.1"),
             ("post", f"/api/assessments/{OPEN_ID}/tokens"), ("post", f"/api/assessments/{OPEN_ID}/close"),
             ("get", "/v2/admin/reports/1"), ("get", "/v2/user/profile")]


def test_s1_public_gets_identical_with_and_without_x_role():
    anon = TestClient(app)
    for path in PUBLIC_GETS:
        plain = anon.get(path)
        spoofed = anon.get(path, headers={"X-Role": "admin"})
        assert plain.status_code == spoofed.status_code == 200, path
        assert plain.json() == spoofed.json(), path


@pytest.mark.parametrize("method, path", PROTECTED)
@pytest.mark.parametrize("role", ["admin", "manager", "auditor", "respondent"])
def test_s1_x_role_without_session_gives_no_access(method, path, role):
    response = getattr(TestClient(app), method)(path, headers={"X-Role": role})
    assert response.status_code == 401


def test_s1_user_session_plus_spoofed_admin_header_is_forbidden():
    client, _ = login(make_user())
    for path in (f"/api/assessments/{CLOSED_ID}/results", "/api/audit-events", "/v2/admin/reports/1"):
        assert client.get(path, headers={"X-Role": "admin"}).status_code == 403, path


def test_s1_admin_session_reaches_protected_routes():
    client, csrf = admin_client()
    assert client.get(f"/api/assessments/{CLOSED_ID}/results").status_code == 200
    assert client.get("/api/audit-events").status_code == 200
    assert client.post(f"/api/assessments/{OPEN_ID}/tokens", headers=csrf).status_code == 201


def test_s1_pending_session_without_2fa_is_not_a_principal():
    client, _ = start_login(make_user("admin"))
    assert client.get(f"/api/assessments/{CLOSED_ID}/results").status_code == 401


# --- S2: анонімні відповіді лише через Survey API з одноразовим кодом -------------

def test_s2_prototype_anonymous_routes_do_not_exist():
    anon = TestClient(app)
    assert anon.get("/v2/anonymous/assessments").status_code == 404
    assert anon.post("/v2/anonymous/assessments/anonymous-integrity-2026/responses",
                     json={"answers": {"a1": 5}}).status_code == 404


def test_s2_code_rules():
    client, csrf = admin_client()
    anon = TestClient(app)
    token = issue_token(client, csrf)
    assert anon.post(f"/api/assessments/{OPEN_ID}/submissions", json=submission(token)).status_code == 201
    assert anon.post(f"/api/assessments/{OPEN_ID}/submissions", json=submission(token)).status_code == 403
    assert anon.post(f"/api/assessments/{OPEN_ID}/submissions", json=submission("made-up")).status_code == 403
    assert anon.post(f"/api/assessments/{OPEN_ID}/submissions", json=submission("")).status_code == 422
    other = TestClient(app).post(f"/api/assessments/{CLOSED_ID}/submissions", json=submission(issue_token(client, csrf)))
    assert other.status_code == 409


def test_s2_twenty_concurrent_posts_with_one_code_accept_exactly_one():
    client, csrf = admin_client()
    token = issue_token(client, csrf)
    before = response_count()
    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda _: TestClient(app).post(f"/api/assessments/{OPEN_ID}/submissions",
                                                              json=submission(token)).status_code, range(20)))
    assert codes.count(201) == 1 and codes.count(403) == 19
    assert response_count() == before + 1


# --- S3: dev-mail недоступний у release -------------------------------------------

def release_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "release")
    monkeypatch.setenv("V2_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("V2_AUTH_DEV_MAIL", "0")
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")
    monkeypatch.delenv("V2_AUTH_SECURE_COOKIE", raising=False)
    monkeypatch.delenv("V2_SMTP_HOST", raising=False)


@pytest.mark.parametrize("flag", ["V2_AUTH_DEV_MAIL", "INTEGRITY_DEMO_XROLE"])
def test_s3_release_refuses_to_start_with_dev_flags(monkeypatch, flag):
    release_env(monkeypatch)
    monkeypatch.setenv(flag, "1")
    with pytest.raises(RuntimeError, match=flag):
        create_app()


def test_s3_release_refuses_insecure_cookies_or_missing_secret(monkeypatch):
    release_env(monkeypatch)
    monkeypatch.setenv("V2_AUTH_SECURE_COOKIE", "0")
    with pytest.raises(RuntimeError, match="V2_AUTH_SECURE_COOKIE"):
        create_app()
    release_env(monkeypatch)
    monkeypatch.setenv("V2_SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="V2_SECRET_KEY"):
        create_app()


def test_s3_release_has_no_dev_mail_route_and_stores_no_otp(monkeypatch):
    release_env(monkeypatch)
    release_app = create_app()
    client = TestClient(release_app, base_url="https://testserver")
    assert client.get("/v2/auth/dev-mail/latest").status_code == 404
    email = make_user()
    preauth = client.get("/v2/auth/csrf").json()["csrf_token"]
    with sqlite3.connect(auth_db_path()) as con:
        before = con.execute("SELECT COUNT(*) FROM v2_dev_mail").fetchone()[0]
    response = client.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"X-CSRF-Token": preauth, "Origin": "https://testserver"})
    assert response.status_code == 503               # SMTP не налаштовано — код не надсилається й не зберігається
    with sqlite3.connect(auth_db_path()) as con:
        after = con.execute("SELECT COUNT(*) FROM v2_dev_mail").fetchone()[0]
        challenges = con.execute("SELECT code_hash FROM v2_challenges").fetchall()
    assert after == before
    assert all(len(row[0]) == 64 for row in challenges)   # лише SHA-256, без відкритих кодів


def test_s3_dev_mail_answers_only_local_requests():
    remote = TestClient(app, client=("203.0.113.7", 50000))
    assert remote.get("/v2/auth/dev-mail/latest").status_code == 404


# --- S4: CSRF за контрактом розділу 3.0 -----------------------------------------

def test_s4_write_without_token_is_rejected():
    client, csrf = login(make_user())
    body = {"assessment_id": "personal-2026-q4", "answers": {"q1": 3}}
    assert client.post("/v2/user/attempts", json=body).status_code == 403
    assert client.post("/v2/user/attempts", json=body, headers=csrf).status_code == 201


def test_s4_token_of_another_session_is_rejected():
    client_a, _ = login(make_user())
    _, csrf_b = login(make_user())
    assert client_a.post("/v2/user/attempts", headers=csrf_b,
                         json={"assessment_id": "personal-2026-q4", "answers": {"q1": 3}}).status_code == 403


def test_s4_token_from_before_session_rotation_is_rejected():
    email = make_user()
    client, pending_csrf = start_login(email)
    verified = client.post("/v2/auth/2fa/verify", json={"code": latest_code(email)},
                           headers={"X-CSRF-Token": pending_csrf})
    assert verified.status_code == 200 and verified.json()["csrf_token"] != pending_csrf
    assert client.post("/v2/user/attempts", headers={"X-CSRF-Token": pending_csrf},
                       json={"assessment_id": "personal-2026-q4", "answers": {"q1": 3}}).status_code == 403


def test_s4_unsigned_preauth_token_is_rejected():
    client, _ = preauth_client()
    response = client.post("/v2/auth/login", json={"email": new_email(), "password": PASSWORD},
                           headers={"X-CSRF-Token": "forged-token"})
    assert response.status_code == 403


def test_s4_foreign_origin_is_rejected():
    client, csrf = login(make_user())
    response = client.post("/v2/user/attempts", json={"assessment_id": "personal-2026-q4", "answers": {"q1": 3}},
                           headers={**csrf, "Origin": "https://evil.example"})
    assert response.status_code == 403
    client2, preauth = preauth_client()
    assert client2.post("/v2/auth/login", json={"email": new_email(), "password": PASSWORD},
                        headers={"X-CSRF-Token": preauth, "Referer": "https://evil.example/page"}).status_code == 403


def test_s4_release_requires_origin_or_referer(monkeypatch):
    monkeypatch.setattr(settings, "is_release", lambda: True)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b"",
                       "scheme": "https", "server": ("testserver", 443)})
    with pytest.raises(HTTPException) as error:
        request_security.check_origin(request)
    assert error.value.status_code == 403


def test_s4_admin_api_write_requires_csrf():
    client, csrf = admin_client()
    assert client.post(f"/api/assessments/{OPEN_ID}/tokens").status_code == 403
    assert client.post(f"/api/assessments/{OPEN_ID}/tokens", headers=csrf).status_code == 201


def test_assessment_manager_requires_verified_admin_session_and_csrf():
    body = {"name": "Синтетичний V2", "start_date": "2026-11-19",
            "categories": ["cadets"], "min_group_size": 5,
            "questionnaire_version": "demo-v1"}
    anon = TestClient(app)
    assert anon.post("/api/assessments", json=body, headers={"X-Role": "admin"}).status_code == 401
    user, user_csrf = login(make_user())
    assert user.post("/api/assessments", json=body,
                     headers={**user_csrf, "X-Role": "admin"}).status_code == 403
    admin, csrf = admin_client()
    assert admin.post("/api/assessments", json=body).status_code == 403
    created = admin.post("/api/assessments", json=body, headers=csrf)
    assert created.status_code == 201
    cycle_id = created.json()["id"]
    path = f"/api/assessments/{cycle_id}"
    assert admin.post(path + "/activate").status_code == 403
    assert admin.post(path + "/activate", headers=csrf).status_code == 200
    assert admin.post(path + "/tokens?category=cadets").status_code == 403
    assert admin.post(path + "/tokens?category=cadets", headers=csrf).status_code == 201
    assert anon.get(path + "/participation").status_code == 401
    assert user.get(path + "/participation").status_code == 403
    assert admin.get(path + "/participation").status_code == 200
    assert admin.post(path + "/close").status_code == 403
    assert admin.post(path + "/close", headers=csrf).status_code == 200


def test_s4_cookie_without_host_prefix_is_ignored_in_secure_mode(monkeypatch):
    monkeypatch.setenv("V2_AUTH_SECURE_COOKIE", "1")
    client, _ = login(make_user(), base_url="https://testserver")
    session_token = client.cookies.get("__Host-v2_session")
    assert session_token and user_for_session(session_token)
    injected = TestClient(app, base_url="https://testserver")
    injected.cookies.set("v2_session", session_token)        # без префікса __Host-
    assert injected.get("/v2/auth/me").status_code == 401


# --- S5: власник персональних спроб ---------------------------------------------

def test_s5_foreign_attempt_is_not_found():
    client_a, csrf_a = login(make_user())
    created = client_a.post("/v2/user/attempts", headers=csrf_a,
                            json={"assessment_id": "personal-2026-q4", "answers": {"q1": 3}}).json()
    client_b, csrf_b = login(make_user())
    assert client_b.get(f"/v2/user/attempts/{created['id']}").status_code == 404
    assert client_b.post(f"/v2/user/attempts/{created['id']}/complete", headers=csrf_b,
                         json={"answers": {f"q{i}": 3 for i in range(1, 8)}}).status_code == 404
    assert all(a["id"] != created["id"] for a in client_b.get("/v2/user/attempts").json())


# --- S6: rate limiting без обходу і без блокування чужого акаунта -----------------

def failed_logins(email, client, preauth, count, extra_headers=None):
    return [client.post("/v2/auth/login", json={"email": email, "password": "wrong-pass"},
                        headers={"X-CSRF-Token": preauth, **(extra_headers or {})}).status_code
            for _ in range(count)]


def test_s6_attacker_ip_does_not_lock_out_owner():
    email = make_user()
    attacker, preauth = preauth_client(client=("198.51.100.1", 1000))
    assert failed_logins(email, attacker, preauth, 6)[-1] == 429
    client, _ = login(email, client=("198.51.100.2", 1000))     # власник з іншого IP
    assert client.get("/v2/user/profile").status_code == 200


def test_s6_spoofed_forwarded_for_from_untrusted_peer_is_ignored():
    email = make_user()
    attacker, preauth = preauth_client(client=("198.51.100.3", 1000))
    statuses = [attacker.post("/v2/auth/login", json={"email": email, "password": "wrong-pass"},
                              headers={"X-CSRF-Token": preauth, "X-Forwarded-For": f"10.9.9.{i}"}).status_code
                for i in range(6)]
    assert statuses[-1] == 429


def test_s6_forwarded_for_from_trusted_proxy_is_used(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "192.0.2.10")
    email = make_user()
    proxy, preauth = preauth_client(client=("192.0.2.10", 1000))
    assert failed_logins(email, proxy, preauth, 6, {"X-Forwarded-For": "203.0.113.50"})[-1] == 429
    # інший клієнт за тим самим проксі не заблокований
    other = proxy.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                       headers={"X-CSRF-Token": preauth, "X-Forwarded-For": "203.0.113.51"})
    assert other.status_code == 200


def test_s6_successful_logins_behind_one_ip_never_exhaust_the_limit():
    """Увесь заклад за однією зовнішньою IP-адресою: 35 успішних входів не блокують 36-й."""
    shared_ip = ("198.51.100.77", 1000)
    for _ in range(35):
        start_login(make_user(), client=shared_ip)
    client, _ = login(make_user(), client=shared_ip)
    assert client.get("/v2/user/profile").status_code == 200


# --- S7: ротація сесії після 2FA -----------------------------------------------

def test_s7_session_token_rotates_after_2fa():
    email = make_user()
    client, pending_csrf = start_login(email)
    pending_token = client.cookies.get(session_cookie_name())
    assert client.post("/v2/auth/2fa/verify", json={"code": latest_code(email)},
                       headers={"X-CSRF-Token": pending_csrf}).status_code == 200
    new_token = client.cookies.get(session_cookie_name())
    assert new_token != pending_token
    assert user_for_session(pending_token) is None
    stale = TestClient(app)
    stale.cookies.set(session_cookie_name(), pending_token)
    assert stale.get("/v2/auth/me").status_code == 401


# --- S8: атрибути cookie (HTTPS reverse proxy перевіряється на стенді) ------------

def test_s8_secure_cookie_attributes(monkeypatch):
    monkeypatch.setenv("V2_AUTH_SECURE_COOKIE", "1")
    client, preauth = preauth_client(base_url="https://testserver")
    email = make_user()
    response = client.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"X-CSRF-Token": preauth})
    cookie = next(c for c in response.headers.get_list("set-cookie") if c.startswith("__Host-v2_session="))
    lowered = cookie.lower()
    assert "secure" in lowered and "httponly" in lowered and "path=/" in lowered and "samesite=lax" in lowered
    assert "domain=" not in lowered


# --- S9: реєстрація не розкриває існування email --------------------------------

def test_s9_register_same_answer_for_new_and_existing_email():
    client, preauth = preauth_client()
    existing = make_user()
    payload = {"name": "Someone", "password": PASSWORD, "password_confirmation": PASSWORD}
    a = client.post("/v2/auth/register", json={**payload, "email": existing}, headers={"X-CSRF-Token": preauth})
    b = client.post("/v2/auth/register", json={**payload, "email": new_email()}, headers={"X-CSRF-Token": preauth})
    assert (a.status_code, a.json()) == (b.status_code, b.json()) == (202, {"status": "accepted"})


# --- S10: журнал доступу без подань анкет ---------------------------------------

def test_s10_access_log_drops_survey_submissions():
    log_filter = DropSurveySubmissionAccessLog()

    def record(path):
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                                 ("203.0.113.9:5000", "POST", path, "1.1", 201), None)
    assert log_filter.filter(record("/api/assessments/3/submissions")) is False
    assert log_filter.filter(record("/api/assessments/3/results")) is True
    assert any(isinstance(f, DropSurveySubmissionAccessLog) for f in logging.getLogger("uvicorn.access").filters)


# --- S11: наскрізна анонімність ------------------------------------------------

def test_s11_end_to_end_anonymity():
    admin, admin_csrf = admin_client()
    token = issue_token(admin, admin_csrf)
    user, user_csrf = login(make_user())                 # респондент має активну сесію V2
    before_audit = SessionLocal().query(AuditEvent).count()
    response = user.post(f"/api/assessments/{OPEN_ID}/submissions", json=submission(token),
                         headers={"X-Role": "admin", **user_csrf})
    assert response.status_code == 201
    assert response.json() == {"status": "accepted"}     # без номера анкети

    columns = {c["name"] for c in inspect(engine).get_columns("response_sets")}
    assert columns == {"id", "cycle_id", "respondent_category", "unit"}
    for table in ("response_sets", "answers"):
        referred = {fk["referred_table"] for fk in inspect(engine).get_foreign_keys(table)}
        assert "access_tokens" not in referred
    token_fks = {fk["referred_table"] for fk in inspect(engine).get_foreign_keys("access_tokens")}
    assert token_fks == {"cycles"}
    db = SessionLocal()
    assert db.query(AccessToken).filter_by(token=token).one().used is True
    assert db.query(AuditEvent).count() == before_audit  # подання не журналюється
    db.close()
    with sqlite3.connect(auth_db_path()) as con:          # V2_AUTH_DB не знає про анкети
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables & {"response_sets", "answers", "access_tokens"}


# --- S12: захист Audit Trail ----------------------------------------------------

def test_s12_audit_trail_admin_only_and_login_recorded_without_identity():
    user, _ = login(make_user())
    assert user.get("/api/audit-events").status_code == 403
    admin, _ = admin_client()
    events = admin.get("/api/audit-events", params={"limit": 50}).json()
    logins = [e for e in events if e["action"] == "auth.login"]
    assert logins and all(e["details"] == {} for e in logins)
    assert all("@" not in str(e) for e in events)          # жодного email у журналі
