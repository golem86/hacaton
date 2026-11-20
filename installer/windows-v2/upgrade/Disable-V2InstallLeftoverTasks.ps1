# Disable-V2InstallLeftoverTasks.ps1 — вимкнення залишкових запланованих завдань встановлення V2 БЕЗ видалення.
# За замовчуванням — звіт (як -WhatIf): ім'я, стан, тип облікового запису (без імені користувача). З -Apply -DecisionRef:
#   1. експорт XML кожного завдання в C:\srv\integrity-v2\backups\tasks-<stamp>\ (лише Administrators/SYSTEM);
#   2. Stop-ScheduledTask, якщо Running (для Codex-V2-TLSFIX5-Interactive-* це закриває відкрите вікно PowerShell -NoExit);
#   3. Disable-ScheduledTask; read-back: State = Disabled. Завдання НЕ видаляються.
# Дозволені лише імена Codex-V2-*; Integrity-V2-* (зокрема Integrity-V2-TLS-Renewal і Integrity-V2-DB-Backup) — ніколи.
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\upgrade\Disable-V2InstallLeftoverTasks.ps1 [-Apply -DecisionRef '<рішення №5>']
[CmdletBinding()]
param(
  [switch] $Apply,
  [string] $DecisionRef,
  [string[]] $TaskName = @('Codex-V2-TLSFIX5-Interactive-20261120', 'Codex-V2-TLS-Renewal-Validation-20261120'),
  [string] $BackupRoot = 'C:\srv\integrity-v2\backups',
  [switch] $Simulate,                   # ЛИШЕ тести: завдання — з <BackupRoot>\..\sim-tasks.json, без планувальника
  [switch] $SimulateFailStop
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { }
$TaskName = @($TaskName | ForEach-Object { $_ -split ',' } | Where-Object { $_ })
foreach ($n in $TaskName) {
  if ($n -notmatch '^Codex-V2-[A-Za-z0-9._-]+$' -or $n -match '^Integrity-V2-') { throw "STOP: дозволені лише залишкові завдання Codex-V2-*: $n" }
}
# --- адаптери планувальника (симуляція перевизначає лише їх)
$simFile = Join-Path (Split-Path -Parent $BackupRoot) 'sim-tasks.json'
function Get-LtTask([string]$Name) {
  if ($Simulate) { $s = Get-Content -LiteralPath $simFile -Raw | ConvertFrom-Json; $p = $s.PSObject.Properties[$Name]; if (-not $p) { return $null }; return [pscustomobject]@{ State = $p.Value.State; UserId = $p.Value.UserId } }
  $t = Get-ScheduledTask -TaskName $Name -TaskPath '\' -ErrorAction SilentlyContinue
  if (-not $t) { return $null }
  [pscustomobject]@{ State = [string]$t.State; UserId = [string]$t.Principal.UserId }
}
function Set-LtSim([string]$Name, [string]$State) { $s = Get-Content -LiteralPath $simFile -Raw | ConvertFrom-Json; $s.$Name.State = $State; [IO.File]::WriteAllText($simFile, (ConvertTo-Json $s), (New-Object Text.UTF8Encoding $false)) }
function Export-LtTask([string]$Name) { if ($Simulate) { "<Task><!-- SIM $Name --></Task>" } else { Export-ScheduledTask -TaskName $Name -TaskPath '\' } }
function Stop-LtTask([string]$Name) { if ($Simulate) { if ($SimulateFailStop) { throw 'SIM: зупинка не вдалася' }; Set-LtSim $Name 'Ready' } else { Stop-ScheduledTask -TaskName $Name -TaskPath '\' } }
function Disable-LtTask([string]$Name) { if ($Simulate) { Set-LtSim $Name 'Disabled' } else { $null = Disable-ScheduledTask -TaskName $Name -TaskPath '\' } }
function Get-AccountKind([string]$UserId) { if ($UserId -in 'SYSTEM', 'S-1-5-18', 'NT AUTHORITY\SYSTEM') { 'SYSTEM' } elseif ($UserId) { 'обліковий запис користувача (ім''я не виводиться)' } else { 'невідомо' } }

if ($Simulate) {
  $tb = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
  if (-not [IO.Path]::GetFullPath($BackupRoot).StartsWith($tb, [StringComparison]::OrdinalIgnoreCase)) { throw 'STOP: симуляція лише з -BackupRoot у %TEMP%' }
} else {
  if ($BackupRoot -cne 'C:\srv\integrity-v2\backups') { throw 'STOP: -BackupRoot має бути C:\srv\integrity-v2\backups' }
  if ($Apply) {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'STOP: потрібні права адміністратора' }
    if ($env:COMPUTERNAME -ne 'V2-HOST') { throw 'STOP: чужий хост' }
  }
}
if ($Apply -and (-not $DecisionRef -or -not $DecisionRef.Trim())) { throw 'STOP: потрібен -DecisionRef' }
"$(if ($Apply) { 'ЗАСТОСУВАННЯ' } else { 'ЗВІТ (нічого не змінюється; застосувати: -Apply -DecisionRef <…>)' })"
$exitCode = 0; $dir = $null
foreach ($n in $TaskName) {
  $t = Get-LtTask $n
  if (-not $t) { "  ${n}: немає — нічого робити"; continue }
  $line = "  ${n}: стан $($t.State); обліковий запис: $(Get-AccountKind $t.UserId)"
  if (-not $Apply) { "$line → буде: експорт XML, $(if ($t.State -eq 'Running') { 'зупинка, ' })вимкнення (без видалення)"; continue }
  if ($t.State -eq 'Disabled') { "$line → уже вимкнено"; continue }
  try {
    if (-not $dir) {
      $dir = Join-Path $BackupRoot ('tasks-' + (Get-Date -Format yyyyMMdd-HHmmss))
      if ($Simulate) { $null = New-Item -ItemType Directory -Path $dir }
      else { $sec = New-Object Security.AccessControl.DirectorySecurity; $sec.SetSecurityDescriptorSddlForm('O:BAD:PAI(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)'); $null = [IO.Directory]::CreateDirectory($dir, $sec) }
    }
    [IO.File]::WriteAllText((Join-Path $dir "$n.xml"), [string](Export-LtTask $n), (New-Object Text.UTF8Encoding $false))
    if ($t.State -eq 'Running') { Stop-LtTask $n; foreach ($i in 1..15) { if ((Get-LtTask $n).State -ne 'Running') { break }; Start-Sleep 1 } }
    if ((Get-LtTask $n).State -eq 'Running') { throw 'завдання досі Running після зупинки' }
    Disable-LtTask $n
    $now = Get-LtTask $n
    if ($now.State -ne 'Disabled') { throw "read-back: стан $($now.State)" }
    "$line → експортовано ($dir), $(if ($t.State -eq 'Running') { 'зупинено, ' })вимкнено"
  } catch { "$line → FAILED: $($_.Exception.Message)"; $exitCode = 2 }
}
exit $exitCode
