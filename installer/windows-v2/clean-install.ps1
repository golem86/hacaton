# clean-install.ps1 — CLEAN INSTALL V2: перше встановлення на Windows з НОВИМИ порожніми SQLite (окремий сценарій, рішення №5 від 19.11).
# НЕ використовує механізми Upgrade/Rollback: Invoke-V2DbRestore, Assert-V2Restore*, Job Object (static-clean-install CI-S1/CI-S2).
# Set-V2ServiceStartMode — лише Disabled і лише у fail-closed (CI-S6).
# НЕ залежить від каталогів V1: WinSW і Caddy — лише з артефакту integrity-v2-tools із закріпленими SHA256 (static P26).
# V1 не обов'язкова: якщо є — baseline і «без змін» після кожного етапу; якщо немає — фіксується відсутність.
# CI-01: будь-який STOP після створення кореня ЦИМ запуском → Invoke-V2CleanInstallFailClosed: READY інвалідується (CLEAN-INIT-FAILED-INSTALL,
#   CLEAN-INIT-OK → REVOKED, CLEAN-INSTALL-FAILED у корені), служби V2 зупинено й Disabled; БД не видаляються; вихід 1 (2 — fail-closed не завершено).
# STOP до створення кореня (зокрема «корінь/служба вже існує») нічого не змінює — наявне встановлення не чіпається.
# Далі — ЛИШЕ свідомо: clean-install.ps1 -Abort -AbortReason '…' (видалення служб V2, корінь → <корінь>-abandoned-<ts>).
# Виконувати лише: (а) на ізольованому тест-хості за погодженням №5 (-TestHost) або (б) на сервері після DEPLOYMENT GO №5.
param(
  [Parameter(Mandatory)] [string] $DecisionRef,          # номер/дата рішення №5 (тест-хост або DEPLOYMENT GO)
  [string] $ToolsZip,                                    # integrity-v2-tools-*.zip (WinSW 2.12.0 + Caddy 2.11.9, SHA256 закріплені)
  [string] $DeployZip,                                   # integrity-v2-dde86e6-deploy.zip, SHA256 62363714…
  [string] $PyBase,                                      # базовий Python 3.13.14 (x64)
  [int] $ExpectedWindowsBuild,                           # C3: збірка Windows сервера з read-only preflight (тест-хост — та сама збірка)
  [string] $SrvDecisionRef,                              # рішення №5 щодо створення C:\srv (4.1а), якщо його немає
  [string] $AdminName = 'Staging Admin',
  [string] $AdminEmail,                                  # скринька адміністратора команди (bootstrap)
  [string] $TlsHost,                                     # ім'я вузла tailnet (production-значення — лише в приватному пакеті, не в Git)
  [string[]] $TlsAddresses,                             # IP вузла tailnet (IPv4, IPv6) — лише в приватному пакеті
  [switch] $TestHost,
  [switch] $Abort,
  [string] $AbortReason
)
$ErrorActionPreference = 'Stop'
$K = $PSScriptRoot
. "$K\V2-install-common.ps1"
function Stage([string]$Name) { "=== CLEAN INSTALL: $Name" }

# ---------------------------------------------------------------- G0: межі сценарію (до будь-якої дії)
if (-not $DecisionRef.Trim()) { Stop-V2 'потрібне посилання на рішення №5' }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Stop-V2 'потрібні права адміністратора' }
if ($V2Services['integrity-v2-backend'].Job) { Stop-V2 'Clean Install: Job Object не використовується ($V2Services.Job має бути $null)' }
if ($V2JobLocalRehearsal -or $V2JobTool.Py -or $V2JobTool.Script) { Stop-V2 'Clean Install: механізми Job Object / локальної репетиції вимкнено' }
if ($V2BackendName -ne 'integrity-v2-backend') { Stop-V2 'Clean Install: службу backend не перевизначено' }

if ($Abort) {
  if (-not $AbortReason) { Stop-V2 'потрібна причина переривання (-AbortReason)' }
  Stage "ПЕРЕРИВАННЯ ($AbortReason)"
  Invoke-V2CleanInstallAbort -Reason $AbortReason -Baseline (Get-V1Baseline -AllowAbsent)
  exit 0
}
foreach ($p in 'ToolsZip', 'DeployZip', 'PyBase', 'AdminEmail', 'ExpectedWindowsBuild', 'TlsHost', 'TlsAddresses') { if (-not (Get-Variable $p -ValueOnly)) { Stop-V2 "потрібен параметр -$p" } }

$Base = $null
$Owned = $false                                          # CI-01: корінь V2 створено саме цим запуском → fail-closed дозволено
try {
  Stage '4.0 preflight (лише читання)'
  $Base = Get-V1Baseline -AllowAbsent
  "INFO  V1: $(if ($Base.Present) { "присутня — контроль «без змін» після кожного етапу ($($Base.Services.Count) служб)" } else { 'відсутня' })"
  if ((Get-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription' -ErrorAction SilentlyContinue).EnableTranscripting -eq 1) { 'INFO  транскрипцію ввімкнено політикою — секрети вводяться лише як SecureString і не виводяться' }
  if ((Get-FileHash -LiteralPath $DeployZip -Algorithm SHA256).Hash.ToLower() -ne '62363714278da539db295bc809bd29bf0cc9bbde073ca8a26ff65f5211052559') { Stop-V2 'deploy ZIP: SHA256 ≠ 62363714…' }
  $null = Assert-V2Exe $PyBase 'python'
  if (@(Invoke-V2Native -Exe $PyBase -ArgList @('-I', '-c', 'import sys,struct; print(sys.version.split()[0], struct.calcsize("P")*8, sys.prefix == sys.base_prefix)') -Utf8 -What 'python version')[-1] -ne '3.13.14 64 True') { Stop-V2 'Python ≠ базовий 3.13.14 x64' }
  Test-V2WinswXml -XmlPath "$K\integrity-v2-backend.xml.template" -Name integrity-v2-backend -WinswVersion $WinswRefVersion -AllowPlaceholders
  Test-V2WinswXml -XmlPath "$K\integrity-v2-caddy.xml.template" -Name integrity-v2-caddy -WinswVersion $WinswRefVersion
  foreach ($n in 'integrity-v2-backend', 'integrity-v2-caddy') { if (Get-V2Service $n) { Stop-V2 "служба $n уже існує — Clean Install лише на чистому хості" } }
  if (Test-Path -LiteralPath $V2Root) { Stop-V2 "$V2Root уже існує — Clean Install лише на чистому хості (попередню спробу: -Abort)" }
  Assert-V2HostPreflight -ExpectedWindowsBuild $ExpectedWindowsBuild           # C3: Windows build, PowerShell 5.1 x64, вільне місце
  Assert-V2PortsFree                                                         # C3: TCP 80/443/8100/8199, UDP 443 — до будь-якого запису

  Stage '4.1 корінь V2 (захищений)'
  if (-not (Test-Path -LiteralPath 'C:\srv')) {
    if (-not $SrvDecisionRef) { Stop-V2 'C:\srv відсутній — потрібне рішення №5 (-SrvDecisionRef, варіант 4.1а)' }
    New-V2ProtectedDirectory -Path 'C:\srv' -DecisionRef $SrvDecisionRef
  }
  Assert-V2Ancestors
  if (Test-Path -LiteralPath $V2Root) { Stop-V2 "$V2Root уже існує — resume/повторне використання заборонено (попередню спробу: -Abort)" }
  $Owned = $true
  New-V2Root
  foreach ($d in 'pkg', 'app', 'app\frontend', 'venv', 'data', 'backups', 'logs\backend', 'logs\caddy', 'services\backend', 'services\caddy', 'caddy\bin', 'caddy\data', 'caddy\config') { $null = New-Item -ItemType Directory -Path "$V2Root\$d" }
  Assert-V2Root
  if ($Base) { Assert-V1Unchanged -Baseline $Base }

  Stage '4.2 пакет і інструменти V2 (без каталогів V1)'
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [IO.Compression.ZipFile]::ExtractToDirectory($DeployZip, "$V2Root\pkg")
  foreach ($l in Get-Content "$V2Root\pkg\SHA256SUMS.txt") { $h, $n = $l -split '\s+', 2; if ((Get-FileHash "$V2Root\pkg\$n" -Algorithm SHA256).Hash.ToLower() -ne $h) { Stop-V2 $n } }
  [IO.Compression.ZipFile]::ExtractToDirectory("$V2Root\pkg\integrity-v2-dde86e6-backend-src.zip", "$V2Root\app")
  [IO.Compression.ZipFile]::ExtractToDirectory("$V2Root\pkg\integrity-v2-dde86e6-dist.zip", "$V2Root\app\frontend")
  foreach ($l in Get-Content "$V2Root\pkg\DIST-SHA256.txt") { $h, $n = $l -split '\s+', 2; if ((Get-FileHash "$V2Root\app\frontend\$n" -Algorithm SHA256).Hash.ToLower() -ne $h) { Stop-V2 $n } }
  $Backend = "$V2Root\app\integrity-v2-dde86e6\backend"
  if (@(Get-ChildItem $Backend -Recurse -File).Count -ne 52) { Stop-V2 'код ≠ 52 файли' }
  Expand-V2Tools -ToolsZip $ToolsZip -Destination "$V2Root\pkg\tools"
  $WinSWSrc = "$V2Root\pkg\tools\winsw\integrity-v2-winsw.exe"; $CaddySrc = "$V2Root\pkg\tools\caddy\caddy.exe"
  $null = Assert-V2Winsw -Path $WinSWSrc -Label 'WinSW (артефакт V2)'
  $DbTool = "$K\v2_db_tool.py"
  if ($Base) { Assert-V1Unchanged -Baseline $Base }

  Stage '4.3 venv і офлайн-залежності'
  $null = Invoke-V2Native -Exe $PyBase -ArgList @('-E', '-s', '-m', 'venv', "$V2Root\venv") -What 'venv'
  $Py = "$V2Root\venv\Scripts\python.exe"; $W = "$V2Root\pkg\wheelhouse"
  [IO.Compression.ZipFile]::ExtractToDirectory("$V2Root\pkg\wheelhouse-cp313-win_amd64.zip", $W)
  $null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-m', 'pip', 'install', '--no-index', '--find-links', "$W\wheelhouse-cp313-win_amd64", '-r', "$Backend\requirements.txt") -What 'pip install'
  $null = Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-m', 'pip', 'check') -What 'pip check'
  $freeze = @(Invoke-V2Native -Exe $Py -ArgList @('-E', '-s', '-m', 'pip', 'freeze') -What 'pip freeze' | ForEach-Object { $_.ToLower().Replace('_', '-') } | Sort-Object)
  $req = @(Get-Content "$Backend\requirements.txt" | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim().ToLower().Replace('_', '-') } | Sort-Object)
  if (@(Compare-Object $freeze $req).Count) { Stop-V2 'pip freeze ≠ requirements.txt' }

  Stage '4.4 репетиція release на копії (5а)'
  $Reh = @(Invoke-V2Rehearsal -Py $Py -Backend $Backend -DbTool $DbTool -Port 8199); $Reh
  $Fp5a = ($Reh | Where-Object { $_.StartsWith('FINGERPRINT ') }) -replace '^FINGERPRINT ', ''
  if ($Fp5a -notmatch '^[0-9a-f]{64}$') { Stop-V2 'немає відбитка 5а' }

  Stage '4.5 нові БД (лише порожній data\), bootstrap адміністратора, строгий auth-schema, початкові копії'
  $D = "$V2Root\data"
  Initialize-V2CleanDatabases -Py $Py -Backend $Backend -DbTool $DbTool -DataDir $D -BackupDir "$V2Root\backups" -ReferenceFingerprint $Fp5a
  $null = Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$D\integrity_v2.db"; V2_AUTH_DB = "$D\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey) } -Body {
    Invoke-V2Interactive -Exe $Py -WorkingDirectory $Backend -What 'bootstrap admin' -ArgList @('-E', '-s', '-X', 'utf8', '-m', 'app.v2_bootstrap_admin', '--name', $AdminName, '--email', $AdminEmail)   # пароль ≥ 10, приховано
  }
  Complete-V2CleanDatabases -Py $Py -DbTool $DbTool -DataDir $D -BackupDir "$V2Root\backups" -ReferenceFingerprint $Fp5a
  if ($Base) { Assert-V1Unchanged -Baseline $Base }

  Stage '4.6 служба backend'
  Copy-Item -LiteralPath $WinSWSrc -Destination "$V2Root\services\backend\integrity-v2-backend.exe"
  $null = Assert-V2Winsw -Path "$V2Root\services\backend\integrity-v2-backend.exe" -Label 'WinSW копія backend'
  Copy-Item -LiteralPath "$K\integrity-v2-backend.xml.template" -Destination "$V2Root\services\backend\integrity-v2-backend.xml"
  Test-V2WinswXml -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Name integrity-v2-backend -WinswVersion $WinswRefVersion -AllowPlaceholders
  Install-V2Service -Name integrity-v2-backend
  $B = 'NT SERVICE\integrity-v2-backend'
  Grant-V2 "$V2Root\app\integrity-v2-dde86e6" $B '(OI)(CI)RX'; Grant-V2 "$V2Root\venv" $B '(OI)(CI)RX'
  Grant-V2 "$V2Root\data" $B '(OI)(CI)M'; Grant-V2 "$V2Root\logs\backend" $B '(OI)(CI)M'; Grant-V2 "$V2Root\services\backend" $B '(OI)(CI)RX'
  Set-V2Secrets -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml"
  Test-V2WinswXml -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Name integrity-v2-backend -WinswVersion $WinswRefVersion
  Assert-V2AclMatrix
  Invoke-V2ServiceStart -Name integrity-v2-backend -Checks {                                   # стандартний PreCheck: Assert-V2DataReady (CLEAN-INIT-OK)
    Assert-V2ServiceRunning -Name integrity-v2-backend -Addresses @('127.0.0.1')
    Wait-V2Http -Url 'http://127.0.0.1:8100/api/health'
    Assert-V2Http -Url 'http://127.0.0.1:8100/docs' -Expected 401
    Assert-V2Http -Url 'http://127.0.0.1:8100/api/assessments/1/participation' -Headers @{ 'X-Role' = 'manager' } -Expected 401
    if ($Base) { Assert-V1Unchanged -Baseline $Base }
  }

  Stage '4.7 Caddy V2 (приватний HTTPS)'
  Copy-Item -LiteralPath $CaddySrc -Destination "$V2Root\caddy\bin\caddy.exe"
  $null = Assert-V2FileHash -Path "$V2Root\caddy\bin\caddy.exe" -Sha256 $CaddyRefSha256 -Label 'копія caddy.exe'
  Copy-Item -LiteralPath "$V2Root\pkg\Caddyfile" -Destination "$V2Root\caddy\Caddyfile"
  $null = Invoke-V2Native -Exe "$V2Root\caddy\bin\caddy.exe" -ArgList @('adapt', '--config', "$V2Root\caddy\Caddyfile", '--adapter', 'caddyfile') -What 'caddy adapt'
  Copy-Item -LiteralPath $WinSWSrc -Destination "$V2Root\services\caddy\integrity-v2-caddy.exe"
  $null = Assert-V2Winsw -Path "$V2Root\services\caddy\integrity-v2-caddy.exe" -Label 'WinSW копія caddy'
  Copy-Item -LiteralPath "$K\integrity-v2-caddy.xml.template" -Destination "$V2Root\services\caddy\integrity-v2-caddy.xml"
  Test-V2WinswXml -XmlPath "$V2Root\services\caddy\integrity-v2-caddy.xml" -Name integrity-v2-caddy -WinswVersion $WinswRefVersion
  Install-V2Service -Name integrity-v2-caddy
  $C = 'NT SERVICE\integrity-v2-caddy'
  Grant-V2 "$V2Root\app\frontend\dist" $C '(OI)(CI)RX'; Grant-V2 "$V2Root\caddy\bin" $C '(OI)(CI)RX'; Grant-V2 "$V2Root\caddy\Caddyfile" $C 'R'
  Grant-V2 "$V2Root\caddy\data" $C '(OI)(CI)M'; Grant-V2 "$V2Root\caddy\config" $C '(OI)(CI)M'
  Grant-V2 "$V2Root\logs\caddy" $C '(OI)(CI)M'; Grant-V2 "$V2Root\services\caddy" $C '(OI)(CI)RX'
  Assert-V2AclMatrix
  Invoke-V2ServiceStart -Name integrity-v2-caddy -Checks {
    Assert-V2ServiceRunning -Name integrity-v2-caddy -Addresses $TlsAddresses
    $code = @(Invoke-V2Native -Exe "$env:SystemRoot\System32\curl.exe" -ArgList @('-sS', '-o', 'NUL', '-w', '%{http_code}', '--max-time', '20', "https://$TlsHost/") -What 'HTTPS (без -k)')[-1]
    if ($code -ne '200') { Stop-V2 "HTTPS → HTTP $code" }
    if (@(Get-NetUDPEndpoint -LocalPort 443 -ErrorAction SilentlyContinue).Count) { Stop-V2 'UDP 443' }
    if (@(Get-NetTCPConnection -State Listen -LocalPort 80 -ErrorAction SilentlyContinue).Count) { Stop-V2 ':80 слухається' }
    if ($Base) { Assert-V1Unchanged -Baseline $Base }
  }

  Stage '5 smoke (автоматична частина; S1–S8 у браузері — окремо)'
  $H = "https://$TlsHost"
  Assert-V2Http -Url "$H/" -Expected 200; Assert-V2Http -Url "$H/login" -Expected 200; Assert-V2Http -Url "$H/api/health" -Expected 200
  Assert-V2Http -Url "$H/docs" -Expected 401; Assert-V2Http -Url "$H/openapi.json" -Expected 401; Assert-V2Http -Url "$H/redoc" -Expected 404
  Assert-V2Http -Url "$H/api/assessments/1/participation" -Headers @{ 'X-Role' = 'manager' } -Expected 401
  Assert-V2Http -Url "$H/v2/auth/logout" -Method POST -Expected 403
  Assert-V2Http -Url "$H/assets/missing.js" -Expected 404
  if ($Base) { Assert-V1Unchanged -Baseline $Base }
  "CLEAN INSTALL PASS ($(if ($TestHost) { 'тест-хост' } else { 'сервер' }); рішення $DecisionRef). Далі — smoke S1–S8 у браузері."
  exit 0
} catch {
  $why = $_.Exception.Message -replace '^STOP: ', ''
  "STOP: CLEAN INSTALL: $why"
  if (-not $Owned) {
    'INFO  корінь V2 цим запуском не створювався — наявний стан (і служби V2, якщо є) не змінено'
    exit 1
  }
  try { Invoke-V2CleanInstallFailClosed -Reason $why }
  catch {
    "КРИТИЧНО: $($_.Exception.Message -replace '^STOP: ', '')"
    exit 2
  }
  'Далі — лише свідомо: clean-install.ps1 -DecisionRef <…> -Abort -AbortReason <…> (служби V2 видаляються, корінь → -abandoned-<ts>); автоматичного resume немає'
  exit 1
}
