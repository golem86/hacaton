"""
v2_db_tool.py — перевірки БД V2 для встановлення (INSTALLATION PLAN REV2). Лише stdlib; запуск: python -E -s -I v2_db_tool.py …
Код виходу 0 — PASS; будь-що інше — STOP. Вихідні БД відкриваються лише для читання (mode=ro), крім джерела backup API.

  fingerprint <db>                         — відбиток синтетичних даних (детерміновані таблиці app.seed; без access_tokens)
  verify <db> --expect-version N           — integrity_check = ok, PRAGMA user_version = N (лише читання)
  backup <src> <dst> --expect-version N    — копія через SQLite backup API → перевірка копії → тест відновлення
                                             (копія копії у тимчасовий каталог, відкриття, integrity_check, відбиток/рядки) → видалення
  users <auth_db>                          — кількість облікових записів V2 за ролями (без email)
  auth-schema <auth_db>                    — строга read-only перевірка V2_AUTH_DB проти release-схеми dde86e6 (A01–A13)
  auth-ddl                                 — вивести закріплений release-DDL V2_AUTH_DB (для синтетичних тестових БД)
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

# Таблиці, які app.seed заповнює детерміновано (random.seed(2026)); access_tokens — випадкові коди, тому поза відбитком
SEED_TABLES = ("answers", "components", "cycles", "objective_indicators", "questions", "recommendations", "response_sets", "units")


def ro(path):
    if not os.path.isfile(path):
        sys.exit(f"STOP: немає файлу {path}")
    return closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True))   # закривається після with (Windows)


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


def arg_version(argv):
    if "--expect-version" not in argv:
        sys.exit("STOP: потрібен --expect-version")
    return int(argv[argv.index("--expect-version") + 1])


# ---------------------------------------------------------------------------------------------------------------------
# Строга перевірка V2_AUTH_DB (етап 1, A01–A13) — прив'язана до release dde86e6.
# DDL нижче — дослівна копія _SCHEMA з integrity-v2-dde86e6/backend/app/v2_auth.py
# (SHA256 файлу cbb529ce0140385e7867bc12e6048614c59fa7fdfb22bc65b70e0626ada92086; відповідність перевіряє тест A00).
# Еталон будується в пам'яті з цього DDL; перевірювана БД відкривається лише read-only і порівнюється з еталоном.
# Легітимна release-БД — лише «чиста» (migrate_auth_db → executescript(_SCHEMA)); БД, мігрована з прототипу v0
# (ALTER TABLE …), має інший DDL і порядок колонок → STOP (для нового встановлення V2 такої БД не існує).
# ---------------------------------------------------------------------------------------------------------------------
RELEASE_AUTH_SOURCE_SHA256 = "cbb529ce0140385e7867bc12e6048614c59fa7fdfb22bc65b70e0626ada92086"
RELEASE_AUTH_VERSION = 1
RELEASE_AUTH_TABLES = ("v2_users", "v2_sessions", "v2_user_attempts", "v2_challenges", "v2_rate_limits")
RELEASE_AUTH_DDL = """
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


def _norm_sql(sql):
    return " ".join((sql or "").split())


def _checks(sql):
    out, s, i = [], _norm_sql(sql), 0
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
        out.append(s[j:k + 1]); i = k


def _catalog(con):
    objs = sorted((r[0], r[1], r[2], _norm_sql(r[3])) for r in con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
    tables = sorted(r[1] for r in objs if r[0] == "table")
    cols, fks, idx, chk = {}, {}, {}, {}
    for t in tables:
        cols[t] = [tuple(r[1:6]) + (r[6],) for r in con.execute(f'PRAGMA table_xinfo("{t}")')]
        fks[t] = sorted(tuple(r[2:8]) for r in con.execute(f'PRAGMA foreign_key_list("{t}")'))
        il = sorted((r[1], r[2], r[3], r[4]) for r in con.execute(f'PRAGMA index_list("{t}")'))
        idx[t] = {(n, u, o, p): [tuple(x) for x in con.execute(f'PRAGMA index_xinfo("{n}")')] for n, u, o, p in il}
        chk[t] = _checks(next((o[3] for o in objs if o[0] == "table" and o[1] == t), ""))
    return {"objs": objs, "tables": tables, "cols": cols, "fks": fks, "idx": idx, "chk": chk}


def _release_catalog():
    ref = sqlite3.connect(":memory:")
    try:
        ref.executescript(RELEASE_AUTH_DDL)
        return _catalog(ref)
    finally:
        ref.close()


def auth_schema_checks(path):
    """Повертає [(id, ok, деталі)]. Будь-яке ok=False → STOP. Файл лише читається."""
    res = []
    add = lambda i, ok, d: res.append((i, bool(ok), d))
    p = os.path.abspath(path)
    if not os.path.lexists(p) or not os.path.isfile(p) or os.path.islink(p):
        add("A01", False, f"немає звичайного файлу {p}")
        return res
    try:
        con = sqlite3.connect(Path(p).as_uri() + "?mode=ro", uri=True, timeout=1)
    except sqlite3.Error as e:
        add("A01", False, f"read-only відкриття неможливе: {e}")
        return res
    try:
        try:
            con.execute("PRAGMA query_only = 1")
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.Error as e:
            add("A01", False, f"read-only читання неможливе: {e}")
            return res
        add("A01", True, "файл відкрито лише read-only (mode=ro, query_only)")
        try:
            uv = con.execute("PRAGMA user_version").fetchone()[0]
            ic = [r[0] for r in con.execute("PRAGMA integrity_check")]
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            cat = _catalog(con)
        except sqlite3.Error as e:
            add("A03", False, f"помилка читання схеми/даних: {e}")
            return res
        ref = _release_catalog()
        add("A02", uv == RELEASE_AUTH_VERSION, f"user_version={uv}, потрібно {RELEASE_AUTH_VERSION}")
        add("A03", ic == ["ok"], f"integrity_check={'; '.join(ic[:3])}")
        add("A04", not fk, f"порушень foreign_key_check: {len(fk)}")
        miss = [t for t in RELEASE_AUTH_TABLES if t not in cat["tables"]]
        add("A05", not miss, f"відсутні таблиці: {', '.join(miss) or 'немає'}")
        bad = [t for t in RELEASE_AUTH_TABLES if t in cat["tables"] and cat["cols"][t] != ref["cols"][t]]
        add("A06", not bad, f"колонки (назва, тип, NOT NULL, default, PK, порядок) — розбіжності з release: {', '.join(bad) or 'немає'}")
        bad = []
        for t, c in (("v2_users", "email"), ("v2_sessions", "token_hash")):
            want = [(k, v) for k, v in ref["idx"][t].items() if k[1] == 1 and k[2] == "u"]
            got = [(k, v) for k, v in cat["idx"].get(t, {}).items() if k[1] == 1 and k[2] == "u"]
            w = [v for k, v in want if [x[2] for x in v if x[5]] == [c]]
            g = [v for k, v in got if [x[2] for x in v if x[5]] == [c]]
            if not g or [x[4] for x in g[0]] != [x[4] for x in w[0]]:
                bad.append(f"{t}.{c}")
        add("A07", not bad, f"UNIQUE/COLLATE (email — NOCASE, token_hash — BINARY) — розбіжності з release: {', '.join(bad) or 'немає'}")
        bad = [t for t in RELEASE_AUTH_TABLES if t in cat["tables"] and cat["fks"][t] != ref["fks"][t]]
        add("A08", not bad, f"зовнішні ключі / ON DELETE CASCADE — розбіжності з release: {', '.join(bad) or 'немає'}")
        bad = [t for t in RELEASE_AUTH_TABLES if t in cat["tables"] and cat["idx"][t] != ref["idx"][t]]
        add("A09", not bad, f"індекси (склад, порядок, DESC, collation, UNIQUE) — розбіжності з release: {', '.join(bad) or 'немає'}")
        bad = [t for t in RELEASE_AUTH_TABLES if t in cat["tables"] and cat["chk"][t] != ref["chk"][t]]
        add("A10", not bad, f"CHECK — розбіжності з release: {', '.join(bad) or 'немає'}")
        add("A11", "v2_dev_mail" not in cat["tables"], "v2_dev_mail у release відсутня" if "v2_dev_mail" not in cat["tables"] else "присутня v2_dev_mail (лише development)")
        want = {o[:3] for o in ref["objs"]}; got = {o[:3] for o in cat["objs"]}
        extra = sorted(got - want); lack = sorted(want - got)
        add("A12", not extra and not lack, f"сторонні об'єкти: {extra or 'немає'}; відсутні: {lack or 'немає'}")
        refsql = {o[:3]: o[3] for o in ref["objs"]}
        diff = sorted(o[1] for o in cat["objs"] if o[:3] in refsql and o[3] != refsql[o[:3]])
        add("A13", not diff, f"нормалізований DDL — розбіжності з release: {', '.join(diff) or 'немає'}")
    finally:
        con.close()
    return res


def main(argv):
    for st in (sys.stdout, sys.stderr):                  # installer читає UTF-8 (Invoke-V2Native -Utf8); -I ігнорує PYTHONIOENCODING
        st.reconfigure(encoding="utf-8", errors="backslashreplace")
    if not argv or (len(argv) < 2 and argv[0] != "auth-ddl"):
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
    elif cmd == "backup":
        src, dst, v = argv[1], argv[2], arg_version(argv)
        if os.path.exists(dst):
            sys.exit(f"STOP: {dst} уже існує")
        with ro(src) as s:
            check(s, v, "джерело")
            src_counts, src_fp = counts(s), (fingerprint(s) if v == 2 else None)
            d = sqlite3.connect(dst)
            try:
                s.backup(d)
            finally:
                d.close()
        with ro(dst) as c:
            check(c, v, "копія")
            if counts(c) != src_counts:
                sys.exit("STOP: кількість рядків копії ≠ джерелу")
        tmp = tempfile.mkdtemp(prefix="v2-restore-test-")
        try:
            r = os.path.join(tmp, "restore.db")
            shutil.copyfile(dst, r)
            with ro(r) as c:
                check(c, v, "тест відновлення")
                if counts(c) != src_counts or (src_fp and fingerprint(c) != src_fp):
                    sys.exit("STOP: тест відновлення: дані ≠ джерелу")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sha = hashlib.sha256(open(dst, "rb").read()).hexdigest()
        print(f"BACKUP OK user_version={v} rows={sum(src_counts.values())} restore-test=ok sha256={sha}")
    elif cmd == "users":
        with ro(argv[1]) as con:
            rows = con.execute("SELECT role, COUNT(*) FROM v2_users GROUP BY role ORDER BY role").fetchall()
            print("USERS " + " ".join(f"{r}={n}" for r, n in rows))
    elif cmd == "auth-schema":
        res = auth_schema_checks(argv[1])
        for i, ok, d in res:
            print(f"{i} {'PASS' if ok else 'FAIL'} {d}")
        bad = [i for i, ok, _ in res if not ok]
        if bad or len(res) < 13:
            sys.exit(f"STOP: auth-schema: FAIL {', '.join(bad) or 'неповна перевірка'} — {argv[1]}")
        print(f"AUTH SCHEMA OK release=dde86e6 checks={len(res)}")
    elif cmd == "auth-ddl":
        sys.stdout.write(RELEASE_AUTH_DDL)
    else:
        sys.exit(f"STOP: невідома команда {cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
