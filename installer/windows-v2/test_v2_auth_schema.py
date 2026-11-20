"""
test_v2_auth_schema.py — тести строгого checker-а V2_AUTH_DB (етап 1): A00–A13 (позитивні), N01–N15 (негативні, кожен
підвипадок окремо). Лише синтетичні БД у тимчасовому каталозі; production БД не використовується.

Запуск:  python -I test_v2_auth_schema.py --tool <v2_db_tool.py> [--release-backend <…\\integrity-v2-dde86e6\\backend> --release-manifest <BACKEND-SHA256.txt>
         --release-py <python з залежностями backend>]
Код виходу: 0 — усі PASS; 1 — будь-який FAIL. Без --release-backend тести A00/AREL позначаються NOT RUN (не PASS).
"""
import sys as _sys
_sys.dont_write_bytecode = True          # не лишати __pycache__ у каталозі комплекту
import ast
import hashlib
import importlib.util
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

for _st in (sys.stdout, sys.stderr):
    _st.reconfigure(encoding="utf-8", errors="backslashreplace")

args = sys.argv[1:]
def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default

TOOL = os.path.abspath(opt("--tool", ""))
REL = opt("--release-backend")
RELPY = opt("--release-py", sys.executable)
spec = importlib.util.spec_from_file_location("v2_db_tool", TOOL)
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
DDL = tool.RELEASE_AUTH_DDL
TMP = tempfile.mkdtemp(prefix="v2-auth-tests-")
results = []
n = [0]


def add(tid, ok, desc, status=None):
    st = status or ("PASS" if ok else "FAIL")
    results.append((tid, st))
    print(f"{tid:<16} {st:<7} {desc}")


def newdb(ddl=DDL, version=1, extra=None, data=None, name=None):
    n[0] += 1
    p = os.path.join(TMP, name or f"auth{n[0]}.db")
    c = sqlite3.connect(p)
    try:
        if ddl:
            c.executescript(ddl)
        if data:
            c.execute("PRAGMA foreign_keys = OFF")
            for sql in data:
                c.execute(sql)
        if extra:
            c.executescript(extra)
        c.execute(f"PRAGMA user_version = {version}")
        c.commit()
    finally:
        c.close()
    return p


def ddl_replace(*pairs):
    d = DDL
    for o, nw in pairs:
        assert d.count(o) == 1, f"фікстура: '{o}' зустрічається {d.count(o)} раз"
        d = d.replace(o, nw)
    return d


def run(path):
    r = subprocess.run([sys.executable, "-I", "-E", "-s", TOOL, "auth-schema", path], capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace"); err = r.stderr.decode("utf-8", "replace")
    fails = [ln.split()[0] for ln in out.splitlines() if " FAIL " in ln]
    return r.returncode, fails, out, err


def files_state(path):
    d = os.path.dirname(path); b = os.path.basename(path)
    return {f: hashlib.sha256(open(os.path.join(d, f), "rb").read()).hexdigest() for f in os.listdir(d) if f.startswith(b)}


def neg(tid, path, want, desc):
    code, fails, out, err = run(path)
    ok = code != 0 and "STOP: auth-schema" in err and all(w in fails for w in want) and "AUTH SCHEMA OK" not in out
    add(tid, ok, f"{desc} → STOP (exit {code}; FAIL {','.join(fails) or '—'}; очікувано {','.join(want)})")


DATA = [
    "INSERT INTO v2_users VALUES (1, 'U', 'u@example.test', 'h', 'user', '2026-11-19')",
    "INSERT INTO v2_sessions VALUES (1, 1, 'tok', '2026-11-20', '2026-11-19', 1)",
    "INSERT INTO v2_user_attempts VALUES ('a1', 1, 'x', 'Назва', 'draft', '{}', '2026-11-19', NULL, '2026-11-19')",
    "INSERT INTO v2_challenges VALUES (1, 1, 'login_2fa', 'c', '2026-11-19', 0, 0, '2026-11-19')",
    "INSERT INTO v2_rate_limits VALUES ('login', 'u', '2026-11-19', 1)",
]

try:
    # ------------------------------------------------------------------ позитивні
    p = newdb()
    before = files_state(p)
    code, fails, out, err = run(p)
    lines = [ln for ln in out.splitlines() if ln[:1] == "A" and ln[1:3].isdigit()]
    add("A01-A13.ref", code == 0 and len(lines) == 13 and all(" PASS " in ln for ln in lines) and "AUTH SCHEMA OK" in out and files_state(p) == before,
        f"еталонна release-БД (DDL dde86e6, v1): 13/13 PASS, exit {code}; файл і супутні файли не змінено (read-only)")
    p = newdb(data=DATA)
    code, fails, out, err = run(p)
    add("A01-A13.data", code == 0 and "AUTH SCHEMA OK" in out, f"еталонна БД з узгодженими даними в усіх 5 таблицях → PASS (exit {code})")
    p = newdb(data=DATA)
    c = sqlite3.connect(p); c.execute("PRAGMA journal_mode=WAL"); c.execute("INSERT INTO v2_rate_limits VALUES ('x','y','z',0)"); c.commit()
    holder = c  # тримає WAL відкритим (-wal/-shm існують)
    before = files_state(p)
    code, fails, out, err = run(p)
    holder.close()
    add("A01.wal", code == 0 and "AUTH SCHEMA OK" in out and before.keys() >= {os.path.basename(p) + "-wal"} , f"БД у режимі WAL з відкритим -wal/-shm → read-only перевірка PASS (exit {code})")
    code, fails, out, err = run(newdb())
    add("A01.nojournal", not any(f.endswith("-journal") for f in os.listdir(TMP)), "після перевірок у каталозі немає -journal (запису не було)")

    # A00 / AREL — прив'язка до справжнього release-коду
    if REL:
        src = os.path.join(REL, "app", "v2_auth.py")
        raw = open(src, "rb").read()
        tree = ast.parse(raw.decode("utf-8"))
        schema = next(n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_SCHEMA" for t in n.targets))
        ver = next(n.value.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "AUTH_SCHEMA_VERSION" for t in n.targets))
        # SHA256 v2_auth.py не закріплено в коді checker-а: еталон — маніфест релізу (BACKEND-SHA256.txt), bind-check звіряє і DDL
        MAN = opt("--release-manifest")
        if MAN:
            r = subprocess.run([sys.executable, "-I", "-E", "-s", TOOL, "bind-check", "--kind", "auth", "--expect-version", "1",
                                "--release-backend", REL, "--release-manifest", MAN], capture_output=True, timeout=60)
            bout = r.stdout.decode("utf-8", "replace")
            add("A00", r.returncode == 0 and "BIND OK kind=auth version=1" in bout and schema == DDL and ver == tool.RELEASE_AUTH_VERSION,
                f"DDL checker-а = _SCHEMA release v2_auth.py (SHA {hashlib.sha256(raw).hexdigest()[:16]}… = маніфест релізу), версія {ver}")
        else:
            add("A00", False, "немає --release-manifest (SHA джерела береться лише з маніфесту релізу)", "NOT RUN")
        for mode, want_ok in (("release", True), ("development", False)):
            db = os.path.join(TMP, f"rel-{mode}.db")
            env = {k: v for k, v in os.environ.items() if not k.startswith(("APP_ENV", "V2_", "INTEGRITY_"))}
            env.update(APP_ENV=mode, V2_AUTH_DB=db, V2_SECRET_KEY="x" * 64, FRONTEND_ORIGINS="https://v2.example.test")
            if mode == "development":
                env["V2_AUTH_DEV_MAIL"] = "1"      # dev-скринька вмикається лише прапорцем (settings.dev_mail_enabled)
            r = subprocess.run([RELPY, "-E", "-s", "-c", "from app.v2_auth import migrate_auth_db; print(migrate_auth_db())"], cwd=REL, env=env, capture_output=True, timeout=120)
            if r.returncode != 0:
                add(f"AREL.{mode}", False, f"release migrate_auth_db ({mode}) не виконано: {r.stderr.decode('utf-8','replace')[-300:]}")
                continue
            code, fails, out, err = run(db)
            if want_ok:
                add("AREL.release", code == 0 and "AUTH SCHEMA OK" in out, f"БД, створена справжнім release migrate_auth_db (APP_ENV=release) → 13/13 PASS (exit {code})")
            else:
                add("N13.devreal", code != 0 and "A11" in fails, f"БД, створена справжнім migrate_auth_db у development (є v2_dev_mail) → STOP A11 (exit {code}; FAIL {','.join(fails)})")
    else:
        add("A00", False, "немає --release-backend", "NOT RUN")
        add("AREL.release", False, "немає --release-backend", "NOT RUN")
        add("N13.devreal", False, "немає --release-backend", "NOT RUN")

    # ------------------------------------------------------------------ негативні (кожен підвипадок окремо)
    neg("N01", newdb(ddl=None), ["A05"], "порожня auth-БД, user_version=1")
    for t in tool.RELEASE_AUTH_TABLES:
        i = DDL.index(f"CREATE TABLE IF NOT EXISTS {t} ("); j = DDL.index(");", i) + 2
        d = DDL[:i] + DDL[j:]
        if t == "v2_sessions":
            d = d.replace("CREATE INDEX IF NOT EXISTS idx_v2_sessions_token ON v2_sessions(token_hash);", "")
        if t == "v2_user_attempts":
            d = d.replace("CREATE INDEX IF NOT EXISTS idx_v2_attempts_user ON v2_user_attempts(user_id, started_at DESC);", "")
        neg(f"N02.{t}", newdb(ddl=d), ["A05"], f"відсутня таблиця {t}")
    for tid, o in (("v2_users.created_at", "    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),\n    created_at TEXT NOT NULL\n"),
                   ("v2_sessions.two_factor_verified", "    created_at TEXT NOT NULL,\n    two_factor_verified INTEGER NOT NULL DEFAULT 0\n"),
                   ("v2_user_attempts.updated_at", "    completed_at TEXT,\n    updated_at TEXT NOT NULL DEFAULT ''\n"),
                   ("v2_challenges.consumed", "    consumed INTEGER NOT NULL DEFAULT 0,\n"),
                   ("v2_rate_limits.attempts", "    attempts INTEGER NOT NULL DEFAULT 0,\n    PRIMARY KEY (scope, subject)")):
        nw = {"v2_users.created_at": "    role TEXT NOT NULL CHECK (role IN ('user', 'admin'))\n",
              "v2_sessions.two_factor_verified": "    created_at TEXT NOT NULL\n",
              "v2_user_attempts.updated_at": "    completed_at TEXT\n",
              "v2_challenges.consumed": "",
              "v2_rate_limits.attempts": "    PRIMARY KEY (scope, subject)"}[tid]
        neg(f"N03.{tid}", newdb(ddl=ddl_replace((o, nw))), ["A06"], f"відсутня колонка {tid}")
    neg("N04.type", newdb(ddl=ddl_replace(("    password_hash TEXT NOT NULL,", "    password_hash BLOB NOT NULL,"))), ["A06"], "неправильний тип v2_users.password_hash (BLOB)")
    neg("N04.notnull", newdb(ddl=ddl_replace(("    name TEXT NOT NULL,", "    name TEXT,"))), ["A06"], "без NOT NULL у v2_users.name")
    neg("N04.pk", newdb(ddl=ddl_replace(("    id TEXT PRIMARY KEY,", "    id TEXT NOT NULL,"))), ["A06"], "немає PK у v2_user_attempts.id")
    neg("N04.pkcomposite", newdb(ddl=ddl_replace(("    PRIMARY KEY (scope, subject)", "    PRIMARY KEY (scope)"))), ["A06"], "PK v2_rate_limits лише (scope)")
    neg("N04.default", newdb(ddl=ddl_replace(("    two_factor_verified INTEGER NOT NULL DEFAULT 0\n", "    two_factor_verified INTEGER NOT NULL DEFAULT 1\n"))), ["A06"], "default two_factor_verified = 1")
    neg("N04.order", newdb(ddl=ddl_replace(("    name TEXT NOT NULL,\n    email TEXT NOT NULL UNIQUE COLLATE NOCASE,", "    email TEXT NOT NULL UNIQUE COLLATE NOCASE,\n    name TEXT NOT NULL,"))), ["A06"], "інший порядок колонок v2_users")
    neg("N05.email", newdb(ddl=ddl_replace(("email TEXT NOT NULL UNIQUE COLLATE NOCASE", "email TEXT NOT NULL COLLATE NOCASE"))), ["A07"], "немає UNIQUE v2_users.email")
    neg("N05.token", newdb(ddl=ddl_replace(("token_hash TEXT NOT NULL UNIQUE,", "token_hash TEXT NOT NULL,"))), ["A07"], "немає UNIQUE v2_sessions.token_hash")
    neg("N06.email-none", newdb(ddl=ddl_replace(("email TEXT NOT NULL UNIQUE COLLATE NOCASE", "email TEXT NOT NULL UNIQUE"))), ["A07"], "email без COLLATE NOCASE")
    neg("N06.email-rtrim", newdb(ddl=ddl_replace(("email TEXT NOT NULL UNIQUE COLLATE NOCASE", "email TEXT NOT NULL UNIQUE COLLATE RTRIM"))), ["A07"], "email COLLATE RTRIM")
    neg("N06.token-nocase", newdb(ddl=ddl_replace(("token_hash TEXT NOT NULL UNIQUE,", "token_hash TEXT NOT NULL UNIQUE COLLATE NOCASE,"))), ["A07"], "token_hash COLLATE NOCASE (у release — BINARY)")
    neg("N07.sessions", newdb(ddl=ddl_replace(("CREATE INDEX IF NOT EXISTS idx_v2_sessions_token ON v2_sessions(token_hash);", ""))), ["A09"], "відсутній idx_v2_sessions_token")
    neg("N07.attempts", newdb(ddl=ddl_replace(("CREATE INDEX IF NOT EXISTS idx_v2_attempts_user ON v2_user_attempts(user_id, started_at DESC);", ""))), ["A09"], "відсутній idx_v2_attempts_user")
    neg("N08.order", newdb(ddl=ddl_replace(("ON v2_user_attempts(user_id, started_at DESC)", "ON v2_user_attempts(started_at DESC, user_id)"))), ["A09"], "інший порядок колонок idx_v2_attempts_user")
    neg("N08.desc", newdb(ddl=ddl_replace(("ON v2_user_attempts(user_id, started_at DESC)", "ON v2_user_attempts(user_id, started_at)"))), ["A09"], "без DESC у idx_v2_attempts_user")
    neg("N08.column", newdb(ddl=ddl_replace(("ON v2_sessions(token_hash)", "ON v2_sessions(expires_at)"))), ["A09"], "idx_v2_sessions_token на іншій колонці")
    neg("N08.extracol", newdb(ddl=ddl_replace(("ON v2_sessions(token_hash)", "ON v2_sessions(token_hash, user_id)"))), ["A09"], "зайва колонка в idx_v2_sessions_token")
    neg("N08.unique", newdb(ddl=ddl_replace(("CREATE INDEX IF NOT EXISTS idx_v2_sessions_token", "CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_sessions_token"))), ["A09"], "idx_v2_sessions_token став UNIQUE")
    fk = "user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE CASCADE,"
    for tbl, anchor in (("v2_sessions", "    token_hash TEXT NOT NULL UNIQUE,"), ("v2_user_attempts", "    assessment_id TEXT NOT NULL DEFAULT 'legacy',"), ("v2_challenges", "    purpose TEXT NOT NULL CHECK")):
        i = DDL.index(f"CREATE TABLE IF NOT EXISTS {tbl} ("); j = DDL.index(fk, i)
        d = DDL[:j] + "user_id INTEGER NOT NULL," + DDL[j + len(fk):]
        neg(f"N09.{tbl}", newdb(ddl=d), ["A08"], f"відсутній FK {tbl}.user_id")
    i = DDL.index("CREATE TABLE IF NOT EXISTS v2_sessions ("); j = DDL.index(fk, i)
    neg("N09.nocascade", newdb(ddl=DDL[:j] + "user_id INTEGER NOT NULL REFERENCES v2_users(id)," + DDL[j + len(fk):]), ["A08"], "FK v2_sessions без ON DELETE CASCADE")
    neg("N09.setnull", newdb(ddl=DDL[:j] + "user_id INTEGER NOT NULL REFERENCES v2_users(id) ON DELETE SET NULL," + DDL[j + len(fk):]), ["A08"], "FK v2_sessions з ON DELETE SET NULL")
    neg("N10", newdb(data=DATA + ["INSERT INTO v2_sessions VALUES (2, 999, 'tok2', '2026-11-20', '2026-11-19', 0)"]), ["A04"], "порушення FK у даних (сесія неіснуючого користувача)")
    neg("N10.attempts", newdb(data=DATA + ["INSERT INTO v2_user_attempts VALUES ('a2', 777, 'x', 'n', 'draft', '{}', 's', NULL, 'u')"]), ["A04"], "порушення FK у v2_user_attempts")
    neg("N11.role-none", newdb(ddl=ddl_replace(("role TEXT NOT NULL CHECK (role IN ('user', 'admin')),", "role TEXT NOT NULL,"))), ["A10"], "немає CHECK для role")
    neg("N11.role-wide", newdb(ddl=ddl_replace(("CHECK (role IN ('user', 'admin'))", "CHECK (role IN ('user', 'admin', 'root'))"))), ["A10"], "CHECK role розширено ('root')")
    neg("N11.status", newdb(ddl=ddl_replace(("status TEXT NOT NULL CHECK (status IN ('draft', 'completed')),", "status TEXT NOT NULL,"))), ["A10"], "немає CHECK для status")
    neg("N11.purpose", newdb(ddl=ddl_replace(("CHECK (purpose IN ('login_2fa', 'password_reset'))", "CHECK (purpose IN ('login_2fa'))"))), ["A10"], "інший CHECK для purpose")
    neg("N11.extra", newdb(ddl=ddl_replace(("    attempts INTEGER NOT NULL DEFAULT 0,\n    consumed", "    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),\n    consumed"))), ["A10"], "зайвий CHECK у v2_challenges")
    # N12 — пошкодження
    p = newdb(data=DATA + [f"INSERT INTO v2_rate_limits VALUES ('s{i}', '{'x' * 200}', 'w', 0)" for i in range(400)])
    b = bytearray(open(p, "rb").read()); ps = int.from_bytes(b[16:18], "big") or 65536
    for pg in range(3, len(b) // ps):
        b[pg * ps + 8: pg * ps + 40] = b"\xff" * 32
    open(p, "wb").write(bytes(b))
    neg("N12.pages", p, [], "пошкоджені сторінки b-tree (integrity_check / читання)")
    code, fails, _, _ = run(p)
    add("N12.pages-id", any(f in fails for f in ("A01", "A03")), f"пошкодження виявлено як A01/A03 ({','.join(fails)})")
    p = os.path.join(TMP, "garbage.db"); open(p, "wb").write(os.urandom(8192))
    neg("N12.notdb", p, ["A01"], "файл не є SQLite")
    p = newdb(data=DATA); sz = os.path.getsize(p); open(p, "r+b").truncate(sz // 2)
    code, fails, out, err = run(p)
    add("N12.truncated", code != 0 and "AUTH SCHEMA OK" not in out, f"обрізаний файл → STOP (exit {code}; FAIL {','.join(fails) or '—'})")
    neg("N13", newdb(extra="CREATE TABLE v2_dev_mail (id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);"), ["A11", "A12"], "присутня v2_dev_mail")
    neg("N14.trigger", newdb(extra="CREATE TRIGGER t1 AFTER INSERT ON v2_users BEGIN SELECT 1; END;"), ["A12"], "сторонній trigger")
    neg("N14.view", newdb(extra="CREATE VIEW v1 AS SELECT email FROM v2_users;"), ["A12"], "сторонній view")
    neg("N14.table", newdb(extra="CREATE TABLE extra_t (x);"), ["A12"], "стороння таблиця")
    neg("N14.index", newdb(extra="CREATE INDEX extra_i ON v2_users(name);"), ["A12", "A09"], "сторонній індекс")
    neg("N15.v0", newdb(version=0), ["A02"], "user_version = 0")
    neg("N15.v2", newdb(version=2), ["A02"], "user_version = 2")
    neg("N15.missing", os.path.join(TMP, "no-such.db"), ["A01"], "файл не існує")
    d = os.path.join(TMP, "dir.db"); os.mkdir(d)
    neg("N15.directory", d, ["A01"], "шлях — каталог")
    p = newdb()
    lock = subprocess.Popen([sys.executable, "-I", "-c", "import sqlite3,sys,time; c=sqlite3.connect(sys.argv[1]); c.execute('PRAGMA locking_mode=EXCLUSIVE'); c.execute('BEGIN EXCLUSIVE'); c.execute('INSERT INTO v2_rate_limits VALUES (1,2,3,4)'); print('L', flush=True); time.sleep(30)", p], stdout=subprocess.PIPE)
    lock.stdout.readline()
    try:
        neg("N15.locked", p, ["A01"], "БД ексклюзивно заблокована іншим процесом (read-only доступ неможливий)")
    finally:
        lock.kill(); lock.wait()
finally:
    shutil.rmtree(TMP, ignore_errors=True)

npass = sum(1 for _, s in results if s == "PASS"); nfail = sum(1 for _, s in results if s == "FAIL"); nnr = sum(1 for _, s in results if s == "NOT RUN")
print(f"Підсумок: {npass} PASS, {nfail} FAIL, {nnr} NOT RUN (усього {len(results)})")
sys.exit(1 if nfail else 0)
