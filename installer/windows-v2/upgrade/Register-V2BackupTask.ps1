# Register-V2BackupTask.ps1 — реєстрація щоденного резервного копіювання БД V2: завдання Integrity-V2-DB-Backup (SYSTEM, 03:30).
# Неінтерактивно (SSH, адміністратор). За замовчуванням — лише план (-WhatIf-подібний вивід); зміни — лише з -Apply -DecisionRef.
# Що робить з -Apply:
#   1. копіює Invoke-V2DailyBackup.ps1 і v2_db_tool.py у C:\srv\integrity-v2\pkg\ops-backup\ (pkg — лише Administrators/SYSTEM;
#      корінь V2 не отримує нових каталогів верхнього рівня), звіряє SHA256 копій із джерелом;
#   2. реєструє завдання: powershell -File <копія Invoke-V2DailyBackup.ps1> -ExpectedToolSha256 <SHA256 копії v2_db_tool.py> -Keep 14;
#      SYSTEM, найвищі права, щодня о -At (03:30), StartWhenAvailable, без паралельних екземплярів, ліміт 1 год;
#   3. read-back: принципал SYSTEM, дія, тригер; -RunNow — один пробний запуск і перевірка журналу backups\daily\daily-backup.log.
# Наявне завдання не перезаписується без -Replace. Завдання TLS-поновлення (Integrity-V2-TLS-Renewal) не зачіпається.
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File …\upgrade\Register-V2BackupTask.ps1 -Apply -DecisionRef '<рішення №5>' [-RunNow]
[CmdletBinding()]
param(
  [switch] $Apply,
  [string] $DecisionRef,
  [string] $At = '03:30',
  [ValidateRange(2, 90)] [int] $Keep = 14,
  [switch] $Replace,
  [switch] $RunNow,
  [string] $Python = 'C:\Program Files\Python313\python.exe'
)
Set-StrictMode -Version 2
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { }
$TaskName = 'Integrity-V2-DB-Backup'
$Root = 'C:\srv\integrity-v2'
$Dest = Join-Path $Root 'pkg\ops-backup'
$K = Split-Path -Parent $PSScriptRoot
$src = @{ 'Invoke-V2DailyBackup.ps1' = (Join-Path $PSScriptRoot 'Invoke-V2DailyBackup.ps1'); 'v2_db_tool.py' = (Join-Path $K 'v2_db_tool.py') }
if ($At -notmatch '^([01][0-9]|2[0-3]):[0-5][0-9]$') { throw "STOP: -At у форматі HH:mm" }
$plan = @(
  "завдання: \$TaskName (SYSTEM, найвищі права), щодня о $At; зберігати $Keep останніх вдалих копій",
  "файли: $($src.Keys -join ', ') → $Dest (ACL успадковується від pkg: лише Administrators/SYSTEM)",
  "дія: powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $Dest\Invoke-V2DailyBackup.ps1 -ExpectedToolSha256 <SHA256 v2_db_tool.py> -Keep $Keep",
  "копії: $Root\backups\daily\<yyyyMMdd-HHmmss>\ (integrity_v2.db, v2_auth.db, SHA256SUMS.txt, DAILY-BACKUP.json); журнал $Root\backups\daily\daily-backup.log")
if (-not $Apply) { 'ПЛАН (нічого не змінено; для виконання: -Apply -DecisionRef <…>):'; $plan | ForEach-Object { "  $_" }; exit 0 }

if (-not $DecisionRef -or -not $DecisionRef.Trim()) { throw 'STOP: потрібен -DecisionRef' }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'STOP: потрібні права адміністратора' }
if ($env:COMPUTERNAME -ne 'V2-HOST') { throw 'STOP: чужий хост' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "STOP: немає $Python" }
. (Join-Path $K 'V2-install-common.ps1')
$ErrorActionPreference = 'Stop'
$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue
if ($existing -and -not $Replace) { throw "STOP: завдання $TaskName уже існує (для заміни: -Replace)" }
foreach ($n in $src.Keys) { if (-not (Test-Path -LiteralPath $src[$n] -PathType Leaf)) { throw "STOP: немає $($src[$n])" } }
$null = Assert-V2InRoot $Dest
if (-not (Test-Path -LiteralPath $Dest)) { $null = New-Item -ItemType Directory -Path $Dest }
foreach ($n in $src.Keys) {
  $d = Join-Path $Dest $n
  [IO.File]::WriteAllBytes($d, [IO.File]::ReadAllBytes($src[$n]))
  if ((Get-FileHash -LiteralPath $d).Hash -ne (Get-FileHash -LiteralPath $src[$n]).Hash) { throw "STOP: копія ${n} не підтверджена" }
}
$null = Assert-V2AclTree -Path $Dest -Role admin          # лише Administrators/SYSTEM, власник Administrators
$toolSha = (Get-FileHash -LiteralPath (Join-Path $Dest 'v2_db_tool.py')).Hash
$arg = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Dest\Invoke-V2DailyBackup.ps1`" -ExpectedToolSha256 $toolSha -Keep $Keep -Python `"$Python`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arg
$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($At, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture))
$principal = New-ScheduledTaskPrincipal -UserId 'S-1-5-18' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$desc = "Integrity V2: щоденна перевірена копія integrity_v2.db і v2_auth.db (restore-test, $Keep копій). Рішення: $DecisionRef"
$null = Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $desc -Force:([bool]$Replace)
$t = Get-ScheduledTask -TaskName $TaskName -TaskPath '\'
if ($t.Principal.UserId -notin 'SYSTEM', 'S-1-5-18', 'NT AUTHORITY\SYSTEM' -or $t.Principal.RunLevel -ne 'Highest' -or @($t.Actions).Count -ne 1 -or $t.Actions[0].Arguments -ne $arg -or @($t.Triggers).Count -ne 1) { throw 'STOP: read-back завдання ≠ заданому' }
"PASS  завдання \${TaskName}: SYSTEM, щодня о $At; v2_db_tool SHA256 $($toolSha.ToLowerInvariant()); файли в $Dest"
if ($RunNow) {
  Start-ScheduledTask -TaskName $TaskName -TaskPath '\'
  $logFile = Join-Path $Root 'backups\daily\daily-backup.log'
  $before = if (Test-Path -LiteralPath $logFile) { @(Get-Content -LiteralPath $logFile).Count } else { 0 }
  foreach ($i in 1..120) { Start-Sleep 2; if ((Get-ScheduledTask -TaskName $TaskName -TaskPath '\').State -ne 'Running' -and (Test-Path -LiteralPath $logFile) -and @(Get-Content -LiteralPath $logFile).Count -gt $before) { break } }
  $last = @(Get-Content -LiteralPath $logFile)[-1]
  $info = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath '\'
  if ($last -notmatch '^[0-9]{8}-[0-9]{6} PASS ' -or $info.LastTaskResult -ne 0) { throw "STOP: пробний запуск не PASS (LastTaskResult $($info.LastTaskResult)): $last" }
  "PASS  пробний запуск: $last"
}
