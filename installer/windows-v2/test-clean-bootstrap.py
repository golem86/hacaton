"""Static and synthetic functional proof for the clean-only auth bootstrap (current release package format).

Run: python -I test-clean-bootstrap.py --package-dir <package with backend-src.zip> --release-id integrity-v2-<sha7>
"""
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
parser.add_argument('--package-dir', required=True)
parser.add_argument('--release-id', required=True)
args = parser.parse_args()
kit = Path(__file__).resolve().parent
script = kit / 'v2_clean_bootstrap_admin.py'
source = script.read_text(encoding='utf-8')
tree = ast.parse(source)
names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
imports = {alias.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for alias in n.names}
static_ok = not {'init_auth_db', 'migrate_auth_db'} & (names | imports)
ci = (kit / 'clean-install.ps1').read_text(encoding='utf-8-sig')
# one-shot call from the installer directory with the release backend on sys.path; the module is never copied into app\
installer_ok = ('"$K\\v2_clean_bootstrap_admin.py", \'--backend\', $Backend' in ci and "'-m', 'app.v2_clean_bootstrap_admin'" not in ci
                and 'v2_clean_bootstrap_admin.py" -Destination' not in ci and "'-I', '-X', 'utf8', \"$K\\v2_clean_bootstrap_admin.py\"" in ci)
with zipfile.ZipFile(Path(args.package_dir) / 'backend-src.zip') as z:
    entries = set(z.namelist())
    release = z.read(f'{args.release_id}/backend/app/v2_bootstrap_admin.py').decode('utf-8')
release_old_path = 'init_auth_db()' in release and f'{args.release_id}/backend/app/v2_clean_bootstrap_admin.py' not in entries
print('CB.static', 'PASS' if static_ok and installer_ok and release_old_path else 'FAIL',
      'clean entry excludes init/migrate; installer runs it once from the kit (--backend), not from app\\; release legacy entry identified')

events = []
import tempfile
tmp = tempfile.mkdtemp(prefix='cb-')          # synthetic backend dir: only app\v2_auth.py for the path guard; modules are fakes
(Path(tmp) / 'app').mkdir()
(Path(tmp) / 'app' / 'v2_auth.py').write_text('# synthetic marker\n', encoding='utf-8')
app = types.ModuleType('app'); app.__path__ = []
audit = types.ModuleType('app.audit')
audit.record = lambda db, who, action, actor_user_id=None: events.append(('audit', who, action, actor_user_id))
database = types.ModuleType('app.database')
auth = types.ModuleType('app.v2_auth')
class Session:
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def commit(self): events.append('commit')
class AdminExists(RuntimeError):
    pass
database.SessionLocal = Session
auth.AdminExists = AdminExists
auth.check_auth_schema = lambda: events.append('schema')
def create_user(name, email, password, role, require_no_admin=False):
    events.append(('create', name, email, password, role, require_no_admin)); return {'id': 7}
auth.create_user = create_user
auth.init_auth_db = lambda: (_ for _ in ()).throw(AssertionError('unexpected init'))
auth.migrate_auth_db = lambda: (_ for _ in ()).throw(AssertionError('unexpected migrate'))
app.audit = audit
saved_modules = {name: sys.modules.get(name) for name in ('app', 'app.audit', 'app.database', 'app.v2_auth')}
saved_argv, saved_getpass, saved_path = sys.argv, getpass.getpass, list(sys.path)
ok = blocked_ok = exists_ok = guard_ok = False
try:
    sys.modules.update({'app': app, 'app.audit': audit, 'app.database': database, 'app.v2_auth': auth})
    sys.argv = [str(script), '--backend', tmp, '--name', 'Synthetic Admin', '--email', 'admin@example.test']
    answers = iter(('synthetic-pass-123', 'synthetic-pass-123'))
    getpass.getpass = lambda prompt: next(answers)
    output = io.StringIO()
    with contextlib.redirect_stdout(output): runpy.run_path(str(script), run_name='__main__')
    ok = (events == ['schema', ('create', 'Synthetic Admin', 'admin@example.test', 'synthetic-pass-123', 'admin', True),
                     ('audit', 'admin', 'user.create_admin', 7), 'commit']
          and 'admin@example.test' not in output.getvalue() and 'synthetic-pass-123' not in output.getvalue()
          and sys.path[0] == str(Path(tmp).resolve()))
    print('CB.functional', 'PASS' if ok else 'FAIL', 'strict check precedes create (require_no_admin); no migration; no credential output; backend on sys.path')
    events.clear()
    def blocked(): raise RuntimeError('invalid schema')
    auth.check_auth_schema = blocked
    try:
        with contextlib.redirect_stdout(io.StringIO()): runpy.run_path(str(script), run_name='__main__')
    except RuntimeError as exc:
        blocked_ok = str(exc) == 'invalid schema' and not events
    print('CB.invalid-schema', 'PASS' if blocked_ok else 'FAIL', 'no create on schema error')
    auth.check_auth_schema = lambda: events.append('schema')
    def exists(*a, **k): raise AdminExists()
    auth.create_user = exists
    answers = iter(('synthetic-pass-123', 'synthetic-pass-123'))
    events.clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()): runpy.run_path(str(script), run_name='__main__')
    except SystemExit as exc:
        exists_ok = 'уже існує' in str(exc) and events == ['schema']
    print('CB.admin-exists', 'PASS' if exists_ok else 'FAIL', 'second admin refused, no audit record')
    sys.argv = [str(script), '--backend', str(Path(tmp) / 'missing'), '--name', 'X', '--email', 'x@example.test']
    try:
        runpy.run_path(str(script), run_name='__main__'); guard_ok = False
    except SystemExit as exc:
        guard_ok = '--backend' in str(exc)
    print('CB.backend-guard', 'PASS' if guard_ok else 'FAIL', '--backend without app\\v2_auth.py refused before any import')
finally:
    sys.argv, getpass.getpass = saved_argv, saved_getpass
    sys.path[:] = saved_path
    for name, value in saved_modules.items():
        if value is None: sys.modules.pop(name, None)
        else: sys.modules[name] = value
    import shutil; shutil.rmtree(tmp, ignore_errors=True)
if not (static_ok and installer_ok and release_old_path and ok and blocked_ok and exists_ok and guard_ok): raise SystemExit(1)
