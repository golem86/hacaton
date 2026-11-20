# Set-V2UserRole.ps1 — призначення й зняття ролей V2 (зокрема admin) власником сервера.
# Роль адміністратора у вебі не призначає й не знімає ніхто; лише ця команда на сервері (python -m app.v2_role_cli).
# ЗАПУСК (неінтерактивно, придатно для SSH від адміністратора Windows):
#   План:       powershell -NoProfile -ExecutionPolicy Bypass -File Set-V2UserRole.ps1 -Email user@example.org -Role admin
#   Виконати:   powershell -NoProfile -ExecutionPolicy Bypass -File Set-V2UserRole.ps1 -Email user@example.org -Role admin -Apply
# Що робить: з живого XML служби integrity-v2-backend бере ЛИШЕ INTEGRITY_DB, V2_AUTH_DB, APP_ENV і workingdirectory
# (секрети не читаються в змінні й не виводяться) → запускає venv\Scripts\python.exe -E -s -X utf8 -m app.v2_role_cli
# з робочого каталогу backend. Без -Apply — лише план. Backend зупиняти не потрібно (транзакція SQLite).
# Коди виходу: 0 — виконано/план, 2 — відмова (немає користувача, та сама роль, останній адміністратор), 1 — помилка.
[CmdletBinding()]
param(
  [Parameter(Mandatory)] [ValidatePattern('^[^\s@<>"]{1,200}@[^\s@<>"]{1,200}$')] [string] $Email,
  [Parameter(Mandatory)] [ValidateSet('admin', 'user', 'data_officer')] [string] $Role,
  [switch] $Apply,
  [string] $Root = 'C:\srv\integrity-v2'
)
$ErrorActionPreference = 'Stop'
$xmlPath = Join-Path $Root 'services\backend\integrity-v2-backend.xml'
$python = Join-Path $Root 'venv\Scripts\python.exe'

try {
  if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Потрібні права адміністратора Windows' }
  if (-not (Test-Path -LiteralPath $xmlPath -PathType Leaf)) { throw "Немає XML служби: $xmlPath" }
  if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Немає Python середовища: $python" }

  [xml]$service = [IO.File]::ReadAllText($xmlPath, (New-Object Text.UTF8Encoding($false, $true)))
  $serviceDir = Split-Path -Parent $xmlPath
  function Expand-ServiceValue([string]$Value) {
    [Environment]::ExpandEnvironmentVariables(($Value -replace '%BASE%', $serviceDir))
  }
  function Get-ServiceEnv([string]$Name) {
    $found = @($service.service.env | Where-Object { $_.name -ceq $Name })
    if ($found.Count -ne 1) { throw "XML служби: змінна $Name має бути рівно один раз (знайдено $($found.Count))" }
    Expand-ServiceValue $found[0].value
  }
  $integrityDb = Get-ServiceEnv 'INTEGRITY_DB'
  $authDb = Get-ServiceEnv 'V2_AUTH_DB'
  $appEnv = Get-ServiceEnv 'APP_ENV'
  $workDirNode = @($service.service.workingdirectory)
  if ($workDirNode.Count -ne 1 -or -not "$($workDirNode[0])".Trim()) { throw 'XML служби: немає workingdirectory' }
  $workDir = Expand-ServiceValue "$($workDirNode[0])".Trim()
  $service = $null
  foreach ($p in @($integrityDb, $authDb)) { if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Немає файлу БД: $p" } }
  if (-not (Test-Path -LiteralPath (Join-Path $workDir 'app\v2_role_cli.py') -PathType Leaf)) { throw "У $workDir немає app\v2_role_cli.py (оновіть backend)" }

  $mode = if ($Apply) { 'ЗАСТОСУВАННЯ' } else { 'ПЛАН (без змін)' }
  "Set-V2UserRole: $mode; роль $Role; APP_ENV=$appEnv; backend: $workDir"
  $cliArgs = @('-E', '-s', '-X', 'utf8', '-m', 'app.v2_role_cli', 'set-role', '--email', $Email, '--role', $Role)
  if ($Apply) { $cliArgs += '--confirm' }

  # Дочірній процес отримує лише потрібні змінні; -E вимикає PYTHON*-змінні, -s — сторонні site-packages користувача.
  $saved = @{}
  foreach ($name in @('INTEGRITY_DB', 'V2_AUTH_DB', 'APP_ENV', 'V2_SECRET_KEY')) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
  $prevEncoding = [Console]::OutputEncoding
  Push-Location -LiteralPath $workDir
  try {
    [Environment]::SetEnvironmentVariable('INTEGRITY_DB', $integrityDb, 'Process')
    [Environment]::SetEnvironmentVariable('V2_AUTH_DB', $authDb, 'Process')
    [Environment]::SetEnvironmentVariable('APP_ENV', $appEnv, 'Process')
    [Environment]::SetEnvironmentVariable('V2_SECRET_KEY', $null, 'Process')     # команді секрет не потрібен
    try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false) } catch { }   # без консолі (SSH) — як є
    & $python @cliArgs
    $code = $LASTEXITCODE
  } finally {
    Pop-Location
    try { [Console]::OutputEncoding = $prevEncoding } catch { }
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
  }
  if ($code -eq 0 -and -not $Apply) { 'Щоб виконати, повторіть з -Apply.' }
  exit $code
} catch {
  "FAIL  $($_.Exception.Message)"
  exit 1
}
