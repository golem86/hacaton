# V2 release-preflight для Windows-сервера (кандидат dde86e68f4405c23ec4aad14db80f0b764fb4556).
# ЛИШЕ ЧИТАННЯ: нічого не створює, не змінює і не запускає служб; налаштування Windows, Firewall, Tailscale, ACL,
# Caddy V1 і V1 не зачіпає. Єдині зовнішні програми: python.exe -I -B -S (запит версії й модулів) і caddy.exe (version,
# adapt — лише перетворення Caddyfile у JSON на stdout; цільова форма TLSFIX5 передається через stdin, у файл не пишеться).
# Hardening (I11): очікування TLSFIX5 — auto_https off, лише IPv4 100.64.0.10, файлова TLS-пара; журнали без IP/URI,
# CSP, Permissions-Policy, request_body, keepalive до backend; Machine/User-змінні — лише імена.
# Окремий режим без перевірок (для звірки з New-V2TargetConfig): -PrintTargetCaddyfile <Caddyfile> → цільовий текст у stdout.
# Запуск — лише з дозволу №5, до DEPLOYMENT GO, після ручної звірки SHA256 цього файлу із сумою з окремого каналу:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\V2-release-preflight.ps1 `
#     -PackageDir <каталог пакета> -ApprovedSums <файл сум з окремого каналу> -Python <повний шлях python.exe 3.13.14> -Caddy <повний шлях caddy.exe>
# Результат: RELEASE-PREFLIGHT PASS (код 0) або BLOCKED (код 2) з переліком причин.
[CmdletBinding(DefaultParameterSetName = 'Preflight')]
param(
  [Parameter(Mandatory, ParameterSetName = 'Preflight')] [string] $PackageDir,
  [Parameter(Mandatory, ParameterSetName = 'Preflight')] [string] $ApprovedSums,
  [Parameter(Mandatory, ParameterSetName = 'Preflight')] [string] $Python,
  [Parameter(Mandatory, ParameterSetName = 'Preflight')] [string] $Caddy,
  [Parameter(Mandatory, ParameterSetName = 'Print')] [string] $PrintTargetCaddyfile
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
$Candidate = 'dde86e68f4405c23ec4aad14db80f0b764fb4556'
$Short = 'dde86e6'
$Host4 = '100.64.0.10'                    # TLSFIX5: production DNS → лише IPv4; IPv6 Tailscale не слухається
$HostName = 'v2-host.example.ts.net'
# Те саме перетворення, що New-V2TargetConfig -UseFileTls (V2-install-common.ps1) для production; результат — лише в пам'яті
function ConvertTo-TargetCaddyfile([string]$Path) {
  $bytes = [IO.File]::ReadAllBytes($Path)
  if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) { throw 'Caddyfile має бути UTF-8 без BOM' }
  $text = (New-Object Text.UTF8Encoding($false, $true)).GetString($bytes)
  $prodBind = 'bind 100.64.0.10 [fd7a:115c:a1e0::10]'; $bind = "bind $Host4"
  if ([regex]::Matches($text, [regex]::Escape($HostName)).Count -ne 1 -or [regex]::Matches($text, [regex]::Escape($prodBind)).Count -ne 1 -or
      [regex]::Matches($text, '(?m)^\s*auto_https disable_redirects\s*$').Count -ne 1 -or $text -match '(?m)^\s*tls\s') { throw 'шаблон Caddyfile не відповідає закріпленій формі' }
  $text = $text.Replace($prodBind, $bind)
  $text.Replace('auto_https disable_redirects', 'auto_https off').Replace($bind, "$bind`n`ttls C:/srv/integrity-v2/caddy/tls/site.crt C:/srv/integrity-v2/caddy/tls/site.key")
}
if ($PSCmdlet.ParameterSetName -eq 'Print') { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false; [Console]::Out.Write((ConvertTo-TargetCaddyfile $PrintTargetCaddyfile)); exit 0 }
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

# 4. Caddy 2.11.9 і Caddyfile V2 (R-07): adapt лише перетворює конфігурацію, нічого не запускає.
# Шаблон пакета — лише синтаксис; очікування перевіряються на цільовій формі TLSFIX5 (stdin, без файлів).
function Invoke-CaddyAdaptText([string]$Text) {
  $psi = New-Object Diagnostics.ProcessStartInfo $Caddy
  $psi.Arguments = 'adapt --config - --adapter caddyfile'
  $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
  $psi.StandardOutputEncoding = [Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [Text.Encoding]::UTF8
  $p = [Diagnostics.Process]::Start($psi)
  try {
    $o = $p.StandardOutput.ReadToEndAsync(); $e = $p.StandardError.ReadToEndAsync()
    $b = (New-Object Text.UTF8Encoding $false).GetBytes($Text)
    $p.StandardInput.BaseStream.Write($b, 0, $b.Length); $p.StandardInput.Close()
    if (-not $p.WaitForExit(60000)) { $p.Kill(); throw 'caddy adapt: тайм-аут' }
    [pscustomobject]@{ Code = $p.ExitCode; Out = $o.Result; Err = $e.Result }
  } finally { $p.Dispose() }
}
function Get-CaddyHandlers($Node, [string]$Ctx, $Acc) {        # усі обробники з контекстом шляху найближчого маршруту
  if ($null -eq $Node) { return }
  if ($Node -is [System.Array]) { foreach ($x in $Node) { Get-CaddyHandlers $x $Ctx $Acc }; return }
  if ($Node -isnot [System.Management.Automation.PSCustomObject]) { return }
  $m = Prop $Node 'match'
  if ($m) { $paths = @(@($m) | ForEach-Object { Prop $_ 'path' } | Where-Object { $_ }); if ($paths.Count) { $Ctx = ($paths -join ',') } }
  if (Prop $Node 'handler') { $Acc.Add([pscustomobject]@{ Ctx = $Ctx; H = $Node }) }
  foreach ($p in $Node.PSObject.Properties) { if ($p.Name -ne 'match') { Get-CaddyHandlers $p.Value $Ctx $Acc } }
}
if (-not [IO.Path]::IsPathRooted($Caddy) -or -not (Test-Path -LiteralPath $Caddy -PathType Leaf)) { Issue "Caddy: некоректний шлях $Caddy" }
else {
  $cv = "$(& $Caddy version)"
  if ($LASTEXITCODE -ne 0 -or -not $cv.StartsWith('v2.11.9')) { Issue "Caddy: версія $cv, очікується v2.11.9" }
  $null = @(& $Caddy adapt --config (Join-Path $PackageDir 'Caddyfile') --adapter caddyfile)
  if ($LASTEXITCODE -ne 0) { Issue 'Caddy: adapt шаблону завершився з помилкою' }
  $target = $null; try { $target = ConvertTo-TargetCaddyfile (Join-Path $PackageDir 'Caddyfile') } catch { Issue "Caddy: $($_.Exception.Message)" }
  $ad = if ($target) { Invoke-CaddyAdaptText $target } else { $null }
  if ($ad -and $ad.Code -ne 0) { Issue 'Caddy: adapt цільової форми TLSFIX5 завершився з помилкою' }
  elseif ($ad) {
    $json = $ad.Out
    $cfg = $json | ConvertFrom-Json
    $srvObj = Prop $cfg 'apps', 'http', 'servers'
    $servers = @(if ($srvObj) { $srvObj.PSObject.Properties | ForEach-Object Value })
    if (-not $servers.Count) { Issue 'Caddy: у конфігурації немає HTTP-серверів' }
    $listen = @($servers | ForEach-Object { Prop $_ 'listen' } | Sort-Object -Unique)
    if (($listen -join ',') -ne "${Host4}:443") { Issue "Caddy: listen = $($listen -join ', ') (TLSFIX5: лише ${Host4}:443)" }
    if (@($servers | Where-Object { (@(Prop $_ 'protocols') -join ',') -ne 'h1,h2' }).Count) { Issue 'Caddy: protocols ≠ h1 h2' }
    if (@($servers | Where-Object { (Prop $_ 'automatic_https', 'disable') -ne $true }).Count) { Issue 'Caddy: auto_https не вимкнено (TLSFIX5: off)' }
    if (@($servers | Where-Object { Prop $_ 'logs' }).Count) { Issue 'Caddy: увімкнено журнал доступу (S10)' }
    $lf = @(Prop $cfg 'apps', 'tls', 'certificates', 'load_files')
    if ($lf.Count -ne 1 -or (Prop $lf[0] 'certificate') -ne 'C:/srv/integrity-v2/caddy/tls/site.crt' -or (Prop $lf[0] 'key') -ne 'C:/srv/integrity-v2/caddy/tls/site.key') { Issue 'Caddy: немає файлової TLS-пари caddy\tls' }
    if (-not (Prop $cfg 'admin', 'disabled')) { Issue 'Caddy: admin не вимкнено' }
    $logs = Prop $cfg 'logging', 'logs'
    $logNames = @(if ($logs) { $logs.PSObject.Properties | ForEach-Object Name })
    $excl = @(if ($logs) { Prop $logs 'default', 'exclude' })
    if (($logNames -join ',') -ne 'default' -or (Prop $logs 'default', 'include') -or @('http.log.error', 'http.handlers.reverse_proxy', 'http.stdlib' | Where-Object { $excl -notcontains $_ }).Count) {
      Issue 'Caddy: журнал default має виключати http.log.error, http.handlers.reverse_proxy, http.stdlib (IP/URI анонімних подань)'
    }
    $hs = New-Object System.Collections.Generic.List[object]; Get-CaddyHandlers $servers '' $hs
    $rp = @($hs | Where-Object { (Prop $_.H 'handler') -eq 'reverse_proxy' })
    if ($rp.Count -lt 4 -or @($rp | Where-Object { ((@(Prop $_.H 'upstreams') | ForEach-Object { Prop $_ 'dial' }) -join ',') -ne '127.0.0.1:8100' -or (Prop $_.H 'transport', 'keep_alive', 'idle_timeout') -ne 4000000000 -or @(Prop $_.H 'headers', 'request', 'delete') -notcontains 'X-Role' }).Count) {
      Issue 'Caddy: кожен reverse_proxy — лише 127.0.0.1:8100, keepalive 4s, header_up -X-Role'
    }
    foreach ($p in '/api/*', '/v2/*') { if (-not @($hs | Where-Object { $_.Ctx -eq $p -and (Prop $_.H 'handler') -eq 'request_body' -and [int64](Prop $_.H 'max_size') -gt 0 -and [int64](Prop $_.H 'max_size') -le 262144 }).Count) { Issue "Caddy: немає request_body max_size для $p" } }
    $csp = { param($ctx) @($hs | Where-Object { $_.Ctx -eq $ctx -and (Prop $_.H 'handler') -eq 'headers' } | ForEach-Object { @(Prop $_.H 'response', 'set', 'Content-Security-Policy') } | Where-Object { $_ }) }
    $spa = @(& $csp ''); $docs = @(& $csp '/docs*')
    if ($spa.Count -ne 1 -or $spa[0] -notmatch "default-src 'self'" -or $spa[0] -match "unsafe-(inline|eval)" -or $spa[0] -notmatch "frame-ancestors 'none'") { Issue 'Caddy: CSP SPA відсутній або послаблений' }
    if ($docs.Count -ne 1 -or $docs[0] -notmatch "script-src 'self' 'sha256-[A-Za-z0-9+/]{43}='" -or $docs[0] -match "'unsafe-eval'|script-src[^;]*'unsafe-inline'") { Issue 'Caddy: CSP /docs без sha256 вбудованого скрипта Swagger або послаблений' }
    $glob = @($hs | Where-Object { (Prop $_.H 'handler') -eq 'headers' -and (Prop $_.H 'response', 'set', 'Strict-Transport-Security') })
    if ($glob.Count -ne 1 -or @(Prop $glob[0].H 'response', 'delete') -notcontains 'Server' -or -not (Prop $glob[0].H 'response', 'set', 'Permissions-Policy') -or
        @(Prop $glob[0].H 'response', 'set', 'X-Frame-Options') -notcontains 'DENY' -or @(Prop $glob[0].H 'response', 'set', 'X-Content-Type-Options') -notcontains 'nosniff') { Issue 'Caddy: загальні заголовки безпеки (HSTS, nosniff, DENY, Permissions-Policy, -Server) неповні' }
    if (-not @($hs | Where-Object { (Prop $_.H 'handler') -eq 'headers' -and @(Prop $_.H 'request', 'delete') -contains 'X-Role' }).Count) { Issue 'Caddy: немає request_header -X-Role' }
    foreach ($p in '/docs*', '/openapi.json', '/api/*', '/v2/*', '/redoc*', '/assets/*') { if (-not $json.Contains("""$p""")) { Issue "Caddy: немає маршруту $p" } }
    if (-not @($hs | Where-Object { $_.Ctx -eq '/redoc*' -and (Prop $_.H 'status_code') -eq 404 }).Count) { Issue 'Caddy: /redoc* має повертати 404' }
    Note "Caddy: $cv; adapt шаблону і цільової форми TLSFIX5 OK; listen $($listen -join ', ')"
  }
}

# 5. Мережа і порти (R-08): 443/8100 вільні, UDP 443 немає; Tailscale-адреси на місці
if (@(Get-NetTCPConnection -State Listen -LocalPort 443, 8100 -ErrorAction SilentlyContinue).Count) { Issue 'порт 443 або 8100 уже слухається' }
if (@(Get-NetUDPEndpoint -LocalPort 443 -ErrorAction SilentlyContinue).Count) { Issue 'UDP 443 уже зайнятий' }
if (-not @(Get-NetIPAddress -IPAddress $Host4 -ErrorAction SilentlyContinue).Count) { Issue "немає адреси Tailscale $Host4" }

# 6. Ціль встановлення ще не існує; служби V2 ще не створені
foreach ($p in 'C:\srv\integrity-v2') { if (Test-Path -LiteralPath $p) { Issue "$p уже існує — встановлення лише в новий каталог (рішення №5)" } }
foreach ($s in 'integrity-v2-backend', 'integrity-v2-caddy') { if (@(Get-Service -Name $s -ErrorAction SilentlyContinue).Count) { Issue "служба $s уже існує" } }
$free = (Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
if ($free -lt 2GB) { Issue "на C: вільно $([math]::Round($free / 1GB, 1)) ГБ, потрібно ≥ 2 ГБ" }

# 7. Небезпечні змінні на рівні Machine/User (служба V2 отримує env лише зі своєї конфігурації; Machine-змінні успадковує
#    будь-яка служба, зокрема FORWARDED_ALLOW_IPS/UVICORN_* змінюють поведінку uvicorn). Виводяться ЛИШЕ імена.
foreach ($scope in 'Machine', 'User') {
  $names = @([Environment]::GetEnvironmentVariables($scope).Keys | ForEach-Object { [string]$_ } |
             Where-Object { $_ -match '^(UVICORN_|V2_|INTEGRITY_)' -or $_ -in 'APP_ENV', 'TRUSTED_PROXIES', 'FRONTEND_ORIGINS', 'FORWARDED_ALLOW_IPS' } | Sort-Object)
  foreach ($n in $names) { Issue "змінна $n задана на рівні $scope — може потрапити в процес V2 (значення не виводиться)" }
}

# 8. V1 працює (лише GET; стан до встановлення — для порівняння на етапі 1)
$v1 = $null
foreach ($u in 'http://127.0.0.1:8080/api/health', "http://${Host4}:8080/api/health") {
  try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -eq 200) { $v1 = $u; break } } catch { }
}
if ($v1) { Note "V1: $v1 → 200" } else { Issue 'V1 /api/health не відповідає 200 — зупинка до з''ясування (runbook, етап 1)' }

Done
