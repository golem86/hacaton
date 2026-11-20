"""
Ролі й керування сесіями V2 (docs/V2_HARDENING_CONTRACT.md, розділи 1 і 3; аудит F3, F7–F10).

  - зміна ролі — одна транзакція (роль, ВСІ сесії цілі включно з pending, відкриті коди, v2_role_changes);
    ролі admin і data_officer призначає й знімає лише власник сервера (server_change_role / app.v2_role_cli,
    test_v2_admin_server_only.py), тож механіку транзакції перевірено через серверну зміну;
  - POST /v2/admin/users/{id}/role: повторна перевірка актора; 403 self_change, admin_role_server_only,
    data_officer_role_server_only, 404, 409, 422 — успішної веб-зміни ролі немає;
  - POST /v2/admin/users/{id}/revoke-sessions і POST /v2/auth/logout-all;
  - GET /v2/admin/users (email замасковано; повний — лише за точним email) і GET /v2/admin/role-changes;
  - події основного журналу без email; SQLite зайнята → 503; data_officer працює з require_role.
"""
import sqlite3
import threading
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import v2_auth
from app.database import SessionLocal
from app.main import app
from app.models import AuditEvent
from app.roles import require_role
from app.routes.v2_auth import require_v2_role
from app.v2_auth import (RoleChangeError, auth_db_path, authenticate, change_user_role, find_user_id,
                         server_change_role, user_for_session)

from v2_helpers import PASSWORD, latest_code, login, make_user, new_email, preauth_client, start_login

MAX_ID = 2 ** 63 - 1


@pytest.fixture(autouse=True)
def no_demo_xrole(monkeypatch):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")


def query(sql: str, *args):
    with closing(sqlite3.connect(auth_db_path())) as db:
        return db.execute(sql, args).fetchall()


def audit_events(action: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        return db.query(AuditEvent).filter(AuditEvent.action == action).all()


def admin_session():
    email = make_user("admin")
    client, csrf = login(email)
    return client, csrf, find_user_id(email)


def role_url(user_id) -> str:
    return f"/v2/admin/users/{user_id}/role"


# --- Зміна ролі -------------------------------------------------------------------------------------------

def test_role_change_revokes_all_target_sessions_codes_and_is_journaled():
    admin, _, _ = admin_session()
    target_email = make_user()
    target_id = find_user_id(target_email)
    verified, _ = login(target_email)
    pending, _ = start_login(target_email)                       # pending-сесія і відкритий код 2FA
    body = server_change_role(target_email, "data_officer")       # лише власник сервера
    assert body["user_id"] == target_id and body["old_role"] == "user" and body["new_role"] == "data_officer"
    assert body["sessions_revoked"] == 2 and target_email not in str(body)
    assert verified.get("/v2/auth/me").status_code == 401 and pending.get("/v2/auth/me").status_code == 401
    assert query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ? AND consumed = 0", target_id) == [(0,)]
    assert authenticate(target_email, PASSWORD)["role"] == "data_officer"
    changes = admin.get("/v2/admin/role-changes").json()          # історію ролей адміністратор бачить
    assert {k: changes[0][k] for k in ("actor_user_id", "target_user_id", "old_role", "new_role")} == \
        {"actor_user_id": 0, "target_user_id": target_id, "old_role": "user", "new_role": "data_officer"}


def test_pending_verify_after_role_change_gets_no_session():
    """F3: код, виданий до зміни ролі, не дає нової сесії — pending-сесію видалено, код погашено."""
    target_email = make_user()
    pending, pending_csrf = start_login(target_email)
    code = latest_code(target_email)
    server_change_role(target_email, "data_officer")
    response = pending.post("/v2/auth/2fa/verify", json={"code": code}, headers={"X-CSRF-Token": pending_csrf})
    assert response.status_code == 401
    assert query("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ?", find_user_id(target_email)) == [(0,)]


def test_role_change_rejections():
    admin, csrf, actor_id = admin_session()
    target_id = find_user_id(make_user())
    body = {"expected_role": "user", "new_role": "data_officer"}
    anonymous, _ = preauth_client()
    assert anonymous.post(role_url(target_id), json=body).status_code == 401
    user, user_csrf = login(make_user())
    assert user.post(role_url(target_id), headers=user_csrf, json=body).status_code == 403
    assert user.post(role_url(target_id), headers={**user_csrf, "X-Role": "admin"}, json=body).status_code == 403
    admin_email = make_user("admin")
    pending, pending_csrf = start_login(admin_email)
    assert pending.post(role_url(target_id), headers={"X-CSRF-Token": pending_csrf}, json=body).status_code == 401
    assert admin.post(role_url(target_id), json=body).status_code == 403                                   # CSRF
    assert admin.post(role_url(target_id), json=body,
                      headers={**csrf, "Origin": "https://evil.example"}).status_code == 403              # Origin
    assert admin.post(role_url(target_id), headers=csrf,
                      json={"expected_role": "user", "new_role": "superadmin"}).status_code == 422
    assert admin.post(role_url(target_id), headers=csrf, json={**body, "extra": 1}).status_code == 422      # forbid
    self_change = admin.post(role_url(actor_id), headers=csrf, json={"expected_role": "admin", "new_role": "user"})
    assert (self_change.status_code, self_change.json()) == (403, {"detail": "self_change"})
    assert admin.post(role_url(target_id), headers=csrf,
                      json={"expected_role": "user", "new_role": "user"}).status_code == 409             # та сама
    same = {"expected_role": "user", "new_role": "user"}
    assert admin.post(role_url(MAX_ID), headers=csrf, json=same).status_code == 404
    for bad in (0, -1, MAX_ID + 1, "99999999999999999999"):                                               # F9
        assert admin.post(role_url(bad), headers=csrf, json=body).status_code == 422, bad
    for attempt in (body, {"expected_role": "data_officer", "new_role": "user"}):
        response = admin.post(role_url(target_id), headers=csrf, json=attempt)
        assert (response.status_code, response.json()) == (403, {"detail": "data_officer_role_server_only"})
    assert query("SELECT role FROM v2_users WHERE id = ?", target_id) == [("user",)]
    assert query("SELECT COUNT(*) FROM v2_role_changes WHERE target_user_id = ?", target_id) == [(0,)]


def test_failed_role_journal_insert_rolls_back_role_and_sessions():
    target_email = make_user()
    target, _ = login(target_email)
    target_id = find_user_id(target_email)
    with closing(sqlite3.connect(auth_db_path())) as db:
        db.execute("CREATE TRIGGER reject_role_journal BEFORE INSERT ON v2_role_changes "
                   "BEGIN SELECT RAISE(ABORT, 'test journal failure'); END")
        db.commit()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="test journal failure"):
            server_change_role(target_email, "data_officer")
        assert authenticate(target_email, PASSWORD)["role"] == "user"
        assert target.get("/v2/user/profile").status_code == 200
        assert query("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ?", target_id) == [(1,)]
    finally:
        with closing(sqlite3.connect(auth_db_path())) as db:
            db.execute("DROP TRIGGER reject_role_journal")
            db.commit()


def test_identical_concurrent_role_changes_have_one_winner():
    email = make_user()
    target_id = find_user_id(email)
    barrier = threading.Barrier(4)

    def run(_):
        barrier.wait(timeout=10)
        try:
            return server_change_role(email, "data_officer")
        except RoleChangeError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert sum(isinstance(r, dict) for r in results) == 1 and results.count("unchanged") == 3
    assert query("SELECT COUNT(*) FROM v2_role_changes WHERE target_user_id = ?", target_id) == [(1,)]


def test_two_admins_cannot_demote_each_other_through_the_web():
    """Раніше — гонка двох admin, що понижують один одного; тепер веб-пониження admin відхиляється для обох."""
    a_email, b_email = make_user("admin"), make_user("admin")
    a, _ = login(a_email)
    b, _ = login(b_email)
    a_id, b_id = find_user_id(a_email), find_user_id(b_email)
    barrier = threading.Barrier(2)

    def run(args):
        actor, session, target = args
        barrier.wait(timeout=10)
        try:
            return change_user_role(actor, session, target, "admin", "user")
        except RoleChangeError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [(a_id, a.cookies.get("v2_session"), b_id),
                                      (b_id, b.cookies.get("v2_session"), a_id)]))
    assert results == ["admin_role_server_only", "admin_role_server_only"]
    assert query("SELECT role FROM v2_users WHERE id IN (?, ?)", a_id, b_id) == [("admin",), ("admin",)]
    assert query("SELECT COUNT(*) FROM v2_role_changes WHERE target_user_id IN (?, ?)", a_id, b_id) == [(0,)]


def test_demoted_admin_session_cannot_finish_a_role_change():
    admin, csrf, actor_id = admin_session()
    other, other_csrf, other_id = admin_session()
    target_id = find_user_id(make_user())
    assert other.post(role_url(actor_id), headers=other_csrf,                 # веб не знімає роль admin
                      json={"expected_role": "admin", "new_role": "user"}).status_code == 403
    actor_email = query("SELECT email FROM v2_users WHERE id = ?", actor_id)[0][0]
    server_change_role(actor_email, "user")                           # знімає лише власник сервера
    assert admin.post(role_url(target_id), headers=csrf,
                      json={"expected_role": "user", "new_role": "user"}).status_code == 401
    with pytest.raises(RoleChangeError, match="actor_unauthorized"):    # навіть з токеном, вкраденим до зміни
        change_user_role(actor_id, admin.cookies.get("v2_session"), target_id, "user", "user")
    assert other_id != actor_id


def test_busy_auth_db_gives_503_not_500(monkeypatch):
    admin, csrf, _ = admin_session()
    target_id = find_user_id(make_user())
    monkeypatch.setattr(v2_auth, "BUSY_TIMEOUT_MS", 50)
    blocker = sqlite3.connect(auth_db_path(), isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")                               # інша транзакція тримає запис
        response = admin.post(role_url(target_id), headers=csrf,
                              json={"expected_role": "user", "new_role": "user"})
        assert response.status_code == 503 and response.headers["retry-after"] == "1"
        revoke = admin.post(f"/v2/admin/users/{target_id}/revoke-sessions", headers=csrf)
        assert revoke.status_code == 503
        login_client, preauth = preauth_client(client=("198.18.90.1", 1000))
        assert login_client.post("/v2/auth/login", json={"email": new_email(), "password": PASSWORD},
                                 headers={"X-CSRF-Token": preauth}).status_code == 503
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert query("SELECT role FROM v2_users WHERE id = ?", target_id) == [("user",)]


# --- Відкликання сесій і вихід з усіх пристроїв -------------------------------------------------------------

def test_admin_revokes_all_sessions_of_a_user():
    admin, csrf, actor_id = admin_session()
    target_email = make_user()
    target_id = find_user_id(target_email)
    first, _ = login(target_email)
    second, _ = start_login(target_email)
    before = len(audit_events("user.sessions_revoke"))
    response = admin.post(f"/v2/admin/users/{target_id}/revoke-sessions", headers=csrf)
    assert (response.status_code, response.json()) == (200, {"revoked": 2})
    assert first.get("/v2/auth/me").status_code == 401 and second.get("/v2/auth/me").status_code == 401
    assert authenticate(target_email, PASSWORD)["role"] == "user"        # роль не змінено
    events = audit_events("user.sessions_revoke")
    assert len(events) == before + 1 and events[-1].details == '{"count": 2}'
    assert events[-1].actor_user_id == actor_id
    assert admin.post(f"/v2/admin/users/{target_id}/revoke-sessions", headers=csrf).json() == {"revoked": 0}
    assert admin.post(f"/v2/admin/users/{MAX_ID}/revoke-sessions", headers=csrf).status_code == 404
    assert admin.post(f"/v2/admin/users/{MAX_ID + 1}/revoke-sessions", headers=csrf).status_code == 422
    assert admin.post(f"/v2/admin/users/{target_id}/revoke-sessions").status_code == 403         # CSRF
    user, user_csrf = login(make_user())
    assert user.post(f"/v2/admin/users/{actor_id}/revoke-sessions", headers=user_csrf).status_code == 403
    assert admin.get("/v2/auth/me").status_code == 200


def test_logout_all_ends_every_session_of_the_user():
    email = make_user()
    first, first_csrf = login(email)
    second, _ = login(email)
    pending, pending_csrf = start_login(email)
    assert pending.post("/v2/auth/logout-all", headers={"X-CSRF-Token": pending_csrf}).status_code == 401
    assert first.post("/v2/auth/logout-all").status_code == 403                                     # CSRF
    before = len(audit_events("auth.logout_all"))
    response = first.post("/v2/auth/logout-all", headers=first_csrf)
    assert (response.status_code, response.json()) == (200, {"status": "logged_out_all"})
    for client in (first, second, pending):
        assert client.get("/v2/auth/me").status_code == 401
    assert query("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ?", find_user_id(email)) == [(0,)]
    events = audit_events("auth.logout_all")
    assert len(events) == before + 1 and events[-1].actor_role == "user" and events[-1].details == '{"count": 3}'
    assert events[-1].actor_user_id == find_user_id(email)


# --- Перегляд користувачів і журналу змін ролей ------------------------------------------------------------

def test_users_list_masks_emails_and_ignores_email_query():
    admin, _, _ = admin_session()
    email = make_user()
    listing = admin.get("/v2/admin/users")
    assert listing.status_code == 200 and listing.headers["cache-control"] == "no-store"
    rows = listing.json()
    assert 0 < len(rows) <= 500
    assert all(set(row) == {"id", "name", "role", "email_masked", "created_at"} for row in rows)
    assert all(row["email_masked"].count("***") == 2 for row in rows)
    assert not any(email in str(row) for row in rows)
    filtered = admin.get("/v2/admin/users", params={"email": email})      # email у URL не підтримується
    assert filtered.status_code == 200 and filtered.json() == rows and email not in filtered.text


def test_exact_lookup_takes_email_from_body_only():
    admin, csrf, _ = admin_session()
    email = make_user()
    lookup = admin.post("/v2/admin/users/lookup", headers=csrf, json={"email": email.upper()})
    assert lookup.status_code == 200 and lookup.headers["cache-control"] == "no-store"
    assert lookup.json() == {"id": find_user_id(email), "name": "Test user", "email": email, "role": "user",
                             "created_at": lookup.json()["created_at"]}
    assert admin.post("/v2/admin/users/lookup", headers=csrf,
                      json={"email": email.split("@")[1]}).status_code == 404                        # не пошук
    assert admin.post("/v2/admin/users/lookup", headers=csrf, json={"email": new_email()}).status_code == 404
    assert admin.post("/v2/admin/users/lookup", headers=csrf, json={"email": ""}).status_code == 422
    assert admin.post("/v2/admin/users/lookup", headers=csrf,
                      json={"email": email, "role": "admin"}).status_code == 422                     # forbid
    assert admin.post("/v2/admin/users/lookup", json={"email": email}).status_code == 403            # CSRF
    assert admin.post("/v2/admin/users/lookup", json={"email": email},
                      headers={**csrf, "Origin": "https://evil.example"}).status_code == 403          # Origin
    user, user_csrf = login(make_user())
    assert user.post("/v2/admin/users/lookup", headers=user_csrf, json={"email": email}).status_code == 403
    assert TestClient(app).post("/v2/admin/users/lookup", json={"email": email}).status_code == 401


def test_role_changes_listing_is_admin_only_and_bounded():
    admin, _, _ = admin_session()
    assert admin.get("/v2/admin/role-changes", params={"limit": 501}).status_code == 422
    assert admin.get("/v2/admin/role-changes", params={"limit": 0}).status_code == 422
    assert admin.get("/v2/admin/role-changes", params={"limit": 1}).status_code == 200
    user, _ = login(make_user())
    for path in ("/v2/admin/users", "/v2/admin/role-changes"):
        assert user.get(path).status_code == 403
        assert TestClient(app).get(path).status_code == 401


# --- Роль data_officer (A18) ----------------------------------------------------------------------------------

def test_data_officer_session_works_with_role_guards_but_not_admin_or_user_routes():
    admin, _, _ = admin_session()
    email = make_user()
    server_change_role(email, "data_officer")                           # лише власник сервера
    officer, officer_csrf = login(email)
    assert officer.get("/v2/auth/me").json()["user"]["role"] == "data_officer"
    probe = FastAPI()

    @probe.get("/officer", dependencies=[Depends(require_role("data_officer"))])
    def officer_only():
        return {"ok": True}

    @probe.get("/participation", dependencies=[Depends(require_role("admin", "data_officer"))])
    def participation():
        return {"ok": True}

    @probe.post("/officer-write", dependencies=[Depends(require_role("data_officer"))])
    def officer_write():
        return {"ok": True}

    @probe.get("/v2-officer")
    def v2_officer(user=Depends(require_v2_role("data_officer"))):
        return {"role": user["role"]}

    client = TestClient(probe)
    client.cookies.set("v2_session", officer.cookies.get("v2_session"))
    assert client.get("/officer").status_code == 200
    assert client.get("/participation").status_code == 200
    assert client.get("/v2-officer").json() == {"role": "data_officer"}
    assert client.post("/officer-write").status_code == 403                                     # CSRF
    assert client.post("/officer-write", headers=officer_csrf).status_code == 200
    admin_probe = TestClient(probe)
    admin_probe.cookies.set("v2_session", admin.cookies.get("v2_session"))
    assert admin_probe.get("/officer").status_code == 403 and admin_probe.get("/participation").status_code == 200
    for path in ("/v2/user/profile", "/v2/admin/reports/1", "/v2/admin/users", "/docs", "/openapi.json",
                 "/api/audit-events", "/api/assessments/1/results", "/api/assessments/1/tracker"):
        assert officer.get(path).status_code == 403, path
    assert user_for_session(officer.cookies.get("v2_session"))["role"] == "data_officer"


def test_admin_path_ids_out_of_int64_range_are_422_not_500():
    admin, csrf, _ = admin_session()
    for bad in (0, MAX_ID + 1, "99999999999999999999"):
        assert admin.get(f"/v2/admin/reports/{bad}").status_code == 422, bad
        assert admin.get(f"/v2/admin/reports/{bad}/export?format=pdf").status_code == 422, bad
        assert admin.post(f"/v2/admin/users/{bad}/revoke-sessions", headers=csrf).status_code == 422, bad
