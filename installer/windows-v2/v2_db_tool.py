"""
v2_db_tool.py — перевірки БД V2 для встановлення й оновлення на місці. Лише stdlib; запуск: python -E -s -I v2_db_tool.py …
Код виходу 0 — PASS; будь-що інше — STOP. Перевірювані БД відкриваються лише для читання (mode=ro), крім:
джерела backup API, нового файлу restore і явного запису mark-synthetic.

  fingerprint <db>                            — відбиток синтетичних даних (детерміновані таблиці app.seed; без access_tokens)
  verify <db> --expect-version N              — integrity_check = ok, PRAGMA user_version = N (лише читання)
  user-version <db>                           — вид БД і PRAGMA user_version (лише читання; для щоденної копії після оновлень)
  backup <src> <dst> --expect-version N [--kind auth|integrity] [--strict]
                                              — копія через SQLite backup API → перевірка копії → тест відновлення
                                                (копія копії у тимчасовий підкаталог поруч із <dst>, відкриття, integrity_check,
                                                відбиток/рядки) → видалення; --strict — ще й строга схема копії
  restore <backup> <dst> --expect-version N [--sha256 HEX] [--kind auth|integrity] [--strict]
                                              — відновлення з перевіреної копії в НОВИЙ файл <dst> (не перезаписує):
                                                SHA256 копії → integrity/версія → backup API у тимчасовий файл поруч →
                                                перевірка рядків/відбитка → перейменування в <dst>
  users <auth_db>                             — кількість облікових записів V2 за ролями (без email)
  schema <db> --kind auth|integrity --expect-version N
                                              — строга read-only перевірка схеми проти SCHEMA_SPECS (нижче)
  auth-schema <auth_db> [--expect-version N]  — те саме для V2_AUTH_DB (за замовчуванням N=1, release dde86e6; A01–A13[+A14])
  integrity-schema <db> --expect-version N    — те саме для INTEGRITY_DB (I01–I13[+I14])
  ddl --kind auth|integrity --expect-version N — вивести очікуваний DDL (для синтетичних тестових БД і звірки)
  auth-ddl                                    — DDL V2_AUTH_DB версії 1 (сумісність)
  bind-check --kind K --expect-version N --release-backend <…\\backend> --release-manifest <BACKEND-SHA256.txt>
             [--release-py <python з залежностями backend>]
                                              — прив'язка очікувань до release-коду: SHA256 файлів-джерел схеми звіряються
                                                з МАНІФЕСТОМ релізу (не з константами в коді), а DDL коду — з SCHEMA_SPECS
  mark-synthetic <integrity_db> --auth-db <auth_db> (--reference-fingerprint HEX | --reference-db <db>)
                 [--marker <файл>] [--expect-version N] [--allow-role ROLE]
                                              — лише якщо БД синтетична за критеріями інсталятора (маркер свіжої БД,
                                                відбиток = еталону, у v2_auth лише адміністратори команди), записує
                                                instance_meta('dataset','synthetic'); інакше STOP без змін
"""
import ast
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

# =====================================================================================================================
# ТАБЛИЦЯ ОЧІКУВАНЬ СХЕМ (одне місце для звірки інтегратором після злиття backend)
#
#  ключ (вид, версія)   статус                                              джерело в release-коді (SHA — з маніфесту релізу)
#  ("integrity", 3)     release dde86e6, сервер TLSFIX5 (точний DDL)          backend/app/models.py + migrations.py
#  ("integrity", 4)     integration/main-final 2a3dae7: + recommendation_actions (точний DDL)
#  ("integrity", 5)     ОЧІКУВАННЯ за V2_HARDENING_CONTRACT.md §2 — замінити DDL на фактичний після злиття потоку даних:
#                         access_tokens.token → token_hash (VARCHAR(64) NOT NULL, UNIQUE), audit_events.actor_user_id
#                         INTEGER NULL (останньою колонкою), instance_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
#  ("auth", 1)          release dde86e6 (точний DDL = _SCHEMA v2_auth.py)     backend/app/v2_auth.py (_SCHEMA, AUTH_SCHEMA_VERSION)
#  ("auth", 2)          ОЧІКУВАННЯ за контрактом §2 — замінити DDL на фактичний після злиття потоку auth:
#                         v2_users.role CHECK (user, admin, data_officer); v2_role_changes(id, actor_user_id,
#                         target_user_id, old_role, new_role, changed_at) з тригерами append-only (UPDATE/DELETE заборонені)
#
#  Для кожної версії: ddl — повний очікуваний DDL; strict_sql — чи звіряти нормалізований текст CREATE (для таблиць, які
#  міграція змінює через ALTER TABLE ADD COLUMN, текст відрізняється від свіжого create_all — тоді лише структура);
#  forbidden — об'єкти, яких бути не може; contract — твердження контракту, які перевіряються незалежно від DDL (якщо
#  інтегратор замінить DDL, контракт однаково має виконуватися; функціональні — на копії БД у пам'яті).
#  bind-check звіряє ddl з фактичним кодом релізу (auth — _SCHEMA через ast; integrity — create_all release-коду).
# =====================================================================================================================

_INTEGRITY_TABLES_V3 = {
    "components": """CREATE TABLE components (
    id INTEGER NOT NULL,
    code VARCHAR(10) NOT NULL,
    name VARCHAR(200) NOT NULL,
    weight FLOAT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (code)
);""",
    "cycles": """CREATE TABLE cycles (
    id INTEGER NOT NULL,
    name VARCHAR(50) NOT NULL,
    start_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL,
    min_group_size INTEGER NOT NULL,
    PRIMARY KEY (id)
);""",
    "units": """CREATE TABLE units (
    id INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (name)
);""",
    "questions": """CREATE TABLE questions (
    id INTEGER NOT NULL,
    component_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    scale_min INTEGER NOT NULL,
    scale_max INTEGER NOT NULL,
    kind VARCHAR(20) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(component_id) REFERENCES components (id)
);""",
    "cycle_configs": """CREATE TABLE cycle_configs (
    cycle_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    scope VARCHAR(200) NOT NULL,
    categories_json TEXT NOT NULL,
    questionnaire_version VARCHAR(50) NOT NULL,
    end_date DATE,
    PRIMARY KEY (cycle_id),
    FOREIGN KEY(cycle_id) REFERENCES cycles (id)
);""",
    "response_sets": """CREATE TABLE response_sets (
    id INTEGER NOT NULL,
    cycle_id INTEGER NOT NULL,
    respondent_category VARCHAR(30) NOT NULL,
    unit VARCHAR(100) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(cycle_id) REFERENCES cycles (id),
    FOREIGN KEY(unit) REFERENCES units (name)
);""",
    "access_tokens": """CREATE TABLE access_tokens (
    id INTEGER NOT NULL,
    cycle_id INTEGER NOT NULL,
    token VARCHAR(64) NOT NULL,
    used BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(cycle_id) REFERENCES cycles (id),
    UNIQUE (token)
);""",
    "objective_indicators": """CREATE TABLE objective_indicators (
    id INTEGER NOT NULL,
    cycle_id INTEGER NOT NULL,
    component_id INTEGER NOT NULL,
    name VARCHAR(200) NOT NULL,
    value FLOAT NOT NULL,
    entered_by_role VARCHAR(50) NOT NULL,
    confirmed_by_role VARCHAR(50),
    confirmed BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(cycle_id) REFERENCES cycles (id),
    FOREIGN KEY(component_id) REFERENCES components (id)
);""",
    "recommendations": """CREATE TABLE recommendations (
    id INTEGER NOT NULL,
    cycle_id INTEGER NOT NULL,
    component_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    basis TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    owner_role VARCHAR(100),
    due_date DATE,
    PRIMARY KEY (id),
    FOREIGN KEY(cycle_id) REFERENCES cycles (id),
    FOREIGN KEY(component_id) REFERENCES components (id)
);""",
    "audit_events": """CREATE TABLE audit_events (
    id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    actor_role VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    assessment_id INTEGER,
    details TEXT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(assessment_id) REFERENCES cycles (id)
);""",
    "answers": """CREATE TABLE answers (
    id INTEGER NOT NULL,
    response_set_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    value INTEGER NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (response_set_id, question_id),
    FOREIGN KEY(response_set_id) REFERENCES response_sets (id),
    FOREIGN KEY(question_id) REFERENCES questions (id)
);""",
    "access_token_policies": """CREATE TABLE access_token_policies (
    token_id INTEGER NOT NULL,
    category VARCHAR(30) NOT NULL,
    expires_at DATETIME NOT NULL,
    PRIMARY KEY (token_id),
    FOREIGN KEY(token_id) REFERENCES access_tokens (id)
);""",
}

_INTEGRITY_TABLES_V4 = dict(_INTEGRITY_TABLES_V3, recommendation_actions="""CREATE TABLE recommendation_actions (
    id INTEGER NOT NULL,
    assessment_id INTEGER NOT NULL,
    recommendation_id VARCHAR(64) NOT NULL,
    rule_id VARCHAR(50) NOT NULL,
    component_code VARCHAR(10) NOT NULL,
    text TEXT NOT NULL,
    methodology_version VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    owner VARCHAR(120),
    due_date DATE,
    decision_reason TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    verified_in_assessment_id INTEGER,
    history_json TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (assessment_id, recommendation_id),
    FOREIGN KEY(assessment_id) REFERENCES cycles (id),
    FOREIGN KEY(verified_in_assessment_id) REFERENCES cycles (id)
);""")

# ОЧІКУВАННЯ (контракт §2) — замінити фактичним DDL потоку даних після злиття
_INTEGRITY_TABLES_V5 = dict(
    _INTEGRITY_TABLES_V4,
    access_tokens="""CREATE TABLE access_tokens (
    id INTEGER NOT NULL,
    cycle_id INTEGER NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    used BOOLEAN NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(cycle_id) REFERENCES cycles (id),
    UNIQUE (token_hash)
);""",
    audit_events="""CREATE TABLE audit_events (
    id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    actor_role VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    assessment_id INTEGER,
    details TEXT NOT NULL,
    actor_user_id INTEGER,
    PRIMARY KEY (id),
    FOREIGN KEY(assessment_id) REFERENCES cycles (id)
);""",
    instance_meta="""CREATE TABLE instance_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);""",
)

_AUTH_DDL_V1 = """
CREATE TABLE IF NOT EXISTS v2_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS v2_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    two_factor_verified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_v2_sessions_token ON v2_sessions(token_hash);
CREATE TABLE IF NOT EXISTS v2_user_attempts (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    assessment_id TEXT NOT NULL DEFAULT 'legacy',
    assessment_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'completed')),
    answers_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_v2_attempts_user ON v2_user_attempts(user_id, started_at DESC);
CREATE TABLE IF NOT EXISTS v2_challenges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('login_2fa', 'password_reset')),
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS v2_rate_limits (
    scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    window_started TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, subject)
);
"""

# ОЧІКУВАННЯ (контракт §2) — замінити фактичним _SCHEMA потоку auth після злиття (імена тригерів, NOT NULL, FK)
_AUTH_DDL_V2 = _AUTH_DDL_V1.replace(
    "role TEXT NOT NULL CHECK (role IN ('user', 'admin')),",
    "role TEXT NOT NULL CHECK (role IN ('user', 'admin', 'data_officer')),") + """CREATE TABLE IF NOT EXISTS v2_role_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER NOT NULL,
    target_user_id INTEGER NOT NULL,
    old_role TEXT NOT NULL,
    new_role TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS v2_role_changes_no_update BEFORE UPDATE ON v2_role_changes
BEGIN
    SELECT RAISE(ABORT, 'v2_role_changes is append-only');
END;
CREATE TRIGGER IF NOT EXISTS v2_role_changes_no_delete BEFORE DELETE ON v2_role_changes
BEGIN
    SELECT RAISE(ABORT, 'v2_role_changes is append-only');
END;
"""


def _join(tables):
    return "\n".join(tables.values()) + "\n"


SCHEMA_SPECS = {
    ("integrity", 3): {
        "status": "release dde86e6 (сервер TLSFIX5)", "ddl": _join(_INTEGRITY_TABLES_V3), "strict_sql": True,
        "source": {"files": ("backend/app/models.py", "backend/app/migrations.py"), "generator": "sqlalchemy",
                   "version_file": "backend/app/migrations.py", "version_symbol": "SCHEMA_VERSION"},
        "forbidden": (), "contract": (),
    },
    ("integrity", 4): {
        "status": "integration/main-final 2a3dae7 (Recommendations Tracker)", "ddl": _join(_INTEGRITY_TABLES_V4), "strict_sql": True,
        "source": {"files": ("backend/app/models.py", "backend/app/migrations.py"), "generator": "sqlalchemy",
                   "version_file": "backend/app/migrations.py", "version_symbol": "SCHEMA_VERSION"},
        "forbidden": (), "contract": (("table", "recommendation_actions"),),
    },
    ("integrity", 5): {
        "status": "ОЧІКУВАННЯ: посилення (контракт §2), звірити з DDL потоку даних", "ddl": _join(_INTEGRITY_TABLES_V5),
        "strict_sql": False,   # audit_events.actor_user_id додається ALTER TABLE → текст CREATE відрізняється від свіжого
        "source": {"files": ("backend/app/models.py", "backend/app/migrations.py"), "generator": "sqlalchemy",
                   "version_file": "backend/app/migrations.py", "version_symbol": "SCHEMA_VERSION"},
        "forbidden": (("column", "access_tokens", "token"),),
        "contract": (("table", "recommendation_actions"),
                     ("column", "access_tokens", "token_hash", {"notnull": 1}),
                     ("no_column", "access_tokens", "token"),
                     ("unique", "access_tokens", ("token_hash",)),
                     ("column", "audit_events", "actor_user_id", {"type": "INTEGER", "notnull": 0, "pk": 0}),
                     ("pk", "instance_meta", ("key",)),
                     ("column", "instance_meta", "value", {"notnull": 1}),
                     ("kv_insert", "instance_meta")),
    },
    ("auth", 1): {
        "status": "release dde86e6", "ddl": _AUTH_DDL_V1, "strict_sql": True,
        "source": {"files": ("backend/app/v2_auth.py",), "generator": "ast", "ddl_symbol": "_SCHEMA",
                   "version_file": "backend/app/v2_auth.py", "version_symbol": "AUTH_SCHEMA_VERSION"},
        "forbidden": (("table", "v2_dev_mail"),), "contract": (),
    },
    ("auth", 2): {
        "status": "ОЧІКУВАННЯ: ролі й журнал змін ролей (контракт §2), звірити з _SCHEMA потоку auth", "ddl": _AUTH_DDL_V2,
        "strict_sql": True,    # нормалізація прибирає лапки імен (перебудова таблиці + RENAME дає "v2_users")
        "source": {"files": ("backend/app/v2_auth.py",), "generator": "ast", "ddl_symbol": "_SCHEMA",
                   "version_file": "backend/app/v2_auth.py", "version_symbol": "AUTH_SCHEMA_VERSION"},
        "forbidden": (("table", "v2_dev_mail"),),
        "contract": (("roles", "v2_users", "role", ("user", "admin", "data_officer"), ("root", "")),
                     ("table", "v2_role_changes"),
                     ("columns", "v2_role_changes", ("id", "actor_user_id", "target_user_id", "old_role", "new_role", "changed_at")),
                     ("append_only", "v2_role_changes")),
    },
}

# Сумісність (installer dde86e6, test_v2_auth_schema.py): V2_AUTH_DB версії 1
RELEASE_AUTH_VERSION = 1
RELEASE_AUTH_TABLES = ("v2_users", "v2_sessions", "v2_user_attempts", "v2_challenges", "v2_rate_limits")
RELEASE_AUTH_DDL = _AUTH_DDL_V1

# Таблиці, які app.seed заповнює детерміновано (random.seed(2026)); access_tokens — випадкові коди, тому поза відбитком
SEED_TABLES = ("answers", "components", "cycles", "objective_indicators", "questions", "recommendations", "response_sets", "units")
SIDECARS = ("-journal", "-wal", "-shm")


def ro(path):
    if not os.path.isfile(path):
        sys.exit(f"STOP: немає файлу {path}")
    return closing(sqlite3.connect(Path(os.path.abspath(path)).as_uri() + "?mode=ro", uri=True))   # закривається після with


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(con):
    h = hashlib.sha256()
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in SEED_TABLES:
        if t not in tables:
            sys.exit(f"STOP: немає таблиці {t}")
        n = 0
        h.update(t.encode())
        for row in con.execute(f'SELECT * FROM "{t}" ORDER BY rowid'):
            h.update(repr(row).encode()); n += 1
        h.update(str(n).encode())
    return h.hexdigest()


def counts(con):
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def check(con, expect_version, label):
    ic = con.execute("PRAGMA integrity_check").fetchone()[0]
    uv = con.execute("PRAGMA user_version").fetchone()[0]
    if ic != "ok" or uv != expect_version:
        sys.exit(f"STOP: {label}: integrity_check={ic}, user_version={uv} (очікується ok/{expect_version})")
    return ic, uv


def detect_kind(con):
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "v2_users" in tables:
        return "auth"
    if all(t in tables for t in SEED_TABLES):
        return "integrity"
    return None


def opt(argv, name, default=None):
    if name not in argv:
        return default
    i = argv.index(name)
    if i + 1 >= len(argv):
        sys.exit(f"STOP: {name} без значення")
    return argv[i + 1]


def opt_int(argv, name, default=None):
    v = opt(argv, name)
    if v is None:
        return default
    if not re.fullmatch(r"[0-9]{1,4}", v):
        sys.exit(f"STOP: {name} має бути цілим числом")
    return int(v)


def arg_version(argv):
    v = opt_int(argv, "--expect-version")
    if v is None:
        sys.exit("STOP: потрібен --expect-version")
    return v


def arg_kind(argv, required=False):
    k = opt(argv, "--kind")
    if k is None and required:
        sys.exit("STOP: потрібен --kind auth|integrity")
    if k is not None and k not in ("auth", "integrity"):
        sys.exit("STOP: --kind має бути auth або integrity")
    return k


def spec_for(kind, version):
    spec = SCHEMA_SPECS.get((kind, version))
    if spec is None:
        known = ", ".join(f"{k}/{v}" for k, v in sorted(SCHEMA_SPECS))
        sys.exit(f"STOP: немає очікувань схеми {kind} версії {version} (відомі: {known})")
    return spec


# ---------------------------------------------------------------------------------------------------------------------
# Каталог схеми і порівняння з еталоном (еталон будується в пам'яті з DDL SCHEMA_SPECS; перевірювана БД — лише read-only)
# ---------------------------------------------------------------------------------------------------------------------
def _norm_sql(sql):
    s = " ".join((sql or "").replace('"', "").split())
    return re.sub(r"(?i)\bIF NOT EXISTS\b ?", "", s)


def _checks(sql):
    out, s, i = [], " ".join((sql or "").split()), 0
    u = s.upper()
    while True:
        i = u.find("CHECK", i)
        if i < 0:
            return sorted(out)
        j = s.find("(", i)
        if j < 0:
            return sorted(out)
        depth, k = 0, j
        while k < len(s):
            depth += {"(": 1, ")": -1}.get(s[k], 0)
            if depth == 0:
                break
            k += 1
        out.append("".join(s[j:k + 1].split())); i = k


def _catalog(con):
    objs = sorted((r[0], r[1], r[2], _norm_sql(r[3])) for r in con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
    tables = sorted(r[1] for r in objs if r[0] == "table")
    cols, fks, idx, chk, uniq = {}, {}, {}, {}, {}
    for t in tables:
        cols[t] = [tuple(r[1:6]) + (r[6],) for r in con.execute(f'PRAGMA table_xinfo("{t}")')]
        fks[t] = sorted(tuple(r[2:8]) for r in con.execute(f'PRAGMA foreign_key_list("{t}")'))
        il = sorted((r[1], r[2], r[3], r[4]) for r in con.execute(f'PRAGMA index_list("{t}")'))
        idx[t] = {(n, u, o, p): [tuple(x) for x in con.execute(f'PRAGMA index_xinfo("{n}")')] for n, u, o, p in il}
        uniq[t] = sorted((tuple(x[2] for x in v if x[5]), tuple(x[4] for x in v if x[5])) for k, v in idx[t].items() if k[1] == 1)
        chk[t] = _checks(next((o[3] for o in objs if o[0] == "table" and o[1] == t), ""))
    return {"objs": objs, "tables": tables, "cols": cols, "fks": fks, "idx": idx, "chk": chk, "uniq": uniq}


def _ref_catalog(ddl):
    ref = sqlite3.connect(":memory:")
    try:
        ref.executescript(ddl)
        return _catalog(ref)
    finally:
        ref.close()


def _dummy(coltype, name, n):
    t = (coltype or "").upper()
    if "INT" in t or "BOOL" in t:
        return n
    if "FLOAT" in t or "REAL" in t or "DOUB" in t:
        return float(n)
    return f"{name}-{n}"


def _insert_generic(mem, table, n, override=None):
    cols = [r for r in mem.execute(f'PRAGMA table_xinfo("{table}")') if r[6] == 0]
    names, vals = [], []
    for cid, name, ctype, notnull, default, pk, hidden in cols:
        if override and name in override:
            names.append(name); vals.append(override[name]); continue
        if pk and "INT" in (ctype or "").upper():
            continue
        if notnull and default is None or pk:
            names.append(name)
            vals.append("user" if "role" in name.lower() else _dummy(ctype, name, n))
    ph = ", ".join("?" for _ in vals)
    mem.execute(f'INSERT INTO "{table}" ({", ".join(chr(34) + x + chr(34) for x in names)}) VALUES ({ph})', vals)


def _contract(con, cat, assertions):
    """Твердження контракту. Функціональні — лише на копії в пам'яті (файл не змінюється)."""
    bad = []
    mem = None
    try:
        for a in assertions:
            kind, t = a[0], a[1]
            if kind == "table":
                if t not in cat["tables"]:
                    bad.append(f"немає таблиці {t}")
            elif kind == "columns":
                got = [c[0] for c in cat["cols"].get(t, [])]
                if got != list(a[2]):
                    bad.append(f"{t}: колонки {got} ≠ {list(a[2])}")
            elif kind in ("column", "no_column"):
                col = next((c for c in cat["cols"].get(t, []) if c[0] == a[2]), None)
                if kind == "no_column":
                    if col is not None:
                        bad.append(f"{t}.{a[2]} має бути відсутня")
                    continue
                if col is None:
                    bad.append(f"немає {t}.{a[2]}"); continue
                want = a[3]
                if "type" in want and (col[1] or "").upper() != want["type"]:
                    bad.append(f"{t}.{a[2]}: тип {col[1]} ≠ {want['type']}")
                if "notnull" in want and col[2] != want["notnull"]:
                    bad.append(f"{t}.{a[2]}: NOT NULL={col[2]} ≠ {want['notnull']}")
                if "pk" in want and (col[4] > 0) != bool(want["pk"]):
                    bad.append(f"{t}.{a[2]}: PK={col[4]}")
            elif kind == "unique":
                if not any(u[0] == tuple(a[2]) for u in cat["uniq"].get(t, [])):
                    bad.append(f"{t}: немає UNIQUE {a[2]}")
            elif kind == "pk":
                pk = [c[0] for c in sorted(cat["cols"].get(t, []), key=lambda c: c[4]) if c[4] > 0]
                if pk != list(a[2]):
                    bad.append(f"{t}: PK {pk} ≠ {list(a[2])}")
            elif kind in ("roles", "append_only", "kv_insert"):
                if mem is None:
                    mem = sqlite3.connect(":memory:")
                    con.backup(mem)
                    mem.execute("PRAGMA foreign_keys = OFF")
                if t not in cat["tables"]:
                    bad.append(f"немає таблиці {t}"); continue
                if kind == "roles":
                    for i, role in enumerate(a[3]):
                        try:
                            _insert_generic(mem, t, 900000 + i, {a[2]: role})
                        except sqlite3.Error as e:
                            bad.append(f"{t}.{a[2]}='{role}' відхилено ({e})")
                    for i, role in enumerate(a[4]):
                        try:
                            _insert_generic(mem, t, 910000 + i, {a[2]: role})
                            bad.append(f"{t}.{a[2]}='{role}' прийнято (CHECK ролей ширший за контракт)")
                        except sqlite3.IntegrityError:
                            pass
                elif kind == "append_only":
                    try:
                        _insert_generic(mem, t, 920000)
                    except sqlite3.Error as e:
                        bad.append(f"{t}: INSERT неможливий ({e})"); continue
                    col = next(c[0] for c in cat["cols"][t] if c[4] == 0)
                    for op, sql in (("UPDATE", f'UPDATE "{t}" SET "{col}" = "{col}"'), ("DELETE", f'DELETE FROM "{t}"')):
                        try:
                            mem.execute(sql)
                            bad.append(f"{t}: {op} дозволено (немає append-only тригера)")
                        except sqlite3.DatabaseError:
                            pass
                elif kind == "kv_insert":
                    try:
                        mem.execute(f'INSERT INTO "{t}" (key, value) VALUES (?, ?)', ("__contract_probe__", "x"))
                    except sqlite3.Error as e:
                        bad.append(f"{t}: INSERT (key, value) неможливий ({e})"); continue
                    try:
                        mem.execute(f'INSERT INTO "{t}" (key, value) VALUES (?, ?)', ("__contract_probe__", "y"))
                        bad.append(f"{t}: дубль key прийнято (немає PRIMARY KEY)")
                    except sqlite3.IntegrityError:
                        pass
                    try:
                        mem.execute(f'INSERT INTO "{t}" (key, value) VALUES (?, NULL)', ("__contract_probe2__",))
                        bad.append(f"{t}: value NULL прийнято")
                    except sqlite3.IntegrityError:
                        pass
            else:
                bad.append(f"невідоме твердження {kind}")
    finally:
        if mem is not None:
            mem.close()
    return bad


def schema_checks(path, kind, version):
    """Повертає [(id, ok, деталі)]. Будь-яке ok=False → STOP. Файл лише читається."""
    spec = spec_for(kind, version)
    px = "A" if kind == "auth" else "I"
    res = []
    add = lambda i, ok, d: res.append((f"{px}{i:02d}", bool(ok), d))
    p = os.path.abspath(path)
    if not os.path.lexists(p) or not os.path.isfile(p) or os.path.islink(p):
        add(1, False, f"немає звичайного файлу {p}")
        return res
    try:
        con = sqlite3.connect(Path(p).as_uri() + "?mode=ro", uri=True, timeout=1)
    except sqlite3.Error as e:
        add(1, False, f"read-only відкриття неможливе: {e}")
        return res
    try:
        try:
            con.execute("PRAGMA query_only = 1")
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.Error as e:
            add(1, False, f"read-only читання неможливе: {e}")
            return res
        add(1, True, "файл відкрито лише read-only (mode=ro, query_only)")
        try:
            uv = con.execute("PRAGMA user_version").fetchone()[0]
            ic = [r[0] for r in con.execute("PRAGMA integrity_check")]
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            cat = _catalog(con)
        except sqlite3.Error as e:
            add(3, False, f"помилка читання схеми/даних: {e}")
            return res
        ref = _ref_catalog(spec["ddl"])
        want_tables = [t for t in ref["tables"] if not t.startswith("sqlite_")]
        add(2, uv == version, f"user_version={uv}, потрібно {version}")
        add(3, ic == ["ok"], f"integrity_check={'; '.join(ic[:3])}")
        add(4, not fk, f"порушень foreign_key_check: {len(fk)}")
        miss = [t for t in want_tables if t not in cat["tables"]]
        add(5, not miss, f"відсутні таблиці: {', '.join(miss) or 'немає'}")
        bad = [t for t in want_tables if t in cat["tables"] and cat["cols"][t] != ref["cols"][t]]
        add(6, not bad, f"колонки (назва, тип, NOT NULL, default, PK, порядок) — розбіжності: {', '.join(bad) or 'немає'}")
        bad = [t for t in want_tables if t in cat["tables"] and cat["uniq"][t] != ref["uniq"][t]]
        add(7, not bad, f"UNIQUE (склад колонок, COLLATE) — розбіжності: {', '.join(bad) or 'немає'}")
        bad = [t for t in want_tables if t in cat["tables"] and cat["fks"][t] != ref["fks"][t]]
        add(8, not bad, f"зовнішні ключі / ON DELETE — розбіжності: {', '.join(bad) or 'немає'}")
        bad = [t for t in want_tables if t in cat["tables"] and cat["idx"][t] != ref["idx"][t]]
        add(9, not bad, f"індекси (склад, порядок, DESC, collation, UNIQUE) — розбіжності: {', '.join(bad) or 'немає'}")
        bad = [t for t in want_tables if t in cat["tables"] and cat["chk"][t] != ref["chk"][t]]
        add(10, not bad, f"CHECK — розбіжності: {', '.join(bad) or 'немає'}")
        hit = []
        for f in spec["forbidden"]:
            if f[0] == "table" and f[1] in cat["tables"]:
                hit.append(f"таблиця {f[1]}")
            if f[0] == "column" and any(c[0] == f[2] for c in cat["cols"].get(f[1], [])):
                hit.append(f"колонка {f[1]}.{f[2]}")
        add(11, not hit, f"заборонені об'єкти: {', '.join(hit) or 'немає'}" + (" (v2_dev_mail лише development)" if hit and kind == "auth" else ""))
        want = {o[:3] for o in ref["objs"]}; got = {o[:3] for o in cat["objs"]}
        extra = sorted(got - want); lack = sorted(want - got)
        add(12, not extra and not lack, f"сторонні об'єкти: {extra or 'немає'}; відсутні: {lack or 'немає'}")
        if spec["strict_sql"]:
            refsql = {o[:3]: o[3] for o in ref["objs"]}
            diff = sorted(o[1] for o in cat["objs"] if o[:3] in refsql and o[3] != refsql[o[:3]])
            add(13, not diff, f"нормалізований DDL — розбіжності: {', '.join(diff) or 'немає'}")
        else:
            add(13, True, "нормалізований текст DDL не порівнюється (strict_sql=False); структуру звірено перевірками 05–12")
        if spec["contract"]:
            bad = _contract(con, cat, spec["contract"])
            add(14, not bad, f"контракт ({len(spec['contract'])} тверджень, функціональні — на копії в пам'яті): {'; '.join(bad) or 'виконано'}")
    finally:
        con.close()
    return res


def run_schema(path, kind, version):
    res = schema_checks(path, kind, version)
    for i, ok, d in res:
        print(f"{i} {'PASS' if ok else 'FAIL'} {d}")
    need = 13 + (1 if spec_for(kind, version)["contract"] else 0)
    bad = [i for i, ok, _ in res if not ok]
    label = "auth-schema" if kind == "auth" else "integrity-schema"
    if bad or len(res) < need:
        sys.exit(f"STOP: {label}: FAIL {', '.join(bad) or 'неповна перевірка'} — {path}")
    tag = "release=dde86e6" if (kind, version) == ("auth", 1) else f"version={version}"
    return f"{'AUTH' if kind == 'auth' else 'INTEGRITY'} SCHEMA OK {tag} checks={len(res)}"


# ---------------------------------------------------------------------------------------------------------------------
# backup / restore
# ---------------------------------------------------------------------------------------------------------------------
def _state(con, kind):
    c = counts(con)
    fp = fingerprint(con) if kind == "integrity" else None
    return c, fp


def cmd_backup(argv):
    if len(argv) < 3:
        sys.exit("STOP: backup <src> <dst> --expect-version N")
    src, dst, v = argv[1], argv[2], arg_version(argv)
    kind = arg_kind(argv)
    if os.path.lexists(dst) or any(os.path.lexists(dst + s) for s in SIDECARS):
        sys.exit(f"STOP: {dst} уже існує")
    with ro(src) as s:
        check(s, v, "джерело")
        kind = kind or detect_kind(s)
        src_counts, src_fp = _state(s, kind)
        d = sqlite3.connect(dst)
        try:
            s.backup(d)
        finally:
            d.close()
    with ro(dst) as c:
        check(c, v, "копія")
        if counts(c) != src_counts:
            sys.exit("STOP: кількість рядків копії ≠ джерелу")
    strict = ""
    if "--strict" in argv:
        if not kind:
            sys.exit("STOP: --strict потребує --kind або розпізнаваної БД")
        print(run_schema(dst, kind, v))
        strict = "schema=strict "
    tmp = tempfile.mkdtemp(prefix="v2-restore-test-", dir=os.path.dirname(os.path.abspath(dst)))
    try:
        r = os.path.join(tmp, "restore.db")
        shutil.copyfile(dst, r)
        with ro(r) as c:
            check(c, v, "тест відновлення")
            if counts(c) != src_counts or (src_fp and fingerprint(c) != src_fp):
                sys.exit("STOP: тест відновлення: дані ≠ джерелу")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if os.path.exists(tmp):
        sys.exit(f"STOP: тимчасовий каталог тесту відновлення не видалено: {tmp}")
    print(f"BACKUP OK user_version={v} rows={sum(src_counts.values())} {strict}restore-test=ok sha256={sha256_file(dst)}")


def cmd_restore(argv):
    if len(argv) < 3:
        sys.exit("STOP: restore <backup> <dst> --expect-version N [--sha256 HEX]")
    src, dst, v = argv[1], argv[2], arg_version(argv)
    kind = arg_kind(argv)
    want_sha = opt(argv, "--sha256")
    if want_sha is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", want_sha):
        sys.exit("STOP: --sha256 має бути 64 hex")
    if os.path.abspath(src) == os.path.abspath(dst):
        sys.exit("STOP: копія і ціль збігаються")
    if os.path.lexists(dst) or any(os.path.lexists(dst + s) for s in SIDECARS):
        sys.exit(f"STOP: ціль {dst} (або її -journal/-wal/-shm) уже існує — відновлення лише в новий файл")
    if not os.path.isdir(os.path.dirname(os.path.abspath(dst))):
        sys.exit(f"STOP: немає каталогу цілі {os.path.dirname(dst)}")
    if want_sha and sha256_file(src) != want_sha.lower():
        sys.exit("STOP: SHA256 резервної копії ≠ очікуваному")
    with ro(src) as s:
        check(s, v, "резервна копія")
        kind = kind or detect_kind(s)
        src_counts, src_fp = _state(s, kind)
        fd, tmp = tempfile.mkstemp(prefix=".v2-restore-", suffix=".db", dir=os.path.dirname(os.path.abspath(dst)))
        os.close(fd)
        os.remove(tmp)
        d = sqlite3.connect(tmp)
        try:
            s.backup(d)
        finally:
            d.close()
    try:
        for s in SIDECARS:
            if os.path.lexists(tmp + s):
                os.remove(tmp + s)
        with ro(tmp) as c:
            check(c, v, "відновлений файл")
            got_counts, got_fp = _state(c, kind)
            if got_counts != src_counts or got_fp != src_fp:
                sys.exit("STOP: відновлений файл: дані ≠ резервній копії")
        if "--strict" in argv:
            if not kind:
                sys.exit("STOP: --strict потребує --kind або розпізнаваної БД")
            print(run_schema(tmp, kind, v))
        os.rename(tmp, dst)                       # Windows: не перезаписує наявний файл
    finally:
        if os.path.lexists(tmp):
            os.remove(tmp)
    with ro(dst) as c:
        check(c, v, "ціль після перейменування")
    print(f"RESTORE OK user_version={v} rows={sum(src_counts.values())} sha256={sha256_file(dst)}")


# ---------------------------------------------------------------------------------------------------------------------
# mark-synthetic — ті самі критерії, що й інсталятор (V2-install-common.ps1, Assert-V2SyntheticDb)
# ---------------------------------------------------------------------------------------------------------------------
def users_line(auth_db):
    with ro(auth_db) as con:
        rows = con.execute("SELECT role, COUNT(*) FROM v2_users GROUP BY role ORDER BY role").fetchall()
    return rows, "USERS " + " ".join(f"{r}={n}" for r, n in rows)


def cmd_mark_synthetic(argv):
    if len(argv) < 2:
        sys.exit("STOP: mark-synthetic <integrity_db> --auth-db <auth_db> (--reference-fingerprint HEX | --reference-db <db>)")
    db = argv[1]
    auth_db = opt(argv, "--auth-db")
    if not auth_db:
        sys.exit("STOP: потрібен --auth-db")
    v = opt_int(argv, "--expect-version", 5)
    ref_fp = opt(argv, "--reference-fingerprint")
    ref_db = opt(argv, "--reference-db")
    if bool(ref_fp) == bool(ref_db):
        sys.exit("STOP: потрібен рівно один із --reference-fingerprint / --reference-db")
    if ref_db:
        with ro(ref_db) as c:
            ref_fp = fingerprint(c)
    if not re.fullmatch(r"[0-9a-f]{64}", ref_fp or ""):
        sys.exit("STOP: еталонний відбиток має бути 64 hex (нижній регістр)")
    marker = opt(argv, "--marker", os.path.join(os.path.dirname(os.path.abspath(db)), "CREATED-BY-V2-INSTALL.txt"))
    allowed = {"admin"} | {argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--allow-role"}
    if not allowed <= {"admin", "data_officer"}:
        sys.exit("STOP: --allow-role дозволяє лише data_officer")
    # 1. маркер свіжої синтетичної БД (створює лише інсталятор у порожньому data\)
    if not os.path.isfile(marker) or os.path.islink(marker):
        sys.exit(f"STOP: немає маркера свіжої синтетичної БД {marker} — позначка synthetic заборонена")
    # 2. лише адміністратори команди (самореєстрація створює user)
    rows, line = users_line(auth_db)
    roles = {r for r, _ in rows}
    if not rows or not roles <= allowed or "admin" not in roles:
        sys.exit(f"STOP: у v2_auth є не лише адміністратори команди ({line}) — позначка synthetic заборонена")
    # 3. відбиток і схема (read-only)
    with ro(db) as c:
        check(c, v, "INTEGRITY_DB")
        if "instance_meta" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            sys.exit("STOP: немає таблиці instance_meta (потрібна схема з контракту)")
        fp = fingerprint(c)
        cur = c.execute("SELECT value FROM instance_meta WHERE key='dataset'").fetchone()
    if fp != ref_fp:
        sys.exit(f"STOP: відбиток БД {fp} ≠ еталону {ref_fp} — дані не є чистим seed, позначка synthetic заборонена")
    if cur is not None:
        if cur[0] == "synthetic":
            print(f"MARK-SYNTHETIC OK dataset=synthetic (уже встановлено) fingerprint={fp} {line}")
            return
        sys.exit(f"STOP: instance_meta.dataset уже має інше значення — без змін")
    # 4. запис в одній транзакції з повторною перевіркою відбитка (без TOCTOU)
    con = sqlite3.connect(os.path.abspath(db), timeout=5, isolation_level=None)
    try:
        con.execute("PRAGMA busy_timeout = 5000")
        con.execute("BEGIN IMMEDIATE")
        try:
            if fingerprint(con) != ref_fp or con.execute("PRAGMA user_version").fetchone()[0] != v:
                raise RuntimeError("дані змінилися під час позначки")
            con.execute("INSERT INTO instance_meta (key, value) VALUES ('dataset', 'synthetic')")
            con.execute("COMMIT")
        except BaseException as e:
            con.execute("ROLLBACK")
            sys.exit(f"STOP: позначку не записано: {e}")
    finally:
        con.close()
    with ro(db) as c:
        check(c, v, "INTEGRITY_DB після позначки")
        if c.execute("SELECT value FROM instance_meta WHERE key='dataset'").fetchone() != ("synthetic",):
            sys.exit("STOP: позначку не підтверджено читанням")
    print(f"MARK-SYNTHETIC OK dataset=synthetic fingerprint={fp} {line}")


# ---------------------------------------------------------------------------------------------------------------------
# bind-check — SHA файлів-джерел з маніфесту релізу + DDL коду = SCHEMA_SPECS
# ---------------------------------------------------------------------------------------------------------------------
def read_manifest(path):
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.fullmatch(r"([0-9a-fA-F]{64}) [ *]?(\S.*)", line)
            if not m:
                sys.exit(f"STOP: маніфест {path}: некоректний рядок {n}")
            rel = m.group(2).strip().replace("\\", "/")
            if rel.startswith("/") or ".." in rel.split("/") or rel in out:
                sys.exit(f"STOP: маніфест {path}: недопустимий або повторний шлях у рядку {n}")
            out[rel] = m.group(1).lower()
    return out


def _source_path(release_backend, rel):
    if not rel.startswith("backend/"):
        sys.exit(f"STOP: шлях джерела має починатися з backend/: {rel}")
    return os.path.join(release_backend, *rel.split("/")[1:])


_GEN_INTEGRITY = r"""
import os, sqlite3, sys, importlib
backend, db = sys.argv[1], sys.argv[2]
os.environ["INTEGRITY_DB"] = db
os.environ["APP_ENV"] = "development"
sys.path.insert(0, backend)
from app.database import Base, engine
importlib.import_module("app.models")
mig = importlib.import_module("app.migrations")
Base.metadata.create_all(engine)
engine.dispose()
print(mig.SCHEMA_VERSION)
"""


def cmd_bind_check(argv):
    kind, v = arg_kind(argv, required=True), arg_version(argv)
    spec = spec_for(kind, v)
    backend, manifest = opt(argv, "--release-backend"), opt(argv, "--release-manifest")
    if not backend or not manifest:
        sys.exit("STOP: потрібні --release-backend і --release-manifest")
    man = read_manifest(manifest)
    src = spec["source"]
    shas = []
    for rel in src["files"]:
        if rel not in man:
            sys.exit(f"STOP: B01: у маніфесті релізу немає {rel}")
        got = sha256_file(_source_path(backend, rel))
        if got != man[rel]:
            sys.exit(f"STOP: B01: SHA256 {rel} = {got} ≠ маніфесту {man[rel]}")
        shas.append(f"{rel.rsplit('/', 1)[-1]}={got[:16]}…")
    print(f"B01 PASS SHA256 джерел схеми = маніфест релізу: {', '.join(shas)}")
    if src["generator"] == "ast":
        raw = open(_source_path(backend, src["version_file"]), "rb").read()
        tree = ast.parse(raw.decode("utf-8"))
        sym = lambda name: next((n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                                 and any(getattr(t, "id", "") == name for t in n.targets)), None)
        ver, ddl = sym(src["version_symbol"]), sym(src["ddl_symbol"])
        if ddl is None:
            sys.exit(f"STOP: B02: у {src['version_file']} немає {src['ddl_symbol']}")
        got_cat = _ref_catalog(ddl)
    else:
        py = opt(argv, "--release-py")
        if not py:
            print("B02 NOT RUN DDL integrity потребує --release-py (python із SQLAlchemy release)")
            sys.exit(3)
        tmp = tempfile.mkdtemp(prefix="v2-bind-")
        try:
            db = os.path.join(tmp, "ref.db")
            r = subprocess.run([py, "-I", "-B", "-c", _GEN_INTEGRITY, os.path.abspath(backend), db], capture_output=True, timeout=300)
            if r.returncode != 0:
                sys.exit(f"STOP: B02: create_all release-коду не виконано: {r.stderr.decode('utf-8', 'replace')[-400:]}")
            ver = int(r.stdout.decode().strip().splitlines()[-1])
            with closing(sqlite3.connect(db)) as c:
                got_cat = _catalog(c)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if ver != v:
        sys.exit(f"STOP: B02: версія схеми в коді {ver} ≠ {v}")
    print(f"B02 PASS версія схеми в коді = {v}")
    ref = _ref_catalog(spec["ddl"])
    diff = [k for k in ("tables", "cols", "uniq", "fks", "idx", "chk") if got_cat[k] != ref[k]]
    if {o[:3] for o in got_cat["objs"]} != {o[:3] for o in ref["objs"]}:
        diff.append("objs")
    if spec["strict_sql"] and {o[:3]: o[3] for o in got_cat["objs"]} != {o[:3]: o[3] for o in ref["objs"]}:
        diff.append("sql")
    if diff:
        detail = []
        for k in diff:
            if k in ("cols", "uniq", "fks", "idx", "chk"):
                detail += [f"{k}:{t}" for t in sorted(set(got_cat[k]) | set(ref[k])) if got_cat[k].get(t) != ref[k].get(t)]
            else:
                detail.append(k)
        sys.exit(f"STOP: B03: DDL release-коду ≠ SCHEMA_SPECS[{kind},{v}]: {', '.join(detail)} — оновіть таблицю очікувань")
    print(f"B03 PASS DDL release-коду = SCHEMA_SPECS[{kind},{v}] ({spec['status']})")
    print(f"BIND OK kind={kind} version={v}")


def main(argv):
    for st in (sys.stdout, sys.stderr):                  # installer читає UTF-8 (Invoke-V2Native -Utf8); -I ігнорує PYTHONIOENCODING
        st.reconfigure(encoding="utf-8", errors="backslashreplace")
    if not argv or (len(argv) < 2 and argv[0] not in ("auth-ddl", "specs")):
        sys.exit(__doc__)
    cmd = argv[0]
    if cmd == "fingerprint":
        with ro(argv[1]) as con:
            print(fingerprint(con))
    elif cmd == "verify":
        v = arg_version(argv)
        with ro(argv[1]) as con:
            check(con, v, argv[1])
            print(f"VERIFY OK user_version={v} rows={sum(counts(con).values())}")
    elif cmd == "user-version":
        with ro(argv[1]) as con:
            print(f"USER-VERSION kind={detect_kind(con) or 'unknown'} user_version={con.execute('PRAGMA user_version').fetchone()[0]}"
                  f" spec={'yes' if (detect_kind(con), con.execute('PRAGMA user_version').fetchone()[0]) in SCHEMA_SPECS else 'no'}")
    elif cmd == "backup":
        cmd_backup(argv)
    elif cmd == "restore":
        cmd_restore(argv)
    elif cmd == "users":
        print(users_line(argv[1])[1])
    elif cmd == "auth-schema":
        print(run_schema(argv[1], "auth", opt_int(argv, "--expect-version", RELEASE_AUTH_VERSION)))
    elif cmd == "integrity-schema":
        print(run_schema(argv[1], "integrity", arg_version(argv)))
    elif cmd == "schema":
        print(run_schema(argv[1], arg_kind(argv, required=True), arg_version(argv)))
    elif cmd == "ddl":
        sys.stdout.write(spec_for(arg_kind(argv, required=True), arg_version(argv))["ddl"])
    elif cmd == "auth-ddl":
        sys.stdout.write(RELEASE_AUTH_DDL)
    elif cmd == "bind-check":
        cmd_bind_check(argv)
    elif cmd == "mark-synthetic":
        cmd_mark_synthetic(argv)
    elif cmd == "specs":
        print(json.dumps({f"{k}/{v}": {"status": s["status"], "strict_sql": s["strict_sql"], "contract": len(s["contract"])}
                          for (k, v), s in sorted(SCHEMA_SPECS.items())}, ensure_ascii=False))
    else:
        sys.exit(f"STOP: невідома команда {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
