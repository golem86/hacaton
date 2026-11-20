# clean-install.ps1 — CLEAN INSTALL V2: перше встановлення ПОТОЧНОГО релізу на Windows з НОВИМИ порожніми SQLite (окремий сценарій,
# рішення №5). Документація: docs\CLEAN_INSTALL_CURRENT.md.
# Пакет — того самого формату, що й пакет оновлення (docs\UPGRADE_IN_PLACE.md §1), усі частини обов'язкові:
#   <PackageDir>\backend-src.zip + BACKEND-SHA256.txt, dist.zip + DIST-SHA256.txt, Caddyfile (шаблон), requirements-hashed.txt (ПОВНИЙ
#   набір з sha256) + wheels\*.whl; <ApprovedSums> (APPROVED-SHA256.txt) — окремим каналом, поза каталогом пакета.
# БД створюються одразу версій коду релізу (за замовчуванням integrity 6 / auth 2 = $V2ReleaseSchema; bind-check проти коду й SCHEMA_SPECS),
# після seed і першого адміністратора — mark-synthetic (демо-аналітика в release). Модулі bootstrap у app\ не розгортаються: перший
# адміністратор створюється одноразовим викликом v2_clean_bootstrap_admin.py з каталогу інсталятора. Маніфест коду →
# pkg\<ReleaseId>-BACKEND-SHA256.txt (його бере Update-V2InPlace). Після smoke обидві служби → Automatic (Delayed Start).
# SMTP: Gmail (smtp.gmail.com:587, starttls, FROM = USER; пароль застосунку — приховано) або інший SMTP (-SmtpMode Custom). dev-mail — ні.
# -WithLm: після успішного встановлення — lm\Install-V2LmService.ps1 -Apply (лише сервер; збій LM не скасовує базове встановлення, exit 4).
# НЕ використовує механізми Upgrade/Rollback: Invoke-V2DbRestore, Assert-V2Restore*, Job Object (static-clean-install CI-S1/CI-S2).
# Set-V2ServiceStartMode — лише Disabled і лише у fail-closed (CI-S6); Automatic (Delayed Start) — лише Set-V2ServiceDelayedAuto після smoke (CI-S10).
# НЕ залежить від каталогів V1: WinSW і Caddy — лише з артефакту integrity-v2-tools із закріпленими SHA256 (static P26).
# V1 не обов'язкова: якщо є — baseline і «без змін» після кожного етапу; якщо немає — фіксується відсутність.
# CI-01: будь-який STOP після створення кореня ЦИМ запуском → Invoke-V2CleanInstallFailClosed: READY інвалідується (CLEAN-INIT-FAILED-INSTALL,
#   CLEAN-INIT-OK → REVOKED, CLEAN-INSTALL-FAILED у корені), служби V2 зупинено й Disabled; БД не видаляються; вихід 1 (2 — fail-closed не завершено).
# STOP до створення кореня (зокрема «корінь/служба вже існує») нічого не змінює — наявне встановлення не чіпається.
# Далі — ЛИШЕ свідомо: clean-install.ps1 -Abort -AbortReason '…' (видалення служб V2, корінь → <корінь>-abandoned-<ts>).
# Виконувати лише: (а) на ізольованому тест-хості за погодженням №5 (-TestHost) або (б) на сервері після DEPLOYMENT GO №5.
# Коди виходу: 0 — PASS; 1 — STOP (fail-closed виконано або нічого не змінено); 2 — fail-closed не завершено; 4 — базове встановлення PASS, LM — ні.
param(
  [Parameter(Mandatory)] [string] $DecisionRef,          # номер/дата рішення №5 (тест-хост або DEPLOYMENT GO)
  [string] $ToolsZip,                                    # integrity-v2-tools-*.zip (WinSW 2.12.0 + Caddy 2.11.9, SHA256 закріплені)
  [string] $PackageDir,                                  # пакет релізу (формат пакета оновлення)
  [string] $ApprovedSums,                                # APPROVED-SHA256.txt — окремим каналом
  [string] $ReleaseId,                                   # integrity-v2-<sha7>: префікс записів backend-src.zip і каталог app\<ReleaseId>
  [string] $PyBase,                                      # базовий Python 3.13.14 (x64)
  [int] $ExpectedWindowsBuild,                           # C3: збірка Windows сервера з read-only preflight (тест-хост — та сама збірка)
  [string] $SrvDecisionRef,                              # рішення №5 щодо створення C:\srv (4.1а), якщо його немає
  [string] $AdminName = 'Staging Admin',
  [string] $AdminEmail,                                  # скринька адміністратора команди (bootstrap)
  [ValidateSet('Gmail', 'Custom')] [string] $SmtpMode = 'Gmail',
  [string] $SmtpUser,                                    # Gmail: адреса скриньки (вона ж FROM); Custom: логін SMTP
  [string] $SmtpHost,                                    # лише Custom
  [ValidateRange(1, 65535)] [int] $SmtpPort = 587,       # лише Custom
  [ValidateSet('starttls', 'implicit')] [string] $SmtpTlsMode = 'starttls',   # лише Custom
  [string] $SmtpFrom,                                    # лише Custom (за замовчуванням = SmtpUser)
  [ValidateRange(0, 99)] [int] $IntegrityVersion = 0,    # 0 → $V2ReleaseSchema.integrity (6)
  [ValidateRange(0, 99)] [int] $AuthVersion = 0,         # 0 → $V2ReleaseSchema.auth (2)
  [switch] $KeepManualStart,                             # не переводити служби в Automatic (Delayed Start)
  [switch] $WithLm,                                      # після встановлення — lm\Install-V2LmService.ps1 -Apply
  [string] $LlamaZip,                                    # -WithLm: llama-b12180-bin-win-cpu-x64.zip (поза C:\srv\integrity-v2)
  [string] $ModelPath,                                   # -WithLm: Qwen3-8B-Q4_K_M.gguf (поза C:\srv\integrity-v2)
  [string] $LmApprovedSums,                              # -WithLm: необов'язкові суми ZIP/моделі окремим каналом
  [string] $TlsHost = 'v2-host.example.ts.net',
  [string[]] $TlsAddresses = @('100.64.0.10'),
  [string] $TlsPairDirectory,
  [string] $TlsCertificateSha256,
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
foreach ($p in 'ToolsZip', 'PackageDir', 'ApprovedSums', 'ReleaseId', 'PyBase', 'AdminEmail', 'SmtpUser', 'ExpectedWindowsBuild') { if (-not (Get-Variable $p -ValueOnly)) { Stop-V2 "потрібен параметр -$p" } }
if ($ReleaseId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$') { Stop-V2 "ReleaseId поза дозволеною формою: $ReleaseId" }
if (-not $IntegrityVersion) { $IntegrityVersion = $V2ReleaseSchema.integrity }
if (-not $AuthVersion) { $AuthVersion = $V2ReleaseSchema.auth }
$Smtp = Get-V2SmtpPlan -Mode $SmtpMode -User $SmtpUser -SmtpHost $SmtpHost -Port $SmtpPort -TlsMode $SmtpTlsMode -From $SmtpFrom
if ($WithLm) {
  if ($TestHost) { Stop-V2 '-WithLm лише на сервері (lm\Install-V2LmService.ps1 перевіряє хост); на тест-хості LM не встановлюється' }
  foreach ($p in 'LlamaZip', 'ModelPath') { $v = Get-Variable $p -ValueOnly; if (-not $v -or -not (Test-Path -LiteralPath $v -PathType Leaf)) { Stop-V2 "-WithLm: немає файлу -$p" } }
  if ($LmApprovedSums -and -not (Test-Path -LiteralPath $LmApprovedSums -PathType Leaf)) { Stop-V2 '-WithLm: немає -LmApprovedSums' }
} elseif ($LlamaZip -or $ModelPath) { Stop-V2 '-LlamaZip/-ModelPath — лише разом із -WithLm' }

$Base = $null
$Owned = $false                                          # CI-01: корінь V2 створено саме цим запуском → fail-closed дозволено
$OwnedToken = $null
$OwnedServices = New-Object 'System.Collections.Generic.HashSet[string]'
try {
  Stage '4.0 preflight (лише читання)'
  $Base = Get-V1Baseline -AllowAbsent
  "INFO  V1: $(if ($Base.Present) { "присутня — контроль «без змін» після кожного етапу ($($Base.Services.Count) служб)" } else { 'відсутня' })"
  $transcriptionEnabled = Get-ItemPropertyValue -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\PowerShell\Transcription' -Name EnableTranscripting -ErrorAction SilentlyContinue
  if ($transcriptionEnabled -eq 1) { 'INFO  транскрипцію ввімкнено політикою — секрети вводяться лише як SecureString і не виводяться' }
  $Pkg0 = Assert-V2CleanPackage -PackageDir $PackageDir -ApprovedSums $ApprovedSums -ReleaseId $ReleaseId; $Pkg0.Lines
  $null = Assert-V2Exe $PyBase 'python'
  if (@(Invoke-V2Native -Exe $PyBase -ArgList @('-I', '-c', 'import sys,struct; print(sys.version.split()[0], struct.calcsize("P")*8, sys.prefix == sys.base_prefix)') -Utf8 -What 'python version')[-1] -ne '3.13.14 64 True') { Stop-V2 'Python ≠ базовий 3.13.14 x64' }
  $DbTool = "$K\v2_db_tool.py"
  $specs = @(Invoke-V2Native -Exe $PyBase -ArgList @('-E', '-s', '-I', $DbTool, 'specs') -Utf8 -What 'v2_db_tool specs')[-1] | ConvertFrom-Json
  foreach ($k in "integrity/$IntegrityVersion", "auth/$AuthVersion") { if (-not $specs.PSObject.Properties[$k]) { Stop-V2 "SCHEMA_SPECS v2_db_tool не має $k — строгі перевірки неможливі" } }
  "PASS  SCHEMA_SPECS: integrity/$IntegrityVersion, auth/$AuthVersion; SMTP: $(if ($Smtp.Gmail) { 'Gmail smtp.gmail.com:587 starttls' } else { "$SmtpHost`:$SmtpPort $SmtpTlsMode" }); LM: $(if ($WithLm) { 'так' } else { 'ні' })"
  Test-V2WinswXml -XmlPath "$K\integrity-v2-backend.xml.template" -Name integrity-v2-backend -WinswVersion $WinswRefVersion -AllowPlaceholders
  Test-V2WinswXml -XmlPath "$K\integrity-v2-caddy.xml.template" -Name integrity-v2-caddy -WinswVersion $WinswRefVersion
  foreach ($n in 'integrity-v2-backend', 'integrity-v2-caddy', 'integrity-v2-lm') { if (Get-V2Service $n) { Stop-V2 "служба $n уже існує — Clean Install лише на чистому хості" } }
  if (Test-Path -LiteralPath $V2Root) { Stop-V2 "$V2Root уже існує — Clean Install лише на чистому хості (попередню спробу: -Abort)" }
  Assert-V2HostPreflight -ExpectedWindowsBuild $ExpectedWindowsBuild           # C3: Windows build, PowerShell 5.1 x64, вільне місце
  Assert-V2PortsFree                                                         # C3: TCP 80/443/8100/8199, UDP 443 — до будь-якого запису
  Assert-V2TargetIdentity -HostName $TlsHost -Addresses $TlsAddresses -TestHost:$TestHost
  if (-not $TestHost -or $TlsPairDirectory -or $TlsCertificateSha256) {
    Assert-V2Ancestors
    Assert-V2StagedTlsPair -Path $TlsPairDirectory -CertificateSha256 $TlsCertificateSha256
  }

  Stage '4.1 корінь V2 (захищений)'
  if (-not (Test-Path -LiteralPath 'C:\srv')) {
    if (-not $SrvDecisionRef) { Stop-V2 'C:\srv відсутній — потрібне рішення №5 (-SrvDecisionRef, варіант 4.1а)' }
    New-V2ProtectedDirectory -Path 'C:\srv' -DecisionRef $SrvDecisionRef
  }
  Assert-V2Ancestors
  if (Test-Path -LiteralPath $V2Root) { Stop-V2 "$V2Root уже існує — resume/повторне використання заборонено (попередню спробу: -Abort)" }
  New-V2Root -OnCreated { param($token) $script:OwnedToken = $token; $script:Owned = $true }
  foreach ($d in 'pkg', 'app', 'app\frontend', 'venv', 'data', 'backups', 'logs\backend', 'logs\caddy', 'services\backend', 'services\caddy', 'caddy\bin', 'caddy\data', 'caddy\config') { $null = New-Item -ItemType Directory -Path "$V2Root\$d" }
  Assert-V2Root
  if ($Base) { Assert-V1Unchanged -Baseline $Base }

  Stage '4.2 пакет релізу і інструменти V2 (без каталогів V1)'
  $V2AppRelease = $ReleaseId                                                 # каталог релізу для Assert-V2AclMatrix
  $Pkg = Copy-V2CleanPackage -Package $Pkg0 -ApprovedSums $ApprovedSums -Destination "$V2Root\pkg\$ReleaseId"; $Pkg.Lines
  Expand-V2ReleaseBackend -Package $Pkg -AppDir "$V2Root\app\$ReleaseId" -PkgManifestPath "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt"
  Expand-V2ReleaseDist -Package $Pkg -DistDir "$V2Root\app\frontend\dist"
  $Backend = "$V2Root\app\$ReleaseId\backend"
  Expand-V2Tools -ToolsZip $ToolsZip -Destination "$V2Root\pkg\tools"
  $TargetConfig = "$V2Root\pkg\target-config"
  New-V2TargetConfig -CaddySource "$($Pkg.Dir)\Caddyfile" -BackendSource "$K\integrity-v2-backend.xml.template" -Destination $TargetConfig -HostName $TlsHost -Addresses $TlsAddresses -UseFileTls:([bool]$TlsPairDirectory) -ReleaseId $ReleaseId
  $WinSWSrc = "$V2Root\pkg\tools\winsw\integrity-v2-winsw.exe"; $CaddySrc = "$V2Root\pkg\tools\caddy\caddy.exe"
  $null = Assert-V2Winsw -Path $WinSWSrc -Label 'WinSW (артефакт V2)'
  if ($Base) { Assert-V1Unchanged -Baseline $Base }

  Stage '4.3 venv і офлайн-залежності (--require-hashes); прив''язка схем до коду релізу'
  $null = Invoke-V2Native -Exe $PyBase -ArgList @('-E', '-s', '-m', 'venv', "$V2Root\venv") -What 'venv'
  $Py = "$V2Root\venv\Scripts\python.exe"
  Install-V2Requirements -Py $Py -Package $Pkg
  Assert-V2ReleaseSchemaBinding -Py $PyBase -ReleasePy $Py -DbTool $DbTool -Backend $Backend -Manifest "$V2Root\pkg\$ReleaseId-BACKEND-SHA256.txt" -IntegrityVersion $IntegrityVersion -AuthVersion $AuthVersion

  Stage '4.4 репетиція release на копії (5а)'
  $Reh = @(Invoke-V2Rehearsal -Py $Py -Backend $Backend -DbTool $DbTool -Port 8199 -FrontendOrigin "https://$TlsHost" -IntegrityVersion $IntegrityVersion); $Reh
  $Fp5a = ($Reh | Where-Object { $_.StartsWith('FINGERPRINT ') }) -replace '^FINGERPRINT ', ''
  if ($Fp5a -notmatch '^[0-9a-f]{64}$') { Stop-V2 'немає відбитка 5а' }

  Stage '4.5 нові БД (лише порожній data\), bootstrap адміністратора, строгі схеми, synthetic, початкові копії'
  $D = "$V2Root\data"
  Initialize-V2CleanDatabases -Py $Py -Backend $Backend -DbTool $DbTool -DataDir $D -BackupDir "$V2Root\backups" -ReferenceFingerprint $Fp5a -IntegrityVersion $IntegrityVersion -AuthVersion $AuthVersion -ReleaseId $ReleaseId
  $null = Use-V2Env -Vars @{ APP_ENV = 'release'; INTEGRITY_DB = "$D\integrity_v2.db"; V2_AUTH_DB = "$D\v2_auth.db"; V2_SECRET_KEY = (New-V2RandomKey) } -Body {
    # одноразово з каталогу інсталятора (у app\ не копіюється); пароль ≥ 10, приховано; без init_auth_db
    Invoke-V2Interactive -Exe $Py -WorkingDirectory $Backend -What 'bootstrap admin' -ArgList @('-I', '-X', 'utf8', "$K\v2_clean_bootstrap_admin.py", '--backend', $Backend, '--name', $AdminName, '--email', $AdminEmail)
  }
  Complete-V2CleanDatabases -Py $Py -DbTool $DbTool -DataDir $D -BackupDir "$V2Root\backups" -ReferenceFingerprint $Fp5a -IntegrityVersion $IntegrityVersion -AuthVersion $AuthVersion
  if (@(Get-ChildItem -LiteralPath "$V2Root\app" -Recurse -File -Force | Where-Object { $_.Name -match '(?i)bootstrap' }).Count) { Stop-V2 'у app\ є модуль bootstrap' }
  if ($Base) { Assert-V1Unchanged -Baseline $Base }

  Stage '4.6 служба backend'
  $null = Assert-V2TargetConfigManifest -Directory $TargetConfig -HostName $TlsHost -Addresses $TlsAddresses
  Copy-Item -LiteralPath $WinSWSrc -Destination "$V2Root\services\backend\integrity-v2-backend.exe"
  $null = Assert-V2Winsw -Path "$V2Root\services\backend\integrity-v2-backend.exe" -Label 'WinSW копія backend'
  Copy-Item -LiteralPath "$TargetConfig\integrity-v2-backend.xml" -Destination "$V2Root\services\backend\integrity-v2-backend.xml"
  $null = Assert-V2FileHash -Path "$V2Root\services\backend\integrity-v2-backend.xml" -Sha256 (Get-FileHash -LiteralPath "$TargetConfig\integrity-v2-backend.xml" -Algorithm SHA256).Hash -Label 'backend XML target config'
  Test-V2WinswXml -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Name integrity-v2-backend -WinswVersion $WinswRefVersion -AllowPlaceholders
  Assert-V2TargetIdentity -HostName $TlsHost -Addresses $TlsAddresses -TestHost:$TestHost
  Install-V2Service -Name integrity-v2-backend -OnCreated { param($name) $null = $OwnedServices.Add($name) }
  $B = 'NT SERVICE\integrity-v2-backend'
  Grant-V2 "$V2Root\app\$ReleaseId" $B '(OI)(CI)RX'; Grant-V2 "$V2Root\venv" $B '(OI)(CI)RX'
  Grant-V2 "$V2Root\data" $B '(OI)(CI)M'; Grant-V2 "$V2Root\logs\backend" $B '(OI)(CI)M'; Grant-V2 "$V2Root\services\backend" $B '(OI)(CI)RX'
  # SMTP: несекретні значення — з параметрів (Get-V2SmtpPlan), пароль — лише приховано (Gmail: пароль застосунку, 16 літер, двічі)
  $SmtpReader = if ($Smtp.Gmail) { { param($n) Read-V2GmailAppPassword } } else { { param($n) Read-Host -Prompt $n -AsSecureString } }
  Set-V2Secrets -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Prompted @('V2_SMTP_PASSWORD') -Values $Smtp.Values -SecretReader $SmtpReader
  Test-V2WinswXml -XmlPath "$V2Root\services\backend\integrity-v2-backend.xml" -Name integrity-v2-backend -WinswVersion $WinswRefVersion
  Assert-V2AclMatrix
  Invoke-V2ServiceStart -Name integrity-v2-backend -Checks {                                   # стандартний PreCheck: Assert-V2DataReady (CLEAN-INIT-OK)
    Assert-V2ServiceRunning -Name integrity-v2-backend -Addresses @('127.0.0.1')
    Wait-V2Http -Url 'http://127.0.0.1:8100/api/health'
    Assert-V2Http -Url 'http://127.0.0.1:8100/docs' -Expected 401
    Assert-V2Http -Url 'http://127.0.0.1:8100/api/assessments/1/participation' -Headers @{ 'X-Role' = 'manager' } -Expected 401
    Assert-V2Http -Url 'http://127.0.0.1:8100/v2/auth/dev-mail/latest' -Expected 404
    if ($Base) { Assert-V1Unchanged -Baseline $Base }
  }

  Stage '4.7 Caddy V2 (приватний HTTPS)'
  if ($TlsPairDirectory) {
    Assert-V2StagedTlsPair -Path $TlsPairDirectory -CertificateSha256 $TlsCertificateSha256
    $privateTls = Assert-V2InRoot "$V2Root\caddy\tls"
    $null = New-Item -ItemType Directory -Path $privateTls -ErrorAction Stop
    foreach ($name in 'site.crt','site.key') {
      $src = Join-Path $TlsPairDirectory $name
      $dst = Join-Path $privateTls $name
      [IO.File]::Copy($src,$dst,$false)
      if ((Get-FileHash -LiteralPath $src).Hash -ne (Get-FileHash -LiteralPath $dst).Hash) { Stop-V2 'TLS pair copy verification failed' }
    }
    Assert-V2TlsDirectory -Path $privateTls
  }
  $null = Assert-V2TargetConfigManifest -Directory $TargetConfig -HostName $TlsHost -Addresses $TlsAddresses
  Copy-Item -LiteralPath $CaddySrc -Destination "$V2Root\caddy\bin\caddy.exe"
  $null = Assert-V2FileHash -Path "$V2Root\caddy\bin\caddy.exe" -Sha256 $CaddyRefSha256 -Label 'копія caddy.exe'
  Copy-Item -LiteralPath "$TargetConfig\Caddyfile" -Destination "$V2Root\caddy\Caddyfile"
  $null = Assert-V2FileHash -Path "$V2Root\caddy\Caddyfile" -Sha256 (Get-FileHash -LiteralPath "$TargetConfig\Caddyfile" -Algorithm SHA256).Hash -Label 'Caddyfile target config'
  Assert-V2TargetIdentity -HostName $TlsHost -Addresses $TlsAddresses -TestHost:$TestHost
  $null = Invoke-V2Native -Exe "$V2Root\caddy\bin\caddy.exe" -ArgList @('adapt', '--config', "$V2Root\caddy\Caddyfile", '--adapter', 'caddyfile') -What 'caddy adapt'
  Copy-Item -LiteralPath $WinSWSrc -Destination "$V2Root\services\caddy\integrity-v2-caddy.exe"
  $null = Assert-V2Winsw -Path "$V2Root\services\caddy\integrity-v2-caddy.exe" -Label 'WinSW копія caddy'
  Copy-Item -LiteralPath "$K\integrity-v2-caddy.xml.template" -Destination "$V2Root\services\caddy\integrity-v2-caddy.xml"
  Test-V2WinswXml -XmlPath "$V2Root\services\caddy\integrity-v2-caddy.xml" -Name integrity-v2-caddy -WinswVersion $WinswRefVersion
  Install-V2Service -Name integrity-v2-caddy -OnCreated { param($name) $null = $OwnedServices.Add($name) }
  $C = 'NT SERVICE\integrity-v2-caddy'
  Grant-V2 "$V2Root\app\frontend\dist" $C '(OI)(CI)RX'; Grant-V2 "$V2Root\caddy\bin" $C '(OI)(CI)RX'; Grant-V2 "$V2Root\caddy\Caddyfile" $C 'R'
  Grant-V2 "$V2Root\caddy\data" $C '(OI)(CI)M'; Grant-V2 "$V2Root\caddy\config" $C '(OI)(CI)M'
  Grant-V2 "$V2Root\logs\caddy" $C '(OI)(CI)M'; Grant-V2 "$V2Root\services\caddy" $C '(OI)(CI)RX'
  if ($TlsPairDirectory) {
    Grant-V2 $privateTls $C 'RX'
    Grant-V2 "$privateTls\site.crt" $C 'R'
    Grant-V2 "$privateTls\site.key" $C 'R'
  }
  Assert-V2AclMatrix
  $PinnedHttps = @{ HostName = $TlsHost; Addresses = $TlsAddresses; TestHost = $TestHost }
  Invoke-V2ServiceStart -Name integrity-v2-caddy -Checks {
    Assert-V2ServiceRunning -Name integrity-v2-caddy -Addresses $TlsAddresses
    Assert-V2PinnedHttps @PinnedHttps -Path '/' -Expected 200
    if (@(Get-V2UdpEndpoints -Ports @(443)).Count) { Stop-V2 'UDP 443' }
    if (@(Get-V2Listeners -Ports @(80)).Count) { Stop-V2 ':80 слухається' }
    if ($Base) { Assert-V1Unchanged -Baseline $Base }
  }

  Stage '5 smoke (автоматична частина; S1–S8 у браузері — окремо)'
  Assert-V2PinnedHttps @PinnedHttps -Path '/' -Expected 200; Assert-V2PinnedHttps @PinnedHttps -Path '/login' -Expected 200; Assert-V2PinnedHttps @PinnedHttps -Path '/api/health' -Expected 200
  Assert-V2PinnedHttps @PinnedHttps -Path '/docs' -Expected 401; Assert-V2PinnedHttps @PinnedHttps -Path '/openapi.json' -Expected 401; Assert-V2PinnedHttps @PinnedHttps -Path '/redoc' -Expected 404
  Assert-V2PinnedHttps @PinnedHttps -Path '/api/assessments/1/participation' -Headers @{ 'X-Role' = 'manager' } -Expected 401
  Assert-V2PinnedHttps @PinnedHttps -Path '/v2/auth/logout' -Method POST -Expected 403
  Assert-V2PinnedHttps @PinnedHttps -Path '/assets/missing.js' -Expected 404
  if ($Base) { Assert-V1Unchanged -Baseline $Base }

  Stage '5.1 режим запуску служб'
  if ($KeepManualStart) { 'INFO  -KeepManualStart: служби лишаються Manual' }
  else { foreach ($n in 'integrity-v2-backend', 'integrity-v2-caddy') { Set-V2ServiceDelayedAuto -Name $n } }
  "CLEAN INSTALL PASS ($(if ($TestHost) { 'тест-хост' } else { 'сервер' }); реліз $ReleaseId; БД integrity $IntegrityVersion / auth $AuthVersion; рішення $DecisionRef). Далі — smoke S1–S8 у браузері."
} catch {
  $why = $_.Exception.Message -replace '^STOP: ', ''
  "STOP: CLEAN INSTALL: $why"
  if (-not $Owned) {
    'INFO  корінь V2 цим запуском не створювався — наявний стан (і служби V2, якщо є) не змінено'
    exit 1
  }
  try { Invoke-V2CleanInstallFailClosed -Reason $why -OwnedServices @($OwnedServices) }
  catch {
    "КРИТИЧНО: $($_.Exception.Message -replace '^STOP: ', '')"
    exit 2
  }
  'Далі — лише свідомо: clean-install.ps1 -DecisionRef <…> -Abort -AbortReason <…> (служби V2 видаляються, корінь → -abandoned-<ts>); автоматичного resume немає'
  exit 1
}

# ---------------------------------------------------------------- 6: локальна LM (необов'язково; базове встановлення вже PASS)
if (-not $WithLm) { exit 0 }
Stage '6 локальна LM (lm\Install-V2LmService.ps1 -Apply)'
$lmArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$K\lm\Install-V2LmService.ps1", '-Apply', '-DecisionRef', $DecisionRef, '-LlamaZip', $LlamaZip, '-ModelPath', $ModelPath)
if ($LmApprovedSums) { $lmArgs += @('-ApprovedSums', $LmApprovedSums) }
try {
  Invoke-V2Native -Exe "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgList $lmArgs -Utf8 -TimeoutSec 1800 -What 'Install-V2LmService -Apply'
  Assert-V2AclMatrix                                                         # повна матриця вже з lm\
  'CLEAN INSTALL + LM PASS: служба integrity-v2-lm Automatic (Delayed Start), 127.0.0.1:8200; backend із V2_LM_URL'
  exit 0
} catch {
  "STOP: LM: $($_.Exception.Message -replace '^STOP: ', '')"
  'INFO  базове встановлення працює (backend, Caddy); LM відкочено інсталятором LM (доказ: backups\lm-install-<stamp>\LM-INSTALL-EVIDENCE.json). Повтор — lm\Install-V2LmService.ps1 окремо.'
  exit 4
}
