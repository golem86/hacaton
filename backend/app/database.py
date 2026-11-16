"""
Підключення до бази даних.

Тут ми кажемо програмі: «наша база — це файл integrity.db у папці backend».
Усі інші файли беруть звідси `engine` (з'єднання з базою) і `SessionLocal`
(«сесія» — розмова з базою: відкрили, щось прочитали/записали, закрили).
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Шлях до файлу бази: за замовчуванням E:\hacaton\backend\integrity.db
# (Path(__file__) — це цей файл, .parent.parent — піднімаємось з app/ до backend/).
# Змінна середовища INTEGRITY_DB дозволяє вказати інший файл — так тести
# працюють з окремою тимчасовою базою і не чіпають вашу.
DB_PATH = Path(os.environ.get("INTEGRITY_DB",
                              Path(__file__).resolve().parent.parent / "integrity.db"))

# Рядок підключення. Щоб потім перейти на PostgreSQL, достатньо змінити лише його.
DATABASE_URL = f"sqlite:///{DB_PATH}"

# engine — «двигун», який вміє говорити з базою.
# check_same_thread=False потрібне лише для SQLite, щоб FastAPI міг працювати з базою з різних потоків.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Фабрика сесій: кожен запит до API отримує свою окрему сесію.
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    """Батьківський клас для всіх таблиць. Кожна таблиця в models.py «успадковується» від нього."""


def get_db():
    """
    Видає сесію для одного запиту до API і гарантовано закриває її після.
    FastAPI викликає цю функцію сам, якщо написати `db: Session = Depends(get_db)`.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
