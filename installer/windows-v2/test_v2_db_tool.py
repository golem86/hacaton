"""
test_v2_db_tool.py — pytest-тести v2_db_tool.py на синтетичних SQLite (лише тимчасові каталоги pytest).
Покриває: таблицю очікувань схем (integrity 3/4/5, auth 1/2), синтетичні міграції integrity 3→5 і auth 1→2 за контрактом,
негативні випадки контракту, backup/restore з --expect-version і --strict, mark-synthetic, bind-check за маніфестом релізу.

Запуск:  python -I -m pytest -q -p no:cacheprovider installer/windows-v2/test_v2_db_tool.py
"""
import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
TOOL = Path(__file__).with_name("v2_db_tool.py")
sys.path.insert(0, str(TOOL.parent))
import v2_db_tool as tool  # noqa: E402


def run(*args):
    r = subprocess.run([sys.executable, "-I", "-B", str(TOOL), *map(str, args)], capture_output=True, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def make_db(path, kind, version, data=True):
    con = sqlite3.connect(path)
    try:
        con.executescript(tool.spec_for(kind, version)["ddl"])
        if data and kind == "integrity":
            fill_integrity(con, version)
        if data and kind == "auth":
            con.execute("INSERT INTO v2_users (name, email, password_hash, role, created_at) VALUES ('Адмін', 'a@example.test', 'h', 'admin', 't')")
            con.execute("INSERT INTO v2_sessions (user_id, token_hash, expires_at, created_at, two_factor_verified) VALUES (1, 'th', 'e', 'c', 1)")
            con.execute("INSERT INTO v2_rate_limits VALUES ('login', 's', 'w', 1)")
        con.execute(f"PRAGMA user_version = {version}")
        con.commit()
    finally:
        con.close()
    return path


def fill_integrity(con, version):
    con.execute("INSERT INTO components VALUES (1, 'C1', 'Компонент', 0.5)")
    con.execute("INSERT INTO cycles VALUES (1, '2026-I', '2026-01-01', 'closed', 5)")
    con.execute("INSERT INTO units VALUES (1, 'Підрозділ А')")
    con.execute("INSERT INTO questions VALUES (1, 1, 'Питання', 1, 5, 'survey')")
    for i in range(1, 7):
        con.execute("INSERT INTO response_sets VALUES (?, 1, 'staff', 'Підрозділ А')", (i,))
        con.execute("INSERT INTO answers VALUES (?, ?, 1, ?)", (i, i, 1 + i % 5))
    con.execute("INSERT INTO objective_indicators VALUES (1, 1, 1, 'Показник', 81.0, 'admin', NULL, 0)")
    con.execute("INSERT INTO recommendations VALUES (1, 1, 1, 'Текст', 'Підстава', 'proposed', NULL, NULL)")
    tok = "token" if version < 5 else "token_hash"
    for i in range(1, 4):
        con.execute(f"INSERT INTO access_tokens (id, cycle_id, {tok}, used) VALUES (?, 1, ?, 0)", (i, f"CODE{i:04d}"))
    con.execute("INSERT INTO audit_events (id, created_at, actor_role, action, assessment_id, details) VALUES (1, '2026-11-20', 'admin', 'cycle.close', 1, '{}')")


def migrate_integrity_3_to_5(path):
    """Синтетична міграція за контрактом §2 (так, як її очікує таблиця SCHEMA_SPECS[integrity,5])."""
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN")
        con.execute(" ".join(tool._INTEGRITY_TABLES_V4["recommendation_actions"].split()).rstrip(";"))
        # 12-крокова процедура SQLite: нова таблиця → копія → DROP старої → RENAME нової (посилання FK інших таблиць
        # на "access_tokens" лишаються чинними; RENAME старої таблиці переписав би їх на тимчасове ім'я — це ловить I08)
        con.execute(" ".join(tool._INTEGRITY_TABLES_V5["access_tokens"].split()).rstrip(";").replace("CREATE TABLE access_tokens", "CREATE TABLE access_tokens_new"))
        rows = con.execute("SELECT id, cycle_id, token, used FROM access_tokens").fetchall()
        for i, c, t, u in rows:
            con.execute("INSERT INTO access_tokens_new (id, cycle_id, token_hash, used) VALUES (?, ?, ?, ?)", (i, c, hashlib.sha256(t.encode()).hexdigest(), u))
        con.execute("DROP TABLE access_tokens")
        con.execute("ALTER TABLE access_tokens_new RENAME TO access_tokens")
        con.execute("ALTER TABLE audit_events ADD COLUMN actor_user_id INTEGER")
        con.execute(" ".join(tool._INTEGRITY_TABLES_V5["instance_meta"].split()).rstrip(";"))
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        con.execute("PRAGMA user_version = 5")
        con.execute("COMMIT")
    finally:
        con.close()


def migrate_auth_1_to_2(path, triggers=True, roles="'user', 'admin', 'data_officer'"):
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN")
        con.execute(f"""CREATE TABLE v2_users_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ({roles})),
    created_at TEXT NOT NULL
)""")
        con.execute("INSERT INTO v2_users_new SELECT * FROM v2_users")
        con.execute("DROP TABLE v2_users")
        con.execute("ALTER TABLE v2_users_new RENAME TO v2_users")
        tail = tool._AUTH_DDL_V2[tool._AUTH_DDL_V2.index("CREATE TABLE IF NOT EXISTS v2_role_changes"):]
        if not triggers:
            tail = tail[:tail.index("CREATE TRIGGER")]
        con.execute("COMMIT")
        con.executescript("BEGIN;" + tail + "PRAGMA user_version = 2; COMMIT;")
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------ таблиця очікувань
@pytest.mark.parametrize("kind,version", sorted(tool.SCHEMA_SPECS))
def test_fresh_ddl_passes_its_own_spec(tmp_path, kind, version):
    p = make_db(tmp_path / "x.db", kind, version)
    before = sha(p)
    code, out, err = run("schema", p, "--kind", kind, "--expect-version", version)
    assert code == 0, out + err
    assert "SCHEMA OK" in out
    need = 13 + (1 if tool.SCHEMA_SPECS[(kind, version)]["contract"] else 0)
    assert len([ln for ln in out.splitlines() if " PASS " in ln]) == need
    assert sha(p) == before and not any(Path(str(p) + s).exists() for s in tool.SIDECARS)


def test_auth_schema_default_is_release_v1(tmp_path):
    p = make_db(tmp_path / "a.db", "auth", 1)
    code, out, _ = run("auth-schema", p)
    assert code == 0 and "AUTH SCHEMA OK release=dde86e6 checks=13" in out


def test_old_versions_fail_new_expectations(tmp_path):
    i3 = make_db(tmp_path / "i3.db", "integrity", 3)
    code, out, err = run("integrity-schema", i3, "--expect-version", "5")
    assert code != 0 and "STOP: integrity-schema" in err
    for cid in ("I02", "I05", "I06", "I11", "I14"):
        assert f"{cid} FAIL" in out, cid
    a1 = make_db(tmp_path / "a1.db", "auth", 1)
    code, out, err = run("auth-schema", a1, "--expect-version", "2")
    assert code != 0
    for cid in ("A02", "A05", "A10", "A12", "A14"):
        assert f"{cid} FAIL" in out, cid


def test_unknown_version_is_stop(tmp_path):
    p = make_db(tmp_path / "x.db", "integrity", 3)
    code, _, err = run("integrity-schema", p, "--expect-version", "6")
    assert code != 0 and "немає очікувань схеми integrity версії 6" in err


# ------------------------------------------------------------------------------------------------ синтетичні міграції
def test_migrated_integrity_3_to_5_passes_contract(tmp_path):
    p = make_db(tmp_path / "i.db", "integrity", 3)
    fp = tool.fingerprint(sqlite3.connect(p))
    migrate_integrity_3_to_5(p)
    code, out, err = run("integrity-schema", p, "--expect-version", "5")
    assert code == 0, out + err
    assert "I14 PASS" in out and "INTEGRITY SCHEMA OK version=5" in out
    with sqlite3.connect(p) as c:
        assert tool.fingerprint(c) == fp                      # міграція не змінює детерміновані таблиці seed
        assert c.execute("SELECT COUNT(*) FROM access_tokens WHERE length(token_hash) = 64").fetchone()[0] == 3


def test_migrated_auth_1_to_2_passes_contract(tmp_path):
    p = make_db(tmp_path / "a.db", "auth", 1)
    migrate_auth_1_to_2(p)
    code, out, err = run("auth-schema", p, "--expect-version", "2")
    assert code == 0, out + err
    assert "A13 PASS" in out and "A14 PASS" in out      # RENAME дає "v2_users" у лапках — нормалізація це враховує


def test_auth_v2_without_append_only_triggers_fails(tmp_path):
    p = make_db(tmp_path / "a.db", "auth", 1)
    migrate_auth_1_to_2(p, triggers=False)
    code, out, _ = run("auth-schema", p, "--expect-version", "2")
    assert code != 0 and "A12 FAIL" in out and "A14 FAIL" in out and "UPDATE дозволено" in out


def test_auth_v2_roles_wider_than_contract_fails(tmp_path):
    p = make_db(tmp_path / "a.db", "auth", 1)
    migrate_auth_1_to_2(p, roles="'user', 'admin', 'data_officer', 'root'")
    code, out, _ = run("auth-schema", p, "--expect-version", "2")
    assert code != 0 and "A10 FAIL" in out and "A14 FAIL" in out and "'root' прийнято" in out


def test_rename_of_old_table_breaks_fk_and_is_detected(tmp_path):
    p = make_db(tmp_path / "i.db", "integrity", 3)
    migrate_integrity_3_to_5(p)
    con = sqlite3.connect(p, isolation_level=None)
    con.execute("PRAGMA foreign_keys = OFF")
    con.executescript("BEGIN; ALTER TABLE access_tokens RENAME TO _old_tokens; CREATE TABLE access_tokens AS SELECT * FROM _old_tokens; DROP TABLE _old_tokens; COMMIT;")
    con.close()
    code, out, _ = run("integrity-schema", p, "--expect-version", "5")
    assert code != 0 and "I08 FAIL" in out and "I06 FAIL" in out


def test_integrity_v5_with_plain_token_column_fails(tmp_path):
    p = make_db(tmp_path / "i.db", "integrity", 3)
    con = sqlite3.connect(p)
    con.execute("ALTER TABLE audit_events ADD COLUMN actor_user_id INTEGER")
    con.execute("CREATE TABLE instance_meta (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("PRAGMA user_version = 5"); con.commit(); con.close()
    code, out, _ = run("integrity-schema", p, "--expect-version", "5")
    assert code != 0
    for cid in ("I06", "I11", "I14"):
        assert f"{cid} FAIL" in out, cid
    assert "value NULL прийнято" in out and "access_tokens.token має бути відсутня" in out


# ------------------------------------------------------------------------------------------------ backup / restore
@pytest.mark.parametrize("kind,version", [("integrity", 3), ("integrity", 5), ("auth", 1), ("auth", 2)])
def test_backup_and_restore_with_expect_version(tmp_path, kind, version):
    src = make_db(tmp_path / "src.db", kind, version)
    bk = tmp_path / "bk" / "copy.db"; bk.parent.mkdir()
    code, out, err = run("backup", src, bk, "--expect-version", version, "--kind", kind, "--strict")
    assert code == 0, out + err
    last = out.strip().splitlines()[-1]
    assert last.startswith(f"BACKUP OK user_version={version}") and "schema=strict restore-test=ok" in last
    assert last.endswith(f"sha256={sha(bk)}")
    assert [x.name for x in bk.parent.iterdir()] == ["copy.db"]          # тимчасовий каталог тесту відновлення прибрано
    dst = tmp_path / "data" / "restored.db"; dst.parent.mkdir()
    code, out, err = run("restore", bk, dst, "--expect-version", version, "--sha256", sha(bk), "--strict")
    assert code == 0, out + err
    assert out.strip().splitlines()[-1].startswith(f"RESTORE OK user_version={version}")
    assert sorted(x.name for x in dst.parent.iterdir()) == ["restored.db"]
    with sqlite3.connect(src) as a, sqlite3.connect(dst) as b:
        assert list(a.iterdump()) == list(b.iterdump())


def test_backup_wrong_version_is_stop(tmp_path):
    src = make_db(tmp_path / "src.db", "integrity", 3)
    code, _, err = run("backup", src, tmp_path / "c.db", "--expect-version", "5")
    assert code != 0 and "user_version=3" in err and not (tmp_path / "c.db").exists()


def test_restore_refuses_existing_target_and_bad_sha(tmp_path):
    src = make_db(tmp_path / "src.db", "auth", 1)
    bk = tmp_path / "bk.db"
    assert run("backup", src, bk, "--expect-version", "1")[0] == 0
    existing = make_db(tmp_path / "live.db", "auth", 1)
    before = sha(existing)
    code, _, err = run("restore", bk, existing, "--expect-version", "1")
    assert code != 0 and "лише в новий файл" in err and sha(existing) == before
    Path(str(tmp_path / "new.db") + "-wal").write_bytes(b"x")
    code, _, err = run("restore", bk, tmp_path / "new.db", "--expect-version", "1")
    assert code != 0 and not (tmp_path / "new.db").exists()
    code, _, err = run("restore", bk, tmp_path / "n2.db", "--expect-version", "1", "--sha256", "0" * 64)
    assert code != 0 and "SHA256" in err and not (tmp_path / "n2.db").exists()
    code, _, err = run("restore", bk, tmp_path / "n3.db", "--expect-version", "2")
    assert code != 0 and not (tmp_path / "n3.db").exists()
    assert not [x for x in tmp_path.iterdir() if x.name.startswith(".v2-restore-")]


# ------------------------------------------------------------------------------------------------ mark-synthetic
def synthetic_set(tmp_path, roles=("admin",), marker=True, version=5):
    d = tmp_path / "data"; d.mkdir()
    ref = make_db(tmp_path / "reference-initial.db", "integrity", 3)
    db = make_db(d / "integrity_v2.db", "integrity", 3)
    if version == 5:
        migrate_integrity_3_to_5(db)
    auth = make_db(d / "v2_auth.db", "auth", 1, data=False)
    migrate_auth_1_to_2(auth)
    con = sqlite3.connect(auth)
    for i, r in enumerate(roles, 1):
        con.execute("INSERT INTO v2_users (name, email, password_hash, role, created_at) VALUES (?, ?, 'h', ?, 't')", (f"u{i}", f"u{i}@example.test", r))
    con.commit(); con.close()
    if marker:
        (d / "CREATED-BY-V2-INSTALL.txt").write_text("created by test", encoding="utf-8")
    return db, auth, ref


def meta(db):
    with sqlite3.connect(db) as c:
        return c.execute("SELECT value FROM instance_meta WHERE key='dataset'").fetchone()


def test_mark_synthetic_success_and_idempotent(tmp_path):
    db, auth, ref = synthetic_set(tmp_path)
    code, out, err = run("mark-synthetic", db, "--auth-db", auth, "--reference-db", ref)
    assert code == 0, out + err
    assert "MARK-SYNTHETIC OK dataset=synthetic" in out and meta(db) == ("synthetic",)
    assert run("integrity-schema", db, "--expect-version", "5")[0] == 0
    before = sha(db)
    code, out, _ = run("mark-synthetic", db, "--auth-db", auth, "--reference-fingerprint", tool.fingerprint(sqlite3.connect(ref)))
    assert code == 0 and "уже встановлено" in out and sha(db) == before


@pytest.mark.parametrize("case", ["no-marker", "user-role", "data-officer", "fingerprint", "schema3", "other-value"])
def test_mark_synthetic_refusals_change_nothing(tmp_path, case):
    db, auth, ref = synthetic_set(tmp_path, roles=("admin", "user") if case == "user-role" else ("admin", "data_officer") if case == "data-officer" else ("admin",),
                                  marker=case != "no-marker", version=3 if case == "schema3" else 5)
    if case == "fingerprint":
        with sqlite3.connect(db) as c:
            c.execute("UPDATE answers SET value = 5 WHERE id = 1")
    if case == "other-value":
        with sqlite3.connect(db) as c:
            c.execute("INSERT INTO instance_meta VALUES ('dataset', 'production')")
    before = sha(db)
    args = ["mark-synthetic", db, "--auth-db", auth, "--reference-db", ref] + (["--expect-version", "3"] if case == "schema3" else [])
    code, out, err = run(*args)
    assert code != 0 and "STOP" in err and "MARK-SYNTHETIC OK" not in out
    assert sha(db) == before


def test_mark_synthetic_allow_role_data_officer(tmp_path):
    db, auth, ref = synthetic_set(tmp_path, roles=("admin", "data_officer"))
    code, out, err = run("mark-synthetic", db, "--auth-db", auth, "--reference-db", ref, "--allow-role", "data_officer")
    assert code == 0, err
    assert meta(db) == ("synthetic",)
    code, _, err = run("mark-synthetic", db, "--auth-db", auth, "--reference-db", ref, "--allow-role", "user")
    assert code != 0


# ------------------------------------------------------------------------------------------------ bind-check
def fake_release(tmp_path, ddl, version, tamper=False):
    be = tmp_path / "rel" / "backend"; (be / "app").mkdir(parents=True)
    src = f'AUTH_SCHEMA_VERSION = {version}\n_SCHEMA = """{ddl}"""\n'
    (be / "app" / "v2_auth.py").write_text(src, encoding="utf-8", newline="\n")
    man = tmp_path / "rel" / "BACKEND-SHA256.txt"
    man.write_text(f"{sha(be / 'app' / 'v2_auth.py')}  backend/app/v2_auth.py\n", encoding="utf-8")
    if tamper:
        with open(be / "app" / "v2_auth.py", "a", encoding="utf-8") as f:
            f.write("# змінено після маніфесту\n")
    return be, man


def test_bind_check_uses_release_manifest(tmp_path):
    be, man = fake_release(tmp_path, tool._AUTH_DDL_V2, 2)
    code, out, err = run("bind-check", "--kind", "auth", "--expect-version", "2", "--release-backend", be, "--release-manifest", man)
    assert code == 0 and "BIND OK kind=auth version=2" in out, out + err


def test_bind_check_detects_tamper_and_ddl_drift(tmp_path):
    be, man = fake_release(tmp_path / "t", tool._AUTH_DDL_V2, 2, tamper=True)
    code, _, err = run("bind-check", "--kind", "auth", "--expect-version", "2", "--release-backend", be, "--release-manifest", man)
    assert code != 0 and "B01" in err
    drift = tool._AUTH_DDL_V2.replace("v2_role_changes_no_delete", "v2_role_changes_nodel")
    be, man = fake_release(tmp_path / "d", drift, 2)
    code, _, err = run("bind-check", "--kind", "auth", "--expect-version", "2", "--release-backend", be, "--release-manifest", man)
    assert code != 0 and "B03" in err and "оновіть таблицю очікувань" in err


def test_no_pinned_source_sha_in_tool():
    src = TOOL.read_text(encoding="utf-8")
    assert "RELEASE_AUTH_SOURCE_SHA256" not in src and "cbb529ce" not in src
