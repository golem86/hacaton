"""
Паролі V2 (аудит backend 20.11.2026; docs/V2_HARDENING_CONTRACT.md, розділ 3):
  - A9: scrypt N=2^17, r=8, p=1, maxmem 256 MiB; старі хеші перевіряються за параметрами з рядка
    і переобчислюються після успішного входу;
  - A6: час login і register не залежить від існування email (фіктивний scrypt з тими самими параметрами).

conftest.py для швидкості знижує SCRYPT_N до 2^14; продакшн-значення перевіряються тут в окремому процесі,
а тест часу вмикає їх явно.
"""
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import v2_auth
from app.v2_auth import authenticate, create_user, find_user_id, hash_password, register_user, verify_password

from v2_helpers import PASSWORD, new_email, preauth_client

BACKEND = Path(__file__).resolve().parents[1]


def stored_hash(email: str) -> str:
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(v2_auth.auth_db_path())) as db:
        return db.execute("SELECT password_hash FROM v2_users WHERE email = ?", (email,)).fetchone()[0]


def test_production_scrypt_parameters_without_test_override():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import app.v2_auth as a; "
            "h = a.hash_password('synthetic-password-1'); "
            "print(a.SCRYPT_N, a.SCRYPT_R, a.SCRYPT_P, a.SCRYPT_MAXMEM, h.rsplit('$', 2)[0], "
            "a.verify_password('synthetic-password-1', h), a.needs_rehash(h))")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(BACKEND)], capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["131072", "8", "1", str(256 * 1024 * 1024), "scrypt$131072$8$1",
                                     "True", "False"]


def test_old_hash_is_verified_by_its_own_parameters_and_upgraded_after_login(monkeypatch):
    email = new_email()
    create_user("Legacy", email, PASSWORD)                      # хеш зі «старими» параметрами (N=2^14)
    old = stored_hash(email)
    assert old.startswith("scrypt$16384$8$1$")
    monkeypatch.setattr(v2_auth, "SCRYPT_N", 2 ** 15)            # «поточні» параметри стали сильнішими
    assert authenticate(email, "wrong-password") is None
    assert stored_hash(email) == old                             # невдалий вхід хеш не змінює
    client, preauth = preauth_client()
    response = client.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"X-CSRF-Token": preauth})
    assert response.status_code == 200
    upgraded = stored_hash(email)
    assert upgraded.startswith("scrypt$32768$8$1$") and upgraded != old
    assert verify_password(PASSWORD, upgraded) and authenticate(email, PASSWORD)["email"] == email


def test_upgrade_does_not_overwrite_a_concurrent_password_change(monkeypatch):
    email = new_email()
    create_user("Legacy", email, PASSWORD)
    user_id = find_user_id(email)
    monkeypatch.setattr(v2_auth, "SCRYPT_N", 2 ** 15)
    real_hash = v2_auth.hash_password

    def hash_then_reset(password):
        monkeypatch.setattr(v2_auth, "hash_password", real_hash)
        encoded = real_hash(password)
        v2_auth.update_password(user_id, "ChangedMeanwhile1!")    # скидання пароля між перевіркою і записом
        return encoded

    monkeypatch.setattr(v2_auth, "hash_password", hash_then_reset)
    assert authenticate(email, PASSWORD) is not None
    monkeypatch.setattr(v2_auth, "hash_password", real_hash)
    assert verify_password("ChangedMeanwhile1!", stored_hash(email))


@pytest.mark.parametrize("encoded", ["scrypt$x", "bcrypt$16384$8$1$AAAA$AAAA", "", "scrypt$16384$8$1$$"])
def test_malformed_hashes_never_verify(encoded):
    assert verify_password(PASSWORD, encoded) is False


def count_scrypt(monkeypatch) -> list:
    calls = []
    real = v2_auth._scrypt

    def counted(*args, **kwargs):
        calls.append(args[2:5])
        return real(*args, **kwargs)
    monkeypatch.setattr(v2_auth, "_scrypt", counted)
    return calls


def test_equal_scrypt_work_for_known_and_unknown_email(monkeypatch):
    """Детермінований бік A6: кількість і параметри обчислень scrypt не залежать від існування email."""
    email = new_email()
    create_user("Known", email, PASSWORD)
    current = (v2_auth.SCRYPT_N, v2_auth.SCRYPT_R, v2_auth.SCRYPT_P)
    calls = count_scrypt(monkeypatch)
    for login_email, password in ((new_email(), PASSWORD), (email, "wrong-password"), (email, PASSWORD)):
        calls.clear()
        authenticate(login_email, password)
        assert calls == [current], (login_email == email, password)
    for register_email in (new_email(), email):
        calls.clear()
        register_user("Someone", register_email, PASSWORD)
        assert calls == [current]
    assert authenticate(email, PASSWORD)["name"] == "Known"      # наявний акаунт не перезаписано


def test_old_hash_login_costs_at_least_one_current_computation(monkeypatch):
    email = new_email()
    create_user("Legacy", email, PASSWORD)
    monkeypatch.setattr(v2_auth, "SCRYPT_N", 2 ** 15)
    calls = count_scrypt(monkeypatch)
    authenticate(email, "wrong-password")
    assert calls == [(2 ** 14, 8, 1), (2 ** 15, 8, 1)]          # старий хеш + вирівнювання


def _median_seconds(action, samples: int) -> float:
    durations = []
    for index in range(samples):
        started = time.perf_counter()
        action(index)
        durations.append(time.perf_counter() - started)
    return statistics.median(durations)


def test_login_and_register_timing_do_not_reveal_email(monkeypatch):
    """Статистично (медіани, продакшн-scrypt): раніше 24 мс для невідомого email проти 99 мс для наявного."""
    monkeypatch.setattr(v2_auth, "SCRYPT_N", 2 ** 17)
    email = new_email()
    create_user("Known", email, PASSWORD)

    def login(target):
        def run(index):
            client, preauth = preauth_client(client=(f"198.18.{10 + index}.{1 if target == email else 2}", 1000))
            response = client.post("/v2/auth/login", json={"email": target, "password": "wrong-password"},
                                   headers={"X-CSRF-Token": preauth})
            assert response.status_code == 401
        return run

    def register(target):
        def run(index):
            client, preauth = preauth_client(client=(f"198.18.{40 + index}.{1 if target == email else 2}", 1000))
            response = client.post("/v2/auth/register", headers={"X-CSRF-Token": preauth}, json={
                "name": "Someone", "email": target if target == email else new_email(),
                "password": PASSWORD, "password_confirmation": PASSWORD})
            assert response.status_code == 202
        return run

    for action in (login, register):
        known = _median_seconds(action(email), 5)
        unknown = _median_seconds(action("missing-" + new_email()), 5)
        ratio = unknown / known
        assert 0.7 < ratio < 1.4, f"{action.__name__}: відомий {known:.3f} с, невідомий {unknown:.3f} с"
