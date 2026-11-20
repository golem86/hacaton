"""
Гонки автентифікації V2 (аудит backend 20.11.2026, PoC H1–H3; docs/V2_HARDENING_CONTRACT.md, розділ 3).

Постійні регресійні тести замість разових PoC:
  - один OTP → рівно одна verified-сесія навіть за паралельних verify (H1);
  - не більше 5 перевірок на один код за паралельних запитів (H2);
  - атомарний ліміт спроб (H3);
  - rotate_session_after_2fa без pending-сесії нічого не видає;
  - verify проти зміни ролі, logout і скидання пароля: відкликана сесія не «воскресає».
Потоки стартують одночасно через threading.Barrier.
"""
import sqlite3
import threading
from contextlib import closing

import pytest

from app import v2_auth
from app.routes import v2_auth as auth_routes
from app.v2_auth import (SessionRevoked, auth_db_path, complete_two_factor, consume_rate_limit, create_session,
                         delete_session, find_user_id, issue_challenge, reset_password_with_code,
                         rotate_session_after_2fa, server_change_role, user_for_session, verify_challenge)

from v2_helpers import latest_code, make_user, start_login


def parallel(count: int, target) -> list:
    """count потоків стартують разом; результат або виняток кожного — у списку."""
    barrier = threading.Barrier(count)
    results: list = [None] * count

    def worker(index: int) -> None:
        barrier.wait(timeout=30)
        try:
            results[index] = target(index)
        except Exception as error:  # noqa: BLE001 — виняток теж результат гонки
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def query(sql: str, *args):
    with closing(sqlite3.connect(auth_db_path())) as db:
        return db.execute(sql, args).fetchall()


def sessions(user_id: int, verified: int | None = None) -> int:
    if verified is None:
        return query("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ?", user_id)[0][0]
    return query("SELECT COUNT(*) FROM v2_sessions WHERE user_id = ? AND two_factor_verified = ?",
                 user_id, verified)[0][0]


def challenge_state(user_id: int, purpose: str = "login_2fa") -> tuple[int, int]:
    return tuple(query("SELECT attempts, consumed FROM v2_challenges WHERE user_id = ? AND purpose = ? "
                       "ORDER BY id DESC LIMIT 1", user_id, purpose)[0])


def wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def pending_user():
    """Користувач після пароля: pending-сесія, код 2FA у dev-скриньці."""
    email = make_user()
    client, pending_csrf = start_login(email)
    return email, find_user_id(email), client, client.cookies.get("v2_session"), latest_code(email)


# --- A1 / H1: одне споживання OTP ---------------------------------------------------------------------------

def test_one_otp_gives_exactly_one_verified_session_under_parallel_verify():
    _, user_id, _, pending, code = pending_user()
    results = parallel(8, lambda _: complete_two_factor(pending, code))
    statuses = [r.status for r in results]
    assert statuses.count("ok") == 1, statuses
    assert set(statuses) <= {"ok", "no_pending"}
    assert sessions(user_id, verified=1) == 1 and sessions(user_id, verified=0) == 0
    assert challenge_state(user_id) == (1, 1)                 # одне порівняння, одне споживання


def test_legacy_verify_and_rotate_are_atomic_like_poc_h1():
    """Копія PoC H1 на внутрішньому API: verify_challenge + rotate_session_after_2fa паралельно."""
    email = make_user()
    user_id = find_user_id(email)
    issue_challenge(user_id, "login_2fa", email)
    code = latest_code(email)
    old_token, _ = create_session(user_id)

    def attempt(_):
        if verify_challenge(user_id, "login_2fa", code):
            return rotate_session_after_2fa(old_token, user_id)
        return False

    results = parallel(8, attempt)
    assert sum(isinstance(r, tuple) for r in results) == 1, results
    assert not any(isinstance(r, Exception) for r in results), results
    assert sessions(user_id, verified=1) == 1


# --- A1 / H2: не більше 5 перевірок на код ------------------------------------------------------------------

def test_five_wrong_codes_exhaust_challenge_even_for_correct_code():
    email = make_user()
    user_id = find_user_id(email)
    issue_challenge(user_id, "login_2fa", email)
    code = latest_code(email)
    assert not any(verify_challenge(user_id, "login_2fa", wrong(code)) for _ in range(5))
    assert verify_challenge(user_id, "login_2fa", code) is False
    assert challenge_state(user_id) == (5, 0)


@pytest.mark.parametrize("count", [10, 40])
def test_parallel_attempts_on_one_code_never_exceed_five_checks(count):
    email = make_user()
    user_id = find_user_id(email)
    issue_challenge(user_id, "login_2fa", email)
    code = latest_code(email)
    results = parallel(count, lambda i: verify_challenge(user_id, "login_2fa", code if i == count - 1 else wrong(code)))
    assert not any(isinstance(r, Exception) for r in results), results
    attempts, consumed = challenge_state(user_id)
    assert attempts <= 5
    assert sum(r is True for r in results) == consumed <= 1


def test_parallel_wrong_codes_through_pending_session_count_five_failures():
    _, user_id, _, pending, code = pending_user()
    results = parallel(20, lambda _: complete_two_factor(pending, wrong(code)))
    assert {r.status for r in results} == {"invalid"}
    assert challenge_state(user_id) == (5, 0)
    failures = query("SELECT attempts FROM v2_rate_limits WHERE scope = '2fa_fail' AND subject = ?", str(user_id))
    assert failures == [(5,)]                                 # лише справжні порівняння
    assert user_for_session(pending)["two_factor_verified"] is False


# --- A3 / H3: атомарний ліміт спроб --------------------------------------------------------------------------

@pytest.mark.parametrize("prefill, allowed", [(0, 5), (4, 1)])
def test_rate_limit_is_atomic_under_parallel_consumers(prefill, allowed):
    subject = f"race-{prefill}-{v2_auth.secrets.token_hex(4)}"
    for _ in range(prefill):
        assert consume_rate_limit("race_scope", subject, 5, 15)
    results = parallel(20, lambda _: consume_rate_limit("race_scope", subject, 5, 15))
    assert not any(isinstance(r, Exception) for r in results), results
    assert sum(r is True for r in results) == allowed
    assert query("SELECT attempts FROM v2_rate_limits WHERE scope = 'race_scope' AND subject = ?", subject) == [(5,)]


# --- A2: ротація лише з наявної pending-сесії ----------------------------------------------------------------

def test_rotate_without_pending_session_issues_nothing():
    email = make_user()
    user_id = find_user_id(email)
    with pytest.raises(SessionRevoked):
        rotate_session_after_2fa("never-existed-token", user_id)
    assert sessions(user_id) == 0
    verified, _ = create_session(user_id, two_factor_verified=True)
    with pytest.raises(SessionRevoked):                       # verified-сесія не «ротується» вдруге
        rotate_session_after_2fa(verified, user_id)
    pending, _ = create_session(user_id)
    delete_session(pending)                                   # logout до завершення 2FA
    with pytest.raises(SessionRevoked):
        rotate_session_after_2fa(pending, user_id)
    other = find_user_id(make_user())
    foreign, _ = create_session(other)
    with pytest.raises(SessionRevoked):                       # чужа pending-сесія
        rotate_session_after_2fa(foreign, user_id)
    assert sessions(user_id, verified=1) == 1 and sessions(other) == 1


# --- A2: verify проти зміни ролі / logout / скидання пароля -----------------------------------------------------

def _interleave(monkeypatch, before_verify):
    """Подія, що комітиться після перевірки сесії маршрутом, але до транзакції verify (P3)."""
    real = auth_routes.complete_two_factor

    def interleaved(token, code):
        before_verify()
        return real(token, code)

    monkeypatch.setattr(auth_routes, "complete_two_factor", interleaved)


def _verify(client, pending_csrf, code):
    return client.post("/v2/auth/2fa/verify", json={"code": code}, headers={"X-CSRF-Token": pending_csrf})


def test_role_change_before_verify_commit_blocks_new_session(monkeypatch):
    # Ролі admin і data_officer змінює лише власник сервера: та сама транзакція через server_change_role.
    email = make_user()
    target_id = find_user_id(email)
    client, pending_csrf = start_login(email)
    code = latest_code(email)
    _interleave(monkeypatch, lambda: server_change_role(email, "data_officer"))
    response = _verify(client, pending_csrf, code)
    assert response.status_code == 401
    assert sessions(target_id) == 0
    assert challenge_state(target_id) == (0, 1)               # відкритий код погашено зміною ролі


def test_verify_committed_before_role_change_session_is_still_revoked():
    email = make_user()
    client, pending_csrf = start_login(email)
    assert _verify(client, pending_csrf, latest_code(email)).status_code == 200
    server_change_role(email, "data_officer")
    assert user_for_session(client.cookies.get("v2_session")) is None
    assert client.get("/v2/auth/me").status_code == 401


def test_logout_before_verify_commit_blocks_new_session(monkeypatch):
    email = make_user()
    user_id = find_user_id(email)
    client, pending_csrf = start_login(email)
    code = latest_code(email)
    pending = client.cookies.get("v2_session")
    _interleave(monkeypatch, lambda: delete_session(pending))
    assert _verify(client, pending_csrf, code).status_code == 401
    assert sessions(user_id) == 0


def test_password_reset_before_verify_commit_blocks_new_session(monkeypatch):
    email = make_user()
    user_id = find_user_id(email)
    client, pending_csrf = start_login(email)
    login_code = latest_code(email)
    issue_challenge(user_id, "password_reset", email)
    reset_code = latest_code(email)
    _interleave(monkeypatch, lambda: reset_password_with_code(email, reset_code, "AnotherStrongPass1!"))
    assert _verify(client, pending_csrf, login_code).status_code == 401
    assert sessions(user_id) == 0
    assert query("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ? AND consumed = 0", user_id) == [(0,)]


@pytest.mark.parametrize("rounds", [5])
def test_concurrent_verify_and_role_change_never_leave_a_session(rounds):
    for _ in range(rounds):
        email, target_id, _, pending, code = pending_user()
        actions = [lambda: complete_two_factor(pending, code),
                   lambda: server_change_role(email, "data_officer")]
        results = parallel(2, lambda i: actions[i]())
        assert not any(isinstance(r, Exception) for r in results), results
        assert results[0].status in {"ok", "no_pending"}
        assert sessions(target_id) == 0                       # хто б не був першим — сесії цілі немає
        assert query("SELECT role FROM v2_users WHERE id = ?", target_id) == [("data_officer",)]


def test_concurrent_verify_and_password_reset_never_leave_a_session():
    for _ in range(3):
        email, user_id, _, pending, login_code = pending_user()
        issue_challenge(user_id, "password_reset", email)
        reset_code = latest_code(email)
        actions = [lambda: complete_two_factor(pending, login_code),
                   lambda: reset_password_with_code(email, reset_code, "AnotherStrongPass1!")]
        results = parallel(2, lambda i: actions[i]())
        assert not any(isinstance(r, Exception) for r in results), results
        assert results[1].status == "ok"
        assert sessions(user_id) == 0


def test_concurrent_verify_and_logout_never_resurrect_pending():
    for _ in range(3):
        _, user_id, _, pending, code = pending_user()
        actions = [lambda: complete_two_factor(pending, code), lambda: delete_session(pending)]
        verify_result, logout_result = parallel(2, lambda i: actions[i]())
        assert not isinstance(verify_result, Exception) and not isinstance(logout_result, Exception)
        if logout_result is not None:                          # logout видалив pending першим
            assert verify_result.status == "no_pending" and sessions(user_id) == 0
        else:                                                  # verify першим: pending уже замінено
            assert verify_result.status == "ok" and sessions(user_id, verified=1) == 1
