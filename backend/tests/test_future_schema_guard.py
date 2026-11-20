"""Reject a newer SQLite format before migration can modify data or make backups."""
from contextlib import closing
import sqlite3

import pytest
from sqlalchemy import create_engine
from app.migrations import MigrationError, migrate


@pytest.mark.parametrize("shape", ["empty", "unknown_table", "legacy_table"])
def test_future_version_refused_without_any_migration_write(tmp_path, shape):
    target = tmp_path / "future.db"
    with closing(sqlite3.connect(target)) as con:
        if shape == "unknown_table":
            con.execute("CREATE TABLE future_marker (id INTEGER PRIMARY KEY, value TEXT)")
            con.execute("INSERT INTO future_marker VALUES (1, 'synthetic')")
        elif shape == "legacy_table":
            con.execute("CREATE TABLE response_sets (id INTEGER PRIMARY KEY)")
        con.execute("PRAGMA user_version = 4")
        con.commit()
    before = target.read_bytes()
    engine = create_engine(f"sqlite:///{target}")
    try:
        with pytest.raises(MigrationError, match="newer"):
            migrate(engine)
    finally:
        engine.dispose()
    assert target.read_bytes() == before
    assert list(tmp_path.glob("*.backup-*.db")) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["future.db"]
