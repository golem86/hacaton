"""Допоміжні функції для тестів V2: вхід через справжню сесію з 2FA і CSRF."""
import re
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.v2_auth import create_user, latest_dev_mail

PASSWORD = "StrongPass123!"


def new_email() -> str:
    return f"{uuid4().hex}@example.test"


def preauth_client(**kwargs) -> tuple[TestClient, str]:
    client = TestClient(app, **kwargs)
    return client, client.get("/v2/auth/csrf").json()["csrf_token"]


def latest_code(email: str) -> str:
    return re.search(r"(\d{6})", latest_dev_mail(email)["body"]).group(1)


def start_login(email: str, password: str = PASSWORD, **kwargs) -> tuple[TestClient, str]:
    """Вхід до 2FA. Повертає клієнта з pending-сесією і CSRF-токен цієї сесії."""
    client, preauth = preauth_client(**kwargs)
    response = client.post("/v2/auth/login", json={"email": email, "password": password},
                           headers={"X-CSRF-Token": preauth})
    assert response.status_code == 200, response.text
    return client, response.json()["csrf_token"]


def login(email: str, password: str = PASSWORD, **kwargs) -> tuple[TestClient, dict[str, str]]:
    """Повний вхід з 2FA. Повертає клієнта і заголовок з CSRF-токеном сесії."""
    client, pending_csrf = start_login(email, password, **kwargs)
    response = client.post("/v2/auth/2fa/verify", json={"code": latest_code(email)},
                           headers={"X-CSRF-Token": pending_csrf})
    assert response.status_code == 200, response.text
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}


def make_user(role: str = "user") -> str:
    email = new_email()
    create_user("Test " + role, email, PASSWORD, role=role)
    return email
