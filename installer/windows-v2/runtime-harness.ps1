# runtime-harness.ps1 — ЕТАП 5: інтеграційна перевірка на ІЗОЛЬОВАНОМУ тестовому Windows-хості (НЕ production, НЕ сервер V2).
# Виконує лише після окремого погодження №5 для конкретного тестового хоста. Створює ТЕСТОВУ службу integrity-v2-jobtest
# (WinSW 2.12.0, NT SERVICE\integrity-v2-jobtest, Manual) з експериментальним launcher-ом Job Object і синтетичним дочірнім
# процесом; перевіряє J10 / J18 (WinSW), SID служби, утримання handle, доказ зупинки; наприкінці видаляє службу й тестове дерево.
# Не чіпає V1, V2, C:\srv, Firewall, Tailscale, Caddy, БД. Будь-яка невідповідність захисних умов → STOP ДО будь-якої зміни.
param(
  [Parameter(Mandatory)] [string] $TestRoot,          # новий порожній каталог, напр. D:\v2-jobtest (не C:\srv)
  [Parameter(Mandatory)] [string] $BasePython,        # базовий Python 3.13.14 (не venv)
  [Parameter(Mandatory)] [string] $WinSWExe,          # WinSW 2.12.0, SHA256 05b82d46…
  [Parameter(Mandatory)] [string] $ApprovalRef,       # номер/дата погодження №5 саме для цього тестового хоста
  [switch] $IAmOnIsolatedTestHost,
  [string] $BackendPy,                # Python 3.13.14 з залежностями backend (для RH-RB: відкат на синтетичних БД зі справжньою службою)
  [string] $PackageDir,               # пакет поточного релізу (формат пакета оновлення) — release backend для перевірки схеми
  [string] $ApprovedSums,             # APPROVED-SHA256.txt пакета (окремий канал)
  [string] $ReleaseId                 # integrity-v2-<sha7>
)
$ErrorActionPreference = 'Stop'
$K = $PSScriptRoot
. "$K\V2-install-common.ps1"
$log = New-Object System.Collections.Generic.List[string]
function Step([string]$id, [bool]$ok, [string]$d) { $l = ('{0,-14} {1,-7} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d); $log.Add($l); $l }

# ---------------------------------------------------------------- RH0: захисні умови (жодних змін до їх проходження)
$why = New-Object System.Collections.Generic.List[string]
if (-not $IAmOnIsolatedTestHost) { $why.Add('не підтверджено ізольований тестовий хост (-IAmOnIsolatedTestHost)') }
if (-not $ApprovalRef.Trim()) { $why.Add('немає посилання на погодження №5') }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { $why.Add('потрібні права адміністратора') }
if ($env:COMPUTERNAME -ieq 'DESKTOP-JTGC2SG') { $why.Add('це production-хост V2 — заборонено') }
if (Test-Path -LiteralPath 'C:\srv') { $why.Add('існує C:\srv — хост схожий на production') }
foreach ($svc in 'HacatonBackend', 'integrity-v2-backend', 'integrity-v2-caddy', 'integrity-v2-jobtest') {
  try { if (Get-V2Service $svc) { $why.Add("існує служба $svc") } }
  catch { $why.Add("стан служби ${svc} не підтверджено: $($_.Exception.Message)") }
}
$tr = [IO.Path]::GetFullPath($TestRoot)
if ($tr -like 'C:\srv*' -or $tr -like "$env:SystemRoot*") { $why.Add("заборонений TestRoot $tr") }
if ((Test-Path -LiteralPath $tr) -and @(Get-ChildItem -LiteralPath $tr -Force).Count) { $why.Add("TestRoot не порожній: $tr") }
if (-not (Test-Path -LiteralPath $WinSWExe -PathType Leaf) -or (Get-FileHash -LiteralPath $WinSWExe -Algorithm SHA256).Hash.ToLower() -ne '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da') { $why.Add('WinSW не 2.12.0 (SHA256 ≠ 05b82d46…)') }
if (-not (Test-Path -LiteralPath $BasePython -PathType Leaf)) { $why.Add('немає BasePython') }
else { $ver = @(Invoke-V2Native -Exe $BasePython -ArgList @('-I', '-c', 'import sys; print(sys.version.split()[0], sys.prefix == sys.base_prefix)') -Utf8 -What 'python version')[-1]; if ($ver -ne '3.13.14 True') { $why.Add("Python ≠ базовий 3.13.14 ($ver)") } }
if ($why.Count) { Write-Output "RH0            STOP    захисні умови не виконано — жодних змін не зроблено: $($why -join '; ')"; exit 3 }
Step 'RH0' $true "захисні умови: погодження $ApprovalRef; адмін; не production; WinSW 2.12.0; Python 3.13.14"

$svcName = 'integrity-v2-jobtest'; $jobName = 'Global\integrity-v2-jobtest-job'; $svcSid = Get-V2ServiceSid $svcName
$svcExe = "$tr\service\$svcName.exe"
$created = $false
try {
  # ---------------------------------------------------------------- підготовка тестового дерева й служби
  foreach ($d in 'kit', 'state', 'logs', 'service') { $null = New-Item -ItemType Directory -Path "$tr\$d" -Force }
  foreach ($f in 'v2_job_launcher.py', 'job_child.py', 'v2_db_tool.py') { Copy-Item -LiteralPath "$K\$f" -Destination "$tr\kit\$f" }
  Copy-Item -LiteralPath $WinSWExe -Destination $svcExe
  $x = [IO.File]::ReadAllText("$K\integrity-v2-jobtest.TEST-ONLY.xml.template").Replace('__TEST_ROOT__', $tr).Replace('__BASE_PYTHON__', $BasePython).Replace('__STOP_TIMEOUT__', '15 sec')
  [IO.File]::WriteAllText("$tr\service\$svcName.xml", $x, (New-Object Text.UTF8Encoding $false))
  $null = Invoke-V2Native -Exe 'icacls.exe' -ArgList @("$tr", '/grant', "*${svcSid}:(OI)(CI)M") -What 'icacls test tree'   # лише тестове дерево
  $null = Invoke-V2Native -Exe $svcExe -ArgList @('install') -What 'WinSW install (test)'; $created = $true
  $s = Get-V2Service $svcName
  Step 'RH1' ($s -and $s.StartMode -eq 'Manual' -and $s.StartName -eq "NT SERVICE\$svcName") "тестова служба: Manual, StartName $($s.StartName), SID $svcSid"
  $V2Services[$svcName] = @{ Exe = $svcExe; Account = "NT SERVICE\$svcName"; Port = 8199; Job = $jobName }
  $V2JobTool.Py = $BasePython; $V2JobTool.Script = "$tr\kit\v2_job_launcher.py"
  $V2Root = $tr
  function Start-Test { Remove-Item "$tr\state\*" -Force -ErrorAction Stop; $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('start', $svcName) -What 'sc start (test)'
                        foreach ($i in 1..60) { if (Test-Path "$tr\state\child.json") { break }; Start-Sleep -Milliseconds 500 }; Get-Content "$tr\state\child.json" -Raw | ConvertFrom-Json }
  # J10.start — служба стартує, дочірні процеси в job, власник — SID служби
  $c = Start-Test
  $rep = Get-V2JobReport -JobName $jobName -OwnerSid $svcSid
  Step 'J10.start' ($rep.found -and $rep.sd_ok -and $rep.limits_ok -and @($rep.pids) -contains [int]$c.child -and @($rep.pids) -contains [int]$c.grandchild) "WinSW → launcher → job: PID-list $(@($rep.pids) -join ','), SD/ліміти OK, власник job $svcSid"
  # J10.stop — штатна зупинка через Stop-V2Service (job + власник + порт)
  $r = @(Stop-V2Service -Name $svcName)
  Step 'J10.stop' ($r[-1] -like 'PASS*повнота: Job Object*' -and $V2StopProof[$svcName].Completeness -eq 'job') "sc stop → Stop-V2Service: $($r[-1])"
  # J18.timeout — короткий stoptimeout (WinSW примусово завершує launcher) → job закрито → доказ
  [IO.File]::WriteAllText("$tr\service\$svcName.xml", $x.Replace('<stoptimeout>15 sec</stoptimeout>', '<stoptimeout>1 sec</stoptimeout>'), (New-Object Text.UTF8Encoding $false))
  $c = Start-Test; $r = @(Stop-V2Service -Name $svcName)
  Step 'J18.timeout' ($r[-1] -like 'PASS*Job Object*') "stoptimeout 1 s: $($r[-1])"
  # J18.launcher-crash — launcher завершено примусово, служба зупиняється сама → job порожній
  $c = Start-Test; $st = Get-Content "$tr\state\launcher.json" -Raw | ConvertFrom-Json
  $h = Open-V2ProcessHandle ([int]$st.launcher); Stop-V2Handle $h; $null = Wait-V2Handle $h 10000
  foreach ($i in 1..30) { if ((Get-V2Service $svcName).State -eq 'Stopped') { break }; Start-Sleep 1 }
  $rep = Get-V2JobReport -JobName $jobName -OwnerSid $svcSid -Scan
  Step 'J18.launcher-crash' (-not $rep.found -or $rep.verdict -eq 'PASS') "аварія launcher-а: job $(if ($rep.found) { "active=$($rep.active)" } else { 'закрито (KILL_ON_JOB_CLOSE)' }); сканування SID служби: $(@($rep.scan.alive).Count) живих"
  # J18.installer-held — installer утримує handle під час stop → процеси job живі до terminate → доказ
  $c = Start-Test; $r = @(Stop-V2Service -Name $svcName)
  Step 'J18.installer-held' ($r[-1] -like 'PASS*Job Object*') "утримання handle під час stop: $($r[-1])"

  # J10.disabled-1058 — гарантія W1 на справжньому SCM: вимкнена служба не стартує (ERROR_SERVICE_DISABLED = 1058)
  Set-V2ServiceStartMode -Name $svcName -Mode Disabled
  $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('start', $svcName) -OkCodes @(1058) -What 'sc start вимкненої служби → 1058'
  Start-Sleep -Seconds 2; $s2 = Get-V2Service $svcName
  $rep2 = Get-V2JobReport -JobName $jobName -OwnerSid $svcSid -Scan
  Step 'J10.disabled-1058' ($s2.State -eq 'Stopped' -and -not $s2.ProcessId -and @($rep2.scan.alive).Count -eq 0) "Disabled → sc start = 1058; служба Stopped; процесів service SID $(@($rep2.scan.alive).Count)"
  Set-V2ServiceStartMode -Name $svcName -Mode Manual
  # RH-RB — відкат на синтетичних БД зі справжньою службою: W1 на справжньому SCM, W2–W5, sidecar-и, повернення Manual, старт після відкату
  if ($BackendPy -and $PackageDir -and $ApprovedSums -and $ReleaseId) {
    $pkgRh = Assert-V2CleanPackage -PackageDir $PackageDir -ApprovedSums $ApprovedSums -ReleaseId $ReleaseId
    $null = New-Item -ItemType Directory -Path "$tr\app", "$tr\pkg" -Force
    $null = Expand-V2ReleaseBackend -Package $pkgRh -AppDir "$tr\app\$ReleaseId" -PkgManifestPath "$tr\pkg\$ReleaseId-BACKEND-SHA256.txt"
    $V2AppRelease = $ReleaseId
    $be = "$tr\app\$ReleaseId\backend"; $dd = "$tr\data"; $bk = "$tr\backups"
    foreach ($d in $dd, $bk) { $null = New-Item -ItemType Directory -Path $d -Force }
    $null = Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$dd\integrity_v2.db"; V2_AUTH_DB = "$dd\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey); FRONTEND_ORIGINS = 'https://v2.example.test' } -Body {
      $null = Invoke-V2Seed -Py $BackendPy -Backend $be -What 'seed (тест-хост)'
      $null = Invoke-V2Py -Py $BackendPy -Backend $be -ArgList @('-m', 'app.migrations', '--apply', '--confirm-verified-backup') -What 'migrations (тест-хост)'
    }
    # I4 (hardening): версії — з $V2DbSet (поточний реліз, $V2ReleaseSchema), а не закріплені числа
    $items = foreach ($db in @($V2DbSet.Keys | ForEach-Object { , @($_, $V2DbSet[$_]) })) {
      $dst = "$bk\$($db[0])"; $null = Invoke-V2DbTool -Py $BackendPy -DbTool "$tr\kit\v2_db_tool.py" -ArgList @('backup', "$dd\$($db[0])", $dst, '--expect-version', "$($db[1])")
      @{ Db = $db[0]; Backup = $dst; Sha256 = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash.ToLower(); Version = $db[1] }
    }
    $V2BackendName = $svcName                                                      # лише тут: логіка відкату працює з тестовою службою
    $c = Start-Test; $r = @(Stop-V2Service -Name $svcName)
    $rb = @(Invoke-V2DbRestore -DataDir $dd -Known @() -Py $BackendPy -DbTool "$tr\kit\v2_db_tool.py" -Items $items)
    $s3 = Get-V2Service $svcName
    Step 'RH-RB.ok' ($rb[-1] -like 'PASS*відновлення завершено*' -and @($rb | Where-Object { $_ -like 'PASS  W1:*' }).Count -eq 1 -and @($rb | Where-Object { $_ -like 'PASS  W5 sidecars*' }).Count -eq 2 -and $s3.StartMode -eq 'Manual' -and -not $V2StopProof.ContainsKey($svcName)) "справжній SCM: W1 Disabled → W2–W5 → RESTORE-OK → Manual; lease звільнено: $($rb[-1])"
    $c = Start-Test
    Step 'RH-RB.restart' ((Get-V2Service $svcName).State -eq 'Running') 'старт служби після успішного відкату'
    $r = @(Stop-V2Service -Name $svcName)
    # RH-RB.failed — примусова помилка після мутації → RESTORE-FAILED; служба лишається Disabled; старт → 1058
    $bad = $items | ForEach-Object { @{ Db = $_.Db; Backup = $_.Backup; Sha256 = $_.Sha256; Version = $_.Version } }
    $origTool = (Get-Item function:Invoke-V2DbTool).ScriptBlock
    Set-Item function:script:Invoke-V2DbTool { param([string]$Py, [string]$DbTool, [string[]]$ArgList) if ($ArgList[0] -eq 'auth-schema' -and $ArgList[1] -like "$dd\*") { Stop-V2 'примусова помилка (тест-хост)' }; & $origTool -Py $Py -DbTool $DbTool -ArgList $ArgList }
    $mf = $null; try { $null = Invoke-V2DbRestore -DataDir $dd -Known @() -Py $BackendPy -DbTool "$tr\kit\v2_db_tool.py" -Items $bad } catch { $mf = $_.Exception.Message } finally { Set-Item function:script:Invoke-V2DbTool $origTool }
    $s4 = Get-V2Service $svcName
    $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('start', $svcName) -OkCodes @(1058) -What 'sc start після FAILED → 1058'
    Step 'RH-RB.failed' ($mf -like 'STOP:*ВІДНОВЛЕННЯ НЕВДАЛЕ*' -and @(Get-ChildItem -LiteralPath $dd -Filter 'RESTORE-FAILED-*').Count -eq 1 -and $s4.StartMode -eq 'Disabled') 'справжній SCM: помилка після мутації → RESTORE-FAILED; служба Disabled; sc start = 1058'
    Set-V2ServiceStartMode -Name $svcName -Mode Manual
    $V2BackendName = 'integrity-v2-backend'
  } else {
    $log.Add(('{0,-14} {1,-7} {2}' -f 'RH-RB', 'NOT RUN', 'немає -BackendPy/-PackageDir/-ApprovedSums/-ReleaseId — відкат на синтетичних БД зі справжньою службою не виконано'))
  }
} catch {
  Step 'RH-ERR' $false "помилка: $($_.Exception.Message)"
} finally {
  # ---------------------------------------------------------------- очищення лише тестових об'єктів
  if ($created) {
    try { if ((Get-V2Service $svcName).State -ne 'Stopped') { $null = Invoke-V2Native -Exe "$env:SystemRoot\System32\sc.exe" -ArgList @('stop', $svcName) -OkCodes @(0, 1062) -What 'sc stop (cleanup)' } } catch { }
    try { $null = Invoke-V2Native -Exe $svcExe -ArgList @('uninstall') -What 'WinSW uninstall (test)' } catch { Step 'RH9' $false "uninstall: $($_.Exception.Message)" }
  }
  $left = @(Get-V2SuspectProcesses)
  Step 'RH9' (-not (Get-V2Service $svcName) -and -not $left.Count) "очищення: служба $svcName видалена; процесів тестового дерева: $($left.Count)"
  $log | Set-Content -LiteralPath "$K\runtime-harness.$((Get-Date).ToString('yyyyMMdd-HHmmss')).log" -Encoding UTF8
}
$fail = @($log | Where-Object { $_ -match '^\S+\s+FAIL ' }).Count
$nr = @($log | Where-Object { $_ -match '^\S+\s+NOT RUN ' }).Count
"Підсумок: $(@($log | Where-Object { $_ -match '^\S+\s+PASS ' }).Count) PASS, $fail FAIL, $nr NOT RUN"
if ($nr) { exit 1 }
if ($fail) { exit 1 } else { exit 0 }
