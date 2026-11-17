"""
Налаштування для тестів: вони працюють з ОКРЕМОЮ тимчасовою базою,
тому ваша integrity.db під час тестів не змінюється.
Цей код виконується автоматично перед усіма тестами.
"""
import os
import tempfile
from pathlib import Path

# Має бути ДО будь-якого імпорту з app, бо database.py читає шлях під час імпорту
_test_dir = Path(tempfile.mkdtemp())
os.environ["INTEGRITY_DB"] = str(_test_dir / "test_integrity.db")
os.environ["V2_AUTH_DB"] = str(_test_dir / "test_v2_auth.db")
os.environ["V2_ANONYMOUS_DB"] = str(_test_dir / "test_v2_anonymous.db")
os.environ["V2_CATALOG_NOW"] = "2026-11-18T12:00:00+00:00"

from app import seed  # noqa: E402

seed.run(reset=True)
