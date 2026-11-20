"""
Налаштування для тестів: вони працюють з ОКРЕМИМИ тимчасовими базами,
тому ваші integrity.db і v2_auth.db під час тестів не змінюються.
Цей код виконується автоматично перед усіма тестами.

Режим тестів — development:
  - INTEGRITY_DEMO_XROLE=1 лише для регресійних тестів V1, що використовують X-Role.
    Тести безпеки V2 (test_v2_security.py) вимикають його і перевіряють справжні сесії;
  - V2_AUTH_DEV_MAIL=1 — коди 2FA потрапляють у локальну dev-скриньку тимчасової БД.
"""
import os
import tempfile
from pathlib import Path

# Має бути ДО будь-якого імпорту з app, бо шляхи й режими читаються під час імпорту
_test_dir = Path(tempfile.mkdtemp())
os.environ["APP_ENV"] = "development"
os.environ["INTEGRITY_DB"] = str(_test_dir / "test_integrity.db")
os.environ["V2_AUTH_DB"] = str(_test_dir / "test_v2_auth.db")
os.environ["INTEGRITY_DEMO_XROLE"] = "1"
os.environ["V2_AUTH_DEV_MAIL"] = "1"
os.environ["V2_CATALOG_NOW"] = "2026-11-18T12:00:00+00:00"
os.environ.pop("V2_AUTH_SECURE_COOKIE", None)
os.environ.pop("TRUSTED_PROXIES", None)

from app import seed, v2_auth  # noqa: E402

# Тести працюють зі швидким scrypt (N=2^14 замість 2^17), як PASSWORD_HASHERS у тестах Django: сотні входів
# інакше тривали б хвилини. Продакшн-параметри (N=2^17, r=8, p=1, maxmem 256 MiB) перевіряються в окремому
# процесі без цього перевизначення (test_v2_passwords.py); тест часу відповіді вмикає їх явно.
v2_auth.SCRYPT_N = 2 ** 14

seed.run(reset=True)

import pytest  # noqa: E402

from app import v2_mail_queue  # noqa: E402


@pytest.fixture(autouse=True)
def _drain_mail_queue(monkeypatch):
    """Фонова черга листів (скидання пароля) спорожнюється до відкату monkeypatch (env, SMTP) цього тесту."""
    yield
    assert v2_mail_queue.mail_queue.wait_idle(timeout=30), "фонова черга листів не спорожнилася"
