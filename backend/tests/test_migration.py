"""
Тести міграції бази зі схеми попередньої версії (v0) на поточну (v1).
Кожен тест працює з власним тимчасовим файлом бази.
"""
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.migrations import MigrationError, migrate
from app.models import AccessToken, Answer, ResponseSet

# Схема таблиць так, як її створювала попередня версія бекенду (PR #4)
LEGACY_DDL = """
CREATE TABLE components (id INTEGER PRIMARY KEY, code VARCHAR(10) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL, weight FLOAT NOT NULL);
CREATE TABLE questions (id INTEGER PRIMARY KEY, component_id INTEGER NOT NULL REFERENCES components(id),
    text TEXT NOT NULL, scale_min INTEGER NOT NULL, scale_max INTEGER NOT NULL, kind VARCHAR(20) NOT NULL);
CREATE TABLE cycles (id INTEGER PRIMARY KEY, name VARCHAR(50) NOT NULL, start_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL, min_group_size INTEGER NOT NULL);
CREATE TABLE response_sets (id INTEGER PRIMARY KEY, cycle_id INTEGER NOT NULL REFERENCES cycles(id),
    respondent_category VARCHAR(30) NOT NULL, unit VARCHAR(100) NOT NULL);
CREATE TABLE answers (id INTEGER PRIMARY KEY, response_set_id INTEGER NOT NULL REFERENCES response_sets(id),
    question_id INTEGER NOT NULL REFERENCES questions(id), value INTEGER NOT NULL);
"""
LEGACY_DATA = """
INSERT INTO components VALUES (1, 'C1', 'Компонент', 1.0);
INSERT INTO questions VALUES (1, 1, 'Питання 1', 1, 5, 'survey'), (2, 1, 'Питання 2', 1, 5, 'survey');
INSERT INTO cycles VALUES (1, '2026-II', '2026-11-01', 'open', 5);
INSERT INTO response_sets VALUES (1, 1, 'cadets', 'Факультет 1'), (2, 1, 'npp', 'Факультет 1'),
                                 (3, 1, 'cadets', 'Кафедра історії');
INSERT INTO answers VALUES (1, 1, 1, 4), (2, 1, 2, 5), (3, 2, 1, 3), (4, 2, 2, 2), (5, 3, 1, 1), (6, 3, 2, 5);
"""


def make_legacy_db(path, extra_sql: str = "", with_empty_units: bool = False) -> None:
    con = sqlite3.connect(path)
    con.executescript(LEGACY_DDL + LEGACY_DATA + extra_sql)
    if with_empty_units:
        # сценарій з аудиту: новий код уже відкривав стару базу і create_all додав порожню units
        con.execute("CREATE TABLE units (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE)")
    con.commit()
    con.close()


def inspect_db(path) -> dict:
    con = sqlite3.connect(path)
    info = {
        "version": con.execute("PRAGMA user_version").fetchone()[0],
        "sets": con.execute("SELECT COUNT(*) FROM response_sets").fetchone()[0],
        "answers": con.execute("SELECT COUNT(*) FROM answers").fetchone()[0],
        "answer_rows": con.execute("SELECT * FROM answers ORDER BY id").fetchall(),
        "set_rows": con.execute("SELECT * FROM response_sets ORDER BY id").fetchall(),
        "unit_fk": any(r[2] == "units" for r in con.execute("PRAGMA foreign_key_list(response_sets)")),
        "tables": {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")},
    }
    info["units"] = (sorted(r[0] for r in con.execute("SELECT name FROM units"))
                     if "units" in info["tables"] else None)
    con.close()
    return info


@pytest.mark.parametrize("with_empty_units", [False, True])
def test_legacy_database_is_migrated_without_data_loss(tmp_path, with_empty_units):
    db = tmp_path / "integrity.db"
    make_legacy_db(db, with_empty_units=with_empty_units)
    before = inspect_db(db)

    report = migrate(create_engine(f"sqlite:///{db}"))

    after = inspect_db(db)
    assert report["action"] == "migrated"
    assert after["set_rows"] == before["set_rows"]          # кожна анкета на місці, без змін
    assert after["answer_rows"] == before["answer_rows"]    # кожна відповідь на місці, без змін
    assert after["units"] == ["Кафедра історії", "Факультет 1"]  # підрозділи перенесено в довідник
    assert after["unit_fk"] is True
    assert after["version"] == 1
    assert {"access_tokens", "objective_indicators", "recommendations"} <= after["tables"]
    assert not any(t.startswith("_legacy") for t in after["tables"])


def test_backup_is_created_and_contains_original_data(tmp_path):
    db = tmp_path / "integrity.db"
    make_legacy_db(db)
    report = migrate(create_engine(f"sqlite:///{db}"))
    backups = list(tmp_path.glob("integrity.backup-*.db"))
    assert len(backups) == 1 and report["backup"] == str(backups[0])
    original = inspect_db(backups[0])
    assert original["version"] == 0 and original["unit_fk"] is False and original["answers"] == 6


def test_constraints_work_after_migration(tmp_path):
    db = tmp_path / "integrity.db"
    make_legacy_db(db)
    engine = create_engine(f"sqlite:///{db}")
    migrate(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(Answer(response_set_id=1, question_id=1, value=2))      # дубль відповіді
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        s.add(ResponseSet(cycle_id=1, respondent_category="cadets", unit="Іваненко, кімн. 214"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "integrity.db"
    make_legacy_db(db)
    engine = create_engine(f"sqlite:///{db}")
    migrate(engine)
    snapshot = inspect_db(db)
    assert migrate(engine)["action"] == "up_to_date"
    assert inspect_db(db) == snapshot
    assert len(list(tmp_path.glob("integrity.backup-*.db"))) == 1   # повторно копію не робить


def test_duplicate_answers_stop_migration_and_leave_db_untouched(tmp_path):
    db = tmp_path / "integrity.db"
    make_legacy_db(db, extra_sql="INSERT INTO answers VALUES (7, 1, 1, 2);")
    before = inspect_db(db)
    with pytest.raises(MigrationError, match="дубльованих"):
        migrate(create_engine(f"sqlite:///{db}"))
    assert inspect_db(db) == before


def test_api_accepts_old_unit_after_migration(tmp_path):
    """Сценарій з аудиту: після міграції /units не порожній і анкета зі старим підрозділом приймається."""
    db = tmp_path / "integrity.db"
    make_legacy_db(db)
    engine = create_engine(f"sqlite:///{db}")
    migrate(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(AccessToken(cycle_id=1, token="legacy-test-token", used=False))
        s.commit()

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    try:
        client = TestClient(app)
        assert client.get("/api/units", headers={"X-Role": "respondent"}).json() == \
            ["Кафедра історії", "Факультет 1"]
        response = client.post("/api/assessments/1/submissions", headers={"X-Role": "respondent"},
                               json={"token": "legacy-test-token", "respondent_category": "cadets",
                                     "unit": "Кафедра історії",
                                     "answers": [{"question_id": 1, "value": 3}, {"question_id": 2, "value": 4}]})
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()
    assert inspect_db(db)["sets"] == 4
