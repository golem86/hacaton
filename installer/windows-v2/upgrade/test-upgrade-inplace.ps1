# test-upgrade-inplace.ps1 — ізольований «сухий» прогін Update/Rollback-V2InPlace (-Simulate) на синтетичному стенді в %TEMP%.
# Справжні: файли, ZIP, SHA256, v2_db_tool (backup/restore/schema/bind-check), venv і pip (колесо v2simpkg), міграція (фейковий
# реліз), caddy adapt/validate. Підмінені (sim\V2-upgrade-sim.ps1): SCM, ACL, HTTP. Служби, ACL, мережа, C:\srv не змінюються.
# Доводить: послідовність кроків; для КОЖНОГО кроку — імітований збій після нього і повний відкат (або «нічого не змінено»);
# успішне оновлення; Rollback-V2InPlace; fail-closed при збої відкату; секрети XML не потрапляють у вивід/доказ.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-upgrade-inplace.ps1 -Py <python із trustme> -Caddy <caddy.exe 2.11.9>
#         [-BasePython <базовий python 3.13 для venv>] [-Quick]
param(
  [Parameter(Mandatory)] [string] $Py,
  [string] $Caddy,
  [string] $BasePython,
  [switch] $Quick
)
$ErrorActionPreference = 'Stop'
$K = Split-Path -Parent $PSScriptRoot
$res = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $res.Add(('{0,-34} {1,-7} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
if (-not $Caddy) { $res.Add(('{0,-34} {1,-7} {2}' -f 'U0.prereq', 'NOT RUN', 'немає -Caddy (caddy.exe 2.11.9)')); $res; exit 1 }
if (-not $BasePython) { $BasePython = Join-Path ((& $Py -I -c 'import sys; print(sys.base_prefix)') | Select-Object -Last 1) 'python.exe' }
$PSX = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$W = Join-Path $env:TEMP ('u' + [guid]::NewGuid().ToString('N').Substring(0, 6)); $null = New-Item -ItemType Directory $W   # короткі шляхи (MAX_PATH у venv)
$script:ScenarioNo = 0
$utf8 = New-Object Text.UTF8Encoding $false

function Invoke-Child([string]$Script, [string[]]$A) {
  $all = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $Script) + $A
  $psi = New-Object Diagnostics.ProcessStartInfo $PSX, ((@($all | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } })) -join ' ')
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $psi.EnvironmentVariables['TEMP'] = $W; $psi.EnvironmentVariables['TMP'] = $W
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit(900000)) { $p.Kill(); throw "тайм-аут $Script" }
  [pscustomobject]@{ Code = $p.ExitCode; Out = $o.Result + $e.Result }
}
function New-Scenario([string]$Name) {
  $script:ScenarioNo++
  $d = Join-Path $W ('s{0:D2}' -f $script:ScenarioNo)
  [IO.File]::AppendAllText((Join-Path $W 'scenarios.txt'), "$d = $Name`r`n")
  Copy-Item -LiteralPath (Join-Path $W 'fx\t') -Destination $d -Recurse
  $root = Join-Path $d 'v2'
  foreach ($x in "$root\services\backend\integrity-v2-backend.xml", "$root\services\caddy\integrity-v2-caddy.xml") { [IO.File]::WriteAllText($x, [IO.File]::ReadAllText($x).Replace('@@ROOT@@', $root), $utf8) }
  $root
}
function Invoke-Update([string]$Root, [string[]]$Extra = @(), [string]$Pkg = (Join-Path $W 'fx\package'), [string]$Sums = (Join-Path $W 'fx\APPROVED-SHA256.txt')) {
  Invoke-Child (Join-Path $PSScriptRoot 'Update-V2InPlace.ps1') (@('-Simulate', '-Root', $Root, '-PackageDir', $Pkg, '-ApprovedSums', $Sums, '-ReleaseId', 'integrity-v2-sim0002',
    '-WheelDir', "$Pkg\wheels", '-Requirements', "$Pkg\requirements-hashed.txt", '-DecisionRef', 'TEST-SIM', '-BasePython', $Py, '-ConfirmVerifiedBackup') + $Extra)
}
# Допоміжні python-скрипти — файлами (Windows PowerShell 5.1 спотворює подвійні лапки в аргументах -c)
[IO.File]::WriteAllText((Join-Path $W 'dbdump.py'), "import sqlite3, sys, hashlib`nc = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)`nprint(c.execute('PRAGMA user_version').fetchone()[0], hashlib.sha256(chr(10).join(c.iterdump()).encode()).hexdigest())`n", $utf8)
[IO.File]::WriteAllText((Join-Path $W 'hasmod.py'), "import importlib.util, sys`nprint(bool(importlib.util.find_spec(sys.argv[1])))`n", $utf8)
function Get-DbDump([string]$Db) { @(& $Py -I -B (Join-Path $W 'dbdump.py') $Db)[-1] }
function Get-Snapshot([string]$Root) {
  $st = Get-Content -LiteralPath (Join-Path (Split-Path $Root) 'sim\state.json') -Raw | ConvertFrom-Json
  $venvImp = & (Join-Path $Root 'venv\Scripts\python.exe') -I -B (Join-Path $W 'hasmod.py') v2simpkg
  $venvMan = @(Get-ChildItem -LiteralPath "$Root\venv" -Recurse -File -Force | Sort-Object FullName | ForEach-Object { "$((Get-FileHash -LiteralPath $_.FullName).Hash) $($_.FullName.Substring($Root.Length))" }) -join "`n"
  [ordered]@{
    Xml = (Get-FileHash "$Root\services\backend\integrity-v2-backend.xml").Hash; Caddyfile = (Get-FileHash "$Root\caddy\Caddyfile").Hash
    Dist = (@(Get-ChildItem -LiteralPath "$Root\app\frontend\dist" -Recurse -File | Sort-Object FullName | ForEach-Object { "$((Get-FileHash $_.FullName).Hash) $($_.Name)" }) -join ';')
    IntegrityDb = Get-DbDump "$Root\data\integrity_v2.db"; AuthDb = Get-DbDump "$Root\data\v2_auth.db"
    Venv = (Get-FileHash -InputStream ([IO.MemoryStream]::new($utf8.GetBytes($venvMan)))).Hash; VenvHasNew = "$venvImp".Trim()
    Services = "$($st.Services.'integrity-v2-backend'.State)/$($st.Services.'integrity-v2-backend'.StartMode)|$($st.Services.'integrity-v2-caddy'.State)/$($st.Services.'integrity-v2-caddy'.StartMode)"
    App = (@(Get-ChildItem -LiteralPath "$Root\app" -Name) -join ',') + '|' + (@(Get-ChildItem -LiteralPath "$Root\app\frontend" -Name) -join ',')
    Pkg = @(Get-ChildItem -LiteralPath "$Root\pkg" -Name) -join ','
    DataBlock = @(Get-ChildItem -LiteralPath "$Root\data" -Name | Where-Object { $_ -match '^RESTORE-(IN-PROGRESS|FAILED)|\.replaced-|\.backup-' }) -join ','
  }
}
function Compare-Snapshot($A, $B, [string[]]$Ignore = @()) { @($A.Keys | Where-Object { $Ignore -notcontains $_ -and "$($A[$_])" -ne "$($B[$_])" } | ForEach-Object { "$_ : $($A[$_]) → $($B[$_])" }) }
function Get-Evidence([string]$Root) {
  $f = @(Get-ChildItem -LiteralPath "$Root\backups" -Directory -Filter 'pre-upgrade-*' | ForEach-Object { Join-Path $_.FullName 'UPGRADE-EVIDENCE.json' } | Where-Object { Test-Path $_ })
  if ($f.Count -ne 1) { return $null }
  Get-Content -LiteralPath $f[0] -Raw -Encoding UTF8 | ConvertFrom-Json
}
# -Include з -LiteralPath у PS 5.1 ігнорується — фільтр за розширенням
function Test-NoSecret([string]$Root, [string]$Out) {
  $hit = $Out.Contains($script:Secret)
  foreach ($f in @(Get-ChildItem -LiteralPath "$Root\backups" -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Extension -in '.json', '.txt', '.log' })) { if ([IO.File]::ReadAllText($f.FullName).Contains($script:Secret)) { $hit = $true } }
  -not $hit
}

try {
  # ---------------------------------------------------------------- U0: стенд
  $fx = & $Py -I -B (Join-Path $PSScriptRoot 'sim\build_sim_fixture.py') --kit $K --out (Join-Path $W 'fx') --base-python $BasePython --caddy $Caddy
  if ($LASTEXITCODE -ne 0) { throw "стенд не створено: $fx" }
  $script:Secret = ($fx | Select-Object -Last 1 | ConvertFrom-Json).secret_marker
  $steps = @(& $PSX -NoProfile -NonInteractive -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Update-V2InPlace.ps1') -ListSteps)
  $updSteps = @($steps | Where-Object { $_ -notmatch '^(rollback|cleanup)\.' })
  Add-Res 'U0.fixture' ($updSteps.Count -eq 26 -and $script:Secret) "стенд: корінь, venv (базовий Python), БД v3/v1, пакет, колесо; кроків Update: $($updSteps.Count)"

  # ---------------------------------------------------------------- U1: успішне оновлення
  $r1 = New-Scenario 'happy'; $s0 = Get-Snapshot $r1
  $xmlBefore = [IO.File]::ReadAllBytes("$r1\services\backend\integrity-v2-backend.xml")
  $u = Invoke-Update $r1
  $ev = Get-Evidence $r1; $s1 = Get-Snapshot $r1
  $order = if ($ev) { (@($ev.Steps | ForEach-Object Name) -join ',') -eq ($updSteps -join ',') } else { $false }
  Add-Res 'U1.exit' ($u.Code -eq 0 -and $ev.Result -eq 'PASS' -and $order) "exit $($u.Code); результат $($ev.Result); кроки в порядку: $order"
  $wd = ([xml][IO.File]::ReadAllText("$r1\services\backend\integrity-v2-backend.xml")).service.workingdirectory
  $exp = [Text.Encoding]::UTF8.GetString($xmlBefore).Replace("<workingdirectory>$r1\app\integrity-v2-dde86e6\backend</workingdirectory>", "<workingdirectory>$r1\app\integrity-v2-sim0002\backend</workingdirectory>")
  Add-Res 'U1.xml' ($wd -eq "$r1\app\integrity-v2-sim0002\backend" -and [Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes("$r1\services\backend\integrity-v2-backend.xml")) -ceq $exp) 'XML: змінено лише workingdirectory; решта байтів (секрети) незмінна'
  $tool = Join-Path $K 'v2_db_tool.py'
  $si = & $Py -I -B $tool integrity-schema "$r1\data\integrity_v2.db" --expect-version 5 | Select-Object -Last 1
  $sa = & $Py -I -B $tool auth-schema "$r1\data\v2_auth.db" --expect-version 2 | Select-Object -Last 1
  Add-Res 'U1.schema' ($si -like 'INTEGRITY SCHEMA OK version=5*' -and $sa -like 'AUTH SCHEMA OK version=2*') "строгі схеми після оновлення: $si; $sa"
  Add-Res 'U1.state' ($s1.VenvHasNew -eq 'True' -and $s1.Dist -match 'new.js' -and $s1.Caddyfile -ne $s0.Caddyfile -and [IO.File]::ReadAllText("$r1\caddy\Caddyfile").Contains('Content-Security-Policy') -and
                      $s1.Services -eq 'Running/Auto|Running/Auto' -and -not (Test-Path "$r1\app\integrity-v2-sim0002\backend\app\v2_bootstrap_admin.py") -and $s1.DataBlock -eq '') "venv із новою залежністю; dist і Caddyfile нові; служби Running/delayed-auto; bootstrap не розгорнуто; копії міграції не в data\ ($($s1.Services))"
  $bkDir = @(Get-ChildItem -LiteralPath "$r1\backups" -Directory -Filter 'pre-upgrade-*')[0].FullName
  Add-Res 'U1.backup' ((Test-Path "$bkDir\integrity_v2.db") -and (Test-Path "$bkDir\v2_auth.db") -and (Test-Path "$bkDir\venv-SHA256.txt") -and (Test-Path "$bkDir\venv.zip") -and (Test-Path "$bkDir\mig") -and
                       (Get-Content "$bkDir\UPGRADE-STATE.json" -Raw | ConvertFrom-Json).Completed -eq $true -and -not (Test-Path "$bkDir\tmp")) 'копії БД, venv, XML, Caddyfile; власна копія міграції перенесена з data\; стан для відкату'
  Add-Res 'U1.secrets' (Test-NoSecret $r1 $u.Out) 'значення секретів XML відсутні у виводі, доказі й стані'

  # ---------------------------------------------------------------- U2: Rollback після успішного оновлення
  $rb = Invoke-Child (Join-Path $PSScriptRoot 'Rollback-V2InPlace.ps1') @('-Simulate', '-Root', $r1, '-BackupDir', $bkDir, '-DecisionRef', 'TEST-SIM', '-BasePython', $Py)
  Add-Res 'U2.confirm' ($rb.Code -eq 3 -and (@(Compare-Snapshot $s1 (Get-Snapshot $r1)).Count -eq 0)) "без -ConfirmRestoreFromBackup → exit $($rb.Code), нічого не змінено"
  $rb = Invoke-Child (Join-Path $PSScriptRoot 'Rollback-V2InPlace.ps1') @('-Simulate', '-Root', $r1, '-BackupDir', $bkDir, '-DecisionRef', 'TEST-SIM', '-BasePython', $Py, '-ConfirmRestoreFromBackup', '-RestoreStartMode', '-RemoveNewRelease')
  $s2 = Get-Snapshot $r1; $d2 = @(Compare-Snapshot $s0 $s2)
  Add-Res 'U2.rollback' ($rb.Code -eq 0 -and $d2.Count -eq 0 -and (Test-NoSecret $r1 $rb.Out)) "Rollback → exit $($rb.Code); стан = до оновлення$(if ($d2.Count) { ': ' + ($d2 -join '; ') })"

  # ---------------------------------------------------------------- U3: збій після КОЖНОГО кроку → відкат / нічого не змінено
  $matrix = if ($Quick) { @('preflight.db', 'stage.code', 'backup.db', 'db.migrate', 'start.caddy', 'finalize') } else { $updSteps }
  foreach ($st in $matrix) {
    $r = New-Scenario ("f-" + $st.Replace('.', '-')); $b = Get-Snapshot $r
    $x = Invoke-Update $r @('-SimulateFailAt', $st)
    $a = Get-Snapshot $r; $ev = Get-Evidence $r
    $ign = @()
    if ($st -in 'db.migrate', 'db.verify', 'start.backend', 'swap.dist', 'caddyfile.replace', 'start.caddy', 'startmode', 'finalize') { $ign = @('DataBlock') }
    $d = @(Compare-Snapshot $b $a $ign)
    if ($st -like 'preflight.*') { $ok = $x.Code -eq 3 -and $d.Count -eq 0 -and -not @(Get-ChildItem "$r\backups" -Directory).Count; $want = 'exit 3, нічого не змінено' }
    elseif ($st -like 'stage.*') { $ok = $x.Code -eq 1 -and $ev.Result -eq 'FAILED_NOTHING_CHANGED' -and $d.Count -eq 0; $want = 'exit 1, створене прибрано, живе не змінено' }
    else {
      $restored = if ($ign.Count) { @(Get-ChildItem "$r\data" -Name -Filter 'RESTORE-OK-*').Count -eq 1 -and -not @(Get-ChildItem "$r\data" -Name | Where-Object { $_ -match '^RESTORE-(IN-PROGRESS|FAILED)|\.replaced-|\.backup-' }).Count } else { $true }
      $ok = $x.Code -eq 1 -and $ev.Result -eq 'FAILED_ROLLED_BACK' -and $d.Count -eq 0 -and $restored; $want = 'exit 1, автоматичний відкат: стан = до оновлення'
    }
    $ok = $ok -and (Test-NoSecret $r $x.Out)
    Add-Res "U3.fail-after.$st" $ok "$want (exit $($x.Code); $(if ($ev) { $ev.Result } else { '—' }))$(if ($d.Count) { ': ' + ($d -join '; ') })"
    if (-not $ok) { [IO.File]::WriteAllText((Join-Path $W "fail-$st.log"), $x.Out, $utf8) }
  }

  # ---------------------------------------------------------------- U4: збій самого відкату → fail-closed (exit 2, backend не стартує)
  $r = New-Scenario 'double'
  $x = Invoke-Update $r @('-SimulateFailAt', 'db.verify,rollback.db-restore')
  $ev = Get-Evidence $r; $st4 = Get-Content (Join-Path (Split-Path $r) 'sim\state.json') -Raw | ConvertFrom-Json
  Add-Res 'U4.rollback-fails' ($x.Code -eq 2 -and $ev.Result -eq 'ROLLBACK_INCOMPLETE' -and $st4.Services.'integrity-v2-backend'.State -eq 'Stopped' -and -not @($st4.Events | Where-Object { $_ -eq 'start integrity-v2-backend' }).Count) "exit $($x.Code); $($ev.Result); backend лишився зупиненим (fail-closed)"

  # ---------------------------------------------------------------- U5: блокування preflight
  $r = New-Scenario 'tamper'; Add-Content -LiteralPath "$r\app\integrity-v2-dde86e6\backend\app\main.py" -Value '# змінено'; $b = Get-Snapshot $r
  $x = Invoke-Update $r
  Add-Res 'U5.current-code' ($x.Code -eq 3 -and $x.Out -match 'поточний код' -and @(Compare-Snapshot $b (Get-Snapshot $r)).Count -eq 0) "змінений поточний код → exit $($x.Code)"
  $r = New-Scenario 'env'; $c = Get-Content (Join-Path (Split-Path $r) 'sim\config.json') -Raw | ConvertFrom-Json; $c.MachineEnv = @('FORWARDED_ALLOW_IPS', 'PATH')
  [IO.File]::WriteAllText((Join-Path (Split-Path $r) 'sim\config.json'), (ConvertTo-Json $c), $utf8)
  $x = Invoke-Update $r
  Add-Res 'U5.machine-env' ($x.Code -eq 3 -and $x.Out -match 'FORWARDED_ALLOW_IPS' -and $x.Out -notmatch 'PATH,') "Machine-змінна FORWARDED_ALLOW_IPS → exit $($x.Code) (лише ім'я)"
  $r = New-Scenario 'sums'; $bad = Join-Path $W 'bad-sums.txt'
  [IO.File]::WriteAllText($bad, ([IO.File]::ReadAllText((Join-Path $W 'fx\APPROVED-SHA256.txt')) -replace '^[0-9a-f]{8}', '00000000'), $utf8)
  $x = Invoke-Update $r @() (Join-Path $W 'fx\package') $bad
  Add-Res 'U5.approved-sums' ($x.Code -eq 3 -and $x.Out -match 'SHA256') "сума пакета ≠ окремому каналу → exit $($x.Code)"
  $r = New-Scenario 'noconfirm'
  $x = Invoke-Child (Join-Path $PSScriptRoot 'Update-V2InPlace.ps1') @('-Simulate', '-Root', $r, '-PackageDir', (Join-Path $W 'fx\package'), '-ApprovedSums', (Join-Path $W 'fx\APPROVED-SHA256.txt'), '-ReleaseId', 'integrity-v2-sim0002', '-DecisionRef', 'TEST-SIM', '-BasePython', $Py)
  Add-Res 'U5.confirm' ($x.Code -eq 3 -and $x.Out -match 'ConfirmVerifiedBackup') "без -ConfirmVerifiedBackup → exit $($x.Code)"
  $r = New-Scenario 'drift'; $b = Get-Snapshot $r
  $x = Invoke-Update $r @() (Join-Path $W 'fx\package-drift') (Join-Path $W 'fx\APPROVED-SHA256-drift.txt')
  $ev = Get-Evidence $r
  Add-Res 'U5.bind-drift' ($x.Code -eq 1 -and $ev.Result -eq 'FAILED_NOTHING_CHANGED' -and $x.Out -match 'B03' -and @(Compare-Snapshot $b (Get-Snapshot $r)).Count -eq 0) "DDL релізу ≠ таблиці очікувань → зупинка до простою (exit $($x.Code))"

  # ---------------------------------------------------------------- U6: справжній збій відновлення БД → RESTORE-FAILED, Disabled, старт заблоковано
  $r = New-Scenario 'restorefail'
  $probe = Join-Path $W 'restore-probe.ps1'
  [IO.File]::WriteAllText($probe, @"
`$ErrorActionPreference = 'Stop'
. '$PSScriptRoot\V2-upgrade-lib.ps1'
. '$PSScriptRoot\sim\V2-upgrade-sim.ps1'
Initialize-V2Up -Root '$r' -Simulate
`$script:V2UpDbTool = '$K\v2_db_tool.py'; `$script:V2UpBasePython = '$Py'
`$bk = '$r\backups\probe'; `$null = New-Item -ItemType Directory `$bk
`$items = @(Backup-V2UpDatabases -Dir `$bk -Versions @{ integrity = 3; auth = 1 } -Strict)
`$null = Stop-V2UpService integrity-v2-caddy; `$null = Stop-V2UpService integrity-v2-backend
`$sha = `$items[1].Sha256; `$items[1].Sha256 = '0' * 64
`$m1 = `$null; try { Restore-V2UpDatabases -Dir `$bk -Items `$items -Stamp 'probe1' -AsideDir "`$bk\aside" } catch { `$m1 = `$_.Exception.Message }
`$pre = (`$m1 -like '*SHA256*') -and -not @(Get-ChildItem '$r\data' -Name | Where-Object { `$_ -match '^RESTORE-|\.replaced-' }).Count -and (Get-V2UpService integrity-v2-backend).StartMode -eq 'Manual'
`$items[1].Sha256 = `$sha; `$items[1].Rows = 999
`$m2 = `$null; try { Restore-V2UpDatabases -Dir `$bk -Items `$items -Stamp 'probe2' -AsideDir "`$bk\aside" } catch { `$m2 = `$_.Exception.Message }
`$blocked = `$false; try { `$null = Start-V2UpService integrity-v2-backend } catch { `$blocked = `$true }
`$mid = (`$m2 -like '*ВІДНОВЛЕННЯ БД НЕВДАЛЕ*') -and (Test-Path '$r\data\RESTORE-FAILED-probe2.txt') -and `$blocked -and (Get-V2UpService integrity-v2-backend).StartMode -eq 'Disabled'
'RESULT ' + `$pre + ' ' + `$mid
"@, (New-Object Text.UTF8Encoding $true))
  $x = Invoke-Child $probe @()
  Add-Res 'U6.restore-precheck' ($x.Out -match 'RESULT True' -and $x.Out -match 'RESULT True True') 'відновлення БД: пошкоджена копія → STOP до змін (без маркерів); збій після початку → RESTORE-FAILED, backend Disabled, старт заблоковано'
} catch {
  $res.Add(('{0,-34} {1,-7} {2}' -f 'ERROR', 'FAIL', "$($_.Exception.Message) $($_.InvocationInfo.PositionMessage)"))
} finally {
  $keep = @($res | Where-Object { $_ -match '\sFAIL\s' }).Count
  if ($keep) { $res.Add("INFO  стенд збережено для аналізу: $W") } else { try { Remove-Item -LiteralPath $W -Recurse -Force } catch { $res.Add("INFO  стенд не видалено повністю ($($_.Exception.Message)): $W") } }
}
$res
$fail = @($res | Where-Object { $_ -match '\s(FAIL|NOT RUN)\s' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match '\sPASS\s' }).Count) PASS, $fail FAIL"
if ($fail) { exit 1 } else { exit 0 }
