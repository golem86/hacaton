"""
mutate.py — відтворюваний mutation runner комплекту installer-а V2 (етап 4). Кожна мутація — копія комплекту з ОДНІЄЮ зміною
(повернення дефекту або вимкнення safety-перевірки) → відповідні тести мають дати exit ≠ 0 і FAIL з очікуваними ID.

Запуск:  python -I mutate.py --py <python для PS-тестів і J*> [--release-backend <…\\backend>] [--release-py <python з залежностями>]
         [--only M1,MJ2] [--log <файл>] [--jobs N]   (N > 1 — мутанти паралельно, кожен у власній копії комплекту; журнал — у порядку MUT)
Код виходу: 0 — усі мутації виявлено; 1 — є мутація, що вижила (тести її не помітили).
"""
import sys as _sys
_sys.dont_write_bytecode = True          # не лишати __pycache__ у каталозі комплекту
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile

for _st in (sys.stdout, sys.stderr):
    _st.reconfigure(encoding="utf-8", errors="backslashreplace")
args = sys.argv[1:]
opt = lambda n, d=None: args[args.index(n) + 1] if n in args else d
KIT = os.path.dirname(os.path.abspath(__file__))
PY = opt("--py", sys.executable)
REL, RELPY = opt("--release-backend"), opt("--release-py")
DEPLOY = opt("--deploy-zip")
ONLY = opt("--only")
LOG = opt("--log")
JOBS = max(1, int(opt("--jobs", "1")))
PS = opt("--ps") or os.path.join(os.environ["SystemRoot"], r"System32\WindowsPowerShell\v1.0\powershell.exe")   # за замовчуванням — цільовий 5.1
C, T, DB, LA = "V2-install-common.ps1", "test-rev3-negative.ps1", "v2_db_tool.py", "v2_job_launcher.py"


def between(start, end, repl=""):
    def f(s):
        i = s.index(start); j = s.index(end, i)
        return s[:i] + repl + s[j:]
    return f


def sub(old, new):
    def f(s):
        assert s.count(old) == 1, f"мутація: якір зустрічається {s.count(old)} раз: {old[:70]}"
        return s.replace(old, new)
    return f


# (id, файл, перетворення, набори тестів, очікувані FAIL-ID, опис)
# Увага: у PowerShell -and/-or мають однаковий пріоритет — вимикати умову цілком (if ($false)), а не префіксом «$false -and».
MUT = [
    ("M1", C, between("        $h = $null; $openErr = $null", "        $Tree.Add((New-V2Identity -Process $h -ExpectedParent $par.Pid",
                      "        $h = $null; try { $h = Open-V2ProcessHandle $cid } catch { continue }\n"), ["ps"], ["H1", "H4", "H5"], "B1: мовчазний catch { continue }"),
    ("M2", C, lambda s: between("  foreach ($u in $unres) {", "  if ($tree) {\n    $roots")(s).replace("  if ($unres.Count) { Stop-V2 \"CRITICAL BLOCKED — ${Name}: нерозв'язані нащадки — доказ зупинки не створюється\" }   # захист від регресії\n", ""),
     ["ps"], ["H1"], "B1: нерозв'язані нащадки не блокують доказ"),
    ("M3", C, sub("  $out.Add((Assert-V2RestoreItems -DataDir $DataDir -Items $Items))", "  $null = 0"), ["ps"], ["K1", "K3", "K8"], "B3: без валідації набору БД"),
    ("M4", C, sub("if (-not ($ver -is [int]) -or $ver -ne $V2DbSet[$db])", "if ($false)"), ["ps"], ["K5", "K6", "K7"], "B3: без перевірки версій"),
    ("M5", C, sub("if ($bks.ContainsKey($bf.ToLowerInvariant()))", "if ($false)"), ["ps"], ["K8", "K9"], "B3: дублікати копій дозволено"),
    ("M6", C, sub("  if (-not $V2StopProof.ContainsKey($n) -or $null -eq $V2StopProof[$n]) { Stop-V2 'відновлення заборонено: немає доказу зупинки backend (успішний Stop-V2Service у цій сесії)' }",
                  "  if (-not $V2StopProof.ContainsKey($n)) { $V2StopProof[$n] = [pscustomobject]@{ Name = $n; Tree = $null; Unresolved = 0; VerifiedUtc = [datetime]::UtcNow; Completeness = 'job'; JobVerified = $true; JobActive = 0; OwnerScanAlive = 0 } }"),
     ["ps"], ["D3a"], "B3: відкат без доказу Stop-V2Service"),
    ("M7", C, sub("$sc = @(Use-V2Env -Vars @{ INTEGRITY_DB = (Join-Path $DataDir 'integrity_v2.db'); V2_AUTH_DB = (Join-Path $DataDir 'v2_auth.db') } -Body { ", "$sc = @(& { "), ["ps"], ["D3k"], "B3: схема без INTEGRITY_DB/V2_AUTH_DB"),
    ("M8", C, sub(" -or $pr.Unresolved -ne 0)", ")"), ["ps"], ["K15"], "B3: доказ із нерозв'язаними нащадками приймається"),
    ("MA1", DB, sub('add("A07", not bad,', 'add("A07", True,'), ["auth"], ["N05.email", "N06.email-none", "N06.token-nocase"], "auth: UNIQUE/COLLATE не перевіряється"),
    ("MA2", DB, sub('add("A10", not bad,', 'add("A10", True,'), ["auth"], ["N11.role-none", "N11.purpose"], "auth: CHECK не перевіряється"),
    ("MA3", DB, sub('add("A12", not extra and not lack,', 'add("A12", True,'), ["auth"], ["N14.trigger", "N14.view", "N14.table"], "auth: сторонні об'єкти не перевіряються"),
    ("MA4", DB, sub('add("A11", "v2_dev_mail" not in cat["tables"],', 'add("A11", True,'), ["auth"], ["N13"], "auth: v2_dev_mail дозволено"),
    ("MA5", DB, sub('add("A04", not fk,', 'add("A04", True,'), ["auth"], ["N10"], "auth: foreign_key_check не перевіряється"),
    ("MA6", DB, sub('add(2, uv == version,', 'add(2, True,'), ["auth"], ["N15.v0", "N15.v2"], "auth: версія не перевіряється"),
    ("MA7", C, sub("if ($it.Db -eq 'v2_auth.db') {                                                            # етап 1: строга схема auth — ДО мутації", "if ($false) {"),
     ["ps"], ["R06.auth-incomplete"], "відкат: без строгої перевірки копії auth до мутації"),
    ("MA8", C, sub("if ($it.Db -eq 'v2_auth.db') {                                                          # етап 1: строга схема ВІДНОВЛЕНОЇ auth-БД", "if ($false) {"),
     ["ps"], ["R09.auth"], "відкат: без строгої перевірки відновленої auth"),
    ("MA9", C, sub("  if ($pr.Completeness -ne 'job' -or $pr.JobVerified -ne $true -or $pr.JobActive -ne 0 -or $pr.OwnerScanAlive -ne 0) {", "  if ($false) {"), ["ps"], ["R05.treeonly", "R05.jobactive"], "відкат: доказ без моделі повноти приймається"),
    ("MJ1", LA, sub("REQUIRED_LIMITS = KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION\n", "REQUIRED_LIMITS = KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION | BREAKAWAY_OK\n"),
     ["job:J02,J16"], ["J02", "J16.expected"], "Job: breakaway дозволено"),
    ("MJ2", LA, sub('        if not api.UpdateProcThreadAttribute(alist, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, harr, ctypes.sizeof(harr), None, None):\n            raise Win32Error("UpdateProcThreadAttribute(HANDLE_LIST)")\n', ""),
     ["job:J05,J15"], ["J15"], "Job: без whitelist handle (успадковується все)"),
    ("MJ3", LA, sub("REQUIRED_LIMITS = KILL_ON_JOB_CLOSE | DIE_ON_UNHANDLED_EXCEPTION\n", "REQUIRED_LIMITS = DIE_ON_UNHANDLED_EXCEPTION\n"), ["job:J01,J11"], ["J01", "J11"], "Job: без KILL_ON_JOB_CLOSE"),
    ("MJ4", LA, sub("        if not is_in_job(pi.hProcess, job):\n            raise Stop(", "        if False:\n            raise Stop("), ["job:J04"], ["J04.assign"], "Job: без перевірки членства до ResumeThread"),
    ("MJ5", LA, sub('                pr.append(f"у job живі процеси: ActiveProcesses={rep[\'active\']}, PID {pids}")', "                pass"), ["job:J08"], ["J08.running"], "Job: proof ігнорує живі процеси"),
    ("MJ6", LA, sub("    if sorted(aces) != want:", "    if False:"), ["job:J12"], ["J12.extra-ace", "J12.admins-full"], "Job: DACL job не перевіряється"),
    ("MJ7", LA, sub("    if err == ERROR_ALREADY_EXISTS:", "    if False:"), ["job:J03,J19"], ["J03", "J19"], "Job: захист від підміни/конкурентного імені вимкнено"),
    ("MJ8", LA, sub("def query_pids(job, tries=6):", "def query_pids(job, tries=1):"), ["job:J17"], ["J17.resize-retry"], "Job: без повторів PID-list"),
    ("MS1", C, sub("      if ($post.verdict -ne 'PASS') {", "      if ($false) {"), ["ps"], ["S07", "S08"], "Stop-V2Service: вердикт job після stop ігнорується"),
    ("MS2", C, sub("if ([int]$t.Pid -ne [int]$lau[0].Pid -and $desc.ContainsKey([int]$t.Pid) -and $inJob -notcontains [int]$t.Pid)", "if ($false)"), ["ps"], ["S06.membership"], "Stop-V2Service: членство в job не перевіряється"),
    ("MS3", C, sub("if ($Name -eq 'integrity-v2-backend' -and (Test-Path -LiteralPath \"$V2Root\\data\")) {", "if ($false) {"), ["ps"], ["S10"], "Stop-V2Service: блокування DB/WAL/SHM не перевіряються"),
    ("MS4", C, sub("      $holder = Start-V2JobHolder -JobName $jobName\n", "      $holder = $null\n"), ["ps"], ["S06.hold"], "Stop-V2Service: handle job не утримується"),
    ("MB1", C, sub("        if ($problems.Count -or -not $pre -or -not $pre.found -or -not $pre.sd_ok -or -not $pre.limits_ok -or -not $post.sd_ok -or -not $post.limits_ok) {", "        if ($false) {"), ["ps"], ["S06.limits", "S06.sd"], "B-01: terminate викликається після невірних SD/limits"),
    ("MB2", C, sub("  $V2StopProof.Remove($Name)  # до будь-якого early return", "  # stale proof навмисно залишено"), ["ps"], ["B02.absent", "B02.restore"], "B-02: stale stop proof після відсутньої служби"),
    ("MB3", C, between("  if ($fresh.verdict -ne 'PASS'", "  $null = Assert-V2DbFilesFree -DataDir $DataDir                                              # W3", "  if ($false) { }\n"), ["ps"], ["B03.late-sid", "W2.after"], "B-03: фінальний scan пропущено перед DB mutation"),
    ("MW1", C, sub("    Set-V2ServiceStartMode -Name $n -Mode Disabled\n", ""), ["ps"], ["W.ok"], "auditfix2 W1: start type не переводиться в Disabled"),
    ("MW2", C, sub("if (-not $now -or $now.StartMode -ne 'Disabled' -or $now.State -ne 'Stopped' -or $now.ProcessId)", "if ($false)"), ["ps"], ["W5.startmode", "W5.running"], "auditfix2 W5: стан служби наприкінці не перевіряється"),
    ("MW3", C, sub("    if ($end.verdict -ne 'PASS' -or [int]$end.active -ne 0 -or @($end.pids).Count -ne 0 -or @($end.scan.alive).Count -ne 0 -or @($end.scan.unknown).Count -ne 0) {", "    if ($false) {"), ["ps"], ["W5.scan"], "auditfix2 W5: scan наприкінці не перевіряється"),
    ("MW4", C, sub("if ((Get-FileHash -LiteralPath $k -Algorithm SHA256).Hash -ne $hash[$k])", "if ($false)"), ["ps"], ["W5.hash"], "auditfix2 W5: SHA256 відновлених БД не перевіряється"),
    ("MW5", C, sub("    if ($pf -and $pf.PSObject.Properties['Lease'] -and $pf.Lease) { try { Stop-V2JobHolder -Holder $pf.Lease }", "    if ($false) { try { Stop-V2JobHolder -Holder $pf.Lease }"), ["ps"], ["W.ok", "L.items", "L.mutation"], "auditfix2: lease не звільняється після відкату"),
    ("MW6", C, sub("if ($ctx.StartTypeChanged -and -not $ctx.MutationStarted)", "if ($false)"), ["ps"], ["W2.after", "W1.fail"], "auditfix2: start type не повертається після відмови до мутації"),
    ("MW7", C, sub("  $Ctx.MutationStarted = $true", "  $null = 0"), ["ps"], ["L.mutation", "W5.hash"], "auditfix2: після мутації start type повертається (має лишатися Disabled)"),
    ("ML1", C, sub("  $prevProof = $V2StopProof[$Name]; $V2StopProof.Remove($Name)", "  $prevProof = $null"), ["ps"], ["L.start-invalidates"], "auditfix2: старт не інвалідує proof/lease"),
    ("ML2", C, sub("      if ($ctx.Holder) { try { Stop-V2JobHolder -Holder $ctx.Holder }", "      if ($false) { try { Stop-V2JobHolder -Holder $ctx.Holder }"), ["ps"], ["L.stop-throw"], "auditfix2: holder не звільняється при відмові Stop-V2Service"),
    ("MR1", C, sub("if (-not $scanOnly -or $try -eq 5) { break }", "break"), ["ps"], ["J.retry-transient"], "auditfix2: без повтору scan для короткоживучих процесів"),
    ("MR2", C, sub("    $scanOnly = $Scan -and $r.verdict -ne 'PASS' -and $r.found -and $r.sd_ok -and $r.limits_ok -and [int]$r.active -eq 0 -and @($r.pids).Count -eq 0", "    $scanOnly = $Scan -and $r.verdict -ne 'PASS'"), ["ps"], ["J.retry-jobnotempty"], "auditfix2: повтор і для непорожнього job"),
    ("MW8", C, sub("    foreach ($k in $hash.Keys) { $out.Add((Assert-V2SqliteSidecars -DbPath $k)) }", "    $null = 0"), ["ps"], ["SC.wal", "SC.journal", "SC.empty-ok"], "auditfix3 P0: sidecar-и SQLite не перевіряються"),
    ("MW9", C, sub("if ($mode -eq 'rollback' -and $st['-shm'] -ge 0)", "if ($false)"), ["ps"], ["SC.shm-rollback"], "auditfix3: -shm у rollback-режимі дозволено"),
    ("MW10", C, sub("if ($st['-journal'] -gt 0)", "if ($false)"), ["ps"], ["SC.journal"], "auditfix3: непорожній -journal (hot journal) дозволено"),
    ("MO1", C, sub(" -and -not ($V2OwnHelpers.ContainsKey([int]$_.ProcessId) -and [math]::Abs((ConvertTo-V2Ticks $_.CreationDate) - $V2OwnHelpers[[int]$_.ProcessId]) -le 20000)", ""), ["ps"], ["OH.excluded"], "auditfix3: власний процес утримання вважається процесом V2"),
    ("MC1", C, sub("  if (-not @($all | Where-Object { $_ -match '^(CLEAN-INIT-OK|RESTORE-OK)-' }).Count) {", "  if ($false) {"), ["ps"], ["CI.ready-none", "CI.start-blocked"], "Clean Install: старт без позитивного маркера ініціалізації"),
    ("MC2", C, sub("  if ($pre.Count) { Stop-V2", "  if ($false) { Stop-V2"), ["ps"], ["CI.init-notempty"], "Clean Install: ініціалізація поверх наявних БД"),
    ("MC3", C, sub("$ab = Invoke-V2DbTool -Py $Py -DbTool $DbTool -ArgList @('auth-schema', $ba)", "$ab = 'AUTH SCHEMA OK (mutant)'"), ["ps"], ["CI.complete-badbackup"], "Clean Install: фінальна копія v2_auth без строгої перевірки"),
    ("MC4", C, sub('  if ($problems.Count) { Stop-V2 "ПЕРЕРИВАННЯ НЕ ЗАВЕРШЕНО', '  if ($false) { Stop-V2 "ПЕРЕРИВАННЯ НЕ ЗАВЕРШЕНО'), ["ps"], ["CI.abort-stuck"], "Clean Install: корінь перейменовується, хоча служба лишилась"),
    ("MC20", C, between("  if (-not (Test-Path -LiteralPath $dataDir -PathType Container) -or\n", "    Stop-V2 'Abort: немає маркера невдалого встановлення", "  if ($false) {\n"), ["ps"], ["CI.abort-ready"], "Clean Install: -Abort без failed-маркерів зупиняє готове встановлення"),
    ("MC21", C, sub('    if ($path -ne $V2Services[$n].Exe) { Stop-V2 "Abort: PathName $n', '    if ($false) { Stop-V2 "Abort: PathName $n'), ["ps"], ["CI.abort-foreign"], "Clean Install: -Abort зупиняє сторонню однойменну службу"),
    ("MC22", C, sub('    if ($svcPath -ne $V2Services[$n].Exe) { $problems.Add(', '    if ($false) { $problems.Add('), ["ps"], ["CI.owned-replaced"], "Clean Install: fail-closed зупиняє замінену після callback службу"),
    ("MC5", C, sub("if ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() -ne $ExpectedSha256[$k])", "if ($false)"), ["ps"], ["CI.tools-tamper", "CI.tools-default"], "Clean Install: SHA256 інструментів не перевіряється"),
    ("MC6", C, sub("  if (-not $AllowAbsent) {", "  if ($true) {"), ["ps"], ["CI.v1-absent"], "Clean Install: V1 обов'язкова (залежність від V1)"),
    ("MC7", C, sub('$null = Assert-V2DataReady -DataDir "$V2Root\\data" } },', '$null = Assert-V2NoRestoreBlock -DataDir "$V2Root\\data" } },'), ["ps"], ["CI.start-blocked"], "Clean Install: стандартний PreCheck без перевірки ініціалізації"),
    ("MC8", C, sub("Port = 443; Job = $null }", "Port = 443 }"), ["ps"], ["CI.stop-caddy"], "запис Caddy без поля Job (зупинка Caddy падає під StrictMode)"),
    ("MC9", C, sub("  if ($mk.Count -ne 1 -or $mk[0] -notmatch '^CLEAN-INIT-IN-PROGRESS-') {", "  if ($false) {"), ["ps"], ["CI.complete-state"], "Clean Install: Complete за невизначеного стану маркерів"),
    ("MCS1", "clean-install.ps1", sub("  Stage '4.6 служба backend'\n", "  Stage '4.6 служба backend'\n  $null = Invoke-V2DbRestore -DataDir $D -Known @() -Py $Py -DbTool $DbTool -Items @()\n"), ["cistatic"], ["CI-S1"], "Clean Install викликає механізм Rollback"),
    ("MCS2", "clean-install.ps1", sub('$WinSWSrc = "$V2Root\\pkg\\tools\\winsw\\integrity-v2-winsw.exe"', "$WinSWSrc = 'C:\\Users\\Public\\HacatonServer\\tools\\services\\HacatonBackend.exe'"), ["cistatic"], ["CI-S3", "CI-S4"], "Clean Install бере WinSW із каталогу V1"),
    ("MC10", C, lambda t: sub("    [IO.File]::WriteAllText((Join-Path $dataDir \"CLEAN-INIT-FAILED-INSTALL-$ts.txt\"), \"збій Clean Install $ts`nпричина: $Reason`n\", $enc)\n", "")(sub("      Rename-Item -LiteralPath $ok.FullName -NewName ($ok.Name -replace '^CLEAN-INIT-OK-', 'CLEAN-INIT-REVOKED-') -ErrorAction Stop\n", "")(t)), ["ps"], ["CI.late-4.6", "CI.late-4.7", "CI.late-5"], "CI-01: пізній збій не інвалідує READY у data\\ (немає FAILED-INSTALL і відкликання OK)"),
    ("MC11", C, sub("$bad = @($all | Where-Object { $_ -match '^CLEAN-INIT-' -and $_ -notmatch '^CLEAN-INIT-OK-' })", "$bad = @($all | Where-Object { $_ -match '^CLEAN-INIT-(IN-PROGRESS|FAILED)-' })"), ["ps"], ["CI.ready-ok+revoked", "CI.ready-ok+unknown"], "CI-01: Assert-V2DataReady приймає REVOKED/невідомий маркер (стара перевірка)"),
    ("MC12", C, sub("Get-ChildItem -LiteralPath $root -File -Force -Filter 'CLEAN-INSTALL-FAILED-*'", "Get-ChildItem -LiteralPath $root -File -Force -Filter 'NO-SUCH-*'"), ["ps"], ["CI.ready-rootfailed"], "CI-01: маркер невдалого встановлення в корені ігнорується"),
    ("MC13", C, sub("    try { Set-V2ServiceStartMode -Name $n -Mode Disabled; $out.Add(\"PASS  $n → Disabled\") }", "    try { $out.Add(\"PASS  $n → Disabled\") }"), ["ps"], ["CI.late-4.6", "CI.late-4.7", "CI.late-5"], "CI-01: служби V2 лишаються Manual (ручний sc start можливий)"),
    ("MC14", C, sub("  foreach ($n in 'integrity-v2-caddy', 'integrity-v2-backend') {                 # (4)+(5) лише служби V2\n", "  Remove-Item -LiteralPath (Join-Path $dataDir 'v2_auth.db') -Force -ErrorAction SilentlyContinue\n  foreach ($n in 'integrity-v2-caddy', 'integrity-v2-backend') {                 # (4)+(5) лише служби V2\n"), ["ps"], ["CI.late-4.6", "CI.late-4.7", "CI.late-5"], "CI-01: fail-closed видаляє БД"),
    ("MC15", C, sub("  if ($problems.Count) { Stop-V2 \"FAIL-CLOSED НЕ ЗАВЕРШЕНО", "  if ($false) { Stop-V2 \"FAIL-CLOSED НЕ ЗАВЕРШЕНО"), ["ps"], ["CI.late-markerfail", "CI.late-nodisable"], "CI-01: незавершений fail-closed звітує успіх"),
    ("MCS3", "clean-install.ps1", sub("  try { Invoke-V2CleanInstallFailClosed -Reason $why -OwnedServices @($OwnedServices) }", "  try { }"), ["cistatic"], ["CI-S6"], "CI-01: catch оркестратора не інвалідує READY (поведінка до виправлення)"),
    ("MCS4", "clean-install.ps1", sub("  if (-not $Owned) {", "  if ($false) {"), ["cistatic"], ["CI-S6"], "CI-01: fail-closed діє і на чуже (наявне) встановлення"),
    ("MC16", C, sub("  if ($busy.Count) { Stop-V2 \"порти V2 зайняті", "  if ($false) { Stop-V2 \"порти V2 зайняті"), ["ps"], ["CI.ports-tcp8100", "CI.ports-udp443"], "C3: зайняті порти V2 не блокують Clean Install"),
    ("MC17", C, sub("    try { $null = Set-V2InitMarker -DataDir $DataDir -From $mk -To FAILED -Note \"причина: $why\" } catch { }\n", ""), ["ps"], ["CI.fault-seed", "CI.fault-migrations"], "C7: збій ініціалізації не маркує FAILED (IN-PROGRESS лишається)"),
    ("MCS5", "clean-install.ps1", sub("  Assert-V2PortsFree                                                         # C3", "  # (mutant) без перевірки портів"), ["cistatic"], ["CI-S7"], "C3: preflight без перевірки портів"),
    ("MC18", C, sub("  if ([int]$h.Build -ne $ExpectedWindowsBuild) {", "  if ($false) {"), ["ps"], ["CI.host-build"], "C3: збірка Windows не перевіряється"),
    ("MC19", C, sub("  if ([long]$h.FreeBytes -lt $MinFreeBytes) {", "  if ($false) {"), ["ps"], ["CI.host-space"], "C3: вільне місце не перевіряється"),
    ("MB4", "run-all.ps1", sub(" -and $nr -eq 0", ""), ["gate"], ["B04.required-not-run"], "B-04: required NOT RUN помилково приймається"),
    ("MR00", C, sub("  [V2AtomicRoot]::Create($V2Root, $sec.GetSecurityDescriptorBinaryForm())\n  & $OnCreated ([guid]::NewGuid().ToString('N'))", "  & $OnCreated ([guid]::NewGuid().ToString('N'))\n  [V2AtomicRoot]::Create($V2Root, $sec.GetSecurityDescriptorBinaryForm())"), ["root"], ["R00.race", "R00.create-fail"], "R-00: owned до успішного atomic create"),
    ("MR00S", C, sub("    if ($OwnedServices -notcontains $n) {", "    if ($false) {"), ["ps"], ["CI.foreign-service"], "R-00: fail-closed stop/disable чужої служби"),
    ("MR01", C, sub("  $xml = $xml.Replace('name=\"FRONTEND_ORIGINS\" value=\"https://' + $prodHost + '\"', 'name=\"FRONTEND_ORIGINS\" value=\"https://' + $HostName + '\"')", "  # origin залишається production"), ["ps"], ["CI.target-staging"], "R-01: test-host origin не змінено"),
    ("MR02", C, sub('  catch { Stop-V2 "TCP enumeration неможлива: $($_.Exception.Message)" }', '  catch { @() }'), ["ps"], ["CI.ports-tcp-error"], "R-02: TCP API error сприйнято за вільний порт"),
    ("MR03", "test_v2_job.py", sub('    if "--local-only" not in sys.argv:\n        add("J10"', '    if True:\n        add("J10"'), ["r03"], ["R03.local-split"], "R-03: local-only включає host-only J10"),
    ("MR04", "clean-install.ps1", sub("'-m', 'app.v2_clean_bootstrap_admin'", "'-m', 'app.v2_bootstrap_admin'"), ["bootstrap"], ["CB.static"], "R-04: повернення bootstrap з init_auth_db/migrate_auth_db"),
    ("MR01D", C, sub("if (@(Compare-Object -ReferenceObject @($approved | Sort-Object -Unique) -DifferenceObject @($resolved | Sort-Object -Unique)).Count)", "if ($false)"), ["r01"], ["R01.extra-dns"], "R-01: зайву DNS-адресу прийнято"),
    ("MR01R", C, sub("  $null = Assert-V2TargetIdentity -HostName $HostName -Addresses $Addresses -TestHost:$TestHost", "  # DNS recheck пропущено"), ["r01"], ["R01.rebinding"], "R-01: DNS recheck перед HTTPS пропущено"),
    ("MR01P", C, sub("'--noproxy','*','--resolve',\"${HostName}:${Port}:$address\",'--request'", "'--noproxy','*','--request'"), ["r01"], ["R01.pinned-endpoint"], "R-01: HTTPS endpoint не прив'язано"),
    ("MR01T", C, sub("@('--disable','--silent'", "@('--disable','--insecure','--silent'"), ["r01"], ["R01.pinned-endpoint"], "R-01: TLS certificate check вимкнено"),
    ("MR01N", C, sub("'--noproxy','*','--resolve'", "'--resolve'"), ["r01"], ["R01.pinned-endpoint"], "R-01: проксі може обійти pinned endpoint"),
    ("MR01W", "clean-install.ps1", sub("Assert-V2PinnedHttps @PinnedHttps -Path '/assets/missing.js' -Expected 404", "Assert-V2Http -Url \"$H/assets/missing.js\" -Expected 404"), ["cistatic"], ["CI-S9"], "R-01: один HTTPS smoke повернуто до DNS-залежного клієнта"),
]


def run_suite(kit, suite, tmp=None):
    if suite == "ps":
        cmd = [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", os.path.join(kit, T), "-Py", PY]
    elif suite == "static":
        cmd = [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", os.path.join(kit, "static-rev3.ps1")]
    elif suite == "auth":
        cmd = [PY, "-I", os.path.join(kit, "test_v2_auth_schema.py"), "--tool", os.path.join(kit, DB)] + (["--release-backend", REL, "--release-py", RELPY] if REL else [])
    elif suite.startswith("job:"):
        cmd = [PY, "-I", os.path.join(kit, "test_v2_job.py"), "--only", suite[4:]]
    elif suite == "cistatic":
        cmd = [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", os.path.join(kit, "static-clean-install.ps1")]
    elif suite == "gate":
        cmd = [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", os.path.join(kit, "test-audit-gate.ps1"), "-Py", PY]
    elif suite == "root":
        cmd = [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", os.path.join(kit, "test-clean-root-race.ps1")]
    elif suite == "bootstrap":
        if not DEPLOY: raise RuntimeError('bootstrap mutation requires --deploy-zip')
        cmd = [PY, "-I", os.path.join(kit, "test-clean-bootstrap.py"), "--deploy-zip", DEPLOY]
    elif suite == "r03":
        cmd = [PY, "-I", os.path.join(kit, "test-r03-gate.py"), "--ps", PS]
    elif suite == "r01":
        cmd = [PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", os.path.join(kit, "test-r01-target.ps1")]
    env = None
    if tmp:                                  # власний %TEMP% мутанта: паралельні прогони не бачать тимчасових каталогів один одного
        env = dict(os.environ, TEMP=tmp, TMP=tmp)
    r = subprocess.run(cmd, capture_output=True, timeout=1800, env=env)
    out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
    return r.returncode, sorted(set(m.group(1) for m in re.finditer(r"(?m)^(\S+)\s+FAIL\s", out))), cmd, out


if "--check" in args:                     # лише перевірити, що кожна мутація однозначно застосовна (без тестів)
    bad = 0
    for mid, fname, fn, suites, expect, desc in MUT:
        raw = open(os.path.join(KIT, fname), "rb").read(); src = raw[3 if raw.startswith(b"\xef\xbb\xbf") else 0:].decode("utf-8")
        try:
            ok = fn(src) != src
        except Exception as e:
            ok = False; print(mid, "ERROR", e)
        bad += 0 if ok else 1
        print(f"{mid:<5} {'OK' if ok else 'BAD'} {desc}")
    sys.exit(1 if bad else 0)

lines = [f"# mutate.py — {datetime.datetime.now():%Y-%m-%d %H:%M:%S}; kit {KIT}; python {PY}; паралельно: {JOBS}", ""]


def run_mutant(spec):
    """Одна мутація у власній тимчасовій копії комплекту → (рядок журналу, вижила?)."""
    mid, fname, fn, suites, expect, desc = spec
    d = tempfile.mkdtemp(prefix=f"v2-mut-{mid}-")
    try:
        kit = os.path.join(d, "kit"); shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns("*.log", "__pycache__"))
        tmp = os.path.join(d, "tmp"); os.makedirs(tmp)
        p = os.path.join(kit, fname); raw = open(p, "rb").read()
        bom = raw.startswith(b"\xef\xbb\xbf"); src = raw[3 if bom else 0:].decode("utf-8")
        mutated = fn(src)
        assert mutated != src, f"{mid}: мутація не змінила файл"
        open(p, "wb").write((b"\xef\xbb\xbf" if bom else b"") + mutated.encode("utf-8"))
        fails, codes = [], []
        for s_ in suites:
            code, f, cmd, raw_output = run_suite(kit, s_, tmp)
            codes.append(f"{s_}:exit={code}"); fails += f
            if "ERR" in f: codes.append("ERR=" + next((line[:500] for line in raw_output.splitlines() if line.startswith('ERR ')), 'unknown'))
            if code and not f: codes.append("OUTPUT=" + raw_output[:350].replace('\n', ' '))
        killed = all(not c.endswith("exit=0") for c in codes) and all(e in fails for e in expect)
        return f"{mid:<5} {'KILLED' if killed else 'SURVIVED':<9} {desc}: {', '.join(codes)}; FAIL: {','.join(fails) or '—'} (очікувано серед них: {','.join(expect)})", not killed
    except Exception as e:
        return f"{mid:<5} ERROR     {desc}: {e}", True
    finally:
        shutil.rmtree(d, ignore_errors=True)


todo = [m for m in MUT if not ONLY or m[0] in ONLY.split(",")]
res = {}
if JOBS == 1:
    for m in todo:
        res[m[0]] = run_mutant(m); print(res[m[0]][0], flush=True)
else:
    from concurrent.futures import ThreadPoolExecutor, as_completed   # потоки лише чекають на дочірні процеси тестів
    with ThreadPoolExecutor(max_workers=JOBS) as ex:
        fut = {ex.submit(run_mutant, m): m[0] for m in todo}
        for f in as_completed(fut):
            res[fut[f]] = f.result(); print(res[fut[f]][0], flush=True)
survivors = sum(1 for m in todo if res[m[0]][1])
lines += [res[m[0]][0] for m in todo]                                    # порядок журналу = порядок MUT (незалежно від завершення)
total = len([l for l in lines if re.match(r"^M\S*\s+(KILLED|SURVIVED|ERROR)", l)])
lines += ["", f"# результат: {total - survivors}/{total} мутацій виявлено; вижили/помилки: {survivors}"]
print(lines[-1])
if LOG:
    open(LOG, "w", encoding="utf-8-sig").write("\n".join(lines) + "\n")
sys.exit(1 if survivors else 0)
