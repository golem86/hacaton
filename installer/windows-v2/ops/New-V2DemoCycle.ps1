# New-V2DemoCycle.ps1 — синтетичний закритий демо-цикл (≈150 анонімних анкет вигаданих учасників) на СИНТЕТИЧНОМУ сервері.
# Працює лише з БД, позначеною instance_meta('dataset','synthetic'); інакше відмова (python -m app.demo_cycle, docs/DEMO_DATA.md).
# ЗАПУСК (неінтерактивно, придатно для SSH від адміністратора Windows):
#   План:       powershell -NoProfile -ExecutionPolicy Bypass -File New-V2DemoCycle.ps1
#   Виконати:   powershell -NoProfile -ExecutionPolicy Bypass -File New-V2DemoCycle.ps1 -Apply
#   Параметри:  -Responses 150 -Seed 2026 -Name 'Демо-цикл (синтетичні дані)'
# ПЕРЕД -Apply зробіть резервну копію INTEGRITY_DB (v2_db_tool backup, див. docs/DEMO_DATA.md).
# Що робить: з живого XML служби integrity-v2-backend бере ЛИШЕ INTEGRITY_DB, V2_AUTH_DB, APP_ENV і workingdirectory
# (секрети не читаються в змінні й не виводяться) → запускає venv\Scripts\python.exe -E -s -X utf8 -m app.demo_cycle
# з робочого каталогу backend. Без -Apply — лише план. Backend зупиняти не потрібно (одна транзакція SQLite).
# Коди виходу: 0 — виконано/план, 2 — відмова (немає позначки synthetic, назва вже є, аргументи), 1 — помилка.
[CmdletBinding()]
param(
  [ValidateRange(30, 2000)] [int] $Responses = 150,
  [ValidateRange(0, 2147483647)] [int] $Seed = 2026,
  [ValidateLength(1, 50)] [ValidatePattern('^[^\x00-\x1f\x7f"]+$')] [string] $Name = 'Демо-цикл (синтетичні дані)',
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
  function Get-ServiceEnv([string]$EnvName) {
    $found = @($service.service.env | Where-Object { $_.name -ceq $EnvName })
    if ($found.Count -ne 1) { throw "XML служби: змінна $EnvName має бути рівно один раз (знайдено $($found.Count))" }
    Expand-ServiceValue $found[0].value
  }
  $integrityDb = Get-ServiceEnv 'INTEGRITY_DB'
  $authDb = Get-ServiceEnv 'V2_AUTH_DB'
  $appEnv = Get-ServiceEnv 'APP_ENV'
  $workDirNode = @($service.service.workingdirectory)
  if ($workDirNode.Count -ne 1 -or -not "$($workDirNode[0])".Trim()) { throw 'XML служби: немає workingdirectory' }
  $workDir = Expand-ServiceValue "$($workDirNode[0])".Trim()
  $service = $null
  if (-not (Test-Path -LiteralPath $integrityDb -PathType Leaf)) { throw "Немає файлу БД: $integrityDb" }
  if (-not (Test-Path -LiteralPath (Join-Path $workDir 'app\demo_cycle.py') -PathType Leaf)) { throw "У $workDir немає app\demo_cycle.py (оновіть backend)" }

  $mode = if ($Apply) { 'ЗАСТОСУВАННЯ' } else { 'ПЛАН (без змін)' }
  "New-V2DemoCycle: $mode; анкет $Responses; seed $Seed; APP_ENV=$appEnv; backend: $workDir"
  $cliArgs = @('-E', '-s', '-X', 'utf8', '-m', 'app.demo_cycle', '--responses', "$Responses", '--seed', "$Seed", '--name', $Name)
  if ($Apply) { $cliArgs += '--confirm' }

  # Дочірній процес отримує лише потрібні змінні; -E вимикає PYTHON*-змінні, -s — сторонні site-packages користувача.
  $saved = @{}
  foreach ($envName in @('INTEGRITY_DB', 'V2_AUTH_DB', 'APP_ENV', 'V2_SECRET_KEY')) { $saved[$envName] = [Environment]::GetEnvironmentVariable($envName, 'Process') }
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
    foreach ($envName in $saved.Keys) { [Environment]::SetEnvironmentVariable($envName, $saved[$envName], 'Process') }
  }
  if ($code -eq 0 -and -not $Apply) { 'Щоб виконати, повторіть з -Apply (спершу резервна копія INTEGRITY_DB).' }
  exit $code
} catch {
  "FAIL  $($_.Exception.Message)"
  exit 1
}
