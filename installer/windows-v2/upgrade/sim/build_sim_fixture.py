"""
build_sim_fixture.py — ЛИШЕ ДЛЯ ТЕСТІВ: синтетичний стенд для сухого прогону Update/Rollback-V2InPlace (-Simulate).
Усе створюється в каталозі --out (у %TEMP%): корінь «C:\\srv\\integrity-v2» (шаблон із маркером @@ROOT@@ у XML), справжній venv
(базовий Python, -m venv), синтетичні БД integrity v3 / auth v1 (DDL із v2_db_tool.SCHEMA_SPECS), фейковий поточний реліз,
пакет нового релізу (фейкова міграція 3→5 і 1→2 за контрактом, шими для bind-check, модуль bootstrap, який не має розгортатися),
справжнє колесо v2simpkg (pip --require-hashes), dist, шаблон Caddyfile з комплекту, суми «з окремого каналу».

  python -I -B build_sim_fixture.py --kit <installer\\windows-v2> --out <каталог> --base-python <python.exe> --caddy <caddy.exe>
"""
import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
import zipfile

sys.dont_write_bytecode = True
args = sys.argv[1:]
opt = lambda n: args[args.index(n) + 1]
KIT, OUT, BASEPY, CADDY = opt("--kit"), opt("--out"), opt("--base-python"), opt("--caddy")
sys.path.insert(0, KIT)
import v2_db_tool as tool  # noqa: E402

OLD, NEW = "integrity-v2-dde86e6", "integrity-v2-sim0002"
TPL = os.path.join(OUT, "t")                       # короткі шляхи: pip у venv має файли з довгими іменами (MAX_PATH)
ROOT = os.path.join(TPL, "v2")
PKG = os.path.join(OUT, "package")


def w(path, data, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if mode == "w":
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
    else:
        with open(path, "wb") as f:
            f.write(data)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def manifest(base, prefix="backend/", skip=()):
    out = {}
    for d, _, files in os.walk(base):
        for n in files:
            p = os.path.join(d, n)
            rel = prefix + os.path.relpath(p, base).replace("\\", "/")
            if not any(s in rel for s in skip):
                out[rel] = sha(p)
    return dict(sorted(out.items()))


def write_sums(path, entries):
    w(path, "".join(f"{h}  {n}\n" for n, h in entries.items()))


# ------------------------------------------------------------------------------------------------ корінь V2 (поточний стан)
for d in ("pkg", "backups", "logs/backend", "logs/caddy", "services/backend", "services/caddy", "caddy/bin", "caddy/data", "caddy/config", "caddy/tls", "data"):
    os.makedirs(os.path.join(ROOT, d), exist_ok=True)
old_be = os.path.join(ROOT, "app", OLD, "backend")
w(os.path.join(old_be, "app", "__init__.py"), "")
w(os.path.join(old_be, "app", "main.py"), "# SIM: поточний реліз\n")
w(os.path.join(old_be, "app", "migrations.py"), "SCHEMA_VERSION = 3\n")
w(os.path.join(old_be, "app", "sim_expect.json"), json.dumps({"integrity": 3, "auth": 1, "requires": []}))
w(os.path.join(old_be, "requirements.txt"), "fastapi==0.163.1\n")
write_sums(os.path.join(ROOT, "pkg", f"{OLD}-BACKEND-SHA256.txt"), manifest(old_be))
w(os.path.join(old_be, "app", "v2_clean_bootstrap_admin.py"), "# SIM: зайвий файл інсталятора (дозволений, не переноситься)\n")
w(os.path.join(ROOT, "app", "frontend", "dist", "index.html"), "<!doctype html><title>old</title>\n")
w(os.path.join(ROOT, "app", "frontend", "dist", "assets", "old.js"), "console.log('old')\n")
w(os.path.join(ROOT, "caddy", "Caddyfile"), """{
\tadmin off
\tstorage file_system C:/srv/integrity-v2/caddy/data
\tauto_https off
\tservers {
\t\tprotocols h1 h2
\t}
}

desktop-jtgc2sg.taild5c033.ts.net:443 {
\tbind 100.111.221.74
\ttls C:/srv/integrity-v2/caddy/tls/site.crt C:/srv/integrity-v2/caddy/tls/site.key
\theader {
\t\t-Server
\t}
\thandle {
\t\troot * C:/srv/integrity-v2/app/frontend/dist
\t\tfile_server
\t}
}
""")
secret = "SIM-SECRET-" + uuid.uuid4().hex
xml = open(os.path.join(KIT, "integrity-v2-backend.xml.template"), encoding="utf-8").read().replace("\r\n", "\n")
for ph in ("__V2_SECRET_KEY__", "__V2_SMTP_HOST__", "__V2_SMTP_USER__", "__V2_SMTP_PASSWORD__", "__V2_SMTP_FROM__"):
    xml = xml.replace(ph, f"{secret}-{ph.strip('_')}")
xml = xml.replace("C:\\srv\\integrity-v2", "@@ROOT@@")
w(os.path.join(ROOT, "services", "backend", "integrity-v2-backend.xml"), xml)
w(os.path.join(ROOT, "services", "caddy", "integrity-v2-caddy.xml"),
  open(os.path.join(KIT, "integrity-v2-caddy.xml.template"), encoding="utf-8").read().replace("\r\n", "\n").replace("C:\\srv\\integrity-v2", "@@ROOT@@"))

# БД: integrity v3 і auth v1 з даними; маркери інсталятора
idb, adb = os.path.join(ROOT, "data", "integrity_v2.db"), os.path.join(ROOT, "data", "v2_auth.db")
con = sqlite3.connect(idb)
con.executescript(tool.spec_for("integrity", 3)["ddl"])
con.execute("INSERT INTO components VALUES (1, 'C1', 'Компонент', 0.5)")
con.execute("INSERT INTO cycles VALUES (1, '2026-I', '2026-01-01', 'open', 5)")
con.execute("INSERT INTO units VALUES (1, 'Підрозділ А')")
con.execute("INSERT INTO questions VALUES (1, 1, 'Питання', 1, 5, 'survey')")
for i in range(1, 13):
    con.execute("INSERT INTO response_sets VALUES (?, 1, 'staff', 'Підрозділ А')", (i,))
    con.execute("INSERT INTO answers VALUES (?, ?, 1, ?)", (i, i, 1 + i % 5))
con.execute("INSERT INTO objective_indicators VALUES (1, 1, 1, 'Показник', 81.0, 'admin', NULL, 0)")
con.execute("INSERT INTO recommendations VALUES (1, 1, 1, 'Текст', 'Підстава', 'proposed', NULL, NULL)")
for i in range(1, 6):
    con.execute("INSERT INTO access_tokens VALUES (?, 1, ?, ?)", (i, f"CODE-{i:04d}", i % 2))
con.execute("INSERT INTO audit_events VALUES (1, '2026-11-20 10:00:00', 'admin', 'cycle.open', 1, '{}')")
con.execute("PRAGMA user_version = 3"); con.commit(); con.close()
con = sqlite3.connect(adb)
con.executescript(tool.spec_for("auth", 1)["ddl"])
con.execute("INSERT INTO v2_users (name, email, password_hash, role, created_at) VALUES ('Адмін', 'admin@example.test', 'scrypt$x', 'admin', '2026-11-20')")
con.execute("INSERT INTO v2_sessions (user_id, token_hash, expires_at, created_at, two_factor_verified) VALUES (1, 'th', 'e', 'c', 1)")
con.execute("PRAGMA user_version = 1"); con.commit(); con.close()
w(os.path.join(ROOT, "data", "CLEAN-INIT-OK-20261120-134912.txt"), "clean init ok\n")
w(os.path.join(ROOT, "data", "CREATED-BY-V2-INSTALL.txt"), "created by SIM\n")

# venv (справжній, базовий Python) і TLS-пара
# venv без розпакованого pip: pip — з колеса ensurepip через .pth (zipimport). Глибокі шляхи pip\_internal\… у venv
# перевищували б MAX_PATH у довгих %TEMP%; поведінка «python -m pip» для Update-V2InPlace та сама.
subprocess.run([BASEPY, "-I", "-m", "venv", "--without-pip", os.path.join(ROOT, "venv")], check=True, timeout=600)
import glob  # noqa: E402
pipwhl = sorted(glob.glob(os.path.join(os.path.dirname(BASEPY), "Lib", "ensurepip", "_bundled", "pip-*.whl")))[-1]
site = os.path.join(ROOT, "venv", "Lib", "site-packages")
shutil.copyfile(pipwhl, os.path.join(site, os.path.basename(pipwhl)))
w(os.path.join(site, "pip-zip.pth"), os.path.basename(pipwhl) + "\n")
import trustme  # noqa: E402
ca = trustme.CA()
cert = ca.issue_cert("desktop-jtgc2sg.taild5c033.ts.net")
cert.cert_chain_pems[0].write_to_path(os.path.join(ROOT, "caddy", "tls", "site.crt"))
cert.private_key_pem.write_to_path(os.path.join(ROOT, "caddy", "tls", "site.key"))

w(os.path.join(TPL, "sim", "state.json"), json.dumps({"Services": {
    "integrity-v2-backend": {"State": "Running", "StartMode": "Manual", "Delayed": False, "DependsOn": []},
    "integrity-v2-caddy": {"State": "Running", "StartMode": "Manual", "Delayed": False, "DependsOn": ["Tailscale"]}}, "Events": []}, indent=1))
w(os.path.join(TPL, "sim", "config.json"), json.dumps({"Caddy": CADDY, "MachineEnv": [], "FreeBytes": 500 * 1024 ** 3}))

# ------------------------------------------------------------------------------------------------ пакет нового релізу
src = os.path.join(OUT, "newsrc", NEW, "backend")
target_i, target_a = tool.spec_for("integrity", 5)["ddl"], tool.spec_for("auth", 2)["ddl"]
w(os.path.join(src, "app", "__init__.py"), "")
w(os.path.join(src, "app", "main.py"), "# SIM: новий реліз (не імпортується перевіркою)\n")
w(os.path.join(src, "app", "models.py"), "# SIM: шим для bind-check\n")
w(os.path.join(src, "app", "target_integrity.sql"), target_i)
w(os.path.join(src, "app", "target_auth.sql"), target_a)
w(os.path.join(src, "app", "v2_auth.py"), f'AUTH_SCHEMA_VERSION = 2\n_SCHEMA = """{target_a}"""\n')
w(os.path.join(src, "app", "database.py"), '''import os, sqlite3
_HERE = os.path.dirname(os.path.abspath(__file__))
class _Meta:
    def create_all(self, engine):
        con = sqlite3.connect(os.environ["INTEGRITY_DB"])
        con.executescript(open(os.path.join(_HERE, "target_integrity.sql"), encoding="utf-8").read())
        con.close()
class Base:
    metadata = _Meta()
class _Engine:
    def dispose(self):
        pass
engine = _Engine()
''')
w(os.path.join(src, "app", "migrations.py"), r'''"""SIM: явна міграція integrity 3→5 і auth 1→2 за контрактом (12-крокова перебудова таблиць SQLite)."""
import hashlib, os, re, sqlite3, sys
from datetime import datetime
SCHEMA_VERSION = 5
_HERE = os.path.dirname(os.path.abspath(__file__))


def _stmts(name):
    out, buf = [], ""
    for line in open(os.path.join(_HERE, name), encoding="utf-8"):
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip()); buf = ""
    return out


def _one(stmts, pattern):
    hit = [s for s in stmts if re.match(pattern, " ".join(s.split()))]
    assert len(hit) == 1, pattern
    return hit[0]


def _backup(path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem, ext = os.path.splitext(path)
    with sqlite3.connect(path) as s, sqlite3.connect(f"{stem}.backup-{stamp}{ext}") as d:
        s.backup(d)


def _finish(con, version):
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.execute(f"PRAGMA user_version = {version}")
    con.execute("COMMIT")


def migrate_integrity(path):
    con = sqlite3.connect(path, isolation_level=None)
    if con.execute("PRAGMA user_version").fetchone()[0] == 5:
        return "up_to_date"
    _backup(path)
    st = _stmts("target_integrity.sql")
    con.execute("PRAGMA foreign_keys = OFF"); con.execute("BEGIN")
    before = con.execute("SELECT COUNT(*) FROM access_tokens").fetchone()[0]
    con.execute(_one(st, r"CREATE TABLE recommendation_actions \("))
    con.execute(_one(st, r"CREATE TABLE access_tokens \(").replace("CREATE TABLE access_tokens", "CREATE TABLE access_tokens_new", 1))
    for i, c, t, u in con.execute("SELECT id, cycle_id, token, used FROM access_tokens").fetchall():
        con.execute("INSERT INTO access_tokens_new VALUES (?, ?, ?, ?)", (i, c, hashlib.sha256(t.encode()).hexdigest(), u))
    con.execute("DROP TABLE access_tokens"); con.execute("ALTER TABLE access_tokens_new RENAME TO access_tokens")
    assert con.execute("SELECT COUNT(*) FROM access_tokens").fetchone()[0] == before
    con.execute("ALTER TABLE audit_events ADD COLUMN actor_user_id INTEGER")
    con.execute(_one(st, r"CREATE TABLE instance_meta \("))
    _finish(con, 5); con.close()
    return "migrated"


def migrate_auth(path):
    con = sqlite3.connect(path, isolation_level=None)
    if con.execute("PRAGMA user_version").fetchone()[0] == 2:
        return "up_to_date"
    st = _stmts("target_auth.sql")
    con.execute("PRAGMA foreign_keys = OFF"); con.execute("BEGIN")
    con.execute(_one(st, r"CREATE TABLE (IF NOT EXISTS )?v2_users \(").replace("v2_users (", "v2_users_new (", 1).replace("IF NOT EXISTS ", ""))
    con.execute("INSERT INTO v2_users_new SELECT * FROM v2_users")
    con.execute("DROP TABLE v2_users"); con.execute("ALTER TABLE v2_users_new RENAME TO v2_users")
    for s in st:
        if "v2_role_changes" in s:
            con.execute(s)
    _finish(con, 2); con.close()
    return "migrated"


if __name__ == "__main__":
    if not ("--apply" in sys.argv and "--confirm-verified-backup" in sys.argv):
        raise SystemExit("Міграцію не виконано: потрібні --apply і --confirm-verified-backup")
    if os.environ.get("APP_ENV") != "release" or "V2_SECRET_KEY" in os.environ:
        raise SystemExit("SIM: міграція очікує APP_ENV=release і ВІДСУТНІЙ V2_SECRET_KEY")
    print("INTEGRITY_DB:", migrate_integrity(os.environ["INTEGRITY_DB"]))
    print("V2_AUTH_DB:", migrate_auth(os.environ["V2_AUTH_DB"]))
''')
w(os.path.join(src, "app", "sim_expect.json"), json.dumps({"integrity": 5, "auth": 2, "requires": ["v2simpkg"]}))
w(os.path.join(src, "app", "v2_bootstrap_admin.py"), "# SIM: bootstrap — НЕ розгортається\n")
w(os.path.join(src, "app", "routes", "__init__.py"), "")
w(os.path.join(src, "app", "routes", "reports.py"), "import v2simpkg  # нова залежність (як reportlab у main-final)\n")
w(os.path.join(src, "requirements.txt"), "fastapi==0.163.1\nv2simpkg==1.0\n")

os.makedirs(PKG, exist_ok=True)
man = manifest(src)
write_sums(os.path.join(PKG, "BACKEND-SHA256.txt"), man)
with zipfile.ZipFile(os.path.join(PKG, "backend-src.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for rel in man:
        z.write(os.path.join(src, *rel.split("/")[1:]), f"{NEW}/{rel}")
dist = {"dist/index.html": b"<!doctype html><title>new</title>\n", "dist/assets/new.js": b"console.log('new')\n"}
with zipfile.ZipFile(os.path.join(PKG, "dist.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for n, b in dist.items():
        z.writestr(n, b)
write_sums(os.path.join(PKG, "DIST-SHA256.txt"), {n: hashlib.sha256(b).hexdigest() for n, b in dist.items()})
shutil.copyfile(os.path.join(KIT, "deploy", "Caddyfile"), os.path.join(PKG, "Caddyfile"))

# колесо v2simpkg-1.0 (чисте python) з коректним RECORD
files = {"v2simpkg/__init__.py": b"VERSION = '1.0'\n",
         "v2simpkg-1.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: v2simpkg\nVersion: 1.0\n",
         "v2simpkg-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: sim\nRoot-Is-Purelib: true\nTag: py3-none-any\n"}
rec = "".join(f"{n},sha256={base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b'=').decode()},{len(b)}\n" for n, b in files.items())
rec += "v2simpkg-1.0.dist-info/RECORD,,\n"
os.makedirs(os.path.join(PKG, "wheels"), exist_ok=True)
whl = os.path.join(PKG, "wheels", "v2simpkg-1.0-py3-none-any.whl")
with zipfile.ZipFile(whl, "w", zipfile.ZIP_DEFLATED) as z:
    for n, b in files.items():
        z.writestr(n, b)
    z.writestr("v2simpkg-1.0.dist-info/RECORD", rec)
w(os.path.join(PKG, "requirements-hashed.txt"), f"v2simpkg==1.0 --hash=sha256:{sha(whl)}\n")
sums = {n: sha(os.path.join(PKG, n)) for n in ("backend-src.zip", "BACKEND-SHA256.txt", "dist.zip", "DIST-SHA256.txt", "Caddyfile", "requirements-hashed.txt")}
write_sums(os.path.join(OUT, "APPROVED-SHA256.txt"), sums)

# варіант пакета з дрейфом DDL (bind-check має зупинити до простою)
drift = os.path.join(OUT, "package-drift")
shutil.copytree(PKG, drift)
dsrc = os.path.join(OUT, "driftsrc", NEW, "backend")
shutil.copytree(src, dsrc)
w(os.path.join(dsrc, "app", "v2_auth.py"), f'AUTH_SCHEMA_VERSION = 2\n_SCHEMA = """{target_a.replace("v2_role_changes_no_delete", "v2_role_changes_nodel")}"""\n')
dman = manifest(dsrc)
write_sums(os.path.join(drift, "BACKEND-SHA256.txt"), dman)
os.remove(os.path.join(drift, "backend-src.zip"))
with zipfile.ZipFile(os.path.join(drift, "backend-src.zip"), "w", zipfile.ZIP_DEFLATED) as z:
    for rel in dman:
        z.write(os.path.join(dsrc, *rel.split("/")[1:]), f"{NEW}/{rel}")
dsums = dict(sums, **{"backend-src.zip": sha(os.path.join(drift, "backend-src.zip")), "BACKEND-SHA256.txt": sha(os.path.join(drift, "BACKEND-SHA256.txt"))})
write_sums(os.path.join(OUT, "APPROVED-SHA256-drift.txt"), dsums)
print(json.dumps({"secret_marker": secret, "old": OLD, "new": NEW}))
