# test-ops-scripts.ps1 — локальні тести експлуатаційних скриптів V2 (лише %TEMP%; служби, завдання планувальника, C:\srv не змінюються):
#   O1 Invoke-V2DailyBackup (-Simulate): копії з restore-test, суми, журнал без вмісту БД, ротація 14, збій → FAILED без ротації;
#   O2 Register-V2BackupTask без -Apply — лише план;
#   O3 Protect-V2Leftovers (-Simulate): звіт = лише імена каталогів і принципалів; -Apply — справжні icacls на тимчасовому дереві
#      («Administrators» замінено поточним користувачем): лише власник+SYSTEM, без успадкування; виключені каталоги незмінні; файли не видалено;
#   O4 Disable-V2InstallLeftoverTasks (-Simulate): звіт, експорт XML, зупинка, вимкнення, заборона Integrity-V2-*;
#   O5 Rotate-V2SecretKey (-Simulate): змінено лише V2_SECRET_KEY, значення не виводиться; збій перезапуску → XML повернуто побайтово.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-ops-scripts.ps1 -Py <python 3.13>
param([Parameter(Mandatory)] [string] $Py)
$ErrorActionPreference = 'Stop'
$K = Split-Path -Parent $PSScriptRoot
$PSX = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$res = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $res.Add(('{0,-22} {1,-7} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
$W = Join-Path $env:TEMP ('o' + [guid]::NewGuid().ToString('N').Substring(0, 6)); $null = New-Item -ItemType Directory $W
$utf8 = New-Object Text.UTF8Encoding $false
function Invoke-Child([string]$Script, [string[]]$A) {
  $all = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $Script) + $A
  $psi = New-Object Diagnostics.ProcessStartInfo $PSX, ((@($all | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } })) -join ' ')
  $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true; $psi.CreateNoWindow = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $psi.EnvironmentVariables['TEMP'] = $W; $psi.EnvironmentVariables['TMP'] = $W
  $p = [Diagnostics.Process]::Start($psi); $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit(600000)) { $p.Kill(); throw "тайм-аут $Script" }
  [pscustomobject]@{ Code = $p.ExitCode; Out = $o.Result + $e.Result }
}
function New-Root([string]$Name) {
  $r = Join-Path $W "$Name\v2"
  foreach ($d in 'data', 'backups', 'services\backend', 'app\rel1\backend\app') { $null = New-Item -ItemType Directory -Path (Join-Path $r $d) -Force }
  $mk = Join-Path $W 'mkdb.py'
  [IO.File]::WriteAllText($mk, "import sqlite3, sys`nsys.path.insert(0, sys.argv[1])`nimport v2_db_tool as t`nfor path, kind, v in ((sys.argv[2], 'integrity', 3), (sys.argv[3], 'auth', 1)):`n    c = sqlite3.connect(path); c.executescript(t.spec_for(kind, v)['ddl'])`n    if kind == 'auth': c.execute(`"INSERT INTO v2_users (name, email, password_hash, role, created_at) VALUES ('A', 'a@example.test', 'h', 'admin', 't')`")`n    c.execute(f'PRAGMA user_version = {v}'); c.commit(); c.close()`n", $utf8)
  & $Py -I -B $mk $K "$r\data\integrity_v2.db" "$r\data\v2_auth.db"
  [IO.File]::WriteAllText("$r\app\rel1\backend\app\__init__.py", '', $utf8)
  [IO.File]::WriteAllText("$r\app\rel1\backend\app\sim_expect.json", '{"integrity": 3, "auth": 1, "requires": []}', $utf8)
  $xml = [IO.File]::ReadAllText((Join-Path $K 'integrity-v2-backend.xml.template')).Replace('C:\srv\integrity-v2', $r).Replace('integrity-v2-dde86e6', 'rel1')
  foreach ($ph in '__V2_SECRET_KEY__', '__V2_SMTP_HOST__', '__V2_SMTP_USER__', '__V2_SMTP_PASSWORD__', '__V2_SMTP_FROM__') { $xml = $xml.Replace($ph, "$($script:Secret)$($ph.Trim('_'))-0123456789abcdef0123456789abcdef") }
  [IO.File]::WriteAllText("$r\services\backend\integrity-v2-backend.xml", $xml, $utf8)
  $sim = Join-Path $W "$Name\sim"; $null = New-Item -ItemType Directory -Path $sim -Force
  [IO.File]::WriteAllText("$sim\state.json", '{"Services":{"integrity-v2-backend":{"State":"Running","StartMode":"Manual","Delayed":false,"DependsOn":[]},"integrity-v2-caddy":{"State":"Running","StartMode":"Manual","Delayed":false,"DependsOn":["Tailscale"]}},"Events":[]}', $utf8)
  [IO.File]::WriteAllText("$sim\config.json", '{"Caddy":"none","MachineEnv":[],"FreeBytes":500000000000}', $utf8)
  $r
}
$script:Secret = 'SIM-OPS-SECRET-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
try {
  # ------------------------------------------------------------------ O1: щоденна копія
  $r = New-Root 'daily'
  $toolSha = (Get-FileHash (Join-Path $K 'v2_db_tool.py')).Hash
  $runs = @(); foreach ($i in 1..3) { $runs += Invoke-Child (Join-Path $PSScriptRoot 'Invoke-V2DailyBackup.ps1') @('-Simulate', '-Root', $r, '-Python', $Py, '-DbTool', (Join-Path $K 'v2_db_tool.py'), '-ExpectedToolSha256', $toolSha, '-Keep', '2'); Start-Sleep -Milliseconds 1100 }
  $dirs = @(Get-ChildItem "$r\backups\daily" -Directory | Sort-Object Name)
  $j = Get-Content (Join-Path $dirs[-1].FullName 'DAILY-BACKUP.json') -Raw | ConvertFrom-Json
  $sums = @(Get-Content (Join-Path $dirs[-1].FullName 'SHA256SUMS.txt'))
  $logl = @(Get-Content "$r\backups\daily\daily-backup.log")
  Add-Res 'O1.daily' (@($runs | Where-Object { $_.Code -ne 0 }).Count -eq 0 -and $dirs.Count -eq 2 -and $j.Status -eq 'PASS' -and @($j.Databases).Count -eq 2 -and @($j.Databases | Where-Object { -not $_.StrictSchema }).Count -eq 0 -and
                      $sums.Count -eq 2 -and $logl.Count -eq 3 -and $logl[-1] -match ' PASS .*rotated=' -and -not @(Get-ChildItem "$r\backups\daily" -Recurse -Directory -Filter 'v2-restore-test-*').Count) "3 запуски, -Keep 2 → лишилось $($dirs.Count); строга схема; SHA256SUMS; журнал: $($logl.Count) рядки, ротація"
  $bad = Invoke-Child (Join-Path $PSScriptRoot 'Invoke-V2DailyBackup.ps1') @('-Simulate', '-Root', $r, '-Python', $Py, '-DbTool', (Join-Path $K 'v2_db_tool.py'), '-ExpectedToolSha256', ('0' * 64), '-Keep', '2')
  $dirs2 = @(Get-ChildItem "$r\backups\daily" -Directory)
  Add-Res 'O1.tool-sha' ($bad.Code -eq 1 -and $dirs2.Count -eq 2 -and @(Get-Content "$r\backups\daily\daily-backup.log")[-1] -match ' FAILED .*SHA256') "інший SHA256 v2_db_tool → FAILED (exit $($bad.Code)), нових копій немає, старі не ротуються"
  [IO.File]::WriteAllBytes("$r\data\integrity_v2.db", [byte[]](1..64))
  $bad = Invoke-Child (Join-Path $PSScriptRoot 'Invoke-V2DailyBackup.ps1') @('-Simulate', '-Root', $r, '-Python', $Py, '-DbTool', (Join-Path $K 'v2_db_tool.py'), '-ExpectedToolSha256', $toolSha, '-Keep', '2')
  $fail = @(Get-ChildItem "$r\backups\daily" -Directory | Where-Object { (Get-Content (Join-Path $_.FullName 'DAILY-BACKUP.json') -Raw | ConvertFrom-Json).Status -eq 'FAILED' })
  Add-Res 'O1.corrupt' ($bad.Code -eq 1 -and $fail.Count -eq 1 -and @(Get-ChildItem "$r\backups\daily" -Directory).Count -eq 3) 'пошкоджена БД → FAILED, каталог із DAILY-BACKUP.json Status=FAILED; вдалі копії не ротуються'

  # ------------------------------------------------------------------ O2: реєстрація — лише план без -Apply
  $p = Invoke-Child (Join-Path $PSScriptRoot 'Register-V2BackupTask.ps1') @()
  Add-Res 'O2.plan' ($p.Code -eq 0 -and $p.Out -match 'Integrity-V2-DB-Backup' -and $p.Out -match '03:30' -and $p.Out -match 'нічого не змінено') 'без -Apply — лише план (SYSTEM, 03:30, 14 копій)'

  # ------------------------------------------------------------------ O3: Protect-V2Leftovers
  $srv = Join-Path $W 'srv'
  $sidB = 'S-1-5-80-' + ((0..4 | ForEach-Object { $h = [Security.Cryptography.SHA1]::Create().ComputeHash([Text.Encoding]::Unicode.GetBytes('INTEGRITY-V2-BACKEND')); [BitConverter]::ToUInt32($h, $_ * 4) }) -join '-')
  foreach ($d in 'integrity-v2-abandoned-20261120-124807\services\backend', 'integrity-v2-abandoned-20261120-124807\data', 'V2-tls-staging-20261120-133903', 'V2-release-TLSFIX5-20261120\tls-maintenance', 'V1-recovery-20261120-130605', 'integrity-v2\data') { $null = New-Item -ItemType Directory -Path (Join-Path $srv $d) -Force }
  [IO.File]::WriteAllText("$srv\integrity-v2-abandoned-20261120-124807\services\backend\integrity-v2-backend.xml", "<service><env name=`"V2_SMTP_PASSWORD`" value=`"$($script:Secret)`"/></service>", $utf8)
  [IO.File]::WriteAllText("$srv\integrity-v2-abandoned-20261120-124807\data\v2_auth.db", 'db', $utf8)
  [IO.File]::WriteAllText("$srv\V2-tls-staging-20261120-133903\site.key", 'key', $utf8)
  foreach ($x in "$srv\V2-release-TLSFIX5-20261120\tls-maintenance\x.ps1", "$srv\V1-recovery-20261120-130605\v1.db", "$srv\integrity-v2\data\integrity_v2.db") { [IO.File]::WriteAllText($x, 'x', $utf8) }
  function Add-Ace([string]$Path, [string]$Sid, [string]$Rights, [bool]$Dir) {
    $acl = if ($Dir) { [IO.Directory]::GetAccessControl($Path) } else { [IO.File]::GetAccessControl($Path) }
    $flags = if ($Dir) { [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' } else { [Security.AccessControl.InheritanceFlags]::None }
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier $Sid), [Security.AccessControl.FileSystemRights]$Rights, $flags, 'None', 'Allow')))
    if ($Dir) { [IO.Directory]::SetAccessControl($Path, $acl) } else { [IO.File]::SetAccessControl($Path, $acl) }
  }
  Add-Ace "$srv\integrity-v2-abandoned-20261120-124807\services\backend" $sidB 'ReadAndExecute' $true
  Add-Ace "$srv\integrity-v2-abandoned-20261120-124807\data\v2_auth.db" $sidB 'Modify' $false
  Add-Ace "$srv\V2-tls-staging-20261120-133903\site.key" 'S-1-5-32-545' 'Read' $false
  foreach ($x in "$srv\V2-release-TLSFIX5-20261120", "$srv\V1-recovery-20261120-130605", "$srv\integrity-v2\data") { Add-Ace $x 'S-1-5-32-545' 'ReadAndExecute' $true }
  $sddl = { param($p) @(Get-ChildItem -LiteralPath $p -Recurse -Force | ForEach-Object { if ($_.PSIsContainer) { [IO.Directory]::GetAccessControl($_.FullName).Sddl } else { [IO.File]::GetAccessControl($_.FullName).Sddl } }) + @([IO.Directory]::GetAccessControl($p).Sddl) -join '|' }
  $keep = @{}; foreach ($x in 'V2-release-TLSFIX5-20261120', 'V1-recovery-20261120-130605', 'integrity-v2') { $keep[$x] = & $sddl (Join-Path $srv $x) }
  $files0 = @(Get-ChildItem $srv -Recurse -File | ForEach-Object FullName | Sort-Object)
  $rep = Invoke-Child (Join-Path $PSScriptRoot 'Protect-V2Leftovers.ps1') @('-Simulate', '-SrvRoot', $srv)
  $repJson = ($rep.Out -split "`r?`n" | Where-Object { $_.StartsWith('{') } | Select-Object -Last 1) | ConvertFrom-Json
  $names = @($repJson.Targets | ForEach-Object Directory)
  Add-Res 'O3.report' ($rep.Code -eq 0 -and ($names -join ',') -eq 'integrity-v2-abandoned-20261120-124807,V2-tls-staging-20261120-133903' -and $rep.Out -match 'NT SERVICE\\integrity-v2-backend' -and $rep.Out -notmatch 'site\.key|v2_auth\.db|\.xml' -and -not $rep.Out.Contains($script:Secret) -and
                       ((@(Compare-Object $keep['integrity-v2'] (& $sddl (Join-Path $srv 'integrity-v2')))).Count -eq 0)) "звіт: цілі $($names -join ', '); принципали за іменами; без імен файлів і вмісту; нічого не змінено"
  $ap = Invoke-Child (Join-Path $PSScriptRoot 'Protect-V2Leftovers.ps1') @('-Simulate', '-SrvRoot', $srv, '-Apply', '-DecisionRef', 'TEST')
  $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $clean = $true
  foreach ($t in 'integrity-v2-abandoned-20261120-124807', 'V2-tls-staging-20261120-133903') {
    $root = Join-Path $srv $t
    foreach ($it in @(Get-Item $root) + @(Get-ChildItem $root -Recurse -Force)) {
      $acl = if ($it.PSIsContainer) { [IO.Directory]::GetAccessControl($it.FullName) } else { [IO.File]::GetAccessControl($it.FullName) }
      $sids = @($acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]) | ForEach-Object { $_.IdentityReference.Value } | Sort-Object -Unique)
      if (@($sids | Where-Object { $_ -notin $me, 'S-1-5-18' }).Count -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $me) { $clean = $false }
      if ($it.FullName -eq $root -and -not $acl.AreAccessRulesProtected) { $clean = $false }
    }
  }
  $untouched = -not @($keep.Keys | Where-Object { $keep[$_] -ne (& $sddl (Join-Path $srv $_)) }).Count
  $files1 = @(Get-ChildItem $srv -Recurse -File | ForEach-Object FullName | Sort-Object)
  Add-Res 'O3.apply' ($ap.Code -eq 0 -and $clean -and $untouched -and (($files0 -join '|') -eq ($files1 -join '|')) -and $ap.Out -match 'PROTECTED') 'apply: лише власник+SYSTEM, захищений корінь, власник змінено; TLSFIX5/V1-recovery/живий корінь незмінні; жодного файла не видалено'
  $ap2 = Invoke-Child (Join-Path $PSScriptRoot 'Protect-V2Leftovers.ps1') @('-Simulate', '-SrvRoot', $srv, '-Apply', '-DecisionRef', 'TEST')
  Add-Res 'O3.idempotent' ($ap2.Code -eq 0 -and $ap2.Out -match 'ALREADY-COMPLIANT' -and $ap2.Out -notmatch 'PROTECTED"') 'повторний запуск: ALREADY-COMPLIANT'
  $na = Invoke-Child (Join-Path $PSScriptRoot 'Protect-V2Leftovers.ps1') @('-Simulate', '-SrvRoot', $srv, '-Apply')
  Add-Res 'O3.decision' ($na.Code -ne 0 -and $na.Out -match 'DecisionRef') '-Apply без -DecisionRef → STOP'

  # ------------------------------------------------------------------ O4: Disable-V2InstallLeftoverTasks
  $tb = Join-Path $W 'tasks\backups'; $null = New-Item -ItemType Directory -Path $tb -Force
  [IO.File]::WriteAllText((Join-Path $W 'tasks\sim-tasks.json'), '{"Codex-V2-TLSFIX5-Interactive-20261120":{"State":"Running","UserId":"DESKTOP\\operator"},"Codex-V2-TLS-Renewal-Validation-20261120":{"State":"Ready","UserId":"SYSTEM"}}', $utf8)
  $wi = Invoke-Child (Join-Path $PSScriptRoot 'Disable-V2InstallLeftoverTasks.ps1') @('-Simulate', '-BackupRoot', $tb)
  $st0 = Get-Content (Join-Path $W 'tasks\sim-tasks.json') -Raw | ConvertFrom-Json
  Add-Res 'O4.report' ($wi.Code -eq 0 -and $wi.Out -match 'Running' -and $wi.Out -notmatch 'operator' -and $st0.'Codex-V2-TLSFIX5-Interactive-20261120'.State -eq 'Running' -and -not @(Get-ChildItem $tb).Count) 'звіт: стани, тип облікового запису без імені; нічого не змінено'
  $ap = Invoke-Child (Join-Path $PSScriptRoot 'Disable-V2InstallLeftoverTasks.ps1') @('-Simulate', '-BackupRoot', $tb, '-Apply', '-DecisionRef', 'TEST')
  $st1 = Get-Content (Join-Path $W 'tasks\sim-tasks.json') -Raw | ConvertFrom-Json
  Add-Res 'O4.apply' ($ap.Code -eq 0 -and $st1.'Codex-V2-TLSFIX5-Interactive-20261120'.State -eq 'Disabled' -and $st1.'Codex-V2-TLS-Renewal-Validation-20261120'.State -eq 'Disabled' -and @(Get-ChildItem $tb -Recurse -Filter '*.xml').Count -eq 2) 'експорт XML ×2, зупинка Running, вимкнення; без видалення'
  $deny = Invoke-Child (Join-Path $PSScriptRoot 'Disable-V2InstallLeftoverTasks.ps1') @('-Simulate', '-BackupRoot', $tb, '-TaskName', 'Integrity-V2-TLS-Renewal')
  Add-Res 'O4.deny' ($deny.Code -ne 0 -and $deny.Out -match 'Codex-V2') 'Integrity-V2-TLS-Renewal → STOP (дозволені лише Codex-V2-*)'

  # ------------------------------------------------------------------ O5: ротація V2_SECRET_KEY
  $r = New-Root 'rotate'
  $x0 = [IO.File]::ReadAllText("$r\services\backend\integrity-v2-backend.xml")
  $ro = Invoke-Child (Join-Path $PSScriptRoot 'Rotate-V2SecretKey.ps1') @('-Simulate', '-Root', $r, '-Apply', '-DecisionRef', 'TEST', '-BasePython', $Py)
  $x1 = [IO.File]::ReadAllText("$r\services\backend\integrity-v2-backend.xml")
  $k0 = [regex]::Match($x0, 'name="V2_SECRET_KEY" value="([^"]*)"').Groups[1].Value; $k1 = [regex]::Match($x1, 'name="V2_SECRET_KEY" value="([^"]*)"').Groups[1].Value
  $other = [regex]::Replace($x0, 'name="V2_SECRET_KEY" value="[^"]*"', 'K') -ceq [regex]::Replace($x1, 'name="V2_SECRET_KEY" value="[^"]*"', 'K')
  $leak = $ro.Out.Contains($k1) -or $ro.Out.Contains($k0) -or @(Get-ChildItem "$r\backups" -Recurse -Filter '*.json' | Where-Object { $c = [IO.File]::ReadAllText($_.FullName); $c.Contains($k1) -or $c.Contains($k0) }).Count
  Add-Res 'O5.rotate' ($ro.Code -eq 0 -and $k1 -ne $k0 -and $k1 -match '^[A-Za-z0-9+/]{64}$' -and $other -and -not $leak) "exit $($ro.Code); новий ключ 48 байтів base64; інші байти XML (SMTP) незмінні; значення не в журналі/доказі"
  $r = New-Root 'rotatefail'
  $b0 = [IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml")
  $rf = Invoke-Child (Join-Path $PSScriptRoot 'Rotate-V2SecretKey.ps1') @('-Simulate', '-Root', $r, '-Apply', '-DecisionRef', 'TEST', '-BasePython', $Py, '-SimulateFailAt', 'rotate.restart')
  $b1 = [IO.File]::ReadAllBytes("$r\services\backend\integrity-v2-backend.xml")
  $st = Get-Content (Join-Path $W 'rotatefail\sim\state.json') -Raw | ConvertFrom-Json
  Add-Res 'O5.rollback' ($rf.Code -eq 1 -and [Convert]::ToBase64String($b0) -eq [Convert]::ToBase64String($b1) -and $st.Services.'integrity-v2-backend'.State -eq 'Running') "збій після перезапуску → XML повернуто побайтово, backend працює зі старим ключем (exit $($rf.Code))"
  $pl = Invoke-Child (Join-Path $PSScriptRoot 'Rotate-V2SecretKey.ps1') @()
  Add-Res 'O5.plan' ($pl.Code -eq 0 -and $pl.Out -match 'ПЛАН') 'без -Apply — лише план'
} catch {
  $res.Add(('{0,-22} {1,-7} {2}' -f 'ERROR', 'FAIL', "$($_.Exception.Message) $($_.InvocationInfo.PositionMessage)"))
} finally {
  if (@($res | Where-Object { $_ -match '\sFAIL\s' }).Count) { $res.Add("INFO  стенд збережено: $W") } else { try { Remove-Item -LiteralPath $W -Recurse -Force } catch { $res.Add("INFO  стенд не видалено повністю ($($_.Exception.Message)): $W") } }
}
$res
$fail = @($res | Where-Object { $_ -match '\s(FAIL|NOT RUN)\s' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match '\sPASS\s' }).Count) PASS, $fail FAIL"
if ($fail) { exit 1 } else { exit 0 }
