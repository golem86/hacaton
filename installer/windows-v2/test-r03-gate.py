"""R-03: local-only cannot silently turn required WinSW runtime into C3 PASS."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--ps', required=True)
args = parser.parse_args()
kit = Path(__file__).resolve().parent
job = kit / 'test_v2_job.py'
full = subprocess.run([sys.executable, '-I', str(job), '--only', 'J10'], capture_output=True, text=True)
local = subprocess.run([sys.executable, '-I', str(job), '--only', 'J10', '--local-only'], capture_output=True, text=True)
ok = full.returncode == 0 and 'J10' in full.stdout and 'NOT RUN' in full.stdout and 'J10' not in local.stdout and local.returncode == 0
print('R03.local-split', 'PASS' if ok else 'FAIL', 'full records J10 NOT RUN; local-only omits host-only scenario')
with tempfile.TemporaryDirectory(prefix='v2-r03-gate-') as d:
    d = Path(d)
    summary = d/'RUN-SUMMARY.txt'; runtime = d/'runtime.log'; matrix = d/'matrix.tsv'
    summary.write_text('# scope=LOCAL T0 ONLY\nstatic-clean-install   exit=0 PASS=7 FAIL=0 NOT_RUN=0 → PASS\ntest_v2_job            exit=0 PASS=1 FAIL=0 NOT_RUN=0 → PASS\n', encoding='utf-8')
    runtime.write_text('J10.start PASS synthetic\n', encoding='utf-8')
    matrix.write_text('', encoding='utf-8')
    merge = subprocess.run([args.ps, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(kit/'merge-c3-gate.ps1'), '-LocalSummary', str(summary), '-RuntimeLog', str(runtime), '-MatrixTsv', str(matrix), '-V1Absent'], capture_output=True, text=True, encoding='utf-8', errors='replace')
    blocked = merge.returncode != 0 and 'J10.stop' in merge.stdout and 'matrix T1' in merge.stdout
    print('R03.host-required', 'PASS' if blocked else 'FAIL', 'missing runtime/matrix evidence keeps C3/C8 blocked')
if not (ok and blocked): raise SystemExit(1)
