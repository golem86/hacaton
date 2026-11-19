# run-all.ps1 — відтворюваний прогін усього локального тестового комплекту installer-а V2 (етап 4) з журналами.
# Лише локально: тимчасові каталоги, власні процеси, Local\-job-и; служби, сервер, C:\srv, Git не змінюються.
param(
  [Parameter(Mandatory)] [string] $LogDir,
  [Parameter(Mandatory)] [string] $Py,           # Python для auth/job/PS-тестів (stdlib)
  [Parameter(Mandatory)] [string] $BackendPy,    # Python із залежностями backend (rehearse, AREL)
  [Parameter(Mandatory)] [string] $DeployZip,    # integrity-v2-dde86e6-deploy.zip (release backend для A00/AREL)
  [switch] $WithMutation,
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
  if ((Get-FileHash -LiteralPath $DeployZip -Algorithm SHA256).Hash.ToLower() -ne '62363714278da539db295bc809bd29bf0cc9bbde073ca8a26ff65f5211052559') { throw 'deploy ZIP: SHA256 ≠ 62363714…' }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $z = [IO.Compression.ZipFile]::OpenRead($DeployZip); try { $e = $z.GetEntry('integrity-v2-dde86e6-backend-src.zip'); [IO.Compression.ZipFileExtensions]::ExtractToFile($e, "$tmp\backend-src.zip") } finally { $z.Dispose() }
  [IO.Compression.ZipFile]::ExtractToDirectory("$tmp\backend-src.zip", "$tmp\rel")
  $rel = "$tmp\rel\integrity-v2-dde86e6\backend"
  Start-Suite 'test_v2_auth_schema' $Py @('-I', "$K\test_v2_auth_schema.py", '--tool', "$K\v2_db_tool.py", '--release-backend', $rel, '--release-py', $BackendPy)
  Start-Suite 'test_v2_job' $Py @('-I', "$K\test_v2_job.py")
  Start-Suite 'test-rev3-negative' $PSX @('-NoProfile', '-NonInteractive', '-File', "$K\test-rev3-negative.ps1", '-Py', $Py)
  Start-Suite 'test-audit-gate' $PSX @('-NoProfile', '-NonInteractive', '-File', "$K\test-audit-gate.ps1", '-Py', $Py)
  Start-Suite 'static-rev3' $PSX @('-NoProfile', '-NonInteractive', '-File', "$K\static-rev3.ps1")
  Start-Suite 'static-clean-install' $PSX @('-NoProfile', '-NonInteractive', '-File', "$K\static-clean-install.ps1")
  Start-Suite 'rehearse-rev3' $PSX @('-NoProfile', '-NonInteractive', '-File', "$K\rehearse-rev3.ps1", '-Root', "$tmp\rehearse", '-Py', $BackendPy, '-DeployZip', $DeployZip)
  # RH0: runtime-harness на НЕпогодженому хості має відмовити (exit 3) і нічого не створити
  $rhRoot = "$tmp\rh0-must-not-exist"
  Start-Suite 'runtime-harness-RH0' $PSX @('-NoProfile', '-NonInteractive', '-File', "$K\runtime-harness.ps1", '-TestRoot', $rhRoot, '-BasePython', $Py, '-WinSWExe', "$tmp\no-winsw.exe", '-ApprovalRef', 'NONE') @(3)
  if ($WithMutation) { Start-Suite 'mutation' $Py @('-I', "$K\mutate.py", '--ps', $PSX, '--py', $Py, '--release-backend', $rel, '--release-py', $BackendPy, '--jobs', $MutationJobs) }
  Complete-Suites
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
  [IO.File]::WriteAllLines((Join-Path $LogDir 'RUN-SUMMARY.txt'), [string[]](@("# run-all.ps1 $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))", '') + $sum + @('', '# SHA256 файлів комплекту на момент прогону:') + $sha), (New-Object Text.UTF8Encoding $true))
  $sum
}

if (@($sum | Where-Object { $_ -match "→ FAIL$" }).Count) { exit 1 }
exit 0
