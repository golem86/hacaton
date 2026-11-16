"""
Налаштування для тестів: вони працюють з ОКРЕМОЮ тимчасовою базою,
тому ваша integrity.db під час тестів не змінюється.
Цей код виконується автоматично перед усіма тестами.
"""
import os
import tempfile
from pathlib import Path

# Має бути ДО будь-якого імпорту з app, бо database.py читає шлях під час імпорту
os.environ["INTEGRITY_DB"] = str(Path(tempfile.mkdtemp()) / "test_integrity.db")

from app import seed  # noqa: E402

seed.run(reset=True)
