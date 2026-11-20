# V2-upgrade-sim.ps1 — ЛИШЕ ДЛЯ ТЕСТІВ: адаптери симуляції для Update/Rollback-V2InPlace (-Simulate).
# Підключається на рівні скрипта ПІСЛЯ V2-upgrade-lib.ps1 і перевизначає лише адаптери SCM / ACL / мережі.
# Стан «служб» — <корінь>\..\sim\state.json; конфігурація — <корінь>\..\sim\config.json (шлях caddy.exe, Machine-змінні, вільне місце).
# Нічого в системі не змінює: служби не реєструються, ACL не змінюються, мережа не використовується.
# Старт «backend» перевіряє те, що перевірив би справжній застосунок: каталог коду з XML, версії БД (v2_db_tool verify)
# і потрібні пакети у venv (app\sim_expect.json); старт «Caddy» — caddy adapt живого Caddyfile і наявність dist\index.html.

function Get-V2UpSimDir { Join-Path (Split-Path -Parent $V2Root) 'sim' }
function Get-V2UpSimState { Get-Content -LiteralPath (Join-Path (Get-V2UpSimDir) 'state.json') -Raw -Encoding UTF8 | ConvertFrom-Json }
function Save-V2UpSimState($State) { [IO.File]::WriteAllText((Join-Path (Get-V2UpSimDir) 'state.json'), (ConvertTo-Json $State -Depth 5), (New-Object Text.UTF8Encoding $false)) }
function Get-V2UpSimConfig { Get-Content -LiteralPath (Join-Path (Get-V2UpSimDir) 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json }
function Add-V2UpSimEvent([string]$Text) {
  $st = Get-V2UpSimState; $st.Events = @($st.Events) + $Text; Save-V2UpSimState $st
}

function Test-V2UpAdmin { $true }
function Assert-V2UpHost { 'SIM   хост не перевіряється' }
function Get-V2UpService([string]$Name) {
  $st = Get-V2UpSimState
  $p = $st.Services.PSObject.Properties[$Name]; if (-not $p) { return $null }
  $s = $p.Value
  [pscustomobject]@{ Name = $Name; State = [string]$s.State; StartMode = [string]$s.StartMode; DelayedAutoStart = [bool]$s.Delayed
                     StartName = "NT SERVICE\$Name"; PathName = (Join-Path $V2Root "services\$($Name -replace '^integrity-v2-', '')\$Name.exe")
                     ProcessId = $(if ($s.State -eq 'Running') { 4000 + $Name.Length } else { 0 }); DependsOn = @($s.DependsOn) }
}
function Set-V2UpSimService([string]$Name, [hashtable]$Changes) {
  $st = Get-V2UpSimState
  foreach ($k in $Changes.Keys) { $st.Services.$Name.$k = $Changes[$k] }
  Save-V2UpSimState $st
}
function Stop-V2UpService([string]$Name) {
  $s = Assert-V2UpServiceIdentity $Name
  if ($s.State -eq 'Stopped') { return "INFO  $Name уже зупинена (SIM)" }
  Set-V2UpSimService $Name @{ State = 'Stopped' }; Add-V2UpSimEvent "stop $Name"
  "SIM   $Name зупинено"
}
function Start-V2UpService([string]$Name) {
  $s = Assert-V2UpServiceIdentity $Name
  if ($s.State -ne 'Stopped') { Stop-V2 "${Name}: старт лише зі стану Stopped (зараз $($s.State))" }
  if ($s.StartMode -eq 'Disabled') { Stop-V2 "${Name}: служба вимкнена (1058)" }
  if ($Name -eq $V2UpBackend) {
    $null = Assert-V2NoRestoreBlock -DataDir "$V2Root\data"
    $wd = Get-V2UpXmlWorkdir "$V2Root\services\backend\integrity-v2-backend.xml"
    $expectFile = Join-Path $wd 'app\sim_expect.json'
    if (-not (Test-Path -LiteralPath (Join-Path $wd 'app\__init__.py')) -or -not (Test-Path -LiteralPath $expectFile)) { Stop-V2 "SIM backend: у $wd немає app" }
    $exp = Get-Content -LiteralPath $expectFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($d in $V2UpDbs) {
      $want = [int]$exp.($d.Kind)
      $v = @(Invoke-V2Native -Exe $script:V2UpBasePython -ArgList @('-I', '-B', $script:V2UpDbTool, 'verify', (Join-Path "$V2Root\data" $d.Db), '--expect-version', "$want") -Utf8 -OkCodes @(0, 1) -What 'sim verify')
      if (-not $v.Count -or $v[-1] -notlike 'VERIFY OK*') { Stop-V2 "SIM backend: check_schema — $($d.Db) не версії $want" }
    }
    foreach ($m in @($exp.requires)) {
      try { $null = Invoke-V2Native -Exe (Get-V2UpVenvPython) -ArgList @('-I', '-B', '-c', "import $m") -What "sim import $m" } catch { Stop-V2 "SIM backend: ModuleNotFoundError $m у venv" }
    }
  } else {
    $cfgPath = "$V2Root\caddy\Caddyfile"
    $null = Invoke-V2Native -Exe (Get-V2UpCaddyExe) -ArgList @('adapt', '--config', $cfgPath, '--adapter', 'caddyfile') -What 'sim caddy adapt'
    if (-not (Test-Path -LiteralPath "$V2Root\app\frontend\dist\index.html")) { Stop-V2 'SIM caddy: немає dist\index.html' }
  }
  Set-V2UpSimService $Name @{ State = 'Running' }; Add-V2UpSimEvent "start $Name"
  "SIM   $Name запущено"
}
function Set-V2UpStartMode([string]$Name, [ValidateSet('delayed-auto', 'demand', 'disabled')] [string]$Mode) {
  $map = @{ 'delayed-auto' = @('Auto', $true); 'demand' = @('Manual', $false); 'disabled' = @('Disabled', $false) }
  Set-V2UpSimService $Name @{ StartMode = $map[$Mode][0]; Delayed = $map[$Mode][1] }; Add-V2UpSimEvent "startmode $Name $Mode"
  "SIM   $Name start= $Mode"
}
function Get-V2UpHttpStatus([string]$Path, [string]$Method = 'GET') {
  if ((Get-V2UpService $V2UpBackend).State -ne 'Running') { return 0 }
  $map = @{ 'GET /api/health' = 200; 'GET /docs' = 401; 'GET /redoc' = 404; 'POST /v2/auth/logout' = 403; 'GET /api/assessments' = 200 }
  $k = "$Method $Path"; if ($map.ContainsKey($k)) { $map[$k] } else { 404 }
}
function Assert-V2UpHttps([string]$Path, [int]$Expected) {
  if ((Get-V2UpService $V2UpCaddy).State -ne 'Running') { Stop-V2 "SIM HTTPS ${Path}: Caddy не працює" }
  $backend = (Get-V2UpService $V2UpBackend).State -eq 'Running'
  $map = @{ '/' = 200; '/api/health' = $(if ($backend) { 200 } else { 502 }); '/docs' = $(if ($backend) { 401 } else { 502 }); '/redoc' = 404; '/assets/missing.js' = 404 }
  $s = if ($map.ContainsKey($Path)) { $map[$Path] } else { 404 }
  if ($s -ne $Expected) { Stop-V2 "SIM GET https://$V2UpHostName$Path → $s, очікується $Expected" }
  "SIM   GET https://$V2UpHostName$Path → $s"
}
function Get-V2UpHttpsHeaders([string]$Path) {
  if ((Get-V2UpService $V2UpCaddy).State -ne 'Running') { Stop-V2 'SIM HTTPS: Caddy не працює' }
  $t = [IO.File]::ReadAllText("$V2Root\caddy\Caddyfile")
  $csp = @([regex]::Matches($t, 'Content-Security-Policy "([^"]+)"') | ForEach-Object { $_.Groups[1].Value })
  $h = @{}
  $pick = @(if ($Path -like '/docs*') { $csp | Where-Object { $_ -match "'sha256-" } } else { $csp | Where-Object { $_ -match "^default-src 'self'" } })
  if ($pick.Count) { $h['content-security-policy'] = $pick[0] }
  if ($t -match 'Permissions-Policy "') { $h['permissions-policy'] = 'x' }
  if ($t -notmatch '(?m)^\s*-Server\s*$') { $h['server'] = 'Caddy' }
  $h
}
function Grant-V2UpAcl([string]$Path, [string]$Account, [string]$Rights) {
  if (-not (Test-Path -LiteralPath $Path)) { Stop-V2 "немає $Path" }
  Add-V2UpSimEvent "grant $([IO.Path]::GetFileName($Path)) $Account $Rights"; "SIM   ACL $Path $Account $Rights"
}
function Assert-V2UpAclTree([string]$Path, [string]$Service, [string]$Rights, [string]$Role) { "SIM   ACL-дерево $Path ($Service $Rights, $Role) не перевіряється" }
function New-V2UpAdminDir([string]$Path, [string]$DecisionRef) {
  if (Test-Path -LiteralPath $Path) { Stop-V2 "$Path уже існує" }
  $null = New-Item -ItemType Directory -Path $Path; "SIM   каталог $Path (ACL лише Administrators/SYSTEM — не застосовується)"
}
function Assert-V2UpAdminOnly([string]$Path) { if (-not (Test-Path -LiteralPath $Path)) { Stop-V2 "немає $Path" }; "SIM   ACL $Path не перевіряється" }
function Assert-V2UpCaddyfileAcl([string]$Path) { "SIM   ACL $Path не перевіряється" }
function Get-V2UpMachineEnvNames { @((Get-V2UpSimConfig).MachineEnv | Where-Object { $_ -match $V2UpEnvNameRx }) }
function Get-V2UpFreeBytes { [int64](Get-V2UpSimConfig).FreeBytes }
function Get-V2UpCaddyExe { [string](Get-V2UpSimConfig).Caddy }
function Invoke-V2UpCaddyValidate([string]$File) {
  $root = ($V2Root -replace '\\', '/') + '/'
  $tmp = Join-Path (Split-Path -Parent $V2Root) ('sim\validate-' + [guid]::NewGuid().ToString('N') + '.Caddyfile')
  [IO.File]::WriteAllText($tmp, [IO.File]::ReadAllText($File).Replace('C:/srv/integrity-v2/', $root), (New-Object Text.UTF8Encoding $false))
  try { $null = Invoke-V2Native -Exe (Get-V2UpCaddyExe) -ArgList @('validate', '--config', $tmp, '--adapter', 'caddyfile') -What 'caddy validate (SIM: шляхи → корінь симуляції)' }
  finally { Remove-Item -LiteralPath $tmp -Force }
  "PASS  caddy validate $File (SIM: справжній caddy.exe, шляхи C:/srv/integrity-v2 → $root)"
}
