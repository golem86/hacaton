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

from app import seed  # noqa: E402

seed.run(reset=True)
