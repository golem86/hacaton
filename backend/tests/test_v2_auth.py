"""Базові сценарії автентифікації V2 (адаптовано з прототипу під V2 Integration Contract)."""
from app.v2_auth import authenticate

from v2_helpers import PASSWORD, latest_code, login, make_user, new_email, preauth_client, start_login


def test_public_registration_always_creates_user():
    client, preauth = preauth_client()
    email = new_email()
    response = client.post("/v2/auth/register", headers={"X-CSRF-Token": preauth}, json={
        "name": "Local User", "email": email, "password": PASSWORD, "password_confirmation": PASSWORD,
        "role": "admin"})
    assert response.status_code == 202
    assert authenticate(email, PASSWORD)["role"] == "user"


def test_login_session_and_user_cannot_access_admin_api():
    email = make_user()
    client, preauth = preauth_client()
    assert client.post("/v2/auth/login", json={"email": email, "password": "wrong-pass"},
                       headers={"X-CSRF-Token": preauth}).status_code == 401
    client, csrf = login(email)
    assert client.get("/v2/auth/me").json()["user"]["email"] == email
    assert client.get("/v2/user/profile").status_code == 200
    assert client.get("/v2/admin/reports/1").status_code == 403
    assert client.get("/api/assessments/1/results").status_code == 403


def test_admin_session_can_access_admin_api_but_not_user_api():
    email = make_user("admin")
    client, pending_csrf = start_login(email)
    assert client.get("/v2/admin/reports/1").status_code == 401          # до 2FA
    assert client.post("/v2/auth/2fa/verify", json={"code": latest_code(email)},
                       headers={"X-CSRF-Token": pending_csrf}).status_code == 200
    assert client.get("/v2/admin/reports/1").status_code == 200
    assert client.get("/api/assessments/1/results").status_code == 200
    assert client.get("/v2/user/profile").status_code == 403


def test_logout_revokes_session():
    client, csrf = login(make_user())
    assert client.post("/v2/auth/logout", headers=csrf).status_code == 200
    assert client.get("/v2/auth/me").status_code == 401


def test_two_factor_resend_rate_limit_is_scoped_to_user():
    email = make_user()
    client, pending_csrf = start_login(email)
    headers = {"X-CSRF-Token": pending_csrf}
    assert client.post("/v2/auth/2fa/resend", headers=headers).status_code == 200
    assert client.post("/v2/auth/2fa/resend", headers=headers).status_code == 200
    assert client.post("/v2/auth/2fa/resend", headers=headers).status_code == 429
