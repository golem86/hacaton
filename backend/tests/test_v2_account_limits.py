"""
Ліміти на акаунт і строки життя (аудит backend 20.11.2026, PoC H4–H5; docs/V2_HARDENING_CONTRACT.md, розділ 3):
  - скидання пароля: ≤ 5 кодів на акаунт за 24 год з будь-якої кількості IP, ≤ 10 невдалих підтверджень,
    атомарне підтвердження, однакова відповідь для наявного й невідомого email (A4);
  - блокування 2FA: 10 невдалих кодів за 24 год → 429 на verify, resend і видачу коду під час входу (A5);
  - pending-сесія 15 хв, verified — 12 год (A7);
  - OTP зберігається як HMAC-SHA256 із серверним ключем (A8);
  - журнал: лише роль і числові деталі, без email (A10).
"""
import hashlib
import hmac
import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest

from app import settings, v2_auth
from app.database import SessionLocal
from app.models import AuditEvent
from app.v2_auth import (auth_db_path, authenticate, create_session, find_user_id, issue_challenge, user_for_session)

from v2_helpers import (PASSWORD, latest_code, login, make_user, new_email, preauth_client, start_login,
                        wait_mail_queue)

NEW_PASSWORD = "AnotherStrongPass1!"


def query(sql: str, *args):
    with closing(sqlite3.connect(auth_db_path())) as db:
        return db.execute(sql, args).fetchall()


def audit_count(action: str) -> int:
    with SessionLocal() as db:
        return db.query(AuditEvent).filter(AuditEvent.action == action).count()


def wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def reset_request(email: str, ip: str):
    client, preauth = preauth_client(client=(ip, 40000))
    response = client.post("/v2/auth/password-reset/request", json={"email": email},
                           headers={"X-CSRF-Token": preauth})
    wait_mail_queue()                       # код видає фоновий воркер
    return response


def reset_confirm(email: str, code: str, ip: str = "198.18.5.1"):
    client, preauth = preauth_client(client=(ip, 40000))
    return client.post("/v2/auth/password-reset/confirm", headers={"X-CSRF-Token": preauth}, json={
        "email": email, "code": code, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD})


@pytest.fixture
def shifted_clock(monkeypatch):
    """Зсув «зараз» для v2_auth: shift(minutes=…)."""
    real = v2_auth._utc_now
    offset = [timedelta(0)]
    monkeypatch.setattr(v2_auth, "_utc_now", lambda: real() + offset[0])

    def shift(**delta):
        offset[0] = timedelta(**delta)
    return shift


# --- A4: скидання пароля ------------------------------------------------------------------------------------

def test_reset_codes_are_capped_per_account_across_many_ips():
    email = make_user()
    user_id = find_user_id(email)
    statuses, bodies = set(), set()
    for i in range(20):
        for _ in range(4):
            response = reset_request(email, f"198.51.{i // 200}.{i % 200 + 1}")
            statuses.add(response.status_code)
            bodies.add(response.text)
    issued = query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ? AND purpose = 'password_reset'", user_id)
    assert issued == [(v2_auth.RESET_ISSUE_LIMIT,)] == [(5,)]
    assert statuses == {200} and bodies == {'{"status":"sent_if_account_exists"}'}


def test_reset_request_answer_is_identical_for_unknown_email():
    known, unknown = reset_request(make_user(), "198.18.1.1"), reset_request(new_email(), "198.18.1.1")
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == \
        (200, {"status": "sent_if_account_exists"})


def test_reset_confirm_is_atomic_and_revokes_everything():
    email = make_user()
    user_id = find_user_id(email)
    verified, _ = login(email)
    pending, _ = start_login(email)                          # відкрита pending-сесія і код 2FA
    assert query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ? AND purpose = 'login_2fa' AND consumed = 0",
                 user_id) == [(1,)]
    events_before = audit_count("auth.password_reset")
    assert reset_request(email, "198.18.2.1").status_code == 200
    response = reset_confirm(email, latest_code(email))
    assert response.status_code == 200 and response.json() == {"status": "password_updated"}
    assert verified.get("/v2/auth/me").status_code == 401
    assert pending.get("/v2/auth/me").status_code == 401
    assert query("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ?", user_id) == [(0,)]
    assert query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ? AND consumed = 0", user_id) == [(0,)]
    assert authenticate(email, PASSWORD) is None and authenticate(email, NEW_PASSWORD)["id"] == user_id
    assert reset_confirm(email, latest_code(email)).status_code == 401          # код одноразовий
    assert audit_count("auth.password_reset") == events_before + 1
    with SessionLocal() as db:
        event = db.query(AuditEvent).filter(AuditEvent.action == "auth.password_reset") \
            .order_by(AuditEvent.id.desc()).first()
    assert event.actor_role == "user" and event.details == "{}" and "@" not in event.details
    assert event.actor_user_id == user_id


@pytest.mark.parametrize("existing", [True, False])
def test_ten_failed_reset_confirmations_lock_the_account_uniformly(existing):
    email = make_user() if existing else new_email()
    statuses = []
    for round_ in range(2):                                   # 2 коди по 5 спроб (ліміт спроб на код)
        reset_request(email, f"198.18.3.{round_ + 1}")
        code = latest_code(email) if existing else "123456"
        statuses += [reset_confirm(email, wrong(code)).status_code for _ in range(5)]
    assert statuses == [401] * 9 + [429]
    if existing:
        reset_request(email, "198.18.3.9")
        assert reset_confirm(email, latest_code(email)).status_code == 429     # навіть правильний код
        assert authenticate(email, PASSWORD) is not None                          # пароль не змінено
    else:
        assert reset_confirm(email, "123456").status_code == 429


def test_reset_lock_counts_attempts_on_exhausted_code_like_unknown_email():
    """Без цього 10 спроб розрізняли б наявний акаунт (5 порівнянь) і невідомий (10 невдач)."""
    email = make_user()
    reset_request(email, "198.18.4.1")
    code = latest_code(email)
    statuses = [reset_confirm(email, wrong(code)).status_code for _ in range(10)]
    assert statuses == [401] * 9 + [429]


# --- A5: блокування 2FA на акаунт ---------------------------------------------------------------------------

def test_ten_failed_2fa_codes_lock_verify_resend_and_login():
    email = make_user()
    user_id = find_user_id(email)
    client, pending_csrf = start_login(email)
    headers = {"X-CSRF-Token": pending_csrf}
    events_before = audit_count("auth.2fa_lockout")
    code = latest_code(email)
    statuses = [client.post("/v2/auth/2fa/verify", json={"code": wrong(code)}, headers=headers).status_code
                for _ in range(5)]
    assert client.post("/v2/auth/2fa/resend", headers=headers).status_code == 200
    code = latest_code(email)
    statuses += [client.post("/v2/auth/2fa/verify", json={"code": wrong(code)}, headers=headers).status_code
                 for _ in range(5)]
    assert statuses == [401] * 9 + [429]
    assert audit_count("auth.2fa_lockout") == events_before + 1
    assert client.post("/v2/auth/2fa/verify", json={"code": code}, headers=headers).status_code == 429
    assert client.post("/v2/auth/2fa/resend", headers=headers).status_code == 429
    codes_before = query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ?", user_id)
    other, preauth = preauth_client(client=("198.18.6.1", 40000))
    relogin = other.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                         headers={"X-CSRF-Token": preauth})
    assert relogin.status_code == 429
    assert query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ?", user_id) == codes_before   # код не видано
    wrong_password = other.post("/v2/auth/login", json={"email": email, "password": "wrong-password"},
                                headers={"X-CSRF-Token": preauth})
    assert wrong_password.status_code == 401                  # без правильного пароля блокування не видно
    assert audit_count("auth.2fa_lockout") == events_before + 1
    owner, _ = login(make_user())                             # інший акаунт не зачеплено
    assert owner.get("/v2/user/profile").status_code == 200


def test_2fa_lock_expires_after_24_hours(shifted_clock):
    email = make_user()
    user_id = find_user_id(email)
    with closing(sqlite3.connect(auth_db_path())) as db:
        db.execute("INSERT INTO v2_rate_limits(scope, subject, window_started, attempts) VALUES ('2fa_fail', ?, ?, 10)",
                   (str(user_id), v2_auth._utc_now().isoformat()))
        db.commit()
    assert v2_auth.two_factor_locked(user_id)
    shifted_clock(hours=24, seconds=1)
    assert not v2_auth.two_factor_locked(user_id)
    client, _ = login(email)
    assert client.get("/v2/user/profile").status_code == 200


# --- A7: строки життя сесій ------------------------------------------------------------------------------

def test_pending_session_lives_15_minutes(shifted_clock):
    email = make_user()
    client, preauth = preauth_client()
    response = client.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"X-CSRF-Token": preauth})
    cookie = next(c for c in response.headers.get_list("set-cookie") if c.startswith("v2_session="))
    assert "max-age=900" in cookie.lower()
    pending, code = client.cookies.get("v2_session"), latest_code(email)
    shifted_clock(minutes=14)
    assert user_for_session(pending) is not None
    shifted_clock(minutes=15, seconds=1)
    assert user_for_session(pending) is None
    verify = client.post("/v2/auth/2fa/verify", json={"code": code},
                         headers={"X-CSRF-Token": response.json()["csrf_token"]})
    assert verify.status_code == 401


def test_verified_session_lives_12_hours(shifted_clock):
    email = make_user()
    client, pending_csrf = start_login(email)
    verify = client.post("/v2/auth/2fa/verify", json={"code": latest_code(email)},
                         headers={"X-CSRF-Token": pending_csrf})
    cookie = next(c for c in verify.headers.get_list("set-cookie") if c.startswith("v2_session="))
    assert "max-age=43200" in cookie.lower()
    token = client.cookies.get("v2_session")
    shifted_clock(hours=11, minutes=59)
    assert user_for_session(token)["two_factor_verified"] is True
    shifted_clock(hours=12, seconds=1)
    assert user_for_session(token) is None


def test_pending_session_from_before_upgrade_is_cut_to_15_minutes():
    user_id = find_user_id(make_user())
    token, _ = create_session(user_id)
    old = (v2_auth._utc_now() - timedelta(minutes=20)).isoformat()
    with closing(sqlite3.connect(auth_db_path())) as db:       # pending зі старим 12-годинним строком
        db.execute("UPDATE v2_sessions SET created_at = ?, expires_at = ? WHERE token_hash = ?",
                   (old, (v2_auth._utc_now() + timedelta(hours=11)).isoformat(), v2_auth.token_hash(token)))
        db.commit()
    assert user_for_session(token) is None


# --- A8: OTP як HMAC ---------------------------------------------------------------------------------------

def test_otp_is_stored_as_keyed_hmac():
    email = make_user()
    user_id = find_user_id(email)
    issue_challenge(user_id, "login_2fa", email)
    code = latest_code(email)
    stored = query("SELECT code_hash FROM v2_challenges WHERE user_id = ? ORDER BY id DESC LIMIT 1", user_id)[0][0]
    expected = hmac.new(settings.secret_key().encode(), f"otp:login_2fa:{user_id}:{code}".encode(),
                        hashlib.sha256).hexdigest()
    assert stored == expected
    assert stored != hashlib.sha256(code.encode()).hexdigest()
    assert v2_auth.otp_hash(user_id, "password_reset", code) != stored      # прив'язка до призначення
    assert v2_auth.otp_hash(user_id + 1, "login_2fa", code) != stored       # і до акаунта


# --- A10: журнал виходу ------------------------------------------------------------------------------------

def test_logout_is_recorded_with_role_only():
    client, csrf = login(make_user())
    before = audit_count("auth.logout")
    assert client.post("/v2/auth/logout", headers=csrf).status_code == 200
    assert audit_count("auth.logout") == before + 1
    pending, pending_csrf = start_login(make_user())          # вихід без 2FA — не подія входу/виходу
    assert pending.post("/v2/auth/logout", headers={"X-CSRF-Token": pending_csrf}).status_code == 200
    assert audit_count("auth.logout") == before + 1
