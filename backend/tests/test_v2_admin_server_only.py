"""
Ролі admin і data_officer у вебі не призначає й не знімає ніхто — лише власник сервера командою на сервері.

  - POST /v2/admin/users/{id}/role: підвищення до admin і пониження admin → 403 admin_role_server_only без змін
    (роль, сесії, v2_role_changes, основний журнал); user → data_officer і data_officer → user → 403
    data_officer_role_server_only без змін; роль цілі перевіряється й усередині транзакції (гонка);
  - POST /v2/admin/users/{id}/revoke-sessions для іншого admin → 403; для user і data_officer і власні — дозволено;
  - python -m app.v2_role_cli set-role: план без --confirm нічого не змінює; з --confirm — роль, усі сесії цілі,
    v2_role_changes з actor_user_id = 0 і подія user.role_change з actor_role="server"; останній admin не
    знімається; невідомий email → код 2; у release працює без V2_SECRET_KEY.
"""
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from app import v2_auth, v2_role_cli
from app.database import SessionLocal
from app.models import AuditEvent
from app.v2_auth import (SERVER_ACTOR_ID, RoleChangeError, auth_db_path, change_user_role, create_user,
                         find_user_id, mask_email, migrate_auth_db)

from v2_helpers import PASSWORD, login, make_user, start_login

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_demo_xrole(monkeypatch):
    monkeypatch.setenv("INTEGRITY_DEMO_XROLE", "0")


def query(sql: str, *args):
    with closing(sqlite3.connect(auth_db_path())) as db:
        return db.execute(sql, args).fetchall()


def role_of(user_id: int) -> str:
    return query("SELECT role FROM v2_users WHERE id = ?", user_id)[0][0]


def sessions_of(user_id: int) -> int:
    return query("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ?", user_id)[0][0]


def role_changes_of(user_id: int) -> list[tuple]:
    return query("SELECT actor_user_id, old_role, new_role FROM v2_role_changes WHERE target_user_id = ? ORDER BY id",
                 user_id)


def audit_events(action: str = "user.role_change") -> list[AuditEvent]:
    with SessionLocal() as db:
        return db.query(AuditEvent).filter(AuditEvent.action == action).order_by(AuditEvent.id).all()


def admin_session():
    email = make_user("admin")
    client, csrf = login(email)
    return client, csrf, find_user_id(email)


def role_url(user_id: int) -> str:
    return f"/v2/admin/users/{user_id}/role"


# --- Веб: роль admin не призначається й не знімається ---------------------------------------------------------

def test_web_promotion_to_admin_is_403_and_changes_nothing():
    admin, csrf, _ = admin_session()
    target_email = make_user()
    target_id = find_user_id(target_email)
    target, _ = login(target_email)
    events_before = len(audit_events())
    response = admin.post(role_url(target_id), headers=csrf, json={"expected_role": "user", "new_role": "admin"})
    assert (response.status_code, response.json()) == (403, {"detail": "admin_role_server_only"})
    assert role_of(target_id) == "user" and sessions_of(target_id) == 1
    assert target.get("/v2/auth/me").status_code == 200
    assert role_changes_of(target_id) == [] and len(audit_events()) == events_before
    officer_id = find_user_id(make_user("data_officer"))
    response = admin.post(role_url(officer_id), headers=csrf,
                          json={"expected_role": "data_officer", "new_role": "admin"})
    assert response.status_code == 403 and role_of(officer_id) == "data_officer"


def test_web_demotion_of_admin_is_403_and_changes_nothing():
    admin, csrf, _ = admin_session()
    other_email = make_user("admin")
    other_id = find_user_id(other_email)
    other, _ = login(other_email)
    events_before = len(audit_events())
    for new_role in ("user", "data_officer"):
        response = admin.post(role_url(other_id), headers=csrf, json={"expected_role": "admin", "new_role": new_role})
        assert (response.status_code, response.json()) == (403, {"detail": "admin_role_server_only"})
    assert role_of(other_id) == "admin" and sessions_of(other_id) == 1
    assert other.get("/v2/auth/me").status_code == 200
    assert role_changes_of(other_id) == [] and len(audit_events()) == events_before
    with pytest.raises(RoleChangeError, match="admin_role_server_only"):
        change_user_role(find_user_id(make_user()), None, other_id, "admin", "user")


@pytest.mark.parametrize(("raced_role", "code"), [("admin", "admin_role_server_only"),
                                                   ("data_officer", "data_officer_role_server_only")])
def test_target_that_got_a_server_only_role_before_the_transaction_is_403(monkeypatch, raced_role, code):
    """Гонка: адміністратор бачив роль user, але ціль стала admin / data_officer (на сервері) між читанням і
    транзакцією → 403 з кодом ролі цілі, без змін. Тіло user → user проходить попередню перевірку маршруту."""
    admin, csrf, _ = admin_session()
    target_email = make_user()
    target_id = find_user_id(target_email)
    original_now = v2_auth._utc_now

    def promote_then_now():
        if sys._getframe(1).f_code.co_name == "change_user_role":       # між перевіркою тіла і BEGIN IMMEDIATE
            with closing(sqlite3.connect(auth_db_path())) as db:
                db.execute("UPDATE v2_users SET role = ? WHERE id = ?", (raced_role, target_id))
                db.commit()
        return original_now()
    monkeypatch.setattr(v2_auth, "_utc_now", promote_then_now)
    response = admin.post(role_url(target_id), headers=csrf, json={"expected_role": "user", "new_role": "user"})
    assert (response.status_code, response.json()) == (403, {"detail": code})
    assert role_of(target_id) == raced_role and role_changes_of(target_id) == []


# --- Веб: роль data_officer теж не призначається й не знімається ----------------------------------------------

def test_web_user_to_data_officer_is_403_and_changes_nothing():
    admin, csrf, _ = admin_session()
    target_email = make_user()
    target_id = find_user_id(target_email)
    target, _ = login(target_email)
    events_before = len(audit_events())
    response = admin.post(role_url(target_id), headers=csrf, json={"expected_role": "user", "new_role": "data_officer"})
    assert (response.status_code, response.json()) == (403, {"detail": "data_officer_role_server_only"})
    assert role_of(target_id) == "user" and sessions_of(target_id) == 1
    assert target.get("/v2/auth/me").status_code == 200
    assert role_changes_of(target_id) == [] and len(audit_events()) == events_before
    with pytest.raises(RoleChangeError, match="data_officer_role_server_only"):
        change_user_role(find_user_id(make_user()), None, target_id, "user", "data_officer")
    assert role_of(target_id) == "user"


def test_web_data_officer_to_user_is_403_and_changes_nothing():
    admin, csrf, _ = admin_session()
    officer_email = make_user("data_officer")
    officer_id = find_user_id(officer_email)
    officer, _ = login(officer_email)
    events_before = len(audit_events())
    response = admin.post(role_url(officer_id), headers=csrf,
                          json={"expected_role": "data_officer", "new_role": "user"})
    assert (response.status_code, response.json()) == (403, {"detail": "data_officer_role_server_only"})
    # Тіло з неправдивою роллю user → user: роль цілі data_officer перевіряється в транзакції
    disguised = admin.post(role_url(officer_id), headers=csrf, json={"expected_role": "user", "new_role": "user"})
    assert (disguised.status_code, disguised.json()) == (403, {"detail": "data_officer_role_server_only"})
    assert role_of(officer_id) == "data_officer" and sessions_of(officer_id) == 1
    assert officer.get("/v2/auth/me").status_code == 200
    assert role_changes_of(officer_id) == [] and len(audit_events()) == events_before


def test_revoke_sessions_of_data_officer_and_user_is_allowed():
    admin, csrf, _ = admin_session()
    for role in ("data_officer", "user"):
        email = make_user(role)
        target_id = find_user_id(email)
        target, _ = login(email)
        response = admin.post(f"/v2/admin/users/{target_id}/revoke-sessions", headers=csrf)
        assert (response.status_code, response.json()) == (200, {"revoked": 1})
        assert sessions_of(target_id) == 0 and target.get("/v2/auth/me").status_code == 401
        assert role_of(target_id) == role


def test_revoke_sessions_of_another_admin_is_403_own_sessions_still_allowed():
    admin, csrf, actor_id = admin_session()
    other_email = make_user("admin")
    other_id = find_user_id(other_email)
    other, _ = login(other_email)
    response = admin.post(f"/v2/admin/users/{other_id}/revoke-sessions", headers=csrf)
    assert (response.status_code, response.json()) == (403, {"detail": "admin_role_server_only"})
    assert sessions_of(other_id) == 1 and other.get("/v2/auth/me").status_code == 200
    own = admin.post(f"/v2/admin/users/{actor_id}/revoke-sessions", headers=csrf)
    assert (own.status_code, own.json()) == (200, {"revoked": 1})
    assert admin.get("/v2/auth/me").status_code == 401


# --- Серверна команда app.v2_role_cli -------------------------------------------------------------------------

def run_cli(capsys, *args: str) -> tuple[int, str]:
    code = v2_role_cli.main(["set-role", *args])
    return code, capsys.readouterr().out


def test_cli_plan_without_confirm_changes_nothing(capsys):
    email = make_user()
    user_id = find_user_id(email)
    login(email)
    events_before = len(audit_events())
    code, out = run_cli(capsys, "--email", email, "--role", "admin")
    assert code == 0
    assert "user → admin" in out and "сесій: 1" in out and "--confirm" in out
    assert email not in out and mask_email(email) in out
    assert role_of(user_id) == "user" and sessions_of(user_id) == 1
    assert role_changes_of(user_id) == [] and len(audit_events()) == events_before


def test_cli_confirm_promotes_revokes_sessions_and_journals_server_actor(capsys):
    email = make_user()
    user_id = find_user_id(email)
    verified, _ = login(email)
    pending, _ = start_login(email)
    events_before = len(audit_events())
    code, out = run_cli(capsys, "--email", email.upper(), "--role", "admin", "--confirm")
    assert code == 0, out
    assert "ВИКОНАНО" in out and email not in out
    assert role_of(user_id) == "admin" and sessions_of(user_id) == 0
    assert verified.get("/v2/auth/me").status_code == 401 and pending.get("/v2/auth/me").status_code == 401
    assert query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ? AND consumed = 0", user_id) == [(0,)]
    assert role_changes_of(user_id) == [(SERVER_ACTOR_ID, "user", "admin")] and SERVER_ACTOR_ID == 0
    events = audit_events()
    assert len(events) == events_before + 1
    assert (events[-1].actor_role, events[-1].actor_user_id, events[-1].details) == ("server", None, "{}")
    # Знову через CLI: та сама роль → відмова; зняття (адміністраторів більше одного) → виконано
    assert run_cli(capsys, "--email", email, "--role", "admin", "--confirm")[0] == 2
    assert run_cli(capsys, "--email", email, "--role", "data_officer", "--confirm")[0] == 0
    assert role_of(user_id) == "data_officer"
    assert role_changes_of(user_id)[-1] == (SERVER_ACTOR_ID, "admin", "data_officer")


def test_cli_confirm_assigns_and_removes_data_officer_with_server_actor(capsys):
    email = make_user()
    user_id = find_user_id(email)
    verified, _ = login(email)
    events_before = len(audit_events())
    code, out = run_cli(capsys, "--email", email, "--role", "data_officer", "--confirm")
    assert code == 0, out
    assert role_of(user_id) == "data_officer" and sessions_of(user_id) == 0
    assert verified.get("/v2/auth/me").status_code == 401
    assert role_changes_of(user_id) == [(0, "user", "data_officer")]
    events = audit_events()
    assert len(events) == events_before + 1
    assert (events[-1].actor_role, events[-1].actor_user_id) == ("server", None)
    assert run_cli(capsys, "--email", email, "--role", "user", "--confirm")[0] == 0
    assert role_of(user_id) == "user"
    assert role_changes_of(user_id)[-1] == (0, "data_officer", "user")
    assert audit_events()[-1].actor_role == "server" and len(audit_events()) == events_before + 2


def test_cli_refuses_unknown_email_and_bad_arguments(capsys):
    events_before = len(audit_events())
    code, out = run_cli(capsys, "--email", "nobody-here@example.test", "--role", "admin", "--confirm")
    assert code == 2 and "ВІДМОВА" in out and "nobody-here" not in out
    with pytest.raises(SystemExit) as bad_role:
        v2_role_cli.main(["set-role", "--email", "x@example.test", "--role", "root"])
    assert bad_role.value.code == 2
    assert len(audit_events()) == events_before


def test_cli_never_removes_the_last_admin(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("V2_AUTH_DB", str(tmp_path / "single_admin.db"))
    migrate_auth_db()
    only = create_user("Only admin", "only.admin@example.test", PASSWORD, role="admin")
    for confirm in ((), ("--confirm",)):
        code, out = run_cli(capsys, "--email", "only.admin@example.test", "--role", "user", *confirm)
        assert code == 2 and "останній адміністратор" in out
    assert role_of(only["id"]) == "admin" and role_changes_of(only["id"]) == []
    second = create_user("Second", "second@example.test", PASSWORD)
    assert run_cli(capsys, "--email", "second@example.test", "--role", "admin", "--confirm")[0] == 0
    assert run_cli(capsys, "--email", "only.admin@example.test", "--role", "user", "--confirm")[0] == 0
    assert (role_of(only["id"]), role_of(second["id"])) == ("user", "admin")
    code, out = run_cli(capsys, "--email", "second@example.test", "--role", "user", "--confirm")
    assert code == 2 and role_of(second["id"]) == "admin"


def test_cli_does_not_migrate_and_fails_on_missing_database(capsys, tmp_path, monkeypatch):
    missing = tmp_path / "absent.db"
    monkeypatch.setenv("V2_AUTH_DB", str(missing))
    code, out = run_cli(capsys, "--email", "a@example.test", "--role", "admin", "--confirm")
    assert code == 1 and "ПОМИЛКА" in out and not missing.exists()


def _release_env(**overrides: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in {"V2_SECRET_KEY", "V2_AUTH_DEV_MAIL", "INTEGRITY_DEMO_XROLE", "PYTHONPATH"}}
    env.update({"APP_ENV": "release", "PYTHONIOENCODING": "utf-8"}, **overrides)
    return env


def _cli_process(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "app.v2_role_cli", "set-role", *args],
                          cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_cli_in_release_works_without_secret_key():
    email = make_user()
    user_id = find_user_id(email)
    env = _release_env()
    assert "V2_SECRET_KEY" not in env and env["V2_AUTH_DB"] == str(auth_db_path())
    plan = _cli_process(env, "--email", email, "--role", "data_officer")
    assert plan.returncode == 0, plan.stdout + plan.stderr
    assert role_of(user_id) == "user"
    applied = _cli_process(env, "--email", email, "--role", "data_officer", "--confirm")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert email not in applied.stdout + applied.stderr
    assert role_of(user_id) == "data_officer"
    assert role_changes_of(user_id) == [(SERVER_ACTOR_ID, "user", "data_officer")]
    assert audit_events()[-1].actor_role == "server"
    without_db = {k: v for k, v in env.items() if k != "V2_AUTH_DB"}
    refused = _cli_process(without_db, "--email", email, "--role", "user", "--confirm")
    assert refused.returncode == 1 and "V2_AUTH_DB" in refused.stdout
    assert role_of(user_id) == "data_officer"
