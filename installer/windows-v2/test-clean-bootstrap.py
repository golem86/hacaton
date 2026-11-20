"""Static and synthetic functional proof for the clean-only auth bootstrap."""
import argparse
import ast
import contextlib
import getpass
import io
from pathlib import Path
import runpy
import sys
import types
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--deploy-zip', required=True)
args = parser.parse_args()
kit = Path(__file__).resolve().parent
source = (kit / 'v2_clean_bootstrap_admin.py').read_text(encoding='utf-8')
tree = ast.parse(source)
names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
imports = {alias.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for alias in n.names}
static_ok = not {'init_auth_db', 'migrate_auth_db'} & (names | imports)
installer_ok = "'-m', 'app.v2_clean_bootstrap_admin'" in (kit / 'clean-install.ps1').read_text(encoding='utf-8-sig')
with zipfile.ZipFile(args.deploy_zip) as outer:
    with zipfile.ZipFile(io.BytesIO(outer.read('integrity-v2-dde86e6-backend-src.zip'))) as inner:
        release = inner.read('integrity-v2-dde86e6/backend/app/v2_bootstrap_admin.py').decode('utf-8')
release_old_path = 'init_auth_db()' in release
print('CB.static', 'PASS' if static_ok and installer_ok and release_old_path else 'FAIL', 'clean entry excludes init/migrate; release legacy entry identified')

events = []
app = types.ModuleType('app'); app.__path__ = []
audit = types.ModuleType('app.audit')
audit.record = lambda db, who, action: events.append(('audit', who, action))
database = types.ModuleType('app.database')
auth = types.ModuleType('app.v2_auth')
class Session:
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def commit(self): events.append('commit')
database.SessionLocal = Session
auth.check_auth_schema = lambda: events.append('schema')
auth.create_user = lambda name, email, password, role: events.append(('create', name, email, password, role))
auth.init_auth_db = lambda: (_ for _ in ()).throw(AssertionError('unexpected init'))
auth.migrate_auth_db = lambda: (_ for _ in ()).throw(AssertionError('unexpected migrate'))
app.audit = audit
saved_modules = {name: sys.modules.get(name) for name in ('app', 'app.audit', 'app.database', 'app.v2_auth')}
saved_argv, saved_getpass = sys.argv, getpass.getpass
try:
    sys.modules.update({'app': app, 'app.audit': audit, 'app.database': database, 'app.v2_auth': auth})
    sys.argv = [str(kit/'v2_clean_bootstrap_admin.py'), '--name', 'Synthetic Admin', '--email', 'admin@example.test']
    answers = iter(('synthetic-pass-123', 'synthetic-pass-123'))
    getpass.getpass = lambda prompt: next(answers)
    output = io.StringIO()
    with contextlib.redirect_stdout(output): runpy.run_path(str(kit/'v2_clean_bootstrap_admin.py'), run_name='__main__')
    ok = events == ['schema', ('create', 'Synthetic Admin', 'admin@example.test', 'synthetic-pass-123', 'admin'), ('audit', 'admin', 'user.create_admin'), 'commit'] and 'admin@example.test' not in output.getvalue() and 'synthetic-pass-123' not in output.getvalue()
    print('CB.functional', 'PASS' if ok else 'FAIL', 'strict check precedes create; no migration; no credential output')
    events.clear()
    def blocked(): raise RuntimeError('invalid schema')
    auth.check_auth_schema = blocked
    try:
        with contextlib.redirect_stdout(io.StringIO()): runpy.run_path(str(kit/'v2_clean_bootstrap_admin.py'), run_name='__main__')
        blocked_ok = False
    except RuntimeError as exc:
        blocked_ok = str(exc) == 'invalid schema' and not events
    print('CB.invalid-schema', 'PASS' if blocked_ok else 'FAIL', 'no create on schema error')
finally:
    sys.argv, getpass.getpass = saved_argv, saved_getpass
    for name, value in saved_modules.items():
        if value is None: sys.modules.pop(name, None)
        else: sys.modules[name] = value
if not (static_ok and installer_ok and release_old_path and ok and blocked_ok): raise SystemExit(1)
