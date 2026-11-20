# test-clean-install-current.ps1 — сухий прогін Clean Install ПОТОЧНОГО релізу в %TEMP% (без прав адміністратора, без служб і C:\srv).
# Справжні: перевірка пакета (формат пакета оновлення), розгортання коду/dist у тимчасовий корінь, офлайн pip --require-hashes у новий
# venv, bind-check, Initialize → bootstrap (справжній v2_clean_bootstrap_admin.py, getpass підмінено) → Complete (integrity 6 / auth 2,
# mark-synthetic), XML служби з Gmail SMTP. Фейкові (адаптери common): SCM (sc.exe / Win32_Service), ACL, процеси й слухачі.
# NOT RUN тут: WinSW install/start, icacls, Caddy/HTTPS smoke, LM на справжньому хості — лише на тест-хості / сервері.
# Запуск: powershell -NoProfile -ExecutionPolicy Bypass -File .\test-clean-install-current.ps1 -Py <python із залежностями backend>
#           -PackageDir <…\package> -ApprovedSums <…\APPROVED-SHA256.txt> -ReleaseId integrity-v2-<sha7>
param([Parameter(Mandatory)] [string] $Py, [Parameter(Mandatory)] [string] $PackageDir, [Parameter(Mandatory)] [string] $ApprovedSums,
      [Parameter(Mandatory)] [string] $ReleaseId, [switch] $SkipVenv)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'V2-install-common.ps1')
$ErrorActionPreference = 'Stop'
$K = $PSScriptRoot
$res = New-Object System.Collections.Generic.List[string]
function Add-Res([string]$id, [bool]$ok, [string]$d) { $res.Add(('{0,-14} {1,-5} {2}' -f $id, $(if ($ok) { 'PASS' } else { 'FAIL' }), $d)) }
function Add-NotRun([string]$id, [string]$d) { $res.Add(('{0,-14} NOT RUN {1}' -f $id, $d)) }
function Get-Stop([scriptblock]$b) { try { $null = & $b; $null } catch { "$($_.Exception.Message)" } }
$tmp = Join-Path $env:TEMP ('v2ci-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$null = New-Item -ItemType Directory -Path $tmp
$prodRoot = $V2Root
$origNative = (Get-Item function:Invoke-V2Native).ScriptBlock
try {
  # ------------------------------------------------------------- P1: пакет
  $p = $null; $m = Get-Stop { $script:p = Assert-V2CleanPackage -PackageDir $PackageDir -ApprovedSums $ApprovedSums -ReleaseId $ReleaseId }
  Add-Res 'P1.package' (-not $m -and $p.Pins.Count -ge 19 -and $p.BackendManifest.Contains('backend/app/migrations.py') -and @($p.Skipped | Where-Object { $_ -match 'bootstrap' }).Count -ge 1) "пакет PASS: backend $($p.BackendManifest.Count) файлів, dist $($p.DistManifest.Count), вимог $($p.Pins.Count), bootstrap не розгортається: $($p.Skipped -join ', ') $m"
  function New-PkgCopy([string]$tag) { $d = Join-Path $tmp "pk-$tag"; $null = New-Item -ItemType Directory "$d\package\wheels"; foreach ($f in Get-ChildItem $PackageDir -File) { Copy-Item $f.FullName "$d\package" }; foreach ($f in Get-ChildItem "$PackageDir\wheels" -File) { Copy-Item $f.FullName "$d\package\wheels" }; Copy-Item $ApprovedSums "$d\APPROVED-SHA256.txt"; $d }
  function Update-Approved([string]$d) { $l = foreach ($n in 'backend-src.zip', 'BACKEND-SHA256.txt', 'dist.zip', 'DIST-SHA256.txt', 'Caddyfile', 'requirements-hashed.txt') { "$(Get-V2FileSha256 "$d\package\$n")  $n" }; [IO.File]::WriteAllLines("$d\APPROVED-SHA256.txt", [string[]]$l) }
  $neg = @(
    @('P1.sum', { param($d) [IO.File]::AppendAllText("$d\package\Caddyfile", "`n# x`n") }, '*SHA256 Caddyfile ≠ сумі з окремого каналу*'),
    @('P1.approved-in-pkg', { param($d) Copy-Item "$d\APPROVED-SHA256.txt" "$d\package\APPROVED-SHA256.txt" }, '*окремим каналом*'),
    @('P1.req-nohash', { param($d) $r = [IO.File]::ReadAllLines("$d\package\requirements-hashed.txt"); $r[0] = ($r[0] -split ' ')[0]; [IO.File]::WriteAllLines("$d\package\requirements-hashed.txt", $r); Update-Approved $d }, '*без точної версії й sha256*'),
    @('P1.req-missing', { param($d) $r = @([IO.File]::ReadAllLines("$d\package\requirements-hashed.txt") | Where-Object { $_ -notmatch '^(?i)reportlab==' }); [IO.File]::WriteAllLines("$d\package\requirements-hashed.txt", [string[]]$r); Update-Approved $d }, '*не містить reportlab==*'),
    @('P1.no-wheels', { param($d) Remove-Item "$d\package\wheels" -Recurse -Force }, '*лише файли .whl*'),
    @('P1.extra-file', { param($d) [IO.File]::WriteAllText("$d\package\notes.txt", 'x') }, '*зайві об''єкти: notes.txt*'),
    @('P1.dist-manifest', { param($d) $r = [IO.File]::ReadAllLines("$d\package\DIST-SHA256.txt"); $r[0] = ('0' * 64) + $r[0].Substring(64); [IO.File]::WriteAllLines("$d\package\DIST-SHA256.txt", $r); Update-Approved $d }, '*dist.zip:*≠ DIST-SHA256.txt*'),
    @('P1.release-id', { param($d) }, '*запис поза integrity-v2-other/backend/*'))
  foreach ($c in $neg) {
    $d = New-PkgCopy $c[0]; & $c[1] $d
    $rid = if ($c[0] -eq 'P1.release-id') { 'integrity-v2-other' } else { $ReleaseId }
    $ap = if ($c[0] -eq 'P1.approved-in-pkg') { "$d\package\APPROVED-SHA256.txt" } else { "$d\APPROVED-SHA256.txt" }
    $m = Get-Stop { Assert-V2CleanPackage -PackageDir "$d\package" -ApprovedSums $ap -ReleaseId $rid }
    Add-Res $c[0] ($m -like "STOP:$($c[2])") "негативний пакет → STOP до будь-якого запису ($m)"
  }

  # ------------------------------------------------------------- P2: розгортання в тимчасовий корінь (як 4.1–4.2)
  $script:V2Root = Join-Path $tmp 'r\iv2'
  foreach ($d in 'pkg', 'app', 'app\frontend', 'data', 'backups') { $null = New-Item -ItemType Directory -Path "$V2Root\$d" -Force }
  $V2AppRelease = $ReleaseId
  $pk = Copy-V2CleanPackage -Package $p -ApprovedSums $ApprovedSums -Destination "$V2Root\pkg\$ReleaseId"
  $o1 = Expand-V2ReleaseBackend -Package $pk -AppDir "$V2Root\app\$ReleaseId" -PkgManifestPath "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt"
  $o2 = Expand-V2ReleaseDist -Package $pk -DistDir "$V2Root\app\frontend\dist"
  $Backend = "$V2Root\app\$ReleaseId\backend"
  $bs = @(Get-ChildItem "$V2Root\app" -Recurse -File | Where-Object { $_.Name -match '(?i)bootstrap' })
  $pmOk = (Get-V2FileSha256 "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt") -eq (Get-V2FileSha256 "$PackageDir\BACKEND-SHA256.txt")
  Add-Res 'P2.deploy' ($o1 -like 'PASS*' -and $o2 -like 'PASS*' -and -not $bs.Count -and $pmOk -and (Get-V2ReleaseDir) -eq "$V2Root\app\$ReleaseId" -and (Test-Path "$V2Root\app\frontend\dist\index.html")) "код app\$ReleaseId = маніфест без bootstrap; маніфест → pkg\$ReleaseId-BACKEND-SHA256.txt (= пакету, його бере Update-V2InPlace); dist = DIST-SHA256"
  $m = Get-Stop { Expand-V2ReleaseBackend -Package $pk -AppDir "$V2Root\app\$ReleaseId" -PkgManifestPath "$V2Root\pkg\x.txt" }
  Add-Res 'P2.no-reuse' ($m -like 'STOP:*уже існує*') 'повторне розгортання поверх наявного каталогу релізу → STOP'

  # ------------------------------------------------------------- P3: venv офлайн (--require-hashes), bind-check
  $base = (@(& $Py -I -c 'import sys; print(sys._base_executable)'))[-1].Trim()
  $vpy = $Py
  if ($SkipVenv) { Add-NotRun 'P3.venv' '-SkipVenv: використано наданий -Py' }
  else {
    $venv = Join-Path $tmp 'v'
    $null = Invoke-V2Native -Exe $base -ArgList @('-E', '-s', '-m', 'venv', $venv) -What 'venv'
    $vpy = "$venv\Scripts\python.exe"
    $m = Get-Stop { $script:o3 = Install-V2Requirements -Py $vpy -Package $pk }
    Add-Res 'P3.venv' (-not $m -and $o3 -like 'PASS*') "новий venv: $o3 $m"
  }
  $b = @(Assert-V2ReleaseSchemaBinding -Py $base -ReleasePy $vpy -DbTool "$K\v2_db_tool.py" -Backend $Backend -Manifest "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt")
  Add-Res 'P3.bind' (($b -join '|') -eq 'PASS  BIND OK kind=auth version=2|PASS  BIND OK kind=integrity version=6') "bind-check коду релізу: $($b -join '; ')"
  $m = Get-Stop { Assert-V2ReleaseSchemaBinding -Py $base -ReleasePy $vpy -DbTool "$K\v2_db_tool.py" -Backend $Backend -Manifest "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt" -IntegrityVersion 3 -AuthVersion 1 }
  Add-Res 'P3.bind-old' ($m -like 'STOP:*bind-check*') 'очікування 3/1 проти коду релізу → STOP'

  # ------------------------------------------------------------- P4: нові БД 6/2 → bootstrap (справжній) → Complete
  $D = "$V2Root\data"; $Bk = "$V2Root\backups"
  $ri = @(Initialize-V2CleanDatabases -Py $vpy -Backend $Backend -DbTool "$K\v2_db_tool.py" -DataDir $D -BackupDir $Bk -ReleaseId $ReleaseId)
  $fp = Invoke-V2DbTool -Py $base -DbTool "$K\v2_db_tool.py" -ArgList @('fingerprint', "$D\integrity_v2.db")
  Add-Res 'P4.init' (@($ri | Where-Object { $_ -like 'PASS  нова integrity_v2.db: INTEGRITY SCHEMA OK version=6*' }).Count -eq 1 -and @($ri | Where-Object { $_ -like 'PASS  нова v2_auth.db: AUTH SCHEMA OK version=2*' }).Count -eq 1 -and $ri -contains 'SCHEMA OK') 'seed (development, лише нова БД) → migrations (release) → check_schema → строгі схеми integrity 6 / auth 2'
  $patch = 'import getpass,runpy,sys; getpass.getpass=lambda prompt="": "Synthetic-Pass-123"; s=sys.argv[1]; sys.argv=[s]+sys.argv[2:]; runpy.run_path(s, run_name="__main__")'
  $boot = { Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$D\integrity_v2.db"; V2_AUTH_DB = "$D\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey) } -Body {
      Invoke-V2Native -Exe $vpy -WorkingDirectory $Backend -Utf8 -What 'bootstrap admin (getpass підмінено)' -ArgList @('-I', '-X', 'utf8', '-c', $patch.Replace('"', "'"), "$K\v2_clean_bootstrap_admin.py", '--backend', $Backend, '--name', 'Synthetic Admin', '--email', 'admin@example.test') } }
  $ob = @(& $boot)
  Add-Res 'P4.bootstrap' ($ob[-1] -like 'Локального адміністратора створено*' -and ($ob -join ' ') -notmatch 'Synthetic-Pass|admin@example') "перший адміністратор — одноразово з каталогу інсталятора: $($ob[-1])"
  $m = Get-Stop { & $boot }
  Add-Res 'P4.second-admin' ($m -like '*Адміністратор уже існує*') 'повторний bootstrap → відмова (require_no_admin)'
  $rc = @(Complete-V2CleanDatabases -Py $base -DbTool "$K\v2_db_tool.py" -DataDir $D -BackupDir $Bk -ReferenceFingerprint $fp)
  $st = @(Get-ChildItem $D -File | ForEach-Object Name)
  $metaPy = Join-Path $tmp 'meta.py'; [IO.File]::WriteAllText($metaPy, "import sqlite3, sys`nc = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)`nprint(c.execute(""select value from instance_meta where key = 'dataset'"").fetchone()[0])`n")
  $meta = (@(& $base -I $metaPy "$D\integrity_v2.db"))[-1]
  Add-Res 'P4.complete' (@($st | Where-Object { $_ -like 'CLEAN-INIT-OK-*' }).Count -eq 1 -and @($rc | Where-Object { $_ -like 'PASS  MARK-SYNTHETIC OK dataset=synthetic*' }).Count -eq 1 -and $meta -eq 'synthetic' -and (Assert-V2DataReady -DataDir $D) -like 'PASS*' -and @(Get-ChildItem $Bk -Filter '*-initial-*.db').Count -eq 2) "CLEAN-INIT-OK; mark-synthetic; instance_meta.dataset = $meta; копії initial 6/2"
  $vi = Assert-V2DbStrict -Py $base -DbTool "$K\v2_db_tool.py" -Path "$D\integrity_v2.db" -Kind integrity; $va = Assert-V2DbStrict -Py $base -DbTool "$K\v2_db_tool.py" -Path "$D\v2_auth.db" -Kind auth
  Add-Res 'P4.versions' ($vi.Version -eq 6 -and $va.Version -eq 2) "user-version з файлів: integrity $($vi.Version), auth $($va.Version) (строго; так їх читають TLS-скрипти)"
  $m = Get-Stop { Get-V2DbVersion -Py $base -DbTool "$K\v2_db_tool.py" -Path "$D\v2_auth.db" -Kind integrity }
  Add-Res 'P4.kind' ($m -like 'STOP:*вид БД auth ≠ integrity*') 'вид БД перевіряється'

  # ------------------------------------------------------------- P5: XML служби — workingdirectory релізу, SMTP Gmail / Custom
  $script:V2Root = $prodRoot
  $tc = Join-Path $tmp 'tc'
  $null = New-V2TargetConfig -CaddySource "$PackageDir\Caddyfile" -BackendSource "$K\integrity-v2-backend.xml.template" -Destination $tc -HostName 'v2-host.example.ts.net' -Addresses @('100.64.0.10') -UseFileTls -ReleaseId $ReleaseId
  $xmlPath = "$tc\integrity-v2-backend.xml"
  $plan = Get-V2SmtpPlan -Mode Gmail -User 'project.account@example.com'
  $fakeReader = { param($prompt) ConvertTo-SecureString 'abcd efgh ijkl mnop' -AsPlainText -Force }
  $o5 = Set-V2Secrets -XmlPath $xmlPath -Rehearsal -Prompted @('V2_SMTP_PASSWORD') -Values $plan.Values -SecretReader { param($n) Read-V2GmailAppPassword -Reader $fakeReader }
  [xml]$x = Get-Content $xmlPath -Raw -Encoding UTF8; $e = @{}; foreach ($n in $x.service.env) { $e[$n.name] = $n.value }
  $wx = Get-Stop { Test-V2WinswXml -XmlPath $xmlPath -Name integrity-v2-backend -WinswVersion $WinswRefVersion }
  Add-Res 'P5.gmail' ($o5 -like 'PASS*' -and $e['V2_SMTP_HOST'] -eq 'smtp.gmail.com' -and $e['V2_SMTP_PORT'] -eq '587' -and $e['V2_SMTP_TLS_MODE'] -eq 'starttls' -and $e['V2_SMTP_USER'] -eq 'project.account@example.com' -and
                      $e['V2_SMTP_FROM'] -eq $e['V2_SMTP_USER'] -and $e['V2_SMTP_PASSWORD'] -ceq 'abcdefghijklmnop' -and $e['V2_SECRET_KEY'].Length -ge 64 -and -not $e.ContainsKey('V2_AUTH_DEV_MAIL') -and
                      $x.service.workingdirectory -eq "C:\srv\integrity-v2\app\$ReleaseId\backend" -and -not $wx) "Gmail: smtp.gmail.com:587 starttls, FROM = USER, пароль застосунку без пробілів; workingdirectory app\$ReleaseId\backend; Test-V2WinswXml PASS"
  $m = Get-Stop { Read-V2GmailAppPassword -Reader { param($p) if ($p -like 'Повторіть*') { ConvertTo-SecureString 'abcdefghijklmnoq' -AsPlainText -Force } else { ConvertTo-SecureString 'abcdefghijklmnop' -AsPlainText -Force } } }
  Add-Res 'P5.gmail-mismatch' ($m -like 'STOP:*не збігаються*') 'паролі застосунку не збігаються → STOP'
  $m = Get-Stop { Read-V2GmailAppPassword -Reader { param($p) ConvertTo-SecureString 'short-pass-1' -AsPlainText -Force } }
  Add-Res 'P5.gmail-format' ($m -like 'STOP:*16 латинських літер*') 'пароль не 16 літер → STOP'
  $cp = Get-V2SmtpPlan -Mode Custom -User 'mailer' -SmtpHost 'smtp.example.org' -Port 465 -TlsMode implicit -From 'noreply@example.org'
  Add-Res 'P5.custom' ($cp.Values.V2_SMTP_HOST -eq 'smtp.example.org' -and $cp.Values.V2_SMTP_PORT -eq '465' -and $cp.Values.V2_SMTP_TLS_MODE -eq 'implicit' -and -not $cp.Gmail) 'інший SMTP: host/port/TLS mode/from — параметрами'
  $m1 = Get-Stop { Get-V2SmtpPlan -Mode Custom -User 'x' -SmtpHost 'localhost' -From 'a@example.org' }
  $m2 = Get-Stop { Set-V2Secrets -XmlPath $xmlPath -Rehearsal -Prompted @('V2_SMTP_PASSWORD') -Values @{ V2_SMTP_PASSWORD = 'x' } }
  $m3 = Get-Stop { Get-V2SmtpPlan -Mode Gmail -User 'a@gmail.com' -From 'b@gmail.com' }
  Add-Res 'P5.smtp-neg' ($m1 -like 'STOP:*' -and $m2 -like 'STOP:*' -and $m3 -like 'STOP:*FROM = USER*') 'localhost-relay, пароль у -Values, Gmail FROM ≠ USER → STOP'

  # ------------------------------------------------------------- P6: режим запуску (фейковий SCM)
  $svc = @{}
  Set-Item function:script:Get-V2Service { param([string]$Name) $svc[$Name] }
  Set-Item function:script:Invoke-V2Native { param([string]$Exe, [string[]]$ArgList, [string]$What, [int[]]$OkCodes, [string]$WorkingDirectory, [switch]$Utf8, [int]$TimeoutSec)
    if ($Exe -notlike '*\sc.exe') { throw "REAL-CALL-BLOCKED: $Exe" }
    if ($ArgList[2] -eq 'start=' -and $ArgList[3] -eq 'delayed-auto' -and -not $global:ScIgnore) { $svc[$ArgList[1]].StartMode = 'Auto'; $svc[$ArgList[1]] | Add-Member -Force NoteProperty DelayedAutoStart $true }
    @() }
  foreach ($n in 'integrity-v2-backend', 'integrity-v2-caddy') { $svc[$n] = [pscustomobject]@{ Name = $n; State = 'Running'; StartMode = 'Manual'; StartName = $V2Services[$n].Account; PathName = "`"$($V2Services[$n].Exe)`""; ProcessId = 10 } }
  $global:ScIgnore = $false
  $o6 = @(foreach ($n in 'integrity-v2-backend', 'integrity-v2-caddy') { Set-V2ServiceDelayedAuto -Name $n })
  $a6 = Assert-V2Service -Name integrity-v2-backend -State Running -StartModes Manual, Auto
  $m6 = Get-Stop { Assert-V2Service -Name integrity-v2-backend -State Running }
  Add-Res 'P6.delayed' (@($o6 | Where-Object { $_ -like 'PASS*Automatic (Delayed Start)*' }).Count -eq 2 -and $a6 -like 'PASS*Auto, Running' -and $m6 -like 'STOP:*очікується Manual*') 'обидві служби → Automatic (Delayed Start), read-back; Assert-V2Service -StartModes Manual,Auto приймає Auto, за замовчуванням — лише Manual'
  $svc['integrity-v2-backend'] = [pscustomobject]@{ Name = 'integrity-v2-backend'; State = 'Running'; StartMode = 'Auto'; StartName = 'x'; PathName = 'x'; ProcessId = 1 }
  $global:ScIgnore = $true
  $m = Get-Stop { Set-V2ServiceDelayedAuto -Name integrity-v2-backend }
  $m2 = Get-Stop { Set-V2ServiceDelayedAuto -Name 'Spooler' }
  Add-Res 'P6.readback' ($m -like 'STOP:*не підтверджено*Auto/delayed=False*' -and $m2 -like 'STOP:*лише для служб V2*') 'Auto без DelayedAutoStart → STOP; чужа служба → STOP'
  $global:ScIgnore = $false

  # ------------------------------------------------------------- P7: матриця ACL з lm\ (фейкові ACL, справжнє дерево)
  $script:V2Root = Join-Path $tmp 'acl\iv2'; $V2AppRelease = $ReleaseId
  foreach ($d in "app\$ReleaseId\backend\app", 'app\frontend\dist', 'backups', 'caddy\bin', 'caddy\data', 'caddy\config', 'data', 'logs\backend', 'logs\caddy', 'logs\lm', 'pkg',
                 'services\backend', 'services\caddy', 'services\lm', 'venv', 'lm\bin', 'lm\models', 'lm\secrets') { $null = New-Item -ItemType Directory -Path "$V2Root\$d" -Force }
  foreach ($f in "app\$ReleaseId\backend\app\main.py", 'app\frontend\dist\index.html', 'caddy\Caddyfile', 'lm\bin\llama-server.exe', 'lm\models\m.gguf', 'lm\secrets\api-key.txt', 'lm\LM-BIN-SHA256.txt', 'services\lm\integrity-v2-lm.xml') { [IO.File]::WriteAllText("$V2Root\$f", 'x') }
  $global:TSid = @{ b = Get-V2ServiceSid 'integrity-v2-backend'; c = Get-V2ServiceSid 'integrity-v2-caddy'; l = Get-V2ServiceSid 'integrity-v2-lm' }
  $global:AclOverride = @{}
  $global:TRules = @(@("app\$ReleaseId", 'b', 'RX'), @('venv', 'b', 'RX'), @('services\backend', 'b', 'RX'), @('data', 'b', 'M'), @('logs\backend', 'b', 'M'),
             @('app\frontend\dist', 'c', 'RX'), @('caddy\bin', 'c', 'RX'), @('caddy\Caddyfile', 'c', 'R'), @('services\caddy', 'c', 'RX'), @('caddy\data', 'c', 'M'), @('caddy\config', 'c', 'M'), @('logs\caddy', 'c', 'M'),
             @('lm\bin', 'l', 'RX'), @('lm\models', 'l', 'RX'), @('lm\secrets\api-key.txt', 'l', 'R'), @('services\lm', 'l', 'RX'), @('logs\lm', 'l', 'M'))
  Set-Item function:script:Get-V2Acl { param([string]$Path)
    $full = [IO.Path]::GetFullPath($Path); $rel = $full.Substring($V2Root.Length).TrimStart('\'); $dir = Test-Path -LiteralPath $full -PathType Container
    $inh = if ($dir) { 'OICI' } else { '' }
    $sddl = "O:BAD:PAI(A;$inh;FA;;;BA)(A;$inh;FA;;;SY)"
    foreach ($r in $global:TRules) { if ($rel -eq $r[0] -or $rel.StartsWith($r[0] + '\')) { $mask = @{ RX = '0x1200a9'; R = '0x120089'; M = '0x1301bf' }[$r[2]]; $sddl += "(A;$inh;$mask;;;$($global:TSid[$r[1]]))" } }
    if ($global:AclOverride.ContainsKey($rel)) { $sddl = $global:AclOverride[$rel] }
    $sec = if ($dir) { New-Object Security.AccessControl.DirectorySecurity } else { New-Object Security.AccessControl.FileSecurity }
    $sec.SetSecurityDescriptorSddlForm($sddl); $sec }
  $svc['integrity-v2-caddy'] = [pscustomobject]@{ Name = 'integrity-v2-caddy'; State = 'Running'; StartMode = 'Auto'; StartName = 'x'; PathName = 'x'; ProcessId = 1 }
  $m = Get-Stop { $script:o7 = @(Assert-V2AclMatrix) }
  Add-Res 'P7.matrix-lm' (-not $m -and @($o7 | Where-Object { $_ -like "PASS  *\lm\bin*" }).Count -ge 1 -and @($o7 | Where-Object { $_ -like '*api-key.txt: ACL = матриця' }).Count -eq 1) "Assert-V2AclMatrix: корінь із lm\ прийнято; lm\bin/models RX, ключ R, logs\lm M, services\lm RX $m"
  $global:AclOverride['lm\secrets'] = "O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)(A;OICI;0x1200a9;;;$($global:TSid.l))"
  $m1 = Get-Stop { Assert-V2AclMatrix }; $global:AclOverride.Clear()
  [IO.File]::WriteAllText("$V2Root\lm\extra.txt", 'x'); $m2 = Get-Stop { Assert-V2AclMatrix }; Remove-Item "$V2Root\lm\extra.txt"
  Remove-Item "$V2Root\lm" -Recurse -Force; $m3 = Get-Stop { $script:o7b = @(Assert-V2AclMatrix) }
  Add-Res 'P7.matrix-neg' ($m1 -like 'STOP:*lm\secrets: ACL ≠ матриці*' -and $m2 -like 'STOP:*зайві extra.txt*' -and -not $m3) 'lm\secrets із читанням для служби LM → STOP; зайвий файл у lm\ → STOP; без lm\ — матриця як раніше'

  # ------------------------------------------------------------- P8: доказ служби LM для TLS-скриптів (фейкові SCM/процеси/слухачі)
  $script:V2Root = $prodRoot
  Set-Item function:script:Get-V2ServiceTree { param([string]$Name, $Unresolved) $l = New-Object System.Collections.Generic.List[object]; $l.Add([pscustomobject]@{ Pid = 500; Owner = 'NT SERVICE\integrity-v2-lm' }); $l.Add([pscustomobject]@{ Pid = 501; Owner = 'NT SERVICE\integrity-v2-lm' }); , $l }
  $global:Lst = @([pscustomobject]@{ LocalAddress = '127.0.0.1'; LocalPort = 8200; OwningProcess = 501 })
  Set-Item function:script:Get-V2Listeners { param([int[]]$Ports) @($global:Lst) }
  $svc.Remove('integrity-v2-lm')
  $n8 = Get-V2LmServiceEvidence
  $svc['integrity-v2-lm'] = [pscustomobject]@{ Name = 'integrity-v2-lm'; State = 'Running'; StartMode = 'Auto'; StartName = 'NT SERVICE\integrity-v2-lm'; PathName = "`"C:\srv\integrity-v2\services\lm\integrity-v2-lm.exe`""; ProcessId = 500 }
  $e8 = Get-V2LmServiceEvidence
  $global:Lst = @([pscustomobject]@{ LocalAddress = '0.0.0.0'; LocalPort = 8200; OwningProcess = 501 }); $m1 = Get-Stop { Get-V2LmServiceEvidence }
  $global:Lst = @([pscustomobject]@{ LocalAddress = '127.0.0.1'; LocalPort = 8200; OwningProcess = 501 }); $svc['integrity-v2-lm'].State = 'Stopped'; $m2 = Get-Stop { Get-V2LmServiceEvidence }
  Add-Res 'P8.lm-evidence' ($null -eq $n8 -and ($e8.Pids -join ',') -eq '500,501' -and $m1 -like 'STOP:*127.0.0.1*' -and $m2 -like 'STOP:*не працює*') 'LM: немає служби → $null; Running → PID дерева (виключаються з евристик); слухач не loopback / зупинена → STOP'
  Set-Item function:script:Get-V2CimProcessList { @([pscustomobject]@{ ProcessId = 500; ExecutablePath = "$V2Root\services\lm\integrity-v2-lm.exe"; CommandLine = ''; CreationDate = $null }, [pscustomobject]@{ ProcessId = 777; ExecutablePath = "$V2Root\venv\Scripts\python.exe"; CommandLine = ''; CreationDate = $null }) }
  $sp = @(Get-V2SuspectProcesses -IgnorePids $e8.Pids | ForEach-Object ProcessId)
  Add-Res 'P8.ignore' (($sp -join ',') -eq '777') 'евристика «процеси V2» без дерева LM (-IgnorePids), процес backend лишається'

  # ------------------------------------------------------------- P9: операторські TLS-скрипти і завдання поновлення (статично)
  $tlsT = @{}; foreach ($f in 'Restart-V2Tlsfix5Verified.ps1', 'Verify-V2Tlsfix5Runtime.ps1', 'Renew-V2TlsPair.ps1', 'Invoke-V2TlsScheduled.ps1', 'Request-V2TlsPair.ps1') { $tlsT[$f] = [IO.File]::ReadAllText("$K\tls\$f") }
  $op = $tlsT['Restart-V2Tlsfix5Verified.ps1'] + $tlsT['Verify-V2Tlsfix5Runtime.ps1']
  Add-Res 'P9.operator' ($op -notmatch "'--expect-version', '\d'" -and $op -notmatch "@\('integrity_v2\.db','3'\)" -and $op.Contains('-StartModes Manual, Auto') -and $op.Contains('Get-V2LmServiceEvidence') -and $op.Contains('Assert-V2DbStrict') -and
                         $op.Contains('-IgnorePids') -and $op -notmatch 'FB19F4D69A8D505CA17007C542387D4C89036BF5B4AC2E70D2E0AEDB4872A56E') 'Restart/Verify: Auto або Manual; версії БД — user-version/SCHEMA_SPECS; LM перевіряється й не зупиняється; без закріпленого common TLSFIX5'
  $rn = $tlsT['Renew-V2TlsPair.ps1'] + $tlsT['Invoke-V2TlsScheduled.ps1'] + $tlsT['Request-V2TlsPair.ps1']
  Add-Res 'P9.renewal' ($tlsT['Renew-V2TlsPair.ps1'].Contains("`$s.StartMode -notin 'Auto','Manual'") -and $rn -notmatch 'expect-version|auth-schema|user_version' -and $rn -notmatch "StartMode -ne 'Manual'") 'Integrity-V2-TLS-Renewal: Auto і Manual прийнятні; від версій БД не залежить (без змін)'
} catch {
  Add-Res 'ERR' $false "необроблена помилка: $($_.Exception.Message) @ $($_.InvocationInfo.ScriptLineNumber)"
} finally {
  Set-Item function:script:Invoke-V2Native $origNative
  $script:V2Root = $prodRoot
  $full = [IO.Path]::GetFullPath($tmp)
  if ($full.StartsWith([IO.Path]::GetFullPath($env:TEMP), [StringComparison]::OrdinalIgnoreCase) -and (Split-Path $full -Leaf) -match '^v2ci-[0-9a-f]{8}$') { Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction SilentlyContinue }
}
Add-NotRun 'HOST.services' 'WinSW install/start, icacls, sc.exe delayed-auto на справжньому SCM, Caddy/HTTPS smoke — лише clean-install.ps1 -TestHost на ізольованому тест-хості'
Add-NotRun 'HOST.lm' 'lm\Install-V2LmService.ps1 -Apply зі справжнім llama-server і моделлю — лише на сервері (перевірка хоста)'
$res
$fail = @($res | Where-Object { $_ -match '^\S+\s+FAIL ' }).Count
"Підсумок: $(@($res | Where-Object { $_ -match '^\S+\s+PASS ' }).Count) PASS, $fail FAIL, $(@($res | Where-Object { $_ -match ' NOT RUN ' }).Count) NOT RUN (host-only)"
if ($fail) { exit 1 } else { exit 0 }
