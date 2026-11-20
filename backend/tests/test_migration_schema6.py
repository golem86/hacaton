"""Міграція INTEGRITY_DB 5 → 6: лише нові таблиці зрілості, перевірена резервна копія, дані без змін."""
import sqlite3
from contextlib import closing

from sqlalchemy import create_engine

from app.migrations import SCHEMA_VERSION, check_schema, migrate
from app.models import (UserUnit, AnnexVAnswer, AnnexVExpertAssessment, AnnexVResponse, ChecklistEntry,
                        MaturityIndicator)

NEW_TABLES = [AnnexVAnswer, AnnexVExpertAssessment, ChecklistEntry, MaturityIndicator, AnnexVResponse, UserUnit]


def test_schema_5_database_gets_maturity_tables_with_backup(tmp_path):
    db_file = tmp_path / "integrity.db"
    engine = create_engine(f"sqlite:///{db_file}")
    assert migrate(engine)["action"] == "created"
    for model in NEW_TABLES:                                    # імітуємо базу версії 5
        model.__table__.drop(engine)
    with closing(sqlite3.connect(db_file)) as con:
        con.execute("INSERT INTO cycles (id, name, start_date, status, min_group_size) "
                    "VALUES (1, 'SYN', '2026-01-01', 'closed', 5)")
        con.execute("PRAGMA user_version = 5")
        con.commit()

    report = migrate(engine)

    assert SCHEMA_VERSION == 7
    assert report["action"] == "migrated" and report["backup"]
    assert set(report["tables_created"]) == {m.__tablename__ for m in NEW_TABLES}
    with closing(sqlite3.connect(db_file)) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 7
        assert con.execute("SELECT name FROM cycles").fetchall() == [("SYN",)]
        for model in NEW_TABLES:
            assert con.execute(f"SELECT COUNT(*) FROM {model.__tablename__}").fetchone()[0] == 0
    with closing(sqlite3.connect(report["backup"])) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 5
    check_schema(engine)                                        # release-перевірка проходить
    assert migrate(engine)["action"] == "up_to_date"
    engine.dispose()
