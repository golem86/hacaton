# V2 release-preflight для Windows-сервера (кандидат dde86e68f4405c23ec4aad14db80f0b764fb4556).
# ЛИШЕ ЧИТАННЯ: нічого не створює, не змінює і не запускає служб; налаштування Windows, Firewall, Tailscale, ACL,
# Caddy V1 і V1 не зачіпає. Єдині зовнішні програми: python.exe -I -B -S (запит версії й модулів) і caddy.exe (version,
# adapt — лише перетворення Caddyfile у JSON на stdout).
# Запуск — лише з дозволу №5, до DEPLOYMENT GO, після ручної звірки SHA256 цього файлу із сумою з окремого каналу:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\V2-release-preflight.ps1 `
#     -PackageDir <каталог пакета> -ApprovedSums <файл сум з окремого каналу> -Python <повний шлях python.exe 3.13.14> -Caddy <повний шлях caddy.exe>
# Результат: RELEASE-PREFLIGHT PASS (код 0) або BLOCKED (код 2) з переліком причин.
param(
  [Parameter(Mandatory)] [string] $PackageDir,
  [Parameter(Mandatory)] [string] $ApprovedSums,
  [Parameter(Mandatory)] [string] $Python,
  [Parameter(Mandatory)] [string] $Caddy
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
$Candidate = 'dde86e68f4405c23ec4aad14db80f0b764fb4556'
$Short = 'dde86e6'
$Host4 = '100.111.221.74'; $Host6 = 'fd7a:115c:a1e0::ef01:dddc'
$Package = @("integrity-v2-$Short-backend-src.zip", "integrity-v2-$Short-dist.zip", 'wheelhouse-cp313-win_amd64.zip', 'WHEELHOUSE-SHA256.txt',
             'DIST-SHA256.txt', 'SWAGGER-ASSETS-SHA256.txt', 'Caddyfile', 'V2-release-preflight.ps1', 'SHA256SUMS.txt')
$issues = New-Object System.Collections.Generic.List[string]
$notes = New-Object System.Collections.Generic.List[string]
function Issue([string]$m) { $issues.Add($m) }
function Note([string]$m) { $notes.Add($m) }
function Done {
  $notes | ForEach-Object { "INFO: $_" }
  if ($issues.Count) { '=== RELEASE-PREFLIGHT BLOCKED ==='; $issues | ForEach-Object { "BLOCKED: $_" }; 'Нічого не змінено.'; exit 2 }
  '=== RELEASE-PREFLIGHT PASS ==='; 'Нічого не змінено. Це не DEPLOYMENT GO.'; exit 0
}
trap { $issues.Add("помилка перевірки: $($_.Exception.Message)"); Done }
function Hash([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() }
function Hash-Stream($stream) {
  $sha = [Security.Cryptography.SHA256]::Create()
  try { ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLower() } finally { $stream.Dispose(); $sha.Dispose() }
}
function Read-Sums([string]$file) {
  $h = @{}
  foreach ($l in Get-Content -LiteralPath $file) {
    if (-not $l.Trim() -or $l.TrimStart().StartsWith('#')) { continue }
    $sha, $name = $l.Trim() -split '\s+\*?', 2
    if ($sha -notmatch '^[0-9a-fA-F]{64}$') { throw "некоректний рядок суми у $file" }
    $h[$name.Trim()] = $sha.ToLower()
  }
  $h
}
function Prop($o, [string[]]$path) {                         # безпечний доступ до полів JSON у StrictMode
  foreach ($n in $path) { if ($null -eq $o) { return $null }; $p = $o.PSObject.Properties[$n]; if (-not $p) { return $null }; $o = $p.Value }
  $o
}
Add-Type -AssemblyName System.IO.Compression.FileSystem

# 1. Пакет: рівно 9 файлів; 8 із них = суми з окремого каналу (SHA256SUMS.txt у пакеті не є джерелом довіри)
$approved = Read-Sums $ApprovedSums
$names = @(Get-ChildItem -LiteralPath $PackageDir -Force | ForEach-Object Name)
if (@(Compare-Object ($names | Sort-Object) ($Package | Sort-Object)).Count) { Issue "склад пакета: $($names -join ', ')"; Done }
foreach ($n in $Package | Where-Object { $_ -ne 'SHA256SUMS.txt' }) {
  if (-not $approved.ContainsKey($n)) { Issue "у сумах з окремого каналу немає $n"; continue }
  if ((Hash (Join-Path $PackageDir $n)) -ne $approved[$n]) { Issue "SHA256 не збігається: $n" }
}
if ($issues.Count) { Done }
Note 'пакет: 8/8 файлів = суми з окремого каналу (V2-release-preflight.ps1 — також звірити вручну до запуску)'

# 2. Вміст архівів: коментар zip = кандидат; 55 файли коду; Swagger UI, dist і wheelhouse = вкладені переліки сум
$zip = [IO.Compression.ZipFile]::OpenRead((Join-Path $PackageDir "integrity-v2-$Short-backend-src.zip"))
try {
  $src = @($zip.Entries | Where-Object { -not $_.FullName.EndsWith('/') })
  if ($src.Count -ne 55) { Issue "код: $($src.Count) файлів, очікується 55" }
  if (@($src | Where-Object { -not $_.FullName.StartsWith("integrity-v2-$Short/backend/") }).Count) { Issue "код: файли поза integrity-v2-$Short/backend/" }
  foreach ($l in Get-Content -LiteralPath (Join-Path $PackageDir 'SWAGGER-ASSETS-SHA256.txt')) {
    if (-not $l.Trim()) { continue }
    $h, $p = $l -split '\s+', 2
    $e = $zip.GetEntry("integrity-v2-$Short/" + $p.Trim())
    if ($null -eq $e -or (Hash-Stream $e.Open()) -ne $h) { Issue "Swagger UI: $($p.Trim())" }
  }
} finally { $zip.Dispose() }
$raw = [IO.File]::ReadAllBytes((Join-Path $PackageDir "integrity-v2-$Short-backend-src.zip"))
if ([Text.Encoding]::ASCII.GetString($raw, $raw.Length - 40, 40) -ne $Candidate) { Issue 'коментар zip коду ≠ SHA кандидата' }
$dz = [IO.Compression.ZipFile]::OpenRead((Join-Path $PackageDir "integrity-v2-$Short-dist.zip"))
try {
  $want = @{}; foreach ($l in Get-Content -LiteralPath (Join-Path $PackageDir 'DIST-SHA256.txt')) { if ($l.Trim()) { $h, $p = $l -split '\s+', 2; $want[$p.Trim()] = $h } }
  $de = @($dz.Entries | Where-Object { -not $_.FullName.EndsWith('/') })
  if ($de.Count -ne $want.Count) { Issue "dist: $($de.Count) файлів, очікується $($want.Count)" }
  foreach ($e in $de) { if (-not $want.ContainsKey($e.FullName) -or (Hash-Stream $e.Open()) -ne $want[$e.FullName]) { Issue "dist: $($e.FullName)" } }
} finally { $dz.Dispose() }
$wz = [IO.Compression.ZipFile]::OpenRead((Join-Path $PackageDir 'wheelhouse-cp313-win_amd64.zip'))
try {
  $ww = @{}; foreach ($l in Get-Content -LiteralPath (Join-Path $PackageDir 'WHEELHOUSE-SHA256.txt')) { if ($l.Trim()) { $h, $n = $l -split '\s+\*?', 2; $ww[$n.Trim()] = $h.ToLower() } }
  $we = @($wz.Entries | Where-Object { $_.FullName.EndsWith('.whl') })
  if ($we.Count -ne 28 -or $ww.Count -ne 28) { Issue "wheelhouse: $($we.Count) wheel, очікується 28" }
  foreach ($e in $we) { if (-not $ww.ContainsKey($e.Name) -or (Hash-Stream $e.Open()) -ne $ww[$e.Name]) { Issue "wheel: $($e.Name)" } }
} finally { $wz.Dispose() }
Note 'архіви: код 55, Swagger UI 4, dist 3, wheelhouse 28 — перевірено в пам''яті, нічого не розпаковано'

# 3. Python 3.13.14 x64 (R-03): повний шлях, не Store, підпис PSF, потрібні модулі
if (-not [IO.Path]::IsPathRooted($Python) -or $Python -match '\\WindowsApps\\' -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) { Issue "Python: некоректний шлях $Python" }
else {
  $sig = Get-AuthenticodeSignature -LiteralPath $Python
  if ($sig.Status -ne 'Valid' -or "$($sig.SignerCertificate.Subject)" -notmatch 'Python Software Foundation') { Issue "Python: підпис $($sig.Status)" }
  # -I: без PYTHON*-змінних, user site і небезпечного sys.path; -B: без запису .pyc; -S: без модуля site (без .pth і site-packages)
  $pv = @(& $Python -I -B -S -c "import sys,struct,venv,ensurepip,ssl,sqlite3;print(sys.version.split()[0], struct.calcsize('P')*8)")
  if ($LASTEXITCODE -ne 0 -or "$($pv[-1])".Trim() -ne '3.13.14 64') { Issue "Python: $($pv -join ' ') (очікується 3.13.14 64, модулі venv/ensurepip/ssl/sqlite3)" }
  else { Note "Python: 3.13.14 x64, підпис PSF, venv/ensurepip/ssl/sqlite3" }
}

# 4. Caddy 2.11.9 і Caddyfile V2 (R-07): adapt лише перетворює конфігурацію, нічого не запускає
if (-not [IO.Path]::IsPathRooted($Caddy) -or -not (Test-Path -LiteralPath $Caddy -PathType Leaf)) { Issue "Caddy: некоректний шлях $Caddy" }
else {
  $cv = "$(& $Caddy version)"
  if ($LASTEXITCODE -ne 0 -or -not $cv.StartsWith('v2.11.9')) { Issue "Caddy: версія $cv, очікується v2.11.9" }
  $json = (@(& $Caddy adapt --config (Join-Path $PackageDir 'Caddyfile') --adapter caddyfile) -join "`n")
  if ($LASTEXITCODE -ne 0) { Issue 'Caddy: adapt завершився з помилкою' }
  else {
    $cfg = $json | ConvertFrom-Json
    $srvObj = Prop $cfg 'apps', 'http', 'servers'
    $servers = @(if ($srvObj) { $srvObj.PSObject.Properties | ForEach-Object Value })
    if (-not $servers.Count) { Issue 'Caddy: у конфігурації немає HTTP-серверів' }
    $listen = @($servers | ForEach-Object { Prop $_ 'listen' } | Sort-Object -Unique)
    if (@(Compare-Object $listen (@("${Host4}:443", "[${Host6}]:443") | Sort-Object)).Count) { Issue "Caddy: listen = $($listen -join ', ') (очікуються лише Tailscale-IP:443)" }
    if (@($servers | Where-Object { (@(Prop $_ 'protocols') -join ',') -ne 'h1,h2' }).Count) { Issue 'Caddy: protocols ≠ h1 h2' }
    if (@($servers | Where-Object { -not (Prop $_ 'automatic_https', 'disable_redirects') }).Count) { Issue 'Caddy: disable_redirects не ввімкнено' }
    if (-not (Prop $cfg 'admin', 'disabled')) { Issue 'Caddy: admin не вимкнено' }
    if ($json -notmatch '"dial":\s*"127\.0\.0\.1:8100"') { Issue 'Caddy: немає upstream 127.0.0.1:8100' }
    if ($json -match '"logs"|"log"') { Issue 'Caddy: увімкнено журнал' }
    foreach ($p in '/docs*', '/openapi.json', '/api/*', '/v2/*', '/redoc*', '/assets/*') { if (-not $json.Contains("""$p""")) { Issue "Caddy: немає маршруту $p" } }
    Note "Caddy: $cv; adapt OK; listen $($listen -join ', ')"
  }
}

# 5. Мережа і порти (R-08): 443/8100 вільні, UDP 443 немає; Tailscale-адреси на місці
if (@(Get-NetTCPConnection -State Listen -LocalPort 443, 8100 -ErrorAction SilentlyContinue).Count) { Issue 'порт 443 або 8100 уже слухається' }
if (@(Get-NetUDPEndpoint -LocalPort 443 -ErrorAction SilentlyContinue).Count) { Issue 'UDP 443 уже зайнятий' }
foreach ($a in $Host4, $Host6) { if (-not @(Get-NetIPAddress -IPAddress $a -ErrorAction SilentlyContinue).Count) { Issue "немає адреси Tailscale $a" } }

# 6. Ціль встановлення ще не існує; служби V2 ще не створені
foreach ($p in 'C:\srv\integrity-v2') { if (Test-Path -LiteralPath $p) { Issue "$p уже існує — встановлення лише в новий каталог (рішення №5)" } }
foreach ($s in 'integrity-v2-backend', 'integrity-v2-caddy') { if (@(Get-Service -Name $s -ErrorAction SilentlyContinue).Count) { Issue "служба $s уже існує" } }
$free = (Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
if ($free -lt 2GB) { Issue "на C: вільно $([math]::Round($free / 1GB, 1)) ГБ, потрібно ≥ 2 ГБ" }

# 7. Небезпечні змінні на рівні Machine/User (служба V2 отримує env лише зі своєї конфігурації)
foreach ($scope in 'Machine', 'User') {
  foreach ($v in 'INTEGRITY_DEMO_XROLE', 'V2_AUTH_DEV_MAIL', 'V2_AUTH_SECURE_COOKIE', 'APP_ENV', 'INTEGRITY_DB', 'V2_AUTH_DB') {
    $val = [Environment]::GetEnvironmentVariable($v, $scope)
    if ($null -ne $val) { Issue "змінна $v задана на рівні $scope — може потрапити в процес V2" }
  }
}

# 8. V1 працює (лише GET; стан до встановлення — для порівняння на етапі 1)
$v1 = $null
foreach ($u in 'http://127.0.0.1:8080/api/health', "http://${Host4}:8080/api/health") {
  try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { $v1 = $u; break } } catch { }
}
if ($v1) { Note "V1: $v1 → 200" } else { Issue 'V1 /api/health не відповідає 200 — зупинка до з''ясування (runbook, етап 1)' }

Done
