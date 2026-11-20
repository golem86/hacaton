# run-all.ps1 — відтворюваний прогін усього локального тестового комплекту installer-а V2 (етап 4) з журналами.
# Лише локально: тимчасові каталоги, власні процеси, Local\-job-и; служби, сервер, C:\srv, Git не змінюються.
param(
  [Parameter(Mandatory)] [string] $LogDir,
  [Parameter(Mandatory)] [string] $Py,           # Python для auth/job/PS-тестів (stdlib)
  [Parameter(Mandatory)] [string] $BackendPy,    # Python із залежностями backend (rehearse, AREL)
  [Parameter(Mandatory)] [string] $DeployZip,    # integrity-v2-dde86e6-deploy.zip (release backend для A00/AREL)
  [string] $Caddy,                              # caddy.exe 2.11.9 (adapt/validate для test-caddy-config і test-upgrade-inplace; без нього — NOT RUN)
  [string] $DistZip,                            # zip зібраного frontend (сумісність із CSP SPA, test-caddy-config C10)
  [switch] $WithMutation,
  [switch] $LocalOnly,                       # T0: тільки локально виконувані suite; J10/WinSW J18 — окремий host gate
  [ValidateRange(1, 16)] [int] $MutationJobs = 6,   # > 1 — мутанти паралельно (кожен у власній копії комплекту)
  [ValidateSet('powershell', 'pwsh')] [string] $Engine = 'powershell'   # цільове середовище installer-а — Windows PowerShell 5.1
)
$ErrorActionPreference = 'Continue'
$K = $PSScriptRoot
$PSX = if ($Engine -eq 'pwsh') { (Get-Command pwsh -ErrorAction Stop).Source } else { Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe' }
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if (-not (Test-Path $LogDir)) { $null = New-Item -ItemType Directory $LogDir }
$tmp = Join-Path $env:TEMP ('v2-runall-' + [guid]::NewGuid().ToString('N').Substring(0, 8)); $null = New-Item -ItemType Directory $tmp
$sum = New-Object System.Collections.Generic.List[string]
# Паралельний режим: кожен набір — окремий процес з ВЛАСНИМ %TEMP% (тести не бачать тимчасових каталогів один одного);
# журнали оформлюються після завершення в порядку оголошення наборів (порядок RUN-SUMMARY не залежить від часу завершення).
$suites = New-Object System.Collections.Generic.List[object]
function Start-Suite([string]$Name, [string]$Exe, [string[]]$A, [int[]]$PassCodes = @(0)) {
  $st = Join-Path $tmp "t-$Name"; $null = New-Item -ItemType Directory $st
  $argLine = ($A | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
  # System.Diagnostics.Process напряму (Start-Process у PS 5.1 без консолі інколи повертає ExitCode/ExitTime = $null); вивід — асинхронно (без deadlock)
  $psi = New-Object System.Diagnostics.ProcessStartInfo $Exe, $argLine
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $psi.EnvironmentVariables['TEMP'] = $st; $psi.EnvironmentVariables['TMP'] = $st; $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
  $start = Get-Date
  $p = [Diagnostics.Process]::Start($psi)
  $suites.Add([pscustomobject]@{ Name = $Name; Exe = $Exe; A = $A; PassCodes = $PassCodes; Proc = $p; Start = $start; OutTask = $p.StandardOutput.ReadToEndAsync(); ErrTask = $p.StandardError.ReadToEndAsync() })
}
function Complete-Suites {
  foreach ($s in $suites) {
    $s.Proc.WaitForExit(); $code = $s.Proc.ExitCode; $end = $s.Proc.ExitTime
    $out = @(foreach ($t in $s.OutTask, $s.ErrTask) { $t.Result -split "\r?\n" | Where-Object { $_ -ne '' } })
    $pass = @($out | Where-Object { $_ -match '^\S+\s+PASS\s' }).Count
    $fail = @($out | Where-Object { $_ -match '^\S+\s+(FAIL|SURVIVED|ERROR)\s' }).Count
    $nr = @($out | Where-Object { $_ -match '^\S+\s+NOT RUN\s' }).Count
    $kill = @($out | Where-Object { $_ -match '^\S+\s+KILLED\s' }).Count
    $verdict = if ($s.PassCodes -contains $code -and $fail -eq 0 -and $nr -eq 0) { 'PASS' } else { 'FAIL' }
    $cmd = "$($s.Exe) " + (($s.A | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' ')
    $hdr = @("# команда: $cmd", "# початок: $($s.Start.ToString('yyyy-MM-dd HH:mm:ss'))  кінець: $($end.ToString('yyyy-MM-dd HH:mm:ss'))  (паралельно, власний %TEMP%)",
             "# хост: Windows $([Environment]::OSVersion.Version); PowerShell $($PSVersionTable.PSVersion); без прав адміністратора: $(-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))", '')
    $ftr = @('', "# exit code: $code (очікувано: $($s.PassCodes -join '/'))", "# PASS: $pass; FAIL: $fail; NOT RUN: $nr$(if ($kill) { "; KILLED: $kill" }); результат: $verdict")
    [IO.File]::WriteAllLines((Join-Path $LogDir "$($s.Name).log"), [string[]]($hdr + $out + $ftr), (New-Object Text.UTF8Encoding $true))
    $sum.Add(('{0,-22} exit={1,-3} PASS={2,-4} FAIL={3,-3} NOT_RUN={4,-3}{5} → {6}' -f $s.Name, $code, $pass, $fail, $nr, $(if ($kill) { " KILLED=$kill" } else { '' }), $verdict))
  }
}
try {
  # release backend (для A00 / AREL): лише з перевіреного deploy ZIP
  if ((Get-FileHash -LiteralPath $DeployZip -Algorithm SHA256).Hash.ToLower() -ne 'd7c523a167eec578a03ed9b0ede62868aed1d4c59f50fbf2b78f997fbb79a5db') { throw 'deploy ZIP: SHA256 ≠ d7c523a1…' }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $z = [IO.Compression.ZipFile]::OpenRead($DeployZip); try { $e = $z.GetEntry('integrity-v2-dde86e6-backend-src.zip'); [IO.Compression.ZipFileExtensions]::ExtractToFile($e, "$tmp\backend-src.zip") } finally { $z.Dispose() }
  [IO.Compression.ZipFile]::ExtractToDirectory("$tmp\backend-src.zip", "$tmp\rel")
  $rel = "$tmp\rel\integrity-v2-dde86e6\backend"
  # маніфест релізу (BACKEND-SHA256.txt) — із перевіреного deploy ZIP; SHA джерел схеми checker бере лише з нього
  $relMan = "$tmp\rel-BACKEND-SHA256.txt"
  [IO.File]::WriteAllLines($relMan, [string[]]@(Get-ChildItem -LiteralPath $rel -Recurse -File | Sort-Object FullName | ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower())  backend/$($_.FullName.Substring($rel.Length + 1).Replace('\', '/'))" }), (New-Object Text.UTF8Encoding $false))
  Start-Suite 'test_v2_auth_schema' $Py @('-I', "$K\test_v2_auth_schema.py", '--tool', "$K\v2_db_tool.py", '--release-backend', $rel, '--release-manifest', $relMan, '--release-py', $BackendPy)
  Start-Suite 'test_v2_db_tool' $BackendPy @('-I', '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-rA', "$K\test_v2_db_tool.py")
  $cfgArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\test-caddy-config.ps1", '-Py', $BackendPy, '-DeployZip', $DeployZip)
  if ($Caddy) { $cfgArgs += @('-Caddy', $Caddy) }; if ($DistZip) { $cfgArgs += @('-DistZip', $DistZip) }
  Start-Suite 'test-caddy-config' $PSX $cfgArgs
  $upArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\upgrade\test-upgrade-inplace.ps1", '-Py', $BackendPy); if ($Caddy) { $upArgs += @('-Caddy', $Caddy) }
  Start-Suite 'test-upgrade-inplace' $PSX $upArgs
  Start-Suite 'test-ops-scripts' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\upgrade\test-ops-scripts.ps1", '-Py', $BackendPy)
  Start-Suite 'static-upgrade' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\upgrade\static-upgrade.ps1")
  Start-Suite 'test-clean-bootstrap' $Py @('-I', "$K\test-clean-bootstrap.py", '--deploy-zip', $DeployZip)
  Start-Suite 'test-clean-root-race' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\test-clean-root-race.ps1")
  Start-Suite 'test-service-partial-ownership' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\test-service-partial-ownership.ps1")
  Start-Suite 'test-atomic-compile' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\test-atomic-compile.ps1")
  Start-Suite 'test-r03-gate' $Py @('-I', "$K\test-r03-gate.py", '--ps', $PSX)
  Start-Suite 'test-r01-target' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\test-r01-target.ps1")
  Start-Suite 'test-r01-tls' $Py @('-I', "$K\test-r01-tls.py", '--ps', $PSX)
  $jobArgs = @('-I', "$K\test_v2_job.py"); if ($LocalOnly) { $jobArgs += '--local-only' }
  Start-Suite 'test_v2_job' $Py $jobArgs
  Start-Suite 'test-rev3-negative' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\test-rev3-negative.ps1", '-Py', $Py)
  Start-Suite 'test-audit-gate' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\test-audit-gate.ps1", '-Py', $Py)
  Start-Suite 'static-rev3' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\static-rev3.ps1")
  Start-Suite 'static-clean-install' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\static-clean-install.ps1")
  Start-Suite 'rehearse-rev3' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\rehearse-rev3.ps1", '-Root', "$tmp\rehearse", '-Py', $BackendPy, '-DeployZip', $DeployZip)
  # RH0: runtime-harness на НЕпогодженому хості має відмовити (exit 3) і нічого не створити
  $rhRoot = "$tmp\rh0-must-not-exist"
  Start-Suite 'runtime-harness-RH0' $PSX @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\runtime-harness.ps1", '-TestRoot', $rhRoot, '-BasePython', $Py, '-WinSWExe', "$tmp\no-winsw.exe", '-ApprovalRef', 'NONE') @(3)
  if ($WithMutation) { Start-Suite 'mutation' $Py @('-I', "$K\mutate.py", '--ps', $PSX, '--py', $Py, '--release-backend', $rel, '--release-py', $BackendPy, '--deploy-zip', $DeployZip, '--jobs', $MutationJobs) }
  Complete-Suites
  if ($LocalOnly) { $sum.Add('HOST-RUNTIME J10/J18 WinSW → NOT RUN; окремий host gate потрібний, C8/GO не визначено') }
  try { $svcCount = @(Get-CimInstance Win32_Service -Filter "Name='integrity-v2-jobtest'" -ErrorAction Stop).Count }
  catch { $svcCount = 'NOT RUN (CIM access denied)' }
  $sum.Add("runtime-harness-RH0: TestRoot створено: $(Test-Path $rhRoot); служба integrity-v2-jobtest: $svcCount")
  if (Test-Path $rhRoot) { $sum.Add('runtime-harness-RH0-path → FAIL') }
  if ($svcCount -isnot [int] -or $svcCount -ne 0) { $sum.Add('runtime-harness-RH0-service → FAIL') }
} finally {
  $tempBase = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
  $resolvedTmp = [IO.Path]::GetFullPath($tmp)
  if (-not $resolvedTmp.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($resolvedTmp) -notmatch '^v2-runall-[0-9a-f]{8}$') { throw "небезпечний шлях очищення: $resolvedTmp" }
  Remove-Item -LiteralPath $resolvedTmp -Recurse -Force -Confirm:$false -ErrorAction Stop
  $sha = Get-ChildItem -LiteralPath $K -File | Sort-Object Name | ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" }
  [IO.File]::WriteAllLines((Join-Path $LogDir 'RUN-SUMMARY.txt'), [string[]](@("# run-all.ps1 $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss')) scope=$(if ($LocalOnly) { 'LOCAL T0 ONLY; overall C8 BLOCKED' } else { 'FULL; required NOT RUN = FAIL' })", '') + $sum + @('', '# SHA256 файлів комплекту на момент прогону:') + $sha), (New-Object Text.UTF8Encoding $true))
  $sum
}

if (@($sum | Where-Object { $_ -match "→ FAIL$" }).Count) { exit 1 }
exit 0
